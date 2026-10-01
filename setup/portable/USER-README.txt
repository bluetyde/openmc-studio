OPENMC STUDIO FOR WINDOWS

Copy this ENTIRE folder to a writable folder on your Windows computer.
Double-click Start Studio.cmd. Keep its window open while using Studio.
The first launch checks the files and installs a private runtime. Allow several
minutes and at least 20 GB of free space on your Windows system drive, in addition
to this folder. Later launches reuse the private runtime.

Windows 11 on Intel/AMD x86-64 is the supported target. Windows Subsystem for
Linux 2 and hardware virtualization must be enabled. If setup reports missing
WSL, open PowerShell as Administrator and run:
    wsl --install --no-distribution
Restart Windows, then double-click Start Studio.cmd again. This Windows setup
may need internet. Studio's bundled runtime and data install offline afterward.

No separate Python, conda, Git, Java or FreeCAD installation is needed. Your
existing environments are not used. Nuclear data and simulation results stay
in this folder. Save downloaded Studio project files into projects yourself;
your browser may otherwise save them in Downloads.

To stop: press Ctrl+C in the launcher window, then wait for it to finish.
Do not unplug an external drive while a run or save is active.

Troubleshooting: inspect logs in this folder. To recheck all packaged files,
open PowerShell in this folder and run:
    powershell -NoProfile -ExecutionPolicy Bypass -File .\Start-Studio.ps1 -VerifyOnly
If port 8765 is busy, close the other app or add -Port 8769 to that command
(omit -VerifyOnly to launch). Never delete projects/results to repair setup.

UPDATES
Copy a new version into a NEW folder and launch it there. Copy your projects
and results across after verification. Keep the previous folder for rollback.
Each runtime version is separately installed under %LOCALAPPDATA%\OpenMCStudio.
Previous versions are retained intentionally; no updater overwrites your work.

MCNP import/export is included. A licensed MCNP transport executable is not.
See licenses and app/THIRD_PARTY_NOTICES.md for component terms and source
references. Studio's MIT license does not replace dependency licenses.
