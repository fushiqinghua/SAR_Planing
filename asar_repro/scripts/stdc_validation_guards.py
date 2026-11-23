"""Fail-fast, fully recorded validation around the unchanged STDC delivery.

Case generators, planner, scorer and DFS Oracle are reused unchanged. This
driver adds input preservation, per-prefix evidence, independent route replay
and pinned real-data gates; it does not implement a new planner or objective.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from time import perf_counter
import traceback
from unittest.mock import patch

import numpy as np
import psutil

from asar_repro.grid import GridGraph
from asar_repro.heuristic import Heuristic, BOUND_MODES
from asar_repro.motion import MatrixMotion, ParticleMotion
from asar_repro.objective import score_path
from asar_repro.oracle import enumerate_oracle
import asar_repro.search as search_module
from run_stdc_random_audit import make_case, paths_prefixes
from run_stdc_small_search import case as small_case
from stdc_audit_contract import ROOT

ATOL = 1e-10
MODES = ('mass_lb', 'reach_lb', 'capacity_lb', 'stepwise_lb', 'stdc_radius_lb', 'stdc_lb')
PROTOCOL = 'outputs/baseline_v1.1/b7_final/frozen_experiment_protocol.json'
PROTOCOL_SHA = 'bc18ddcb922231168aef34d8805bd3f7388a2b3ed9c27e9522368141fa469ff7'
PARTICLE_SHA = '8b30a87e543f1b33c39e70e1d0054e1750ec046ba2e0b627dd311d9945749456'


def require(ok, message):
    if not ok:
        raise AssertionError(message)


def read(path):
    return json.loads(path.read_bytes())


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf-8')


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def freeze_case(folder, name, grid, cfg):
    motion = cfg['motion']
    data = dict(grid=[grid.rows, grid.cols], start=cfg['start'], T=cfg['budget'],
                p=np.asarray(cfg['p']).tolist(), q=np.asarray(cfg['q']).tolist(),
                forcing_kind='synthetic_toy', time_zero='no sensing', objective='sum M[1:T+1]')
    if isinstance(motion, MatrixMotion):
        mats = [p.toarray() for p in motion._matrices]
        require(all(np.all(p >= 0) and np.allclose(p.sum(axis=1), 1, atol=1e-12, rtol=0)
                    for p in mats), 'invalid stochastic motion input')
        data.update(motion_kind='matrix', repeat=motion._repeat, matrices=[p.tolist() for p in mats])
    else:
        data.update(motion_kind='particles', cell_ids=motion.cell_ids.tolist(),
                    trajectory_ids=motion.trajectory_ids.tolist(), special_bins=4)
    require(abs(float(np.sum(cfg['p']))-1) <= 1e-12, 'initial mass not one')
    path = folder/(name+'.json')
    save(path, data)
    return digest(path)


def check_score(score):
    require(np.all(np.isfinite(score.survival)), 'non-finite mass')
    require(score.g[0] == 0 and abs(score.survival[0]-1) <= 1e-12, 't=0 convention changed')
    require(np.min(score.survival) >= -1e-12 and np.max(np.diff(score.survival), initial=0) <= 1e-12,
            'remaining mass increased or became negative')
    require(abs(float(score.survival[1:].sum())-score.J) <= ATOL, 'objective mismatch')
    require(abs(float(score.delta_pd.sum())-score.pd_final) <= ATOL, 'Pd mass balance mismatch')


def random_audit(folder):
    inputs = folder/'inputs'; inputs.mkdir()
    roots = []; count = 0; max_overrun = 0.; max_dominance = 0.
    timings = dict.fromkeys(MODES, 0.)
    started = perf_counter()
    with (folder/'prefixes.jsonl').open('w', encoding='utf-8', buffering=1) as stream:
        for kind in ('matrix', 'particles'):
            for seed in range(100, 180):
                grid, start, T, p, q, motion = make_case(seed, kind)
                cfg = dict(start=start, budget=T, p=p, q=q, motion=motion)
                identity = freeze_case(inputs, f'{kind}_{seed}', grid, cfg)
                estimates = {m:Heuristic(grid, budget=T, q=q, motion=motion, mode=m) for m in MODES}
                for path in paths_prefixes(grid, start, T):
                    depth = len(path)-1
                    prefix = score_path(grid, path, **{**cfg, 'budget':depth})
                    check_score(prefix)
                    optimum = enumerate_oracle(grid, **cfg, prefix=path)
                    remaining = optimum.J-prefix.J
                    values = {}
                    for mode, estimator in estimates.items():
                        tic = perf_counter()
                        values[mode] = estimator(path[-1], depth, prefix.final_belief)
                        timings[mode] += perf_counter()-tic
                    row = dict(kind=kind, seed=seed, input_sha256=identity, path=list(path),
                               prefix_J=prefix.J, prefix_mass=float(prefix.survival[-1]),
                               oracle_remaining=remaining, h=values)
                    stream.write(json.dumps(row, allow_nan=False)+'\n')
                    save(folder/'last_checked.json', row)
                    for mode, value in values.items():
                        require(np.isfinite(value) and -ATOL <= value <= remaining+ATOL,
                                f'admissibility failure at {kind}/{seed}/{path}/{mode}')
                        max_overrun = max(max_overrun, value-remaining)
                    dominance = max(values[m]-values['stdc_lb'] for m in MODES)
                    max_dominance = max(max_dominance, dominance)
                    require(dominance <= ATOL, f'STDC dominance failure at {kind}/{seed}/{path}')
                    count += 1
                    if depth == 0:
                        roots.append(dict(kind=kind, seed=seed, oracle=remaining, values=values))
                if (seed-99) % 20 == 0:
                    print(f'{kind} cases={seed-99} prefixes={count}', flush=True)
    result = dict(status='passed', forcing_kind='synthetic_toy', scenario_counts={'matrix':80,'particles':80},
                  prefix_evaluations=count, violations=0, positive_overestimation=max_overrun,
                  mass_and_other_dominance_violation=max_dominance, atol=ATOL, roots=roots,
                  root_h_over_opt_mean={m:float(np.mean([r['values'][m]/r['oracle'] for r in roots
                                                        if r['oracle']>ATOL])) for m in MODES},
                  heuristic_time_s=timings, total_wall_s=perf_counter()-started)
    save(folder/'random_audit.json', result)
    return dict(status='passed', cases=160, prefix_evaluations=count, violations=0)


def replay_result(grid, cfg, result, *, oracle=None):
    require(result.status in ('completed','budget_exceeded'), 'unknown search outcome')
    require(not result.theory_certified or (result.status=='completed' and result.heuristic_mode in BOUND_MODES),
            'invalid certification')
    require(result.heuristic_mode not in ('paper_greedy','paper_literal_abs_time') or not result.theory_certified,
            'paper reproduction cannot be certified')
    if result.status=='budget_exceeded':
        require(result.stop_reason is not None and not result.theory_certified, 'budget stop certified')
    require(result.path is not None, 'expected a complete incumbent for this validation')
    score = score_path(grid, result.path, **cfg)
    check_score(score)
    require(abs(score.J-result.J) <= ATOL, 'independent J replay failed')
    if oracle is not None:
        require(result.status=='completed' and result.theory_certified, 'small search did not complete')
        require(oracle-ATOL <= score.J <= result.epsilon*oracle+ATOL, 'Oracle epsilon comparison failed')
        if result.epsilon == 1:
            require(abs(score.J-oracle) <= ATOL, 'epsilon=1 must equal Oracle')
    return score


def small_search(folder):
    inputs=folder/'inputs'; inputs.mkdir()
    rows=[]
    with (folder/'search_rows.jsonl').open('w',encoding='utf-8',buffering=1) as stream:
        for seed in range(15000,15035):
            grid,cfg=small_case(seed)
            identity=freeze_case(inputs,str(seed),grid,cfg)
            oracle=enumerate_oracle(grid,**cfg).J
            for epsilon in (1.,1.1):
                for mode in ('zero',*MODES):
                    tic=perf_counter()
                    result=search_module.search_asar(grid,**cfg,heuristic=mode,epsilon=epsilon)
                    wall=perf_counter()-tic
                    raw=dict(seed=seed,input_sha256=identity,oracle=oracle,search_wall_s=wall,**asdict(result))
                    save(folder/'last_checked.json',raw)
                    score=replay_result(grid,cfg,result,oracle=oracle)
                    raw.update(Pd_T=score.pd_final, replay_J=score.J, replay_error=abs(score.J-result.J),
                               J_minus_oracle=score.J-oracle, legal=True, forcing_kind='synthetic_toy')
                    stream.write(json.dumps(raw,allow_nan=False)+'\n'); rows.append(raw)
            if (seed-14999)%5==0: print(f'small cases={seed-14999}, searches={len(rows)}',flush=True)
    aggregate=[]
    for eps in (1.,1.1):
        for mode in ('zero',*MODES):
            group=[r for r in rows if r['epsilon']==eps and r['heuristic_mode']==mode]
            aggregate.append(dict(mode=mode,epsilon=eps,cases=len(group),
                expanded_mean=float(np.mean([r['expanded'] for r in group])),
                time_ms_mean=1000*float(np.mean([r['search_wall_s'] for r in group])),
                max_replay_error=max(r['replay_error'] for r in group),
                max_J_minus_oracle=max(r['J_minus_oracle'] for r in group)))
    save(folder/'small_search.json',dict(status='passed',cases=35,searches=len(rows),rows=rows,aggregate=aggregate))
    return dict(status='passed',cases=35,searches=len(rows),independent_replays=len(rows))


def load_real():
    require(digest(ROOT/PROTOCOL)==PROTOCOL_SHA,'frozen protocol SHA mismatch')
    protocol=read(ROOT/PROTOCOL)
    require(protocol['forcing_kind']=='historical_real','real forcing label changed')
    require(protocol['mission']['grid_rows_cols']==[17,17] and protocol['mission']['budget']==49
            and protocol['mission']['audit_q']==.78,'frozen mission changed')
    archive=ROOT/protocol['particle_archive']['path']
    require(protocol['particle_archive']['sha256']==PARTICLE_SHA and digest(archive)==PARTICLE_SHA,
            'real particle SHA mismatch; synthetic substitution forbidden')
    meta_path=archive.with_name('metadata.json')
    require(digest(meta_path)==protocol['particle_metadata_sha256'],'metadata SHA mismatch')
    meta=read(meta_path)
    require(meta['provenance']['input_fingerprints']['manifest_sha256']==protocol['source_manifest_sha256'],
            'source manifest identity changed')
    raw=[]
    for sources in protocol['original_forcing'].values():
        for item in sources:
            name=item['local_path']; expected=item.get('subset_sha256') or item['sha256']
            require(digest(ROOT/name)==expected,'forcing source SHA mismatch: '+name)
            raw.append(dict(path=name,sha256=expected))
    for name,expected in protocol['score_code_sha256'].items():
        require(digest(ROOT/f'src/asar_repro/{name}.py')==expected,'frozen evaluator changed: '+name)
    from asar_repro.opendrift_adapter import planning_times
    from asar_repro.scenarios import config_digest
    cfg=protocol['mission']
    require(meta['status']=='passed' and meta['forcing_kind']=='historical_real','invalid B3 provenance')
    require(meta['provenance']['config']==cfg,'B3 mission differs from frozen protocol')
    require(config_digest(protocol['initial_path'])==protocol['initial_path_sha256'],'PT path SHA mismatch')
    with np.load(archive,allow_pickle=False) as z:
        cells=z['cell_ids'].copy(); ids=z['trajectory_id'].copy(); w=z['initial_weights'].copy()
        times=z['time_utc'].copy()
        require(z['config_hash'].item()==meta['config_hash'],'particle configuration identity changed')
    require(cells.shape==(50,500) and np.unique(ids).size==500,'real archive dimensions/IDs changed')
    expected_times=planning_times(cfg['cst_utc'],49,cfg['step_s'])
    require(np.array_equal(times,expected_times),'absolute UTC clock changed')
    graph=GridGraph(17,17)
    args=dict(start=protocol['start_vertex'],budget=49,p=w,q=.78,motion=ParticleMotion(cells,289,ids))
    pt=score_path(graph,tuple(protocol['initial_path']),**args)
    check_score(pt)
    require(abs(pt.J-protocol['initial_J'])<=ATOL,'frozen PT J changed')
    require(protocol['search_limits']==dict(max_expansions=5000,max_open=20000,max_seconds=30),
            'frozen search budget changed')
    return protocol,graph,args,pt,times,raw


def lake_worker(folder,mode):
    t0=perf_counter()
    protocol,graph,cfg,pt,times,raw=load_real()
    pre_s=perf_counter()-t0
    root_h=Heuristic(graph,budget=49,q=.78,motion=cfg['motion'],mode=mode)(cfg['start'],0,cfg['p'])
    counter={'calls':0,'wall_s':0.}
    base=search_module.Heuristic
    def factory(*args,**kwargs):
        h=base(*args,**kwargs)
        def timed(*a,**kw):
            start=perf_counter()
            try: return h(*a,**kw)
            finally:
                counter['calls']+=1; counter['wall_s']+=perf_counter()-start
        return timed
    with patch.object(search_module,'Heuristic',factory):
        tic=perf_counter()
        result=search_module.search_asar(graph,**cfg,heuristic=mode,epsilon=1.1,
                   initial_path=tuple(protocol['initial_path']),**protocol['search_limits'])
        search_s=perf_counter()-tic
    score=replay_result(graph,cfg,result)
    require(score.J<=pt.J+ATOL,'incumbent is worse than supplied PT')
    if result.incumbent_source=='initial_path':
        require(tuple(result.path)==tuple(protocol['initial_path']),'initial incumbent source mismatch')
    mem=psutil.Process().memory_info()
    row=dict(**asdict(result),Pd_T=score.pd_final,replay_J=score.J,replay_error=abs(score.J-result.J),
        legal=True,mode=mode,forcing_kind='historical_real',experiment_label=protocol['experiment_label'],
        particle_sha256=PARTICLE_SHA,protocol_sha256=PROTOCOL_SHA,particle_seed=41,
        incumbent_origin='ParallelTrack' if result.incumbent_source=='initial_path' else result.incumbent_source,
        root_h=root_h,PT_J=pt.J,J_minus_PT=score.J-pt.J,search_wall_s=search_s,
        heuristic_calls=counter['calls'],heuristic_wall_s=counter['wall_s'],preprocessing_s=pre_s,
        process_peak_memory_mib=getattr(mem,'peak_wset',mem.rss)/2**20,
        memory_scope='isolated worker process peak working set; includes preprocessing and replay',
        limits=protocol['search_limits'],verified_raw_sources=raw,time_utc=[str(t)+'Z' for t in times],
        survival=score.survival.tolist(),cumulative_J=score.g.tolist(),
        guarantee='conditional discrete epsilon only' if result.theory_certified else 'uncertified',
        repeat=0,smoke_only=True)
    save(folder/f'{mode}.json',row)
    print(json.dumps({k:row[k] for k in ('mode','status','stop_reason','J','Pd_T','expanded',
          'theory_certified','search_wall_s','process_peak_memory_mib')},allow_nan=False),flush=True)


def lake_smoke(folder):
    protocol,_,_,pt,_,raw=load_real()
    save(folder/'input_gate.json',dict(status='passed',protocol_sha256=PROTOCOL_SHA,
        particle_sha256=PARTICLE_SHA,PT_J=pt.J,verified_raw_sources=raw,limits=protocol['search_limits']))
    rows=[]
    for mode in ('mass_lb','stdc_lb'):
        command=[sys.executable,str(Path(__file__).resolve()),'lake_worker','--output-dir',str(folder),'--mode',mode]
        save(folder/f'{mode}.command.json',dict(command=command,particle_seed=41,threads=1))
        with (folder/f'{mode}.stdout.txt').open('w',encoding='utf-8') as stdout, \
             (folder/f'{mode}.stderr.txt').open('w',encoding='utf-8') as stderr:
            try:
                proc=subprocess.run(command,cwd=ROOT,stdout=stdout,stderr=stderr,timeout=150)
            except subprocess.TimeoutExpired:
                save(folder/f'{mode}.watchdog.json',dict(status='budget_exceeded',stop_reason='watchdog',
                     theory_certified=False,mode=mode,watchdog_s=150,incumbent_source=None,J=None))
                raise
        require(proc.returncode==0,f'{mode} worker failed; stop and inspect stderr')
        row=read(folder/f'{mode}.json'); rows.append(row)
        print(f"{mode}: {row['status']} / {row['stop_reason']}; J={row['J']:.12f}; certified={row['theory_certified']}",flush=True)
    save(folder/'lake_results.json',dict(status='passed',scope='two-mode single-repeat smoke only',
         protocol_sha256=PROTOCOL_SHA,particle_sha256=PARTICLE_SHA,rows=rows))
    return dict(status='passed',runs=2,replays=2,completed=sum(r['status']=='completed' for r in rows),
                budget_exceeded=sum(r['status']=='budget_exceeded' for r in rows),real_input_verified=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage',choices=['random_audit','small_search','lake_smoke','lake_worker'])
    parser.add_argument('--output-dir',type=Path,required=True)
    parser.add_argument('--mode',choices=['mass_lb','stdc_lb'])
    args=parser.parse_args()
    folder=args.output_dir.resolve()
    require(folder.is_relative_to(ROOT/'outputs/stdc_v0_2'),'research outputs only')
    try:
        if args.stage=='lake_worker':
            lake_worker(folder,args.mode)
        else:
            require(not (folder/'guard_summary.json').exists(),'refusing guard result overwrite')
            result=globals()[args.stage](folder)
            save(folder/'guard_summary.json',result)
    except Exception as exc:
        save(folder/(f'{args.mode}.failure.json' if args.stage=='lake_worker' else 'guard_summary.json'),
             dict(status='blocked',error=str(exc),traceback=traceback.format_exc()))
        raise
