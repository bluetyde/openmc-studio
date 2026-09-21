# Setting up OpenMC Studio

Studio is a local app: a small Python server plus a browser page. It runs on **macOS, Linux and Windows
(through WSL2)**, and nothing here depends on a particular machine, drive or folder. Put the repository
wherever you like — an internal disk, a home directory, or an external drive — and the paths follow.

You need three things: a conda environment with OpenMC in it, a nuclear data library, and a way to start
the app. That is the whole setup.

---

## 1. Install conda

Any conda works. [Miniforge](https://github.com/conda-forge/miniforge) is the smallest. On an Apple Silicon Mac
you also need Rosetta 2 (`softwareupdate --install-rosetta --agree-to-license`), because OpenMC has no native
Apple Silicon package (see step 2).

On **Windows**, install conda **inside WSL2**, not in Windows itself: OpenMC's conda package is built for
Linux and macOS. If you don't have WSL2 yet, `wsl --install` in PowerShell, then open the Ubuntu terminal.

## 2. Create the environment

```bash
conda create -n openmc-mcnp -c conda-forge python=3.11 openmc numpy h5py
conda activate openmc-mcnp
```

**Apple Silicon Macs:** conda-forge has no `openmc` build for `osx-arm64`, only for `osx-64`, so the command
above fails there ("No match found"). Build the environment for Intel and let Rosetta run it, and pin the
environment to that so later installs don't drift back to arm64:

```bash
CONDA_SUBDIR=osx-64 conda create -n openmc-mcnp -c conda-forge python=3.11 openmc numpy h5py
conda activate openmc-mcnp
conda config --env --set subdir osx-64
```

That is enough to build models, run them and use every part of Studio except the MCNP export. For that, add:

```bash
conda install -c conda-forge montepy openjdk=8      # deck parsing, and Java for MCNPy's bridge
```

MCNPy is **not on PyPI** (`pip install mcnpy` finds nothing), and neither is MetaPy, which it needs (the
`metapy` on PyPI is an unrelated package). Both are installed from wheel files kept in their repositories.
Clone them somewhere outside this repository and install MetaPy first:

```bash
git clone https://github.rpi.edu/NuCoMP/metapy && git clone https://github.rpi.edu/NuCoMP/mcnpy.git
pip install metapy/dist/metapy-0.0.1-py3-none-any.whl
pip install mcnpy/dist/mcnpy-0.0.7-py3-none-any.whl
python -c "import mcnpy"    # must print "Metamodel Gateway Server Started", then "... Killed"
```

The MCNPy clone is about 130 MB and can take several minutes. That last line is the real test: an import that
succeeds without those two messages means the Java bridge isn't working.

Versions this was developed against: OpenMC 0.15.3, MontePy 1.1.3, MCNPy 0.0.7, MetaPy 0.0.1, Python 3.11.

## 3. Get the nuclear data

OpenMC needs a cross-section library. The official pre-generated **ENDF/B-VIII.0** library is a single
archive: about **3.4 GB to download and 13 GB once extracted**, so make sure the disk you choose has room.

```bash
mkdir -p ~/nuclear_data && cd ~/nuclear_data
curl -L --fail --retry 5 -C - -o endfb80.tar.xz \
  "https://anl.box.com/shared/static/uhbxlrx7hvxqw27psymfbhi7bx7s6u6a.xz"
tar -xJf endfb80.tar.xz          # gives endfb-viii.0-hdf5/
```

Check the download before trusting it (the expected hash is in `nuclear_data/archives/SHA256SUMS` in this
repository):

```bash
sha256sum endfb80.tar.xz         # macOS: shasum -a 256 endfb80.tar.xz
# 200cc6b97aa8cacc3f70ebc169bb91cf39381875fc80fb91ec5d84292da9b970  endfb80.tar.xz
```

The library holds incident neutron, photoatomic, atomic relaxation and thermal scattering data at 250 K,
293.6 K, 600 K, 900 K, 1200 K and 2500 K. Other libraries (ENDF/B-VIII.1, JEFF, JENDL) are listed at
<https://openmc.org/data/> and work the same way. If you would rather fetch data with a tool, the
`openmc_data` package has download scripts.

### Point the environment at it

Store the setting in the conda environment, so it applies whenever the environment is active:

```bash
conda env config vars set -n openmc-mcnp \
  OPENMC_CROSS_SECTIONS="$HOME/nuclear_data/endfb-viii.0-hdf5/cross_sections.xml"
conda deactivate && conda activate openmc-mcnp
python setup/verify.py
```

`verify.py` checks the setting, confirms the files listed in `cross_sections.xml` exist, and runs a tiny
transport problem. If it prints a green summary, the data side is done.

If the data sits beside this repository (see "Running from an external drive" below), the helper does the
same thing without typing the path:

```bash
bash setup/point_conda_env_here.sh openmc-mcnp
```

## 4. Start Studio

**Double-click** `Start OpenMC Studio.command` on macOS, or `Start OpenMC Studio.cmd` on Windows (it starts
the server inside WSL). Both open your browser at the app.

**From a terminal**, from the repository root:

```bash
bash studio/start.sh                          # finds conda, activates the env, starts the server
OPENMC_STUDIO_ENV=myenv bash studio/start.sh  # if your environment has another name
```

**Directly**, if your environment is already active:

```bash
cd studio && python -m openmc_studio --port 8765 --runs ~/OpenMC-runs
```

The server listens on 127.0.0.1 only and requires a token that the launcher puts in the URL, so nothing on
your network can reach it. Runs are written to `~/OpenMC-runs` unless `--runs` says otherwise.

## 5. Check it works

```bash
node test/generate_fixtures.js       # writes test/generated/*.py from the built-in models
python test/test_generated_models.py # builds and runs them (needs the nuclear data)
node test/test_frontend_model.js     # no data or OpenMC needed
```

The MCNP export has its own tests in the companion repository, `openmc-mcnp-project`. Point Studio at it
with `OPENMC_MCNP_PROJECT=/path/to/openmc-mcnp-project` once: Studio remembers the path (in
`~/OpenMC-runs/mcnp_project_path.txt`) after its first successful export. Without it, Studio looks in
`~/openmc-mcnp-project` and a few common folders under your home directory (`~/Developer`, `~/Projects`,
`~/Documents`, `~/code`, `~/git`, `~/repos`). Those tests need MCNPy, which needs Java, and MCNPy's bridge
uses a fixed port (25333), so only one MCNP export can run on a machine at a time.

Some Studio tests import code from that companion repository, and expect it at its current version:

```bash
export OPENMC_MCNP_PROJECT=/path/to/openmc-mcnp-project
PYTHONPATH="$OPENMC_MCNP_PROJECT/src" python test/test_mcnp_group_columns.py
python test/test_thermal_scattering.py                     # finds the repository through OPENMC_MCNP_PROJECT
```

Run `git pull` in `openmc-mcnp-project` first. An old checkout fails these two tests, with
`No module named 'deck_format'` and `Missing c_H_in_H2O_solid in SAB_MCNP_MAP`, and nothing else looks wrong.

---

## Running from an external drive

The repository is self-contained, so it can live on a USB or Thunderbolt drive and move between computers.
Two things to know:

- **Nuclear data may live beside it.** If `nuclear_data/endfb-viii.0-hdf5/cross_sections.xml` exists next to
  the repository, `studio/start.sh` uses it automatically, and `setup/point_conda_env_here.sh` writes that
  path into a conda environment. A copy on the internal disk is faster; a copy on the drive travels with you.
- **Git may refuse a drive owned by another user.** If git complains about "dubious ownership", tell it the
  path is fine:
  ```bash
  git config --global --add safe.directory "/path/to/OpenMC"
  ```

Nothing else in the code assumes a drive letter, a mount point or a user name.

## Troubleshooting

- **"OPENMC_CROSS_SECTIONS is not set"** — the setting lives in the conda environment, so reactivate it after
  setting it (`conda deactivate && conda activate openmc-mcnp`). Check with `echo $OPENMC_CROSS_SECTIONS`.
- **The path exists but files are missing** — the archive extracted partially. Verify the checksum above and
  extract again.
- **"Can't find conda"** — `start.sh` looks in the usual places (`~/miniforge3`, `~/miniconda3`, Homebrew's
  Caskroom, `/opt`). If yours is elsewhere, open a terminal where `conda activate` works and run
  `bash studio/start.sh` from there.
- **Windows: the launcher opens and closes** — the server runs in WSL. Check WSL works (`wsl -e bash -lc
  "conda env list"`), and that the environment exists inside WSL rather than in Windows.
- **Port already in use** — another Studio is still running. Close its window, or start on another port with
  `python -m openmc_studio --port 8766`.
- **A run stops with "secondary particle bank appears to be growing without bound"** — the model contains
  fissile material in a fixed-source run and multiplies without limit. Switch to an eigenvalue run for
  k-effective, or turn off Fission neutrons in the Physics tab to treat fission as capture.
