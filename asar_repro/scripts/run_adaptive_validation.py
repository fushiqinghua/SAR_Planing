"""Recorded fail-fast gates for adaptive STDC; no historical files are rewritten."""
import argparse
from pathlib import Path
import subprocess
import sys
from time import perf_counter
import traceback
import xml.etree.ElementTree as ET
from run_optimization_validation import (
    ROOT,REPO,OLD,read,save,digest,git,sources,snapshot,environment,child_environment,require)
NEW_TESTS=[
 "tests/test_resumable_search.py","tests/test_adaptive_search.py",
 "tests/test_short_window_rollout.py","tests/test_sparse_particle_guide.py",
 "tests/test_compact_particle_dp.py"]
ORDER=("new_tests","oracle","full_tests")
def preservation(run):
    pre=read(run/'preexisting.json');old=read(OLD);base=Path(old['baseline_root'])
    require(digest(OLD)==pre['historical_preflight_sha256'],'old preservation manifest changed')
    require(git('branch','--show-current').decode().strip()=='stdc-research-v0.2','wrong branch')
    require(git('rev-parse','HEAD').decode().strip()==pre['source_commit'],'research HEAD moved')
    require(git('rev-parse','HEAD',cwd=base).decode().strip()==old['base_commit'],'baseline HEAD moved')
    require(git('rev-parse','baseline-v1.1').decode().strip()==old['base_commit'],'baseline ref moved')
    incident=read(run/'transient_cache_incident.json')['files']
    require(set(incident)=={'asar_repro/.pytest_cache/v/cache/lastfailed','asar_repro/.pytest_cache/v/cache/nodeids'},'unexpected preservation exception')
    for name,sha in pre['protected'].items():
        expected=incident[name]['after_sha256'] if name in incident else sha
        require(digest(REPO/name)==expected,'old file changed: '+name)
    for name,sha in old['baseline_all_preserved'].items():require(digest(base/name)==sha,'baseline changed: '+name)
    return dict(status='passed',research_files_byte_unchanged=len(pre['protected'])-len(incident),
        generated_pytest_cache_changes=len(incident),cache_incident_sha256=digest(run/'transient_cache_incident.json'),
        baseline_files=len(old['baseline_all_preserved']))
def summary(run):
    stages={n:read(run/n/'stage.json') for n in ORDER if (run/n/'stage.json').exists()}
    blocked=any(s['status']=='blocked' for s in stages.values())
    pending=[n for n in ORDER if n not in stages or stages[n]['status']!='passed']
    d=dict(status='blocked' if blocked else 'in_progress' if pending else 'passed',
      stages=stages,not_run=pending,source_sha256=read(run/'freeze.json')['source_sha256'],
      global_epsilon_certified=False)
    save(run/'validation_summary.json',d);return d
def freeze(run):
    require(not (run/'freeze.json').exists(),'already frozen')
    for n in NEW_TESTS:require((ROOT/n).is_file(),'missing new test '+n)
    save(run/'freeze.json',dict(status='passed',command=[sys.executable,*sys.argv],
      source_sha256=sources(),preservation=preservation(run),environment=environment(),
      new_tests=NEW_TESTS,historical_test_count=926,seeds=dict(random=list(range(100,180)),small=list(range(15000,15035)))))
    snapshot(run/'source_freeze',run) if (run/'source_freeze').mkdir(exist_ok=False) is None else None
    summary(run);print('source freeze passed',flush=True)
def stage(run,name):
    out=run/name;out.mkdir(exist_ok=False);tic=perf_counter()
    d=dict(status='running',stage=name,driver_command=[sys.executable,*sys.argv],cwd=str(ROOT))
    try:
        require(summary(run)['status']!='blocked','a gate is blocked')
        for prior in ORDER[:ORDER.index(name)]:
            require(read(run/prior/'stage.json')['status']=='passed','prior gate did not pass')
        require(sources()==read(run/'freeze.json')['source_sha256'],'source changed after freeze')
        snapshot(out,run);env=child_environment()
        if name in ('new_tests','full_tests'):
            cmd=[sys.executable,'-m','pytest','-x','-q','-p','no:cacheprovider']
            cmd+=NEW_TESTS if name=='new_tests' else ['tests']
            tmp=Path('C:/Users/35448/Documents/Codex/2026-11-23/new-chat-4')/('adaptive_'+name)
            cmd+=['--junitxml',str(out/'pytest.xml'),'--basetemp',str(tmp)]
        else:cmd=[sys.executable,'scripts/audit_adaptive.py','all','--output-dir',str(out/'audit')]
        d.update(command=cmd,environment={k:env.get(k) for k in ('PYTHONPATH','ASAR_OFFLINE','PROJ_NETWORK','OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS')},
                 seeds=read(run/'freeze.json')['seeds'])
        save(out/'command.json',d)
        with (out/'stdout.txt').open('w',encoding='utf-8') as stdout,(out/'stderr.txt').open('w',encoding='utf-8') as stderr:
            proc=subprocess.run(cmd,cwd=ROOT,env=env,stdout=stdout,stderr=stderr,timeout=1800)
        d['exit_code']=proc.returncode
        if name in ('new_tests','full_tests'):
            xml=ET.parse(out/'pytest.xml').getroot()
            counts={k:sum(int(s.get(k,0)) for s in xml.iter('testsuite')) for k in ('tests','errors','failures','skipped')}
            d['test_counts']=counts
            require(counts['tests']>0 and sum(counts[k] for k in ('errors','failures','skipped'))==0,'test failure/error/skip: STOP')
            if name=='full_tests':
                require(counts['tests']==926+read(run/'new_tests/stage.json')['test_counts']['tests'],'unexpected test inventory')
        require(proc.returncode==0,'gate failed: STOP')
        if name=='oracle':
            d['audit']=read(out/'audit/summary.json');require(d['audit']['status']=='passed','Oracle assertions failed: STOP')
        d.update(status='passed',source_sha256=sources())
    except BaseException as exc:
        d.update(status='blocked',error=str(exc),traceback=traceback.format_exc())
        with (out/'stderr.txt').open('a',encoding='utf-8') as f:f.write(d['traceback'])
    d['wall_s']=perf_counter()-tic;save(out/'stage.json',d);summary(run)
    print({k:d.get(k) for k in ('stage','status','test_counts','wall_s','error')},flush=True)
    return 0 if d['status']=='passed' else 2
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('action',choices=('freeze',*ORDER,'final'))
    p.add_argument('--run-dir',required=True,type=Path);a=p.parse_args();run=a.run_dir.resolve()
    require(run.is_relative_to(ROOT/'outputs/stdc_v0_2'),'research output only')
    if a.action=='freeze':freeze(run)
    elif a.action=='final':
        require(summary(run)['status']=='passed','validation not passed')
        require(sources()==read(run/'freeze.json')['source_sha256'],'source changed')
        save(run/'final_preservation.json',preservation(run));print('final preservation passed')
    else:sys.exit(stage(run,a.action))

