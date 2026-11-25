param(
    [ValidateSet('lake_ontario','arctic_ocean','bay_of_fundy')]
    [string]$Scenario='lake_ontario',
    [ValidateSet('paper_baseline','prior_stdc','recycle_stdc','short_eager','short_lazy','short_diverse','fast_stdc','dense_fallback','compact_dp','adaptive_combo')]
    [string]$Variant='adaptive_combo',
    [ValidateSet('work','wall')]
    [string]$Protocol='work',
    [int]$Repeat=0
)
$ErrorActionPreference='Stop'
$runDir=$PSScriptRoot
$project=Split-Path (Split-Path (Split-Path $runDir -Parent) -Parent) -Parent
$PY='C:\Users\35448\.conda\envs\maritime-sar\python.exe'
$env:PYTHONPATH=(Join-Path $project 'scripts/offline_guard')+';'+(Join-Path $project 'src')+';'+(Join-Path $project 'scripts')
$env:PATH=(Join-Path (Split-Path $PY -Parent) 'Library\bin')+';'+$env:PATH
$env:PYTHONDONTWRITEBYTECODE='1'
$env:PYTHONIOENCODING='utf-8'
$env:PYTHONUTF8='1'
$env:PYTHONHASHSEED='0'
$env:ASAR_OFFLINE='1'
$env:PROJ_NETWORK='OFF'
$env:OMP_NUM_THREADS='1'
$env:OPENBLAS_NUM_THREADS='1'
$env:MKL_NUM_THREADS='1'
$env:NUMEXPR_NUM_THREADS='1'
$env:VECLIB_MAXIMUM_THREADS='1'
$stamp=Get-Date -Format 'yyyyMMdd_HHmmss'
$out=Join-Path (Split-Path $runDir -Parent) ("adaptive_replay_"+$Scenario+"_"+$Variant+"_"+$Protocol+"_"+$stamp)
if(Test-Path -LiteralPath $out){throw 'Refusing to overwrite an existing replay directory.'}
New-Item -ItemType Directory -Path $out | Out-Null
Push-Location -LiteralPath $project
try {
    & $PY scripts/run_adaptive_experiments.py worker --run-dir $runDir --output-dir $out --scenario $Scenario --variant $Variant --protocol $Protocol --repeat $Repeat 1> (Join-Path $out 'stdout.txt') 2> (Join-Path $out 'stderr.txt')
    if($LASTEXITCODE -ne 0){throw "Replay failed; inspect $out"}
    Write-Output "Replay completed: $out"
    Write-Output 'The frozen source, input fingerprints, and original validation evidence are verified by the worker.'
} finally { Pop-Location }

