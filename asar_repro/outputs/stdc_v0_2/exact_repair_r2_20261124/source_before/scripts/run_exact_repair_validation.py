"""Fail-fast gates for the standalone exact-repair diagnostic, preserving old work."""
import argparse
from pathlib import Path
import subprocess
import sys
from time import perf_counter
import traceback
import xml.etree.ElementTree as ET
from run_optimization_validation import ROOT,read,save,digest,git,sources,snapshot,environment,child_environment,require
from run_adaptive_validation import preservation as old_preservation

PREVIOUS=ROOT/'outputs/stdc_v0_2/adaptive_20261124'
DIAG=ROOT/'outputs/stdc_v0_2/rollout_limit_diagnosis_20261124'
ORDER=('new_tests','oracle','full_tests')
NEW_FILES=('src/asar_repro/exact_repair.py','tests/test_exact_repair.py','scripts/audit_exact_repair.py',
           'scripts/run_exact_repair_validation.py','scripts/run_exact_repair_experiments.py')

def preserved():
    result=old_preservation(PREVIOUS)
    for origin in (PREVIOUS,DIAG):
        table=read(origin/'artifact_sha256.json')['files']
        for name,sha in table.items():require(digest(origin/name)==sha,'old artifact changed: '+str(origin/name))
        result[origin.name+'_artifacts']=len(table)
    old=read(PREVIOUS/'freeze.json')['source_sha256']
    current=sources()
    for name,sha in old.items():require(current.get(name)==sha,'existing source changed: '+name)
    result['existing_source_files']=len(old)
    return result

def summary(run):
    stages={n:read(run/n/'stage.json') for n in ORDER if (run/n/'stage.json').exists()}
    missing=[n for n in ORDER if n not in stages or stages[n]['status']!='passed']
    state='blocked' if any(x['status']=='blocked' for x in stages.values()) else 'in_progress' if missing else 'passed'
    d=dict(status=state,stages=stages,not_run=missing,theory_certified=False)
    save(run/'validation_summary.json',d);return d

def main(run,action):
    if action=='preflight':
        require(not (run/'preflight.json').exists(),'preflight already recorded')
        save(run/'preflight.json',dict(status='passed',environment=environment(),preservation=preserved(),
            source_commit=git('rev-parse','HEAD').decode().strip(),new_files=NEW_FILES,
            historical_tests=1114,seeds=list(range(1041,1089)),scope='standalone exact restricted repair; objective/scorer/forcing frozen'))
        print('preflight passed',flush=True);return 0
    if action=='freeze':
        require(not (run/'freeze.json').exists(),'already frozen')
        for name in NEW_FILES:require((ROOT/name).is_file(),'missing new file '+name)
        save(run/'freeze.json',dict(status='passed',source_sha256=sources(),preservation=preserved(),environment=environment(),seeds=list(range(1041,1089))))
        out=run/'source_freeze';out.mkdir();snapshot(out,run);summary(run)
        print('freeze passed',flush=True);return 0
    if action=='final':
        require(summary(run)['status']=='passed','validation incomplete')
        require(sources()==read(run/'freeze.json')['source_sha256'],'source changed after gates')
        save(run/'final_preservation.json',preserved());print('final preservation passed',flush=True);return 0
    out=run/action;out.mkdir(exist_ok=False);tic=perf_counter();d=dict(status='running',stage=action,cwd=str(ROOT))
    try:
        require(summary(run)['status']!='blocked','prior gate blocked')
        for prior in ORDER[:ORDER.index(action)]:require(read(run/prior/'stage.json')['status']=='passed','prior gate not passed')
        require(sources()==read(run/'freeze.json')['source_sha256'],'source changed')
        snapshot(out,run);env=child_environment()
        if action in ('new_tests','full_tests'):
            cmd=[sys.executable,'-m','pytest','-x','-q','-p','no:cacheprovider',
                 'tests/test_exact_repair.py' if action=='new_tests' else 'tests',
                 '--junitxml',str(out/'pytest.xml'),'--basetemp',str(Path('C:/Users/35448/Documents/Codex/2026-11-23/new-chat-4')/('exact_repair_'+action))]
        else:cmd=[sys.executable,'scripts/audit_exact_repair.py','--output-dir',str(out/'audit')]
        d.update(command=cmd,seeds=list(range(1041,1089)),environment={k:env.get(k) for k in ('PYTHONPATH','PYTHONDONTWRITEBYTECODE','ASAR_OFFLINE','PROJ_NETWORK','OMP_NUM_THREADS','OPENBLAS_NUM_THREADS')})
        save(out/'command.json',d)
        with (out/'stdout.txt').open('w',encoding='utf-8') as stdout,(out/'stderr.txt').open('w',encoding='utf-8') as stderr:
            proc=subprocess.run(cmd,cwd=ROOT,env=env,stdout=stdout,stderr=stderr,timeout=1800)
        d['exit_code']=proc.returncode
        if action in ('new_tests','full_tests'):
            root=ET.parse(out/'pytest.xml').getroot()
            counts={k:sum(int(s.get(k,0)) for s in root.iter('testsuite')) for k in ('tests','errors','failures','skipped')}
            d['test_counts']=counts
            require(counts['tests']>0 and sum(counts[k] for k in ('errors','failures','skipped'))==0,'test failure/error/skip: blocked')
            if action=='full_tests':require(counts['tests']==1114+read(run/'new_tests/stage.json')['test_counts']['tests'],'unexpected test inventory')
        require(proc.returncode==0,'gate process failed: blocked')
        if action=='oracle':
            d['audit']=read(out/'audit/summary.json');require(d['audit']['status']=='passed','Oracle failed: blocked')
        d.update(status='passed',source_sha256=sources())
    except BaseException as exc:
        d.update(status='blocked',error=str(exc),traceback=traceback.format_exc())
        with (out/'stderr.txt').open('a',encoding='utf-8') as f:f.write(d['traceback'])
    d['wall_s']=perf_counter()-tic;save(out/'stage.json',d);summary(run)
    print({k:d.get(k) for k in ('stage','status','test_counts','wall_s','error')},flush=True)
    return 0 if d['status']=='passed' else 2

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('action',choices=('preflight','freeze',*ORDER,'final'));p.add_argument('--run-dir',required=True,type=Path)
    a=p.parse_args();run=a.run_dir.resolve();require(run.is_relative_to(ROOT/'outputs/stdc_v0_2'),'research output only')
    sys.exit(main(run,a.action))
