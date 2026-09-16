@echo off
setlocal
title OpenMC Studio
rem Windows: double-click to start OpenMC Studio inside WSL. It opens in your browser.
rem To stop Studio, press Ctrl+C in this window or close it.

set "PORT=8765"
set "HERE=%~dp0"
set "HERE=%HERE:~0,-1%"

rem If an earlier Studio is still running (e.g. its window was closed mid-run), stop it first.
powershell -NoProfile -Command "try { Invoke-WebRequest -UseBasicParsing http://127.0.0.1:%PORT%/api/ping -TimeoutSec 1 | Out-Null; exit 1 } catch { exit 0 }"
if errorlevel 1 (
  echo Stopping the OpenMC Studio that was already running...
  wsl.exe -e bash -c "pkill -INT -f '[o]penmc_studio'; for i in $(seq 20); do pgrep -f '[o]penmc_studio' >/dev/null || exit 0; sleep 0.5; done; pkill -KILL -f '[o]penmc_studio'"
)

for /f "usebackq delims=" %%T in (`powershell -NoProfile -Command "[guid]::NewGuid().ToString('N')"`) do set "TOKEN=%%T"
for /f "usebackq delims=" %%P in (`wsl.exe wslpath -a "%HERE%"`) do set "WSLHERE=%%P"
if not defined WSLHERE (
  echo Couldn't reach WSL. Check that WSL is installed and your Linux distro starts.
  pause
  exit /b 1
)

rem Open the browser once the server answers (up to 60 s).
start "" /b powershell -NoProfile -WindowStyle Hidden -Command "for ($i = 0; $i -lt 120; $i++) { try { Invoke-WebRequest -UseBasicParsing http://127.0.0.1:%PORT%/api/ping -TimeoutSec 1 | Out-Null; Start-Process 'http://127.0.0.1:%PORT%/?token=%TOKEN%'; break } catch { Start-Sleep -Milliseconds 500 } }"

wsl.exe -e bash -lc "export OPENMC_STUDIO_TOKEN='%TOKEN%' OPENMC_STUDIO_PORT='%PORT%'; bash '%WSLHERE%/studio/start.sh' --no-browser --exit-with-launcher"
if errorlevel 1 (
  echo.
  echo Studio stopped with an error. See the messages above.
  pause
)
