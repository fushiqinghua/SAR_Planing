"""Sequential, fail-fast validation of fixed-time window research changes.

This driver imports only the standard library. Environment versions are read
from package metadata; it neither imports nor runs OpenDrift during preflight.
Historical tests run unchanged, with isolated ASCII temporary directories.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
from time import perf_counter
import traceback
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
OLD = ROOT / 'outputs/stdc_v0_2/local_validation_20261123_r5/00_preflight.json'
REFERENCE = '4a01dee2275ce3b732f619e0192fd1a417a5766e'
ORDER = ('new_tests', 'full_tests', 'random_audit', 'small_search')
TEMP_ROOT = Path('C:/Users/35448/Documents/Codex/2026-11-23/new-chat-4/window_validation_tmp')


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def read(path):
    return json.loads(path.read_bytes())


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n',
                    encoding='utf-8')


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def git(*args, cwd=REPO):
    cwd = Path(cwd)
    # Project roots are one level below their repository roots.
    safe = cwd.parent if cwd.name == 'asar_repro' else cwd
    proc = subprocess.run(['git', '-c', f'safe.directory={safe.as_posix()}', *args],
                          cwd=cwd, capture_output=True)
    require(proc.returncode == 0,
            'git failed: ' + ' '.join(args) + '\n' + proc.stderr.decode('utf-8', errors='replace'))
    return proc.stdout


def sources():
    return {p.relative_to(ROOT).as_posix(): digest(p)
            for top in ('src', 'tests', 'scripts')
            for p in sorted((ROOT / top).rglob('*.py'))}


def git_paths(*args):
    return [REPO / name for name in git(*args, '-z').decode('utf-8').split('\0') if name]


def snapshot(folder, run):
    (folder / 'changes.diff').write_bytes(git('diff', 'HEAD', '--binary'))
    (folder / 'git.status').write_bytes(git('status', '--short', '--untracked-files=all'))
    untracked = [p for p in git_paths('ls-files', '--others', '--exclude-standard')
                 if p.is_file() and not p.is_relative_to(run)]
    additions = []
    for path in untracked:
        command = ['git', '-c', f'safe.directory={REPO.as_posix()}', 'diff',
                   '--no-index', '--binary', '--', '/dev/null', path.relative_to(REPO).as_posix()]
        proc = subprocess.run(command, cwd=REPO, capture_output=True)
        require(proc.returncode in (0, 1), 'untracked diff failed: ' + str(path)
                + '\n' + proc.stderr.decode('utf-8', errors='replace'))
        additions.append(proc.stdout)
    (folder / 'untracked_files.diff').write_bytes(b'\n'.join(additions))
    save(folder / 'untracked_sha256.json',
         {p.relative_to(REPO).as_posix(): digest(p) for p in untracked})
    save(folder / 'source_sha256.json', sources())


def preserve(run):
    pre = read(run / 'preflight.json')
    require(pre['status'] == 'passed', 'preflight did not pass')
    require(digest(OLD) == pre['historical_preflight_sha256'], 'historical preservation manifest changed')
    old = read(OLD)
    base = Path(old['baseline_root'])
    require(git('branch', '--show-current').decode().strip() == old['research_branch'],
            'wrong research branch')
    require(git('rev-parse', 'HEAD').decode().strip() == pre['source_commit'],
            'research HEAD changed after validation freeze')
    require(git('rev-parse', 'baseline-v1.1').decode().strip() == old['base_commit'],
            'baseline ref moved in research repository')
    require(git('branch', '--show-current', cwd=base).decode().strip() == 'baseline-v1.1',
            'baseline checkout moved')
    require(git('rev-parse', 'HEAD', cwd=base).decode().strip() == old['base_commit'],
            'baseline checkout HEAD moved')
    for name, sha in old['baseline_all_preserved'].items():
        require(digest(base / name) == sha, 'baseline file changed: ' + name)
    for name, sha in pre['protected'].items():
        require(digest(REPO / name) == sha, 'protected research file changed: ' + name)
    require(sources() == pre['source_sha256'], 'source set/content changed after validation freeze')
    return dict(status='passed', baseline_files=len(old['baseline_all_preserved']),
                protected_research_files=len(pre['protected']), source_files=len(pre['source_sha256']),
                historical_preflight_sha256=pre['historical_preflight_sha256'])


def environment():
    versions = {}
    for name in ('numpy', 'scipy', 'pytest', 'opendrift', 'psutil', 'matplotlib', 'netCDF4', 'pyproj'):
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            versions[name] = None
    return dict(interpreter=sys.executable, python_version=sys.version,
                platform=platform.platform(), versions=versions,
                version_method='importlib.metadata only; no OpenDrift import or execution',
                environment={key: os.environ.get(key) for key in (
                    'OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS',
                    'NUMEXPR_NUM_THREADS', 'PROJ_NETWORK', 'PYTHONPATH', 'PYTHONDONTWRITEBYTECODE')})


def update_summary(run):
    pre = read(run / 'preflight.json')
    known = {name: read(run / name / 'stage.json') for name in ORDER
             if (run / name / 'stage.json').exists()}
    final_path = run / 'final_preservation' / 'stage.json'
    final = read(final_path) if final_path.exists() else None
    blocked = pre['status'] == 'blocked' or any(row['status'] == 'blocked' for row in known.values())
    blocked = blocked or (final is not None and final['status'] == 'blocked')
    not_run = [name for name in ORDER if name not in known or known[name]['status'] != 'passed']
    result = dict(status='blocked' if blocked else 'passed' if not not_run else 'in_progress',
                  order=list(ORDER), stages=known, not_run=not_run,
                  preflight_status=pre['status'], global_epsilon_certified=False,
                  source_sha256=pre.get('source_sha256', {}),
                  real_experiments='separate mandatory archive-SHA-gated runner; not executed by this driver')
    if final is not None:
        result['final_preservation'] = final
    save(run / 'validation_summary.json', result)
    return result


def init(run):
    run.mkdir(parents=True, exist_ok=False)
    tic = perf_counter()
    pre = dict(status='running', started_utc=datetime.now(timezone.utc).isoformat(),
               command=[sys.executable, *sys.argv], cwd=str(ROOT))
    try:
        old = read(OLD)
        require(old['status'] == 'passed', 'historical preflight was not passed')
        current = git('rev-parse', 'HEAD').decode().strip()
        require(git('branch', '--show-current').decode().strip() == old['research_branch'],
                'wrong research branch')
        require(git('merge-base', REFERENCE, current).decode().strip() == REFERENCE,
                'research checkout must descend from frozen reference')
        paths = {p for p in git_paths('ls-files') if p.is_file() and not p.is_relative_to(run)}
        for top in ('data', 'outputs'):
            paths.update(p for p in (ROOT / top).rglob('*') if p.is_file() and not p.is_relative_to(run))
        pre.update(status='passed', source_commit=current, reference_commit=REFERENCE,
                   historical_preflight=str(OLD), historical_preflight_sha256=digest(OLD),
                   source_sha256=sources(), protected={p.relative_to(REPO).as_posix(): digest(p)
                                                       for p in sorted(paths)},
                   environment=environment(),
                   plan=dict(order=list(ORDER), modes=['zero', 'mass_lb', 'stdc_lb', 'stdc_endpoint_lb'],
                             synthetic_seeds=dict(random=list(range(100, 180)),
                                                  historical_small=list(range(15000, 15035)),
                                                  derived_small=list(range(15000, 15005))),
                             real_seed=41, epsilon=[1.1, 1.04, 1.0],
                             limits=dict(max_expansions=5000, max_open=20000, max_seconds=30),
                             seed_expansion_subquota=1500, window_lengths=[4, 6]),
                   scope='Fixed absolute-time endpoint windows, exact fixed-suffix score; unchanged min-J objective',
                   global_epsilon_certified=False,
                   source_freeze='All src/tests/scripts Python sources, including new harnesses; no post-init edits',
                   user_authorization='Implement J/Pd improvement ideas on the STDC research branch')
        save(run / 'preflight.json', pre)
        snapshot(run, run)
        save(run / 'preservation_initial.json', preserve(run))
    except Exception as exc:
        pre.update(status='blocked', error=str(exc), traceback=traceback.format_exc())
    finally:
        pre['wall_s'] = perf_counter() - tic
        save(run / 'preflight.json', pre)
        update_summary(run)
        (run / 'stdout.txt').write_text('Initialization status: ' + pre['status'] + '\n', encoding='utf-8')
        (run / 'stderr.txt').write_text(pre.get('traceback', ''), encoding='utf-8')
    print(json.dumps(dict(action='init', status=pre['status'], wall_s=pre['wall_s']), ensure_ascii=False))
    return 0 if pre['status'] == 'passed' else 2


def child_environment():
    env = os.environ.copy()
    for key in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS', 'NUMEXPR_NUM_THREADS'):
        env[key] = '1'
    env['PROJ_NETWORK'] = 'OFF'
    env['PYTHONDONTWRITEBYTECODE'] = '1'
    env['PYTHONPATH'] = str(ROOT / 'src') + (os.pathsep + env['PYTHONPATH'] if env.get('PYTHONPATH') else '')
    return env


def stage(run, name):
    folder = run / name
    folder.mkdir(exist_ok=False)
    tic = perf_counter()
    record = dict(status='running', stage=name, started_utc=datetime.now(timezone.utc).isoformat(),
                  driver_command=[sys.executable, *sys.argv], cwd=str(ROOT), timeout_s=1200)
    try:
        require(read(run / 'validation_summary.json')['status'] != 'blocked', 'run already blocked: stop')
        for prior in ORDER[:ORDER.index(name)] if name in ORDER else ORDER:
            require(read(run / prior / 'stage.json')['status'] == 'passed', 'prior stage not passed: ' + prior)
        record['preservation_before'] = preserve(run)
        snapshot(folder, run)
        if name == 'final_preservation':
            record.update(command=None, seeds=None, test_counts=None,
                          preservation_after=preserve(run), status='passed')
            (folder / 'stdout.txt').write_text('All frozen baseline, research inputs/results and source fingerprints preserved.\n', encoding='utf-8')
            (folder / 'stderr.txt').write_text('', encoding='utf-8')
        else:
            env = child_environment()
            record['child_environment'] = {key: env[key] for key in (
                'OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS', 'NUMEXPR_NUM_THREADS',
                'PROJ_NETWORK', 'PYTHONDONTWRITEBYTECODE', 'PYTHONPATH')}
            if name in ('new_tests', 'full_tests'):
                command = [sys.executable, '-m', 'pytest', '-x', '-q', '-p', 'no:cacheprovider']
                command += ['tests/test_window_bounds.py', 'tests/test_window_search.py'] if name == 'new_tests' else ['tests']
                # Avoid Unicode NetCDF temp paths and pytest's nonrecursive leaf creation.
                ascii_id = hashlib.sha256(str(run).encode('utf-8')).hexdigest()[:12]
                temp = TEMP_ROOT / ascii_id / name
                temp.parent.mkdir(parents=True, exist_ok=True)
                command += ['--junitxml', str(folder / 'pytest.xml'), '--basetemp', str(temp)]
                record['seeds'] = [100, 101, 102, 103] if name == 'new_tests' else 'Explicit fixed seeds/fixtures in frozen source_sha256.json; includes particle seed 41'
            else:
                script = 'audit_window_bounds.py' if name == 'random_audit' else 'audit_window_search.py'
                command = [sys.executable, 'scripts/' + script, '--output-dir', str(folder / 'audit')]
                record['seeds'] = list(range(100, 180)) if name == 'random_audit' else dict(
                    historical=list(range(15000, 15035)), derived=list(range(15000, 15005)))
                record['test_counts'] = None
            record['command'] = command
            save(folder / 'command.json', dict(command=command, cwd=str(ROOT), seeds=record['seeds'],
                                              environment=record['child_environment'], timeout_s=1200))
            save(folder / 'stage.json', record)
            with (folder / 'stdout.txt').open('w', encoding='utf-8') as stdout, (folder / 'stderr.txt').open('w', encoding='utf-8') as stderr:
                proc = subprocess.run(command, cwd=ROOT, stdout=stdout, stderr=stderr, env=env, timeout=1200)
            record['exit_code'] = proc.returncode
            if name in ('new_tests', 'full_tests'):
                require((folder / 'pytest.xml').is_file(), 'pytest JUnit report missing')
                suites = ET.parse(folder / 'pytest.xml').getroot()
                counts = {key: sum(int(s.get(key, 0)) for s in suites.iter('testsuite'))
                          for key in ('tests', 'errors', 'failures', 'skipped')}
                record['test_counts'] = counts
                require(counts['tests'] > 0, 'empty pytest collection')
                require(counts['errors'] == counts['failures'] == counts['skipped'] == 0,
                        'pytest failure/error/skip: STOP')
                if name == 'full_tests':
                    require(counts['tests'] > read(run / 'new_tests/stage.json')['test_counts']['tests'],
                            'full tests did not include additional historical tests')
            require(proc.returncode == 0, 'stage failed: STOP; inspect stdout/stderr')
            if name in ('random_audit', 'small_search'):
                audit = read(folder / 'audit/summary.json')
                require(audit['status'] == 'passed', 'Oracle audit did not pass')
                if name == 'random_audit':
                    require(audit['case_count'] == 160, 'incomplete random audit')
                else:
                    require(audit['cases'] == 45 and audit['searches'] == 360, 'incomplete small search audit')
                record['audit_summary'] = audit
            record['preservation_after'] = preserve(run)
            record['status'] = 'passed'
    except Exception as exc:
        record.update(status='blocked', error=str(exc), traceback=traceback.format_exc())
        if isinstance(exc, subprocess.TimeoutExpired):
            record.update(stop_reason='validation_watchdog', timeout_s=exc.timeout)
        with (folder / 'stderr.txt').open('a', encoding='utf-8') as stream:
            stream.write('\n' + record['traceback'])
        if not (folder / 'stdout.txt').exists():
            (folder / 'stdout.txt').write_text('', encoding='utf-8')
    finally:
        record['wall_s'] = perf_counter() - tic
        save(folder / 'stage.json', record)
        # Real runs pin the passed four-stage evidence by SHA. A successful
        # final preservation check is separate evidence and must not rewrite it.
        if name != 'final_preservation' or record['status'] != 'passed':
            update_summary(run)
    print(json.dumps(dict(action=name, status=record['status'], wall_s=record['wall_s'],
                          test_counts=record.get('test_counts'), error=record.get('error')), ensure_ascii=False), flush=True)
    return 0 if record['status'] == 'passed' else 2


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['init', *ORDER, 'final_preservation'])
    parser.add_argument('--run-dir', type=Path, required=True)
    args = parser.parse_args()
    run = args.run_dir.resolve()
    output_root = (ROOT / 'outputs/stdc_v0_2').resolve()
    require(run != output_root and run.is_relative_to(output_root), 'new research output subdirectory required')
    return init(run) if args.action == 'init' else stage(run, args.action)


if __name__ == '__main__':
    sys.exit(main())
