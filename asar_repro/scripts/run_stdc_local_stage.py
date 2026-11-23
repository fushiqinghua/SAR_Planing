"""Sequential local acceptance harness; stop on every failed stage.

The delivery is applied unchanged. Extra validation lives outside its algorithm.
Run stages individually in ORDER so an assertion failure stops the entire sequence.
"""

import argparse
from datetime import datetime, timezone
import difflib
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
from time import perf_counter
import traceback
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
ORDER = ('dry_run', 'apply', 'new_tests', 'full_tests', 'random_audit', 'small_search', 'lake_smoke')
PAYLOAD = ('src/asar_repro/stdc_heuristic.py', 'tests/test_stdc_heuristic.py',
           'scripts/run_stdc_random_audit.py', 'scripts/run_stdc_small_search.py',
           'scripts/run_stdc_smoke.py', 'scripts/run_stdc_synthetic_bench.py')


def read(path):
    return json.loads(path.read_bytes())


def save(path, data):
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False, allow_nan=False)+'\n', encoding='utf-8')


def sha(path):
    with path.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def require(value, message):
    if not value:
        raise AssertionError(message)


def git(*args, cwd=ROOT):
    return subprocess.check_output(['git', *args], cwd=cwd)


def preserved(preflight, patched):
    baseline = Path(preflight['baseline_root'])
    require(git('branch','--show-current').decode().strip()=='stdc-research-v0.2', 'research branch mismatch')
    require(git('rev-parse','baseline-v1.1').decode().strip()==preflight['base_commit'], 'baseline branch moved')
    require(git('branch','--show-current',cwd=baseline).decode().strip()=='baseline-v1.1','baseline checkout changed')
    for name, expected in preflight['baseline_all_preserved'].items():
        require(sha(baseline/name)==expected, 'baseline file modified: '+name)
    for name, expected in preflight['baseline_tracked'].items():
        if name in preflight.get('authorized_research_changes', {}):
            require(sha(ROOT/name)==preflight['authorized_research_changes'][name],
                    'research change differs from reviewed revision: '+name)
            continue
        if patched and name=='src/asar_repro/heuristic.py':
            continue
        require(sha(ROOT/name)==expected, 'protected research copy modified: '+name)
    for name, expected in preflight['raw_copies'].items():
        require(sha(ROOT/name)==expected, 'raw forcing copy modified: '+name)


def diff_snapshot(folder, tag):
    (folder/(tag+'.git.diff')).write_bytes(git('diff','HEAD','--binary'))
    (folder/(tag+'.git.status')).write_bytes(git('status','--short'))
    paths=(*PAYLOAD, 'src/asar_repro/heuristic.py', 'scripts/run_stdc_local_stage.py',
           'scripts/stdc_validation_guards.py', 'scripts/stdc_audit_contract.py',
           'tests/conftest.py','tests/test_stdc_audit_contract.py','tests/test_stdc_validation_guards.py',
           'tests/test_b4_artifacts.py','tests/test_b6_comparison.py')
    save(folder/(tag+'.source_sha256.json'),{p:sha(ROOT/p) for p in paths if (ROOT/p).is_file()})


def stage(stage, run):
    require(run.is_relative_to(ROOT/'outputs/stdc_v0_2'), 'outputs must stay under research output root')
    preflight=read(run/'00_preflight.json')
    order = ORDER
    if preflight.get('authorized_resume'):
        require(preflight['previous_attempt_status']=='blocked', 'retain original blocked status')
        require(bool(preflight.get('user_authorization')), 'explicit resume authorization required')
        order = ORDER[2:]
        require(stage in order, 'patch already applied and frozen in prior attempt')
    for previous in order[:order.index(stage)]:
        require(read(run/previous/'stage.json')['status']=='passed', 'prior stage not passed: '+previous)
    folder=run/stage
    require(not folder.exists(), 'refusing stage overwrite or automatic retry')
    folder.mkdir()
    record=dict(stage=stage,status='running',started_utc=datetime.now(timezone.utc).isoformat(),
                source_commit=git('rev-parse','HEAD').decode().strip(),
                baseline_commit=preflight['base_commit'],branch='stdc-research-v0.2',
                interpreter=sys.executable,versions=preflight['versions'],test_total=None)
    seed=dict(dry_run=None,apply=None,new_tests=[5,7,11,13,93,12],
              full_tests='frozen test fixtures and explicit seeds; source hashes in preflight',
              random_audit=dict(matrix=list(range(100,180)),particles=list(range(100,180))),
              small_search=list(range(15000,15035)),lake_smoke=dict(particle_seed=41,search='deterministic'))
    record['seeds']=seed[stage]
    delivery=Path(preflight['delivery_root'])
    patch_script=delivery/'patch/scripts/apply_stdc_patch.py'
    commands={
        'dry_run':[str(patch_script),'--repo',str(ROOT),'--dry-run'],
        'apply':[str(patch_script),'--repo',str(ROOT)],
        'new_tests':['-m','pytest','-x','-q','tests/test_stdc_heuristic.py',
                     'tests/test_stdc_audit_contract.py','tests/test_stdc_validation_guards.py',
                     '--junitxml',str(folder/'pytest.xml')],
        'full_tests':['-m','pytest','-x','-q','--junitxml',str(folder/'pytest.xml')],
        'random_audit':['scripts/stdc_validation_guards.py','random_audit','--output-dir',str(folder)],
        'small_search':['scripts/stdc_validation_guards.py','small_search','--output-dir',str(folder)],
        'lake_smoke':['scripts/stdc_validation_guards.py','lake_smoke','--output-dir',str(folder)],
    }
    record['command']=[sys.executable,*commands[stage]]
    save(folder/'stage.json',record)
    started=perf_counter()
    try:
        preserved(preflight,patched=stage not in ('dry_run','apply'))
        for name, expected in preflight['delivery_sha256'].items():
            require(sha(delivery/name)==expected,'delivery changed: '+name)
        diff_snapshot(folder,'before')
        with (folder/'stdout.txt').open('w',encoding='utf-8') as stdout, (folder/'stderr.txt').open('w',encoding='utf-8') as stderr:
            proc=subprocess.run(record['command'],cwd=ROOT,stdout=stdout,stderr=stderr,timeout=900)
        record['exit_code']=proc.returncode
        if stage in ('new_tests','full_tests') and (folder/'pytest.xml').is_file():
            suites=ET.parse(folder/'pytest.xml').getroot()
            counts={k:sum(int(s.get(k,0)) for s in suites.iter('testsuite'))
                    for k in ('tests','failures','errors','skipped')}
            record['test_total']=counts['tests'];record['test_counts']=counts
        require(proc.returncode==0,'stage process failed; see stderr/stdout; STOP')
        if stage=='dry_run':
            spec=importlib.util.spec_from_file_location('delivered_apply',patch_script)
            module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
            text=(ROOT/'src/asar_repro/heuristic.py').read_text(encoding='utf-8')
            anchors=(
                'from .motion import MatrixMotion, ParticleMotion\n',
                'MODES = ("zero", "mass_lb", "paper_greedy", "paper_literal_abs_time")\nBOUND_MODES = ("zero", "mass_lb")\n',
                '        self.mode = mode\n        self._reachable = {}\n',
                '        b = undetected_mass(belief, self.motion.state_size)\n        if self.mode == "mass_lb":\n')
            counts=[text.count(a) for a in anchors]
            require(counts==[1]*4,'patch anchors must occur exactly once')
            changed=module.patch_heuristic(text)
            save(folder/'anchors.json',dict(counts=counts,targets=list(PAYLOAD),
                 only_existing_source_change='src/asar_repro/heuristic.py',
                 predicted_utf8_lf_sha256=hashlib.sha256(changed.encode()).hexdigest()))
            (folder/'planned_heuristic.diff').write_text(''.join(difflib.unified_diff(
                text.splitlines(True),changed.splitlines(True),fromfile='a/src/asar_repro/heuristic.py',
                tofile='b/src/asar_repro/heuristic.py')),encoding='utf-8')
        elif stage=='apply':
            for name in PAYLOAD:
                require(sha(ROOT/name)==sha(delivery/'patch'/name),'payload differs from delivery: '+name)
            text=(ROOT/'src/asar_repro/heuristic.py').read_text(encoding='utf-8')
            require(hashlib.sha256(text.encode()).hexdigest()==read(run/'dry_run/anchors.json')['predicted_utf8_lf_sha256'],
                    'installed heuristic differs from reviewed patch')
        elif stage in ('new_tests','full_tests'):
            suites=ET.parse(folder/'pytest.xml').getroot()
            counts={k:sum(int(s.get(k,0)) for s in suites.iter('testsuite')) for k in ('tests','failures','errors','skipped')}
            record['test_total']=counts['tests'];record['test_counts']=counts
            require(counts['failures']==counts['errors']==counts['skipped']==0,'failure/error/skip blocks acceptance')
            expected=preflight.get('expected_test_counts',{'new_tests':19,'full_tests':272})[stage]
            require(counts['tests']==expected,'unexpected collection count')
        else:
            record['guard_checks']=read(folder/'guard_summary.json')
            require(record['guard_checks']['status']=='passed','guard did not pass')
        preserved(preflight,patched=stage!='dry_run')
        record['status']='passed'
    except Exception as exc:
        record.update(status='blocked',error=str(exc),traceback=traceback.format_exc())
    finally:
        record['wall_s']=perf_counter()-started
        diff_snapshot(folder,'after')
        save(folder/'stage.json',record)
        known={name:read(run/name/'stage.json') for name in order if (run/name/'stage.json').exists()}
        save(run/'validation_summary.json',dict(status='blocked' if any(r['status']=='blocked' for r in known.values())
             else ('passed' if len(known)==len(order) else 'in_progress'),stages=known,
             not_run=[name for name in order if name not in known]))
    print(json.dumps(dict(stage=stage,status=record['status'],exit_code=record.get('exit_code'),
                         tests=record.get('test_counts'),wall_s=record['wall_s'],error=record.get('error')),ensure_ascii=False),flush=True)
    return 0 if record['status']=='passed' else 2


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage',choices=ORDER)
    parser.add_argument('--run-dir',type=Path,default=ROOT/'outputs/stdc_v0_2/local_validation_20261123')
    args=parser.parse_args()
    sys.exit(stage(args.stage,args.run_dir.resolve()))
