"""Fresh phase freezes: independent diagnostics first, planning second."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from time import perf_counter
import traceback
import xml.etree.ElementTree as ET

from run_optimization_validation import (ROOT, REPO, OLD, REFERENCE, require, read, save,
    digest, git, git_paths, sources, snapshot, preserve, environment, child_environment)

PREVIOUS=ROOT/'outputs/stdc_v0_2/optimization_20261124_resume/validation/validation_summary.json'
NEW_TESTS={'diagnostic':['tests/test_particle_diagnostic.py'],
           'planning':['tests/test_particle_dp.py','tests/test_midpoint_rollout.py','tests/test_trajectory_search.py']}
ORDER=('new_tests','full_tests','oracle_audit')
TEMP_ROOT=Path('C:/Users/35448/Documents/Codex/2026-11-23/new-chat-4/trajectory_validation_tmp')


def summary(run):
    pre=read(run/'preflight.json')
    stages={name:read(run/name/'stage.json') for name in ORDER if (run/name/'stage.json').exists()}
    blocked=pre['status']=='blocked' or any(s['status']=='blocked' for s in stages.values())
    pending=[name for name in ORDER if name not in stages or stages[name]['status']!='passed']
    data=dict(status='blocked' if blocked else 'in_progress' if pending else 'passed',
              order=ORDER,phase=pre['phase'],stages=stages,not_run=pending,
              source_sha256=pre.get('source_sha256',{}),epsilon_certified=False)
    save(run/'validation_summary.json',data)
    return data


def init(run,phase,prior):
    run.mkdir(parents=True,exist_ok=False)
    data=dict(status='running',phase=phase,command=[sys.executable,*sys.argv],cwd=str(ROOT),
              started_utc=datetime.now(timezone.utc).isoformat())
    try:
        previous=read(prior)
        require(previous['status']=='passed' and not previous['not_run'],'previous gate not passed')
        old=read(OLD)
        current=git('rev-parse','HEAD').decode().strip()
        require(git('branch','--show-current').decode().strip()==old['research_branch'],'wrong branch')
        require(git('merge-base',REFERENCE,current).decode().strip()==REFERENCE,'invalid reference ancestry')
        paths={p for p in git_paths('ls-files')+git_paths('ls-files','--others')
               if p.is_file() and not p.is_relative_to(run)}
        for top in ('data','outputs'):
            paths.update(p for p in (ROOT/top).rglob('*') if p.is_file() and not p.is_relative_to(run))
        data.update(status='passed',source_commit=current,historical_preflight_sha256=digest(OLD),
                    prior_validation=str(prior),prior_validation_sha256=digest(prior),
                    historical_test_count=previous['stages']['full_tests']['test_counts']['tests'],
                    source_sha256=sources(),protected={p.relative_to(REPO).as_posix():digest(p) for p in sorted(paths)},
                    environment=environment(),new_tests=NEW_TESTS[phase],
                    stopping_policy='Any failed historical test or admissibility assertion stops dependent stages',
                    model='unchanged J, original evaluator, four-neighbor moves, no t0 sensing, same archived forcing',
                    target_J=17.264874448,epsilon_certified=False)
        save(run/'preflight.json',data);snapshot(run,run)
        save(run/'preservation_initial.json',preserve(run))
    except Exception as e:data.update(status='blocked',error=str(e),traceback=traceback.format_exc())
    save(run/'preflight.json',data);summary(run)
    print(json.dumps(dict(action='init',status=data['status'],phase=phase,error=data.get('error')),ensure_ascii=False),flush=True)
    return 0 if data['status']=='passed' else 2


def stage(run,name):
    folder=run/name;folder.mkdir(exist_ok=False);started=perf_counter()
    data=dict(status='running',stage=name,command=None,cwd=str(ROOT),driver_command=[sys.executable,*sys.argv])
    try:
        pre=read(run/'preflight.json');phase=pre['phase']
        require(summary(run)['status']!='blocked','run already blocked')
        for prior in ORDER[:ORDER.index(name)] if name in ORDER else ORDER:
            require(read(run/prior/'stage.json')['status']=='passed','prior stage not passed')
        data['preservation_before']=preserve(run);snapshot(folder,run)
        if name=='final_preservation':
            data.update(status='passed',preservation_after=preserve(run))
            (folder/'stdout.txt').write_text('Frozen source and historical files preserved.\n',encoding='utf-8')
            (folder/'stderr.txt').write_text('',encoding='utf-8')
        else:
            env=child_environment()
            if name in ('new_tests','full_tests'):
                command=[sys.executable,'-m','pytest','-x','-q','-p','no:cacheprovider']
                command+=pre['new_tests'] if name=='new_tests' else ['tests']
                temp=TEMP_ROOT/hashlib.sha256(str(run).encode()).hexdigest()[:12]/name
                temp.parent.mkdir(parents=True,exist_ok=True)
                command+=['--junitxml',str(folder/'pytest.xml'),'--basetemp',str(temp)]
                seeds='Fixed explicit fixtures/seeds in frozen source files; no generated random seed'
            else:
                command=[sys.executable,'scripts/audit_trajectory.py',phase,'--output-dir',str(folder/'audit')]
                seeds=list(range(63000,63012)) if phase=='diagnostic' else dict(random=list(range(100,180)),small=list(range(15000,15035)))
            data.update(command=command,seeds=seeds,environment={k:env.get(k) for k in ('PYTHONPATH','PYTHONDONTWRITEBYTECODE','ASAR_OFFLINE','PROJ_NETWORK','OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS')})
            save(folder/'command.json',data)
            with (folder/'stdout.txt').open('w',encoding='utf-8') as out,(folder/'stderr.txt').open('w',encoding='utf-8') as err:
                proc=subprocess.run(command,cwd=ROOT,env=env,stdout=out,stderr=err,timeout=1200)
            data['exit_code']=proc.returncode
            if name in ('new_tests','full_tests'):
                suites=ET.parse(folder/'pytest.xml').getroot()
                counts={k:sum(int(s.get(k,0)) for s in suites.iter('testsuite')) for k in ('tests','errors','failures','skipped')}
                data['test_counts']=counts
                require(counts['tests']>0 and counts['errors']==counts['failures']==counts['skipped']==0,'pytest failure/error/skip: STOP')
                if name=='full_tests':
                    expected=pre['historical_test_count']+read(run/'new_tests/stage.json')['test_counts']['tests']
                    require(counts['tests']==expected,'unexpected full test count')
            require(proc.returncode==0,'validation failed: STOP')
            if name=='oracle_audit':
                audit=read(folder/'audit/summary.json');require(audit['status']=='passed','Oracle gate failed')
                data['audit_summary']=audit
            data.update(status='passed',preservation_after=preserve(run))
    except Exception as e:
        data.update(status='blocked',error=str(e),traceback=traceback.format_exc())
        with (folder/'stderr.txt').open('a',encoding='utf-8') as f:f.write(data['traceback'])
    data['wall_s']=perf_counter()-started;save(folder/'stage.json',data)
    if name!='final_preservation' or data['status']!='passed':summary(run)
    print(json.dumps({k:data.get(k) for k in ('stage','status','test_counts','wall_s','error')},ensure_ascii=False),flush=True)
    return 0 if data['status']=='passed' else 2


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('action',choices=('init',*ORDER,'final_preservation'))
    p.add_argument('--phase',choices=NEW_TESTS,default='diagnostic')
    p.add_argument('--run-dir',type=Path,required=True)
    p.add_argument('--prior-validation',type=Path,default=PREVIOUS)
    args=p.parse_args();run=args.run_dir.resolve()
    require(run.is_relative_to(ROOT/'outputs/stdc_v0_2'),'research output only')
    sys.exit(init(run,args.phase,args.prior_validation.resolve()) if args.action=='init' else stage(run,args.action))
