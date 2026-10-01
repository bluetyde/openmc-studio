# Windows PowerShell 5.1 compatible. This launcher only owns its private distro and process.
[CmdletBinding()]
param([switch]$SetupOnly, [switch]$VerifyOnly, [switch]$NoBrowser,
      [ValidateRange(1024,65535)][int]$Port = 8765)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$package = $PSScriptRoot
$script:process = $null
$script:linuxPackage = $null
$script:distro = $null
$script:token = [Guid]::NewGuid().ToString('N')

function Invoke-Wsl([string[]]$Arguments) {
    $previous = $ErrorActionPreference
    try {
        $ErrorActionPreference = 'Continue' # PS 5.1 represents native stderr as ErrorRecord.
        $output = & wsl.exe @Arguments 2>&1
        $code = $LASTEXITCODE
    } finally { $ErrorActionPreference = $previous }
    if ($code -ne 0) { throw "WSL failed: $($output -join [Environment]::NewLine)" }
    return ($output -join "`n").Replace([string][char]0, '').Trim()
}
function Package-Path([string]$Relative) {
    if ([IO.Path]::IsPathRooted($Relative)) { throw "Invalid package path: $Relative" }
    $path = [IO.Path]::GetFullPath((Join-Path $package $Relative))
    if (-not $path.StartsWith($package.TrimEnd('\') + '\', [StringComparison]::OrdinalIgnoreCase)) {
        throw "Path escapes package: $Relative"
    }
    return $path
}
function Check-File($Record) {
    $path = Package-Path $Record.path
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw "Package is incomplete: $($Record.path). Copy the entire folder again." }
    if ((Get-Item -LiteralPath $path).Length -ne $Record.bytes) { throw "Package file has wrong size: $($Record.path). Copy the entire folder again." }
    if ((Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant() -ne $Record.sha256) {
        throw "Package checksum failed: $($Record.path). Copy the entire folder again."
    }
}
function Quote-Argument([string]$Value) {
    # CommandLineToArgvW quoting, including trailing slashes and embedded quotes.
    return '"' + [regex]::Replace([regex]::Replace($Value, '(\\*)"', '$1$1\"'), '(\\+)$', '$1$1') + '"'
}

$mutex = [Threading.Mutex]::new($false, 'Local\OpenMCStudioSetup')
$locked = $false
$transcript = $false
try {
    if (-not [Environment]::Is64BitOperatingSystem -or $env:PROCESSOR_ARCHITECTURE -eq 'ARM64' -or $env:PROCESSOR_ARCHITEW6432 -eq 'ARM64') {
        throw 'This package requires Windows on an Intel or AMD 64-bit computer.'
    }
    $manifest = Get-Content -LiteralPath (Join-Path $package 'manifest.json') -Raw | ConvertFrom-Json
    if ($manifest.schema -ne 1 -or $manifest.runtime.id -notmatch '^[a-z0-9-]{1,48}$' -or $manifest.runtime.sha256 -notmatch '^[a-f0-9]{64}$') {
        throw 'Unsupported or invalid package manifest.'
    }
    if (-not (Get-Command wsl.exe -ErrorAction SilentlyContinue)) {
        throw 'Install Windows Subsystem for Linux first: open PowerShell as Administrator, run wsl --install --no-distribution, restart Windows, then open Start Studio again. Internet is needed for this Windows prerequisite.'
    }
    try { $null = Invoke-Wsl @('--status') } catch {
        throw 'WSL is not ready. In Administrator PowerShell run wsl --install --no-distribution, restart Windows, and try again. If virtualization is disabled, enable it in firmware settings.'
    }
    $locked = $mutex.WaitOne(0)
    if (-not $locked) { throw 'Another Studio setup or launch is active. Close its launcher before retrying.' }
    foreach ($folder in @('projects','results','logs')) { $null = New-Item -ItemType Directory -Force -Path (Join-Path $package $folder) }
    $null = Start-Transcript -Path (Join-Path $package "logs\launcher-$script:token.log")
    $transcript = $true
    $localRoot = Join-Path $env:LOCALAPPDATA 'OpenMCStudio'
    $script:distro = 'OpenMCStudio-' + $manifest.runtime.sha256.Substring(0,16)
    $install = Join-Path $localRoot $script:distro
    $stamp = Join-Path $install 'verified-package.txt'
    $manifestHash = (Get-FileHash -LiteralPath (Join-Path $package 'manifest.json')).Hash
    $verificationKey = $manifestHash + '|' + $package
    $names = (Invoke-Wsl @('--list','--quiet')) -split "`n" | ForEach-Object { $_.Trim() }
    $exists = $script:distro -in $names
    $needsVerify = $VerifyOnly -or -not $exists -or -not (Test-Path -LiteralPath $stamp) -or
        ((Get-Content -LiteralPath $stamp -Raw -ErrorAction SilentlyContinue).Trim() -ne $verificationKey)
    if ($needsVerify) {
        Write-Host 'Checking the package, including nuclear data. This can take several minutes...'
        Check-File $manifest.runtime
        foreach ($file in $manifest.files) { Check-File $file }
    }
    if (-not $exists) {
        $drive = [IO.DriveInfo]::new([IO.Path]::GetPathRoot($localRoot))
        if ($drive.AvailableFreeSpace -lt $manifest.runtime.requiredFreeBytes) {
            throw "Not enough space for the private runtime. At least $([math]::Ceiling($manifest.runtime.requiredFreeBytes / 1GB)) GB is required on $($drive.Name)."
        }
        if (Test-Path -LiteralPath $install) { throw "An incomplete installation exists at $install. Keep it for diagnosis; rename that folder and retry." }
        $null = New-Item -ItemType Directory -Path $install -Force
        Write-Host 'Installing the private Studio runtime. Existing Python and WSL environments are unchanged...'
        $null = Invoke-Wsl @('--import', $script:distro, $install, (Package-Path $manifest.runtime.path), '--version','2')
    }
    $runtimeId = Invoke-Wsl @('-d',$script:distro,'-u','root','--exec','/bin/cat','/opt/openmc/runtime-id')
    if ($runtimeId -ne $manifest.runtime.id) { throw 'Installed runtime identity does not match this package.' }
    $script:linuxPackage = Invoke-Wsl @('-d',$script:distro,'-u','root','--exec','/usr/bin/wslpath','-a',$package)
    $entry = "$script:linuxPackage/app/setup/portable/runtime.py"
    if ($needsVerify) {
        Write-Host (Invoke-Wsl @('-d',$script:distro,'-u','root','--exec','/opt/openmc/conda/envs/openmc-mcnp/bin/python', $entry, 'verify', $script:linuxPackage))
        [IO.File]::WriteAllText($stamp, $verificationKey)
    }
    if ($SetupOnly -or $VerifyOnly) { Write-Host 'Studio setup verified.'; exit 0 }
    $listener = [Net.Sockets.TcpListener]::new([Net.IPAddress]::Loopback, $Port)
    try { $listener.Start() } catch { throw "Port $Port is already in use. Close the other application or launch with -Port 8769." } finally { $listener.Stop() }
    $out = Join-Path $package "logs\studio-$script:token.log"
    $err = Join-Path $package "logs\studio-$script:token-error.log"
    $argsList = @('-d',$script:distro,'-u','root','--exec','/opt/openmc/conda/envs/openmc-mcnp/bin/python',
                  $entry,'start',$script:linuxPackage,'--port',"$Port",'--token',$script:token)
    $script:process = Start-Process -FilePath wsl.exe -ArgumentList (($argsList | ForEach-Object { Quote-Argument $_ }) -join ' ') -PassThru -WindowStyle Hidden -RedirectStandardOutput $out -RedirectStandardError $err
    $ready = $false
    for ($attempt = 0; $attempt -lt 90; $attempt++) {
        if ($script:process.HasExited) { throw "Studio stopped during startup. See $err" }
        try {
            $null = Invoke-WebRequest -UseBasicParsing -Uri "http://localhost:$Port/api/health?token=$script:token" -TimeoutSec 1
            $ready = $true; break
        } catch { Start-Sleep -Milliseconds 500 }
    }
    if (-not $ready) { throw "Studio did not become ready. See $err" }
    if (-not $NoBrowser) { Start-Process "http://localhost:$Port/?token=$script:token" }
    Write-Host "Studio is running on port $Port. Keep this window open; press Ctrl+C to stop."
    $mutex.ReleaseMutex(); $locked = $false
    while (-not $script:process.WaitForExit(500)) { }
    if ($script:process.ExitCode -ne 0) { throw "Studio exited with code $($script:process.ExitCode). See $err" }
} catch {
    Write-Host "`nStudio could not start: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
} finally {
    if ($null -ne $script:process -and $null -ne $script:linuxPackage) {
        & wsl.exe -d $script:distro -u root --exec /opt/openmc/conda/envs/openmc-mcnp/bin/python "$script:linuxPackage/app/setup/portable/runtime.py" stop $script:linuxPackage --token $script:token | Out-Null
    }
    if ($locked) { $mutex.ReleaseMutex() }
    $mutex.Dispose()
    if ($transcript) { $null = Stop-Transcript }
}
