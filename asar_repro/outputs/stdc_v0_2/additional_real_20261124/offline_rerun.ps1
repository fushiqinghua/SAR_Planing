param(
    [string]$ProjectRoot = 'E:\毕业设计\终稿研发\new\baseline\SAR_Planing-stdc-v0.2\asar_repro',
    [string]$OutputName = ('additional_real_rerun_' + (Get-Date -Format 'yyyyMMdd_HHmmss'))
)
# Frozen historical files and existing output folders are never overwritten.
Set-Location -LiteralPath $ProjectRoot
$PY='C:\Users\35448\.conda\envs\maritime-sar\python.exe'
$env:PYTHONPATH=(Resolve-Path 'scripts/offline_guard').Path+[IO.Path]::PathSeparator+(Resolve-Path 'src').Path+[IO.Path]::PathSeparator+(Resolve-Path 'scripts').Path
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
$env:PYTHONUTF8='1'
$Reference = 'outputs/stdc_v0_2/additional_real_20261124'
$RUN = Join-Path 'outputs/stdc_v0_2' $OutputName
if (Test-Path -LiteralPath $RUN) { throw "Output already exists: $RUN" }
New-Item -ItemType Directory -Path $RUN -ErrorAction Stop | Out-Null
Copy-Item -LiteralPath "$Reference/before.json" -Destination "$RUN/before.json" -ErrorAction Stop
Copy-Item -LiteralPath "$Reference/fundy_orientation_diagnosis.json" -Destination "$RUN/fundy_orientation_diagnosis.json" -ErrorAction Stop
$testTemp = Join-Path $env:TEMP ('asar_additional_' + [guid]::NewGuid().ToString('N'))
function Run-Python {
    param([string]$Label, [string[]]$Arguments)
    $Arguments | ConvertTo-Json | Set-Content -LiteralPath "$RUN/$Label.command.json" -Encoding UTF8
    & $PY @Arguments 1> "$RUN/$Label.stdout.txt" 2> "$RUN/$Label.stderr.txt"
    if ($LASTEXITCODE -ne 0) { throw "blocked: $Label exited $LASTEXITCODE. See preserved stderr." }
}
Run-Python 'b2_new_tests_r3' @('-m','pytest','tests/test_additional_forcing.py','-q','-x','-p','no:cacheprovider','--basetemp',"$testTemp/new",'--junitxml',"$RUN/b2_new_tests_r3.xml")
Run-Python 'b2_full_tests_r3' @('-m','pytest','-q','-x','-p','no:cacheprovider','--basetemp',"$testTemp/full",'--junitxml',"$RUN/b2_full_tests_r3.xml")
Run-Python 'b2_hudson' @('scripts/run_additional_real.py','b2','--scenario','arctic_ocean','--run-dir',$RUN)
Run-Python 'b3_hudson' @('scripts/run_additional_real.py','b3','--scenario','arctic_ocean','--run-dir',$RUN)
Run-Python 'prepare' @('scripts/compare_available_real.py','prepare','--run-dir',$RUN)
Run-Python 'smoke' @('scripts/compare_available_real.py','smoke','--run-dir',$RUN)
Run-Python 'benchmark' @('scripts/compare_available_real.py','benchmark','--run-dir',$RUN)
Write-Output "Hudson-only replay finished. Overall two-scene request remains blocked on Fundy B2."
# Independent reproduction of the Fundy block; expected nonzero with the unchanged files:
# & $PY scripts/run_additional_real.py b2 --scenario bay_of_fundy --run-dir $RUN
# Do not run Fundy B3/search unless this direction/provenance gate is resolved and passes.

