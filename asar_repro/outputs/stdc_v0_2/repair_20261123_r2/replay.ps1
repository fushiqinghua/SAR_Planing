param([string]$OutputDirectory)
$ErrorActionPreference='Stop'
$projectRoot=Resolve-Path (Join-Path $PSScriptRoot '../../..')
Push-Location $projectRoot
try {
$PY='C:\Users\35448\.conda\envs\maritime-sar\python.exe'
$env:PYTHONPATH=(Resolve-Path 'scripts/offline_guard').Path+[IO.Path]::PathSeparator+(Resolve-Path 'src').Path+[IO.Path]::PathSeparator+(Resolve-Path 'scripts').Path
$env:PATH=(Join-Path (Split-Path $PY) 'Library\bin')+[IO.Path]::PathSeparator+$env:PATH
$env:PYTHONDONTWRITEBYTECODE='1'
$env:PYTHONIOENCODING='utf-8'
$env:ASAR_OFFLINE='1'
$env:PROJ_NETWORK='OFF'
$env:OMP_NUM_THREADS='1'
$env:OPENBLAS_NUM_THREADS='1'
$env:MKL_NUM_THREADS='1'
$env:NUMEXPR_NUM_THREADS='1'
$env:GIT_CONFIG_COUNT='2'
$env:GIT_CONFIG_KEY_0='safe.directory'
$env:GIT_CONFIG_VALUE_0='E:/毕业设计/终稿研发/new/baseline/SAR_Planing-stdc-v0.2'
$env:GIT_CONFIG_KEY_1='safe.directory'
$env:GIT_CONFIG_VALUE_1='E:/毕业设计/终稿研发/new/baseline/SAR_Planing-v1.1'

    if (-not $OutputDirectory) { $OutputDirectory='outputs/stdc_v0_2/repair_replay_'+(Get-Date -Format 'yyyyMMdd_HHmmss') }
    if (Test-Path -LiteralPath $OutputDirectory) { throw 'Use a fresh output directory.' }
    & $PY scripts/run_stdc_repair.py init --run-dir $OutputDirectory
    if ($LASTEXITCODE -ne 0) { throw 'Preflight failed.' }
    foreach ($stageName in @('new_tests','full_tests','random_audit','small_search','lake_smoke','comparison')) {
        & $PY scripts/run_stdc_repair.py $stageName --run-dir $OutputDirectory
        if ($LASTEXITCODE -ne 0) { throw ('blocked: '+$stageName) }
    }
    & $PY scripts/report_stdc_repair.py --run-dir $OutputDirectory
    if ($LASTEXITCODE -ne 0) { throw 'Report generation failed.' }
    Write-Output $OutputDirectory
} finally { Pop-Location }

