
$ErrorActionPreference = 'Stop'
$runDir = $PSScriptRoot
$pre = Get-Content -LiteralPath (Join-Path $runDir '00_preflight.json') -Raw -Encoding UTF8 | ConvertFrom-Json
$diag = Get-Content -LiteralPath (Join-Path $runDir 'access_diagnostic.json') -Raw -Encoding UTF8 | ConvertFrom-Json
$baseDir = [IO.Path]::GetFullPath($pre.baseline_root)
$account = New-Object System.Security.Principal.NTAccount('JDD','35448')
$sid = $account.Translate([System.Security.Principal.SecurityIdentifier]).Value
$allowedRoots = @(
    [IO.Path]::GetFullPath((Join-Path $baseDir 'outputs/baseline_v1.1/b6_failed_attempt_01')),
    [IO.Path]::GetFullPath((Join-Path $baseDir 'outputs/baseline_v1.1/lake_ontario_real'))
)
$targets = [System.Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
foreach ($relative in $diag.permission_denied) {
    $target = [IO.Path]::GetFullPath((Join-Path $baseDir $relative))
    $anchor = $allowedRoots | Where-Object { $target.StartsWith($_ + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase) } | Select-Object -First 1
    if (-not $anchor) { throw "Target outside authorized directories: $target" }
    [void]$targets.Add($target)
    $parent = [IO.Path]::GetDirectoryName($target)
    while ($parent.Length -ge $anchor.Length) {
        [void]$targets.Add($parent)
        if ($parent -eq $anchor) { break }
        $parent = [IO.Path]::GetDirectoryName($parent)
    }
}
$before = @()
foreach ($target in ($targets | Sort-Object Length)) {
    $before += [pscustomobject]@{path=$target;sddl=(Get-Acl -LiteralPath $target).Sddl}
}
$before | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $runDir 'access_acl_before.json') -Encoding UTF8
$log = Join-Path $runDir 'access_repair.log'
foreach ($target in ($targets | Sort-Object Length)) {
    & icacls.exe $target /grant ('*' + $sid + ':(RX)') 2>&1 | Out-File -LiteralPath $log -Append -Encoding UTF8
    if ($LASTEXITCODE -ne 0) { throw "Read access grant failed: $target" }
}
@{status='read_access_granted';account='JDD/35448';sid=$sid;targets=@($targets);content_changed=$false} |
    ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $runDir 'access_repair.json') -Encoding UTF8
