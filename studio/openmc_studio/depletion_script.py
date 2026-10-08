"""depletion_script.py: generate standalone Python scripts for OpenMC depletion calculations.

Given settings specifying a model path, depletion chain file, integrator class,
power history, and timesteps in days, builds a standalone script that runs an
OpenMC depletion calculation using openmc.deplete.CoupledOperator. This module
validates settings and emits script text; it never imports or runs OpenMC itself.
"""
import math

INTEGRATORS = (
    "PredictorIntegrator",
    "CECMIntegrator",
    "CELIIntegrator",
    "CF4Integrator",
    "EPCRK4Integrator",
    "LEQIIntegrator",
    "SICELIIntegrator",
    "SILEQIIntegrator",
)

_REQUIRED_KEYS = ("model_path", "chain_file", "integrator", "time_steps_days", "power_w")
# Optional: power_density (W per gram of heavy metal) instead of power_w; reduce_chain_level (keep only the nuclides within that many
# transmutation steps of the initial ones, which OpenMC needs on a chain of thousands of nuclides); prepare (call the model script's
# prepare_depletion(model), which Studio's model.py defines to set the volumes of its burnable materials).
_OPTIONAL_KEYS = ("power_density", "reduce_chain_level", "prepare")


class ScriptError(ValueError):
    """Raised when script generation settings are invalid or missing."""


def build_script(settings: dict) -> str:
    """Build a Python script that runs an OpenMC depletion calculation.

    Parameters
    ----------
    settings : dict
        Dictionary of settings with exactly the keys:
        - model_path (str): Non-empty path to the Studio model script.
        - chain_file (str): Non-empty path to the depletion chain XML file.
        - integrator (str): One of INTEGRATORS.
        - time_steps_days (list of float/int): Non-empty list of finite numbers > 0, no bools.
        - power_w (float/int): Finite number > 0 in watts, no bool. Give this or power_density, not both.
        Optional:
        - power_density (float/int): Finite number > 0 in W per gram of heavy metal, no bool.
        - reduce_chain_level (int): 1 or more, no bool.
        - prepare (bool): True to call prepare_depletion(model) from the model script before the operator is built.

    Returns
    -------
    str
        Deterministic Python script text ending in a single newline.

    Raises
    ------
    ScriptError
        If settings is not a dict, has missing or unknown keys, or contains invalid values.
    """
    if not isinstance(settings, dict):
        raise ScriptError(f"settings must be a dict, got {type(settings).__name__}")

    has_density = "power_density" in settings
    missing = [k for k in _REQUIRED_KEYS if k not in settings and not (k == "power_w" and has_density)]
    if missing:
        raise ScriptError(f"Missing required setting: {missing[0]}" + (" (or power_density)" if missing[0] == "power_w" else ""))
    if has_density and "power_w" in settings:
        raise ScriptError("give power_w or power_density, not both")

    extra = [k for k in settings if k not in _REQUIRED_KEYS and k not in _OPTIONAL_KEYS]
    if extra:
        raise ScriptError(f"Unknown setting: {extra[0]}")

    model_path = settings["model_path"]
    if not isinstance(model_path, str) or not model_path:
        raise ScriptError(f"model_path must be a non-empty string, got {model_path!r}")

    chain_file = settings["chain_file"]
    if not isinstance(chain_file, str) or not chain_file:
        raise ScriptError(f"chain_file must be a non-empty string, got {chain_file!r}")

    integrator = settings["integrator"]
    if integrator not in INTEGRATORS:
        raise ScriptError(f"integrator must be one of {INTEGRATORS}, got {integrator!r}")

    time_steps_days = settings["time_steps_days"]
    if not isinstance(time_steps_days, list) or isinstance(time_steps_days, bool):
        raise ScriptError(f"time_steps_days must be a list, got {type(time_steps_days).__name__}")
    if len(time_steps_days) == 0:
        raise ScriptError("time_steps_days must not be empty")

    for i, step in enumerate(time_steps_days):
        if isinstance(step, bool) or not isinstance(step, (int, float)):
            raise ScriptError(f"time_steps_days step {i} must be a number, got {step!r}")
        if not math.isfinite(step) or step <= 0:
            raise ScriptError(f"time_steps_days step {i} must be finite and > 0, got {step!r}")

    power_key = "power_density" if has_density else "power_w"
    power_w = settings[power_key]
    if isinstance(power_w, bool) or not isinstance(power_w, (int, float)):
        raise ScriptError(f"{power_key} must be a number, got {power_w!r}")
    if not math.isfinite(power_w) or power_w <= 0:
        raise ScriptError(f"{power_key} must be finite and > 0, got {power_w!r}")

    reduce_level = settings.get("reduce_chain_level")
    if "reduce_chain_level" in settings and (isinstance(reduce_level, bool) or not isinstance(reduce_level, int) or reduce_level < 1):
        raise ScriptError(f"reduce_chain_level must be a whole number of 1 or more, got {reduce_level!r}")
    prepare = settings.get("prepare", False)
    if not isinstance(prepare, bool):
        raise ScriptError(f"prepare must be true or false, got {prepare!r}")

    timesteps_repr = repr([float(s) for s in time_steps_days])
    power_repr = repr(float(power_w))
    model_path_repr = repr(model_path)
    chain_file_repr = repr(chain_file)

    operator_extra = f", reduce_chain_level={reduce_level}" if "reduce_chain_level" in settings else ""
    return (
        "# Generated by Studio's depletion_script.py; edit the settings, not this file.\n"
        "import runpy\n\n"
        "import openmc\n"
        "import openmc.deplete\n\n"
        f"namespace = runpy.run_path({model_path_repr})\n"
        "model = namespace[\"model\"]\n"
        + ("namespace[\"prepare_depletion\"](model)\n" if prepare else "")
        + f"operator = openmc.deplete.CoupledOperator(model, chain_file={chain_file_repr}{operator_extra})\n"
        f"integrator = openmc.deplete.{integrator}(operator, {timesteps_repr}, {'power_density' if has_density else 'power'}={power_repr}, timestep_units=\"d\")\n"
        "integrator.integrate()\n"
    )
