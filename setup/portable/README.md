# Offline Windows package

The delivery folder is separate from a source checkout. A friend copies the
entire folder to a writable location and opens **Start Studio.cmd**. First launch
imports a private WSL2 distribution; subsequent launches use it explicitly.
Python, conda, Java, OpenMC, the exporter and FreeCAD/GEOUNED live inside that
distribution. Projects, results, logs and nuclear data live beside the launcher.
Browser downloads still follow the browser's chosen download directory.

Windows 11 x86-64 with WSL2 and hardware virtualization is the supported target.
If WSL is missing, the launcher gives the administrator command and restart
instructions. Windows prerequisites may need internet; the package itself does
not download runtime dependencies. It does not bundle a licensed MCNP executable.

## Build

Use a dedicated clone and a fresh, uniquely named build distribution. Never
export a personal Ubuntu distribution or copy an installed environment.

1. Download Ubuntu Base and Miniforge from their official release locations.
   Match their published SHA256 checksums. Record URLs/hashes in `locks/bootstrap.json`.
2. On the maintainer's Linux host, run `collect_inputs.py --conda <conda-root>
   --exporter <clean-exporter-checkout> --output <staging>`. This verifies cached
   conda archives against installed package records and writes explicit locks.
   It exports the companion's committed source, without `.git` or credentials.
3. Populate `staging/wheels` with the exact MCNPy, MetaPy, py4j and adapter wheels
   listed in `locks/wheels.json`. Preserve their source licenses in
   `staging/notices/python`. No login credentials belong in staging.
4. Import the verified Ubuntu Base tar into a new WSL2 build distribution. Install
   Miniforge at `/opt/openmc/conda` with `bash Miniforge3.sh -b -p /opt/openmc/conda`.
5. Inside that distribution, run `bash build-runtime.sh <absolute-staging-path>
   <runtime-id>`. It reinstalls the two environments offline at fixed paths,
   installs only the supplied wheels, and records licenses and source recipes.
6. Before release, run the acceptance checks below. Stop only this build
   distribution, then `wsl --export <build-distro> <runtime.tar>`. Exclude temporary
   acceptance directories and host-path symlinks from the exported image. Keep
   the runtime's notices available as a separate host directory.
7. Run `python setup/portable/build_package.py --data <nuclear-data-directory>
   --runtime <runtime.tar> --notices <notices-directory> --output <new-folder>
   --runtime-id <runtime-id>`. The output must not exist. The builder copies an
   allowlisted application snapshot, data and notices, and hashes every file.

The manifest records the source commit plus hashes of the actual packaged files;
local changes used during packaging are therefore detectable. Package a committed
revision for releases. Runtime archives, data payloads, installed environments,
projects, results and logs are not committed to Git. Keep checksums and licenses
with any delivered archive. Preserve source/source-offer obligations of the
third-party distributions; Studio's MIT license covers only Studio's own code.

## Verification

- Maintainer contract tests: `python test/test_portable.py` and Windows PowerShell
  `-NoProfile -ExecutionPolicy Bypass -File test/test_portable_launcher.ps1`.
- Full package integrity and runtime imports: launch `Start-Studio.ps1 -VerifyOnly`.
- Actual engines: use the bundled core Python to run
  `app/setup/portable/acceptance.py <Linux-package-path>`. This runs a small OpenMC
  transport problem, converts a drilled CAD solid through the job manager, and
  exports a validated MCNP deck. On shared agent hosts, claim MCNPy before running;
  `--without-mcnp` avoids starting its Java gateway.
- On a clean Windows host, check first launch, repeated launch, offline operation,
  browser rendering, save/reopen, spaces in paths and changed drive letters.
- Exercise missing/corrupt payloads, unavailable WSL, insufficient local storage,
  an occupied port and interrupted setup. Verify existing projects and older
  runtime versions are retained, and unrelated distributions/processes survive.

Do not label an untested package as release-verified. Keep acceptance evidence
separate from the shipped runtime and record anything not exercised.

## Upgrades and recovery

An archive hash selects the private distribution name. A changed runtime creates
a new distribution; the previous one is retained. Verification stamps include
the manifest hash and package path, so moving a folder triggers verification.
Use `-VerifyOnly` to force another complete checksum pass. Verification stamps
are written only after successful dependency checks.

Deliver each update as a new folder. Users can move their projects/results after
the new version works, and return to the older folder for rollback. A failed WSL
import leaves its installation directory for diagnosis; the launcher explains
how to rename that incomplete directory and retry. It never unregisters an
existing distribution or recursively deletes user data automatically.

The launcher uses only its own token-tagged process for shutdown. A busy port
produces an error; `-Port <number>` selects another. It never uses a global WSL
shutdown or a broad process-name kill.
