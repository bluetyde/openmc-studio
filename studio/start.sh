#!/bin/bash
# Shared start script for OpenMC Studio (used by both double-click launchers).
# Finds conda, activates the OpenMC env, makes sure nuclear data is set, starts the server.
#
# Env name defaults to openmc-mcnp. To use another one:  OPENMC_STUDIO_ENV=myenv bash start.sh
ENV_NAME="${OPENMC_STUDIO_ENV:-openmc-mcnp}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export PYTHONDONTWRITEBYTECODE=1  # keep __pycache__ off the shared drive

if ! command -v conda >/dev/null 2>&1 || ! type conda 2>/dev/null | grep -q function; then
  for base in "$HOME/miniforge3" "$HOME/miniconda3" "$HOME/anaconda3" "$HOME/mambaforge" \
              "/opt/homebrew/Caskroom/miniforge/base" "/opt/miniconda3" "/opt/anaconda3" "/root/miniconda3"; do
    if [ -f "$base/etc/profile.d/conda.sh" ]; then source "$base/etc/profile.d/conda.sh"; break; fi
  done
fi
if ! type conda >/dev/null 2>&1; then
  echo "Can't find conda on this computer. Install Miniforge or Miniconda, or open a terminal where conda works and run:"
  echo "  bash \"$HERE/start.sh\""
  exit 1
fi
if ! conda activate "$ENV_NAME" 2>/dev/null; then
  echo "Couldn't activate the conda env '$ENV_NAME'. Envs on this computer:"
  conda env list
  echo "Start with your env's name, e.g.:  OPENMC_STUDIO_ENV=<name> bash \"$HERE/start.sh\""
  exit 1
fi
if ! python -c "import openmc" 2>/dev/null; then
  echo "OpenMC isn't installed in '$ENV_NAME'."
  exit 1
fi

# Nuclear data: use the env's setting if it works, otherwise the library on this drive.
if [ -z "${OPENMC_CROSS_SECTIONS:-}" ] || [ ! -f "$OPENMC_CROSS_SECTIONS" ]; then
  DRIVE_XS="$(dirname "$HERE")/nuclear_data/endfb-viii.0-hdf5/cross_sections.xml"
  if [ -f "$DRIVE_XS" ]; then
    export OPENMC_CROSS_SECTIONS="$DRIVE_XS"
    echo "Using the nuclear data on this drive: $DRIVE_XS"
  else
    echo "Warning: no nuclear data found. Runs will fail until OPENMC_CROSS_SECTIONS is set."
  fi
fi

cd "$HERE" || exit 1
exec python -m openmc_studio "$@"
