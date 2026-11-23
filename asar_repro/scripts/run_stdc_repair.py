"""Fail-fast repair validation and paired experiments; frozen inputs stay read-only."""
import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import importlib.util
import importlib.metadata
import json
from pathlib import Path
import subprocess
import sys
from time import perf_counter
import traceback
import xml.etree.ElementTree as ET

import numpy as np
import psutil

from asar_repro.heuristic import Heuristic
from asar_repro.oracle import enumerate_oracle
import asar_repro.search as search_module
from run_stdc_small_search import case
from stdc_validation_guards import (ROOT, read, save, require, digest, load_real,
                                    replay_result, small_search, freeze_case)

REFERENCE = '4a01dee2275ce3b732f619e0192fd1a417a5766e'
OLD = ROOT/'outputs/stdc_v0_2/local_validation_20261123_r5'
ORDER = ('new_tests','full_tests','random_audit','small_search','lake_smoke','comparison')
VARIANTS = {
    'paper_reference': ('paper_greedy', False, 0, True),
    'mass_reference': ('mass_lb', False, 0, True),
    'stdc_reference': ('stdc_lb', False, 0, True),
    'stdc_geometry': ('stdc_lb', False, 0, False),
    'stdc_cache': ('stdc_lb', False, 4096, False),
    'stdc_reuse': ('stdc_lb', True, 4096, False),
    'paper_reuse': ('paper_greedy', True, 4096, False),
    'mass_reuse': ('mass_lb', True, 4096, False),
}


def git(*args, cwd=ROOT):
    return subprocess.check_output(['git','-c',f'safe.directory={Path(cwd).parent.as_posix()}',*args],cwd=cwd)


def sources():
    return {p.relative_to(ROOT).as_posix():digest(p) for top in ('src','tests','scripts')
            for p in sorted((ROOT/top).rglob('*.py'))}


def snapshot(folder):
    (folder/'changes.diff').write_bytes(git('diff','HEAD','--binary'))
    tracked=set(git('ls-files','-z').decode().split('\0'))
    additions=[]
    for name in sources():
        if name not in tracked:
            proc=subprocess.run(['git','diff','--no-index','--','/dev/null','asar_repro/'+name],
                cwd=ROOT.parent,capture_output=True)
            require(proc.returncode==1,'new source diff failed: '+name)
            additions.append(proc.stdout)
    (folder/'new_sources.diff').write_bytes(b'\n'.join(additions))
    (folder/'git.status').write_bytes(git('status','--short'))
    save(folder/'source_sha256.json',sources())


def preserve(run):
    pre=read(run/'preflight.json'); old=read(OLD/'00_preflight.json')
    base=Path(old['baseline_root'])
    require(git('branch','--show-current').decode().strip()=='stdc-research-v0.2','wrong research branch')
    require(git('rev-parse','baseline-v1.1').decode().strip()==old['base_commit'],'baseline ref moved')
    require(git('branch','--show-current',cwd=base).decode().strip()=='baseline-v1.1','baseline checkout moved')
    for name,sha in old['baseline_all_preserved'].items():
        require(digest(base/name)==sha,'baseline file changed: '+name)
    for name,sha in pre['protected'].items():
        require(digest(ROOT/name)==sha,'protected input/result changed: '+name)
    require(sources()==pre['source_sha256'],'source changed after validation freeze')
    return dict(status='passed',baseline_files=len(old['baseline_all_preserved']),
                protected_research_files=len(pre['protected']),source_files=len(pre['source_sha256']))


def init(run):
    require(run.is_relative_to(ROOT/'outputs/stdc_v0_2'),'research output required')
    run.mkdir(exist_ok=False)
    current_commit=git('rev-parse','HEAD').decode().strip()
    require(git('merge-base',REFERENCE,current_commit).decode().strip()==REFERENCE,
            'research checkout must descend from frozen reference')
    paths=[]
    for top in ('data','outputs'):
        paths.extend(p for p in (ROOT/top).rglob('*') if p.is_file() and not p.is_relative_to(run))
    # The frozen scorer, motion, grid and input adapters are not repair targets.
    for p in (ROOT/'src').rglob('*.py'):
        if p.name not in ('stdc_heuristic.py','search.py'):
            paths.append(p)
    pre=dict(status='passed',source_commit=current_commit,reference_commit=REFERENCE,source_sha256=sources(),
             interpreter=sys.executable,python_version=sys.version,
             versions={name:importlib.metadata.version(name) for name in ('numpy','scipy','pytest','opendrift')},
             protected={p.relative_to(ROOT).as_posix():digest(p) for p in sorted(paths)},
             user_authorization='Repair the diagnosed STDC issues on research branch',
             plan=dict(order=ORDER,variants=VARIANTS,epsilons=[1.1,1.04,1.0],repeats=3,
                       limits=dict(max_expansions=5000,max_open=20000,max_seconds=30),
                       h_cache_entries=4096,seed=41,forcing='historical_real',
                       synthetic_seeds=dict(prefixes=[100,179],small=[15000,15034])),
             scope='equivalent geometry cache plus opt-in exact-state reuse; no new heuristic or objective')
    save(run/'preflight.json',pre)
    (run/'reference').mkdir()
    for name in ('search','stdc_heuristic','heuristic'):
        (run/'reference'/f'{name}.py').write_bytes(git('show',f'{REFERENCE}:asar_repro/src/asar_repro/{name}.py'))
    snapshot(run)
    save(run/'preservation_initial.json',preserve(run))


def load_reference(run, name):
    path=run/'reference'/f'{name}.py'
    require(path.read_bytes()==git('show',f'{REFERENCE}:asar_repro/src/asar_repro/{name}.py'),
            'legacy source fingerprint changed')
    key='asar_repro._repair_reference_'+name
    spec=importlib.util.spec_from_file_location(key,path)
    module=importlib.util.module_from_spec(spec);sys.modules[key]=module;spec.loader.exec_module(module)
    return module


def small_worker(folder):
    # Re-run all 490 historical searches before opt-in variants.
    old=folder/'reference_modes';old.mkdir();small_search(old)
    rows=[];inputs=folder/'inputs';inputs.mkdir()
    with (folder/'repair_rows.jsonl').open('w',encoding='utf-8',buffering=1) as stream:
        for seed in range(15000,15035):
            graph,cfg=case(seed)
            sha=freeze_case(inputs,str(seed),graph,cfg)
            optimum=enumerate_oracle(graph,**cfg).J
            for mode in ('zero','mass_lb','stdc_lb'):
                for eps in (1.,1.04,1.1):
                    reference=search_module.search_asar(graph,**cfg,heuristic=mode,epsilon=eps)
                    for dominance in (False,True):
                        stats={};tic=perf_counter()
                        result=search_module.search_asar(graph,**cfg,heuristic=mode,epsilon=eps,
                            exact_dominance=dominance,heuristic_cache_size=4096,reuse_stats=stats)
                        wall=perf_counter()-tic
                        score=replay_result(graph,cfg,result,oracle=optimum)
                        if not dominance:
                            require(asdict(result)==asdict(reference),'h cache changed search result/counts')
                        row=dict(seed=seed,forcing_kind='synthetic_toy',input_sha256=sha,
                            exact_dominance=dominance,stats=stats,wall_s=wall,oracle=optimum,
                            replay_error=abs(score.J-result.J),Pd_T=score.pd_final,**asdict(result))
                        stream.write(json.dumps(row,allow_nan=False)+'\n');rows.append(row)
            print(f'small case {seed}: cumulative repair searches={len(rows)}',flush=True)
    save(folder/'small_search.json',dict(status='passed',cases=35,historical_searches=490,
        repair_searches=len(rows),independent_replays=490+len(rows),rows=rows))


def real_worker(run,folder,variant,epsilon,repeat):
    protocol,graph,cfg,pt,times,raw=load_real()
    mode,dominance,cache,legacy=VARIANTS[variant]
    engine=load_reference(run,'search') if legacy else search_module
    if legacy:
        original_heuristic=load_reference(run,'heuristic')
        original_heuristic.STDCHeuristic=load_reference(run,'stdc_heuristic').STDCHeuristic
        heuristic_class=original_heuristic.Heuristic
    else:heuristic_class=Heuristic
    stats={};counter=dict(calls=0,wall_s=0.);estimators=[]
    def factory(*args,**kwargs):
        estimator=heuristic_class(*args,**kwargs)
        estimators.append(estimator)
        def timed(*a,**kw):
            tic=perf_counter()
            try: return estimator(*a,**kw)
            finally: counter['calls']+=1;counter['wall_s']+=perf_counter()-tic
        return timed
    # Same tracing work for every variant; no belief serialization or trace file I/O.
    observed=dict(max_generated_depth=0,max_popped_depth=0,complete_candidates=0,
        scope='trace-observed push/prune/dominance_prune; a final budget-boundary node can lack an event')
    def trace(row):
        if row['event'] in ('push','prune','dominance_prune'):
            observed['max_generated_depth']=max(observed['max_generated_depth'],row['depth'])
            observed['complete_candidates']+=int(row['depth']==cfg['budget'])
        if row['event']=='pop':observed['max_popped_depth']=max(observed['max_popped_depth'],row['depth'])
    previous=engine.Heuristic;engine.Heuristic=factory
    try:
        options={} if legacy else dict(exact_dominance=dominance,heuristic_cache_size=cache,reuse_stats=stats)
        tic=perf_counter()
        result=engine.search_asar(graph,**cfg,heuristic=mode,epsilon=epsilon,
            initial_path=protocol['initial_path'],trace=trace,**protocol['search_limits'],**options)
        elapsed=perf_counter()-tic
    finally: engine.Heuristic=previous
    score=replay_result(graph,cfg,result)
    require(score.J<=pt.J+1e-10,'incumbent worse than initial PT')
    if variant in ('paper_reference','mass_reference','stdc_reference','stdc_geometry','stdc_cache'):
        old=read(OLD/f"paired_comparison/{mode}_eps_{str(epsilon).replace('.','p')}_rep_0/{mode}.json")
        for key in ('J','path','status','stop_reason','expanded','generated','pruned','peak_open','incumbent_source'):
            actual=getattr(result,key);actual=list(actual) if key=='path' else actual
            require(actual==old[key],f'unchanged reference mismatch: {variant}/{key}')
    geometry=[h._stdc.geometry_cache_info() for h in estimators
              if h._stdc is not None and hasattr(h._stdc,'geometry_cache_info')]
    mem=psutil.Process().memory_info()
    save(folder/'result.json',dict(variant=variant,repeat=repeat,**asdict(result),
        search_wall_s=elapsed,heuristic_calls=counter['calls'],heuristic_wall_s=counter['wall_s'],
        reuse_stats=stats,geometry_cache=geometry,depth_stats=observed,
        process_peak_memory_mib=getattr(mem,'peak_wset',mem.rss)/2**20,
        memory_scope='isolated worker peak working set, including verification and replay',
        Pd_T=score.pd_final,replay_J=score.J,replay_error=abs(score.J-result.J),legal=True,
        survival=score.survival.tolist(),cumulative_J=score.g.tolist(),
        forcing_kind='historical_real',particle_sha256=protocol['particle_archive']['sha256'],
        seed=41,verified_raw_sources=raw,limits=protocol['search_limits'],PT_J=pt.J,
        time_utc=[str(t)+'Z' for t in times],guarantee='conditional discrete epsilon' if result.theory_certified else 'uncertified'))
    print(json.dumps(dict(variant=variant,epsilon=epsilon,J=result.J,status=result.status,
        stop_reason=result.stop_reason,expanded=result.expanded,wall_s=elapsed,stats=stats)),flush=True)


def real_runs(run,folder,smoke):
    protocol,_,_,_,_,_=load_real()
    variants=['mass_reuse','stdc_reuse'] if smoke else list(VARIANTS)
    rows=[]
    for epsilon in ([1.1] if smoke else protocol['epsilon']):
        for repeat in range(1 if smoke else 3):
            for variant in variants[repeat:]+variants[:repeat]:
                target=folder/f"{variant}_eps_{str(epsilon).replace('.','p')}_rep_{repeat}";target.mkdir()
                command=[sys.executable,__file__,'real_worker','--run-dir',str(run),
                    '--output-dir',str(target),'--variant',variant,'--epsilon',str(epsilon),'--repeat',str(repeat)]
                save(target/'command.json',dict(command=command,seed=41,threads=1,watchdog_s=150))
                with (target/'stdout.txt').open('w') as stdout,(target/'stderr.txt').open('w') as stderr:
                    try: proc=subprocess.run(command,cwd=ROOT,stdout=stdout,stderr=stderr,timeout=150)
                    except subprocess.TimeoutExpired:
                        save(target/'watchdog.json',dict(status='budget_exceeded',stop_reason='watchdog',
                             theory_certified=False,incumbent_source=None,J=None));raise
                require(proc.returncode==0,'real worker failed: '+target.name)
                row=read(target/'result.json');rows.append(row)
                save(folder/'results.json',dict(status='running',rows=rows))
                print(f"{len(rows)}: {target.name} J={row['J']:.9f} {row['status']} {row['stop_reason']} wall={row['search_wall_s']:.3f}s",flush=True)
    save(folder/'results.json',dict(status='passed',rows=rows))


def stage(run,name):
    for prior in ORDER[:ORDER.index(name)]:
        require(read(run/prior/'stage.json')['status']=='passed','prior stage not passed: '+prior)
    folder=run/name;folder.mkdir(exist_ok=False)
    stage_seeds=read(run/'preflight.json')['plan']['synthetic_seeds'] if name in ('random_audit','small_search') else 41
    if name=='new_tests':stage_seeds=[0,5,7,11,12,13,93,615,4517]
    if name=='full_tests':stage_seeds='explicit seeds and frozen fixtures in source_sha256.json; includes particle seed 41'
    record=dict(status='running',stage=name,started_utc=datetime.now(timezone.utc).isoformat(),seeds=stage_seeds)
    tests=['tests/test_stdc_optimization.py','tests/test_search_state_reuse.py','tests/test_stdc_heuristic.py']
    command=[sys.executable,'-m','pytest','-x','-q','-p','no:cacheprovider']
    if name=='new_tests':command+=tests
    if name in ('new_tests','full_tests'):
        temp=Path('C:/Users/35448/Documents/Codex/2026-11-23/new-chat-4')/'stdc_repair_tmp'/run.name/name
        # pytest creates the leaf basetemp without parents=True.
        temp.parent.mkdir(parents=True,exist_ok=True)
        command+=['--junitxml',str(folder/'pytest.xml'),'--basetemp',
            str(temp)]
    elif name=='random_audit':
        command=[sys.executable,'scripts/stdc_validation_guards.py','random_audit','--output-dir',str(folder)]
    else:command=[sys.executable,__file__,name+'_worker','--run-dir',str(run),'--output-dir',str(folder)]
    record['command']=command;save(folder/'stage.json',record);tic=perf_counter()
    try:
        record['preservation_before']=preserve(run);snapshot(folder)
        with (folder/'stdout.txt').open('w',encoding='utf-8') as stdout,(folder/'stderr.txt').open('w',encoding='utf-8') as stderr:
            proc=subprocess.run(command,cwd=ROOT,stdout=stdout,stderr=stderr,timeout=1200)
        record['exit_code']=proc.returncode
        if (folder/'pytest.xml').exists():
            suites=ET.parse(folder/'pytest.xml').getroot()
            counts={k:sum(int(s.get(k,0)) for s in suites.iter('testsuite')) for k in ('tests','errors','failures','skipped')}
            record['test_counts']=counts
            require(counts['errors']==counts['failures']==counts['skipped']==0,'pytest failure/error/skip: STOP')
            require(counts['tests']>0,'empty pytest collection')
        require(proc.returncode==0,'stage failed: STOP; inspect stdout/stderr')
        record['preservation_after']=preserve(run);record['status']='passed'
    except Exception as exc:
        record.update(status='blocked',error=str(exc),traceback=traceback.format_exc())
    finally:
        record['wall_s']=perf_counter()-tic;save(folder/'stage.json',record)
        known={s:read(run/s/'stage.json') for s in ORDER if (run/s/'stage.json').exists()}
        save(run/'validation_summary.json',dict(status='blocked' if any(v['status']=='blocked' for v in known.values())
             else 'passed' if len(known)==len(ORDER) else 'in_progress',stages=known,not_run=[s for s in ORDER if s not in known]))
    print(json.dumps(record,ensure_ascii=False),flush=True)
    return 0 if record['status']=='passed' else 2


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['init',*ORDER,'small_search_worker','lake_smoke_worker','comparison_worker','real_worker'])
    parser.add_argument('--run-dir',type=Path,required=True)
    parser.add_argument('--output-dir',type=Path)
    parser.add_argument('--variant',choices=VARIANTS)
    parser.add_argument('--epsilon',type=float,default=1.1)
    parser.add_argument('--repeat',type=int,default=0)
    args=parser.parse_args();run=args.run_dir.resolve()
    require(run.is_relative_to(ROOT/'outputs/stdc_v0_2'),'research output required')
    if args.action=='init':init(run)
    elif args.action in ORDER:sys.exit(stage(run,args.action))
    else:
        try:
            if args.action=='small_search_worker':small_worker(args.output_dir)
            elif args.action=='real_worker':real_worker(run,args.output_dir,args.variant,args.epsilon,args.repeat)
            else:real_runs(run,args.output_dir,args.action=='lake_smoke_worker')
        except Exception as exc:
            save(args.output_dir/'failure.json',dict(status='blocked',error=str(exc),traceback=traceback.format_exc()));raise
