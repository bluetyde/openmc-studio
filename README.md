# OpenMC on this SSD

OpenMC Studio and nuclear data that work on both the Mac and the Windows PC (WSL).
The drive is exFAT, so both can read and write it.

## Start OpenMC Studio

- **Windows:** double-click `Start OpenMC Studio.cmd`
- **Mac:** double-click `Start OpenMC Studio.command`

A window opens with the server, and Studio opens in your browser. Build a model,
press **Run**, and results appear on the viewport (flux map, neutron tracks) and
under **Results**. Click a neutron track, then **Replay neutron** to rerun exactly
that neutron with the same seed.

To stop Studio, close that window or press Ctrl+C in it. Runs are saved on the
computer (not the SSD) in `~/OpenMC-runs`, one folder per run with `model.py`,
the statepoint, tracks and the log. Past runs are under **Runs**.

It needs a conda env named `openmc-mcnp` with OpenMC installed; nothing else to
install. If your env has another name, start it from a terminal:
`OPENMC_STUDIO_ENV=<name> bash "<drive>/OpenMC/studio/start.sh"`.
If the env has no nuclear data set, Studio uses the library on this drive.

If the Mac says the `.command` file can't be opened, run it once from Terminal:
`bash "/Volumes/Extreme SSD/OpenMC/Start OpenMC Studio.command"`.

## What's here

```
OpenMC/
├── Start OpenMC Studio.cmd       Windows launcher (runs Studio in WSL)
├── Start OpenMC Studio.command   Mac launcher
├── studio/
│   ├── start.sh                  shared start script: finds conda, activates the env, starts the server
│   └── openmc_studio/            the local server (Python standard library + OpenMC) and the page
├── nuclear_data/
│   ├── endfb-viii.0-hdf5/        ENDF/B-VIII.0 for OpenMC (13 GB)
│   │   ├── cross_sections.xml    ← OPENMC_CROSS_SECTIONS points here
│   │   ├── neutron/  (556)   photon/  (100)   thermal/  (34)
│   └── archives/
│       ├── endfb80.tar.xz        original download, openmc.org/data (3.4 GB)
│       └── SHA256SUMS
├── setup/
│   ├── point_conda_env_here.sh   sets OPENMC_CROSS_SECTIONS on a conda env
│   └── verify.py                 checks the data and runs a small test
└── test/
    └── shielding_demo.py         OpenMC Studio demo model (D-T source, poly + lead, He-3 detector)
```

`cross_sections.xml` uses paths relative to itself, so the library works wherever
the drive is mounted.

## Git

This folder is the repo `github.com/bluetyde/openmc-studio` (private). The nuclear
data is not in git (see `.gitignore`); `nuclear_data/archives/SHA256SUMS` records
which archive it came from.

- Git refuses repos on exFAT drives until you mark them safe, once per computer:
  - Windows: `git config --global --add safe.directory D:/OpenMC`
  - Mac: `git config --global --add safe.directory "/Volumes/Extreme SSD/OpenMC"`
- To set up a new drive or computer from GitHub: clone the repo, then download
  `endfb80.tar.xz` from https://openmc.org/data/ (ENDF/B-VIII.0), check it with
  `SHA256SUMS`, and extract it into `nuclear_data/`.

## Nuclear data setup (optional)

Studio finds the library on this drive by itself. To use OpenMC outside Studio
(your own scripts), point the conda env at it once:

### Mac

1. Plug in the SSD. It mounts at `/Volumes/Extreme SSD`.
2. Point your OpenMC env at the library (use your env's name if it isn't `openmc-mcnp`):
   ```bash
   bash "/Volumes/Extreme SSD/OpenMC/setup/point_conda_env_here.sh" openmc-mcnp
   ```
3. Reactivate the env and check it:
   ```bash
   conda deactivate; conda activate openmc-mcnp
   python "/Volumes/Extreme SSD/OpenMC/setup/verify.py"
   ```

The setting is saved in the env, so this is a one-time step. If the drive is renamed,
run step 2 again.

### Windows PC (WSL)

The PC already has its own copy at `/root/nuclear_data/endfb-viii.0-hdf5`, and the
`openmc-mcnp` env uses it. That copy is on WSL's own disk, which loads faster than
the SSD through `/mnt/d`, and it works with the SSD unplugged.

To use the SSD copy instead:
```bash
bash /mnt/d/OpenMC/setup/point_conda_env_here.sh openmc-mcnp
```
To switch back to the local copy:
```bash
conda env config vars set -n openmc-mcnp OPENMC_CROSS_SECTIONS=/root/nuclear_data/endfb-viii.0-hdf5/cross_sections.xml
```
Reactivate the env after either change.

## Notes

- **Studio security:** the server only accepts connections from this computer and
  needs the token the launcher puts in the browser link, because it runs the Python
  the page sends it. Don't share that link.
- **Eject before unplugging.** exFAT has no journal, so pulling the drive mid-write can
  corrupt files. On the Mac, eject in Finder; on Windows, use Safely Remove Hardware.
- If OpenMC says it can't find `cross_sections.xml`, the SSD isn't mounted or the env
  points at the other copy. `verify.py` says which.
- macOS may add hidden `._*` files next to the data. They're harmless; OpenMC only
  opens the files listed in `cross_sections.xml`.
- Running `test/shielding_demo.py` writes results into the current folder. Run it from
  a folder on the computer, not on the SSD, e.g. `cd ~ && python "/Volumes/Extreme SSD/OpenMC/test/shielding_demo.py"`.
- To check the archive: `cd nuclear_data/archives && shasum -a 256 -c SHA256SUMS` (Mac) or
  `sha256sum -c SHA256SUMS` (WSL).
