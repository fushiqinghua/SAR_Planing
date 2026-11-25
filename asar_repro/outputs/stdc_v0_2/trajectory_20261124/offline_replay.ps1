# Re-run the integrated frozen source, using a NEW output directory.
# Phase-1's original 734-test count is historical; the integrated source now has 903 tests.
$ErrorActionPreference='Stop'
$Project='E:\毕业设计\终稿研发\new\baseline\SAR_Planing-stdc-v0.2\asar_repro'
$PY='C:\Users\35448\.conda\envs\maritime-sar\python.exe'
Set-Location -LiteralPath $Project
$env:PYTHONPATH=(Join-Path $Project 'scripts/offline_guard')+[IO.Path]::PathSeparator+(Join-Path $Project 'src')+[IO.Path]::PathSeparator+(Join-Path $Project 'scripts')
$env:PATH=(Join-Path (Split-Path $PY) 'Library\bin')+[IO.Path]::PathSeparator+$env:PATH
$env:PYTHONDONTWRITEBYTECODE='1'
$env:PYTHONIOENCODING='utf-8'
$env:PYTHONHASHSEED='0'
$env:ASAR_OFFLINE='1'
$env:PROJ_NETWORK='OFF'
$env:OMP_NUM_THREADS='1'
$env:OPENBLAS_NUM_THREADS='1'
$env:MKL_NUM_THREADS='1'
$env:NUMEXPR_NUM_THREADS='1'
$env:VECLIB_MAXIMUM_THREADS='1'
$env:GIT_CONFIG_COUNT='2'
$env:GIT_CONFIG_KEY_0='safe.directory'
$env:GIT_CONFIG_VALUE_0='E:/毕业设计/终稿研发/new/baseline/SAR_Planing-stdc-v0.2'
$env:GIT_CONFIG_KEY_1='safe.directory'
$env:GIT_CONFIG_VALUE_1='E:/毕业设计/终稿研发/new/baseline/SAR_Planing-v1.1'
$ReplayRun='outputs/stdc_v0_2/trajectory_replay_'+(Get-Date -Format 'yyyyMMdd_HHmmss')
$Validation=$ReplayRun+'/planning_validation'
$Prior='outputs/stdc_v0_2/trajectory_20261124/diagnostic_validation/validation_summary.json'
# Use the original user environment: existing historical tests require Windows hard links.
& $PY scripts/run_trajectory_validation.py init --phase planning --run-dir $Validation --prior-validation $Prior
if ($LASTEXITCODE -ne 0) { throw 'blocked: preflight' }
& $PY scripts/run_trajectory_validation.py new_tests --run-dir $Validation
if ($LASTEXITCODE -ne 0) { throw 'blocked: new_tests' }
& $PY scripts/run_trajectory_validation.py full_tests --run-dir $Validation
if ($LASTEXITCODE -ne 0) { throw 'blocked: full_tests' }
& $PY scripts/run_trajectory_validation.py oracle_audit --run-dir $Validation
if ($LASTEXITCODE -ne 0) { throw 'blocked: oracle_audit' }
# Recheck the independent diagnostic before any new real comparison.
& $PY scripts/audit_trajectory.py diagnostic --output-dir ($ReplayRun+'/diagnostic_oracle')
if ($LASTEXITCODE -ne 0) { throw 'blocked: diagnostic_oracle' }
& $PY scripts/run_trajectory_diagnostic.py --output-dir ($ReplayRun+'/real_diagnostic') --validation ($Validation+'/validation_summary.json')
if ($LASTEXITCODE -ne 0) { throw 'blocked: real_diagnostic' }
& $PY scripts/run_trajectory_experiments.py smoke --output-dir ($ReplayRun+'/smoke') --validation-evidence ($Validation+'/validation_summary.json')
if ($LASTEXITCODE -ne 0) { throw 'blocked: smoke' }
& $PY scripts/run_trajectory_experiments.py benchmark --output-dir ($ReplayRun+'/benchmark') --validation-evidence ($Validation+'/validation_summary.json') --smoke-dir ($ReplayRun+'/smoke')
if ($LASTEXITCODE -ne 0) { throw 'blocked: benchmark' }
& $PY scripts/run_trajectory_validation.py final_preservation --run-dir $Validation
if ($LASTEXITCODE -ne 0) { throw 'blocked: preservation' }
Write-Output ('Replay metrics, plots and logs: '+$ReplayRun)
