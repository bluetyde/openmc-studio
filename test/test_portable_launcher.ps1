$ErrorActionPreference = 'Stop'
$file = Join-Path $PSScriptRoot '../setup/portable/Start-Studio.ps1'
$tokens = $null; $parseErrors = $null
$ast = [Management.Automation.Language.Parser]::ParseFile($file, [ref]$tokens, [ref]$parseErrors)
if ($parseErrors.Count) { throw ($parseErrors | Out-String) }
# Exercise production helpers without importing WSL or running the entry point.
foreach ($function in $ast.FindAll({param($node) $node -is [Management.Automation.Language.FunctionDefinitionAst]}, $false)) {
    . ([scriptblock]::Create($function.Extent.Text))
}
$package = Join-Path ([IO.Path]::GetTempPath()) ('studio-launcher-test-' + [Guid]::NewGuid().ToString('N'))
$null = New-Item -ItemType Directory $package
try {
    foreach ($bad in @('../outside', 'C:\outside', '..\outside')) {
        $failed = $false
        try { $null = Package-Path $bad } catch { $failed = $true }
        if (-not $failed) { throw "Accepted path escape: $bad" }
    }
    [IO.File]::WriteAllText((Join-Path $package 'data.txt'), 'valid')
    $r = [pscustomobject]@{path='data.txt';bytes=5;sha256=(Get-FileHash (Join-Path $package 'data.txt')).Hash.ToLowerInvariant()}
    Check-File $r
    [IO.File]::WriteAllText((Join-Path $package 'data.txt'), 'wrong')
    $failed = $false
    try { Check-File $r } catch { $failed = $true }
    if (-not $failed) { throw 'Accepted corrupt file with same length' }
    $r.path = 'missing.txt'
    $failed = $false
    try { Check-File $r } catch { $failed = $true }
    if (-not $failed) { throw 'Accepted missing file' }
    if ((Quote-Argument 'a b') -ne '"a b"') { throw 'Space quoting failed' }
    Write-Host 'PASS: launcher syntax, path containment, corrupt/missing package files and argument quoting'
} finally {
    # Only this test's new, resolved temporary directory is eligible for deletion.
    $resolved = [IO.Path]::GetFullPath($package)
    if (-not $resolved.StartsWith([IO.Path]::GetTempPath()) -or (Split-Path $resolved -Leaf) -notlike 'studio-launcher-test-*') { throw 'Unsafe test cleanup path' }
    Remove-Item -LiteralPath $resolved -Recurse -Force
}
