#!/bin/bash
# Point a conda env at the ENDF/B-VIII.0 library on this SSD.
# Works on macOS and on Linux/WSL: it finds the library relative to this script,
# so it does not matter where the drive is mounted.
#
#   macOS:  bash "/Volumes/Extreme SSD/OpenMC/setup/point_conda_env_here.sh" [env-name]
#   WSL:    bash /mnt/d/OpenMC/setup/point_conda_env_here.sh [env-name]
#
# env-name defaults to openmc-mcnp.
set -euo pipefail

ENV_NAME="${1:-openmc-mcnp}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(dirname "$HERE")"
XS="$ROOT/nuclear_data/endfb-viii.0-hdf5/cross_sections.xml"

if [ ! -f "$XS" ]; then
  echo "Can't find $XS"
  echo "Check that the SSD is mounted and the library was extracted."
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
