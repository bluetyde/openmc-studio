# A hidden WSL client can survive its PowerShell window. Stop only that launch
# if the parent disappears, including when the user closes the console window.
param([int]$LauncherId, [long]$LauncherStarted, [int]$ClientId, [long]$ClientStarted,
      [string]$Distro, [string]$LinuxPackage, [string]$Token)
$ErrorActionPreference = 'Stop'
function Same-Process([int]$ProcessId, [long]$Started) {
    $found = Get-Process -Id $ProcessId -ErrorAction SilentlyContinue
    return $null -ne $found -and $found.StartTime.ToUniversalTime().Ticks -eq $Started
}
while (Same-Process $ClientId $ClientStarted) {
    if (-not (Same-Process $LauncherId $LauncherStarted)) {
        # Runtime checks the token in /proc before signaling any Linux process.
        $ErrorActionPreference = 'Continue'
        & wsl.exe -d $Distro -u root --exec /opt/openmc/conda/envs/openmc-mcnp/bin/python "$LinuxPackage/app/setup/portable/runtime.py" stop $LinuxPackage --token $Token 2>&1 | Out-Null
        Start-Sleep -Seconds 2
        if (Same-Process $ClientId $ClientStarted) {
            Stop-Process -Id $ClientId -ErrorAction SilentlyContinue
        }
        break
    }
    Start-Sleep -Seconds 1
}
