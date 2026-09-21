#!/bin/bash
# Point a conda env at the ENDF/B-VIII.0 library that sits beside this repository.
# Works on macOS, Linux and WSL: the library is found relative to this script, so it does not matter
# where the repository lives or where a drive is mounted.
#
#   bash setup/point_conda_env_here.sh [env-name]        # from the repository root
#   bash /path/to/OpenMC/setup/point_conda_env_here.sh   # from anywhere
#
# env-name defaults to openmc-mcnp. If your data is elsewhere, set OPENMC_CROSS_SECTIONS yourself
# (see INSTRUCTIONS.md).
set -euo pipefail

ENV_NAME="${1:-openmc-mcnp}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(dirname "$HERE")"
XS="$ROOT/nuclear_data/endfb-viii.0-hdf5/cross_sections.xml"

if [ ! -f "$XS" ]; then
  echo "Can't find $XS"
  echo "Check that the library was extracted there (see INSTRUCTIONS.md). If it is on a removable drive, check the drive is connected."
  exit 1
fi

# Find conda without needing an activated shell.
CONDA="${CONDA_EXE:-}"
if [ -z "$CONDA" ]; then
  for c in "$HOME/miniforge3/bin/conda" "$HOME/miniconda3/bin/conda" "$HOME/anaconda3/bin/conda" \
           "/opt/homebrew/Caskroom/miniforge/base/bin/conda" "/opt/miniconda3/bin/conda" "/opt/anaconda3/bin/conda" \
           "/root/miniconda3/bin/conda"; do
    if [ -x "$c" ]; then CONDA="$c"; break; fi
  done
fi
if [ -z "$CONDA" ] && command -v conda >/dev/null 2>&1; then CONDA="$(command -v conda)"; fi
if [ -z "$CONDA" ]; then
  echo "Can't find conda. Activate your base env first, or set CONDA_EXE."
  exit 1
fi

if ! "$CONDA" env list | awk '{print $1}' | grep -qx "$ENV_NAME"; then
  echo "No conda env named '$ENV_NAME'. Pass the right name as the first argument. Envs on this machine:"
  "$CONDA" env list
  exit 1
fi

"$CONDA" env config vars set -n "$ENV_NAME" OPENMC_CROSS_SECTIONS="$XS" >/dev/null
echo "Set OPENMC_CROSS_SECTIONS for '$ENV_NAME' to:"
echo "  $XS"
echo
echo "Next:"
echo "  conda deactivate; conda activate $ENV_NAME"
echo "  python \"$HERE/verify.py\""
