"""material_assistant: nuclide-by-nuclide mass fractions and atom densities from engineering inputs.

Provides two plain arithmetic functions:
- `uranium_dioxide`: converts enrichment (wt%), percent of theoretical density, and theoretical
  density into mass fractions and atom densities for U-235, U-238, and O-16.
- `borated_water`: converts soluble boron concentration (ppm), solution density, deuterium
  fraction, and B-10 abundance into mass fractions and atom densities for H-1, H-2, O-16,
  B-10, and B-11.

This module is arithmetic only. It does not import openmc, does not construct an openmc.Material,
and does not look up any water density: the caller supplies the densities.
"""
from __future__ import annotations

import math

# Avogadro constant N_A = 6.02214076e23 per mole (exact, SI 2019)
AVOGADRO = 6.02214076e23
N_A = AVOGADRO

# atomic masses as in openmc.data, from AME2016 (Wang et al., Chinese Physics C 41, 030003, 2017) (units: u)
ATOMIC_MASSES: dict[str, float] = {
    "H1": 1.007825031898,
    "H2": 2.014101777844,
    "O16": 15.99491461926,
    "B10": 10.012936862,
    "B11": 11.009305166,
    "U235": 235.043928117,
    "U238": 238.050786936,
}

# natural abundance as in openmc.data
NATURAL_ABUNDANCES: dict[str, float] = {
    "B10": 0.1982,
    "B11": 0.8018,
}

B10_NATURAL_ABUNDANCE = NATURAL_ABUNDANCES["B10"]
B11_NATURAL_ABUNDANCE = NATURAL_ABUNDANCES["B11"]

M_H1 = ATOMIC_MASSES["H1"]
M_H2 = ATOMIC_MASSES["H2"]
M_O16 = ATOMIC_MASSES["O16"]
M_B10 = ATOMIC_MASSES["B10"]
M_B11 = ATOMIC_MASSES["B11"]
M_U235 = ATOMIC_MASSES["U235"]
M_U238 = ATOMIC_MASSES["U238"]

__all__ = [
    "ATOMIC_MASSES",
    "AVOGADRO",
    "B10_NATURAL_ABUNDANCE",
    "B11_NATURAL_ABUNDANCE",
    "NATURAL_ABUNDANCES",
    "N_A",
    "MaterialError",
    "borated_water",
    "uranium_dioxide",
]


class MaterialError(ValueError):
    """Raised for invalid or out-of-range material assistant arguments."""


def _check_number(
    name: str,
    val: object,
    *,
    min_val: float,
    max_val: float | None = None,
    min_exclusive: bool = False,
    max_exclusive: bool = False,
) -> float:
    """Validate a numeric argument against type, finiteness, and bounds."""
    if isinstance(val, bool):
        raise MaterialError(f"Argument '{name}' cannot be a boolean; got {val!r}")
    if not isinstance(val, (int, float)):
        raise MaterialError(f"Argument '{name}' must be a number; got {type(val).__name__}: {val!r}")
    if not math.isfinite(val):
        raise MaterialError(f"Argument '{name}' must be a finite number; got {val!r}")

    fval = float(val)
    if min_exclusive:
        if fval <= min_val:
            raise MaterialError(f"Argument '{name}' must be > {min_val}; got {val!r}")
    else:
        if fval < min_val:
            raise MaterialError(f"Argument '{name}' must be >= {min_val}; got {val!r}")

    if max_val is not None:
        if max_exclusive:
            if fval >= max_val:
                raise MaterialError(f"Argument '{name}' must be < {max_val}; got {val!r}")
        else:
            if fval > max_val:
                raise MaterialError(f"Argument '{name}' must be <= {max_val}; got {val!r}")

    return fval


def uranium_dioxide(
    enrichment_wt_pct: float,
    percent_td: float,
    theoretical_density_g_cm3: float,
) -> dict:
    """Compute density, mass fractions, and atom densities for uranium dioxide (UO2).

    Calculates nuclide-by-nuclide mass fractions and atom densities from
    engineering inputs: enrichment in weight percent, percent of theoretical
    density, and theoretical density.

    Assumptions and definitions:
    - Enrichment is the weight percent of U-235 in the total uranium. The
      other uranium is U-238; U-234 and U-236 are ignored.
    - Percent of theoretical density (`percent_td`) scales the density:
      `density = theoretical_density * percent_td / 100`.
    - Oxygen is taken as pure O-16 (a stated simplification; natural oxygen has
      0.04 percent O-17 and 0.2 percent O-18).
    - No default theoretical density exists in this module: the caller always
      supplies `theoretical_density_g_cm3`. Never invent one.

    Parameters
    ----------
    enrichment_wt_pct : float
        U-235 enrichment in weight percent of total uranium (0 < x <= 100).
    percent_td : float
        Percent of theoretical density (0 < x <= 100).
    theoretical_density_g_cm3 : float
        Theoretical density of UO2 in g/cm³ (> 0).

    Returns
    -------
    dict
        Dict containing:
        - 'density_g_cm3': bulk density in g/cm³ (float).
        - 'mass_fractions': dict mapping 'U235', 'U238', 'O16' to mass fractions summing to 1.
        - 'atom_density_per_b_cm': dict mapping 'U235', 'U238', 'O16' to atom densities in atoms/(b·cm).

    Raises
    ------
    MaterialError
        If any argument is invalid, non-numeric, non-finite, or out of range.
    """
    e = _check_number("enrichment_wt_pct", enrichment_wt_pct, min_val=0.0, max_val=100.0, min_exclusive=True)
    p_td = _check_number("percent_td", percent_td, min_val=0.0, max_val=100.0, min_exclusive=True)
    td = _check_number("theoretical_density_g_cm3", theoretical_density_g_cm3, min_val=0.0, min_exclusive=True)

    # 1. Uranium weight fractions: w5 = enrichment_wt_pct / 100, w8 = 1 - w5
    w5 = e / 100.0
    w8 = 1.0 - w5

    # 2. Uranium atom fraction of U-235: x5 = (w5 / M5) / (w5 / M5 + w8 / M8); molar mass of uranium
    inv_m5 = w5 / M_U235
    inv_m8 = w8 / M_U238
    sum_inv = inv_m5 + inv_m8
    x5 = inv_m5 / sum_inv
    M_U = x5 * M_U235 + (1.0 - x5) * M_U238

    # 3. Molar mass of the oxide: M_UO2 = M_U + 2 * M_O16
    M_UO2 = M_U + 2.0 * M_O16

    # 4. density_g_cm3 = theoretical_density_g_cm3 * percent_td / 100
    density_g_cm3 = td * p_td / 100.0

    # 5. Mass fractions: U235 = (M_U / M_UO2) * w5, U238 = (M_U / M_UO2) * w8, O16 = 2 * M_O16 / M_UO2
    mf_u235 = (M_U / M_UO2) * w5
    mf_u238 = (M_U / M_UO2) * w8 if w8 > 0.0 else 0.0
    mf_o16 = 2.0 * M_O16 / M_UO2

    # 6. Atom densities: N_UO2 = density * N_A / M_UO2 * 1e-24
    N_UO2 = density_g_cm3 * N_A / M_UO2 * 1e-24
    ad_u235 = x5 * N_UO2
    ad_u238 = (1.0 - x5) * N_UO2 if (1.0 - x5) > 0.0 else 0.0
    ad_o16 = 2.0 * N_UO2

    return {
        "density_g_cm3": density_g_cm3,
        "mass_fractions": {
            "U235": mf_u235,
            "U238": mf_u238,
            "O16": mf_o16,
        },
        "atom_density_per_b_cm": {
            "U235": ad_u235,
            "U238": ad_u238,
            "O16": ad_o16,
        },
    }


def borated_water(
    boron_ppm: float,
    solution_density_g_cm3: float,
    deuterium_fraction: float = 0.0,
    b10_atom_fraction: float = B10_NATURAL_ABUNDANCE,
) -> dict:
    """Compute density, mass fractions, and atom densities for borated water.

    Calculates nuclide-by-nuclide mass fractions and atom densities from
    engineering inputs: soluble boron concentration in ppm, solution density,
    deuterium fraction, and B-10 isotopic abundance.

    Assumptions and definitions:
    - Soluble boron in ppm means grams of boron (the element, natural or enriched
      as given) per million grams of the whole solution (water plus boron).
      The boron mass fraction of the solution is exactly `ppm * 1e-6`.
    - `deuterium_fraction` is the fraction of the water's hydrogen ATOMS that
      are H-2 (0 is light water, 1 is heavy water).
    - Oxygen is taken as pure O-16 (a stated simplification; natural oxygen has
      0.04 percent O-17 and 0.2 percent O-18).
    - No default water density exists in this module: the caller always supplies
      `solution_density_g_cm3`. Never invent one.
    - The thermal scattering table (for hydrogen bound in water) is NOT chosen
      by this function; the caller attaches it.

    Parameters
    ----------
    boron_ppm : float
        Boron concentration in ppm by mass (0 <= x < 1e6).
    solution_density_g_cm3 : float
        Solution density in g/cm³ (> 0).
    deuterium_fraction : float, optional
        Fraction of hydrogen atoms that are H-2 (0 <= x <= 1, default 0.0).
    b10_atom_fraction : float, optional
        Atom fraction of B-10 in total boron (0 <= x <= 1, default natural B-10 abundance).

    Returns
    -------
    dict
        Dict containing:
        - 'density_g_cm3': solution density in g/cm³ (float).
        - 'mass_fractions': dict mapping 'H1', 'H2', 'O16', 'B10', 'B11' to mass fractions summing to 1.
        - 'atom_density_per_b_cm': dict mapping 'H1', 'H2', 'O16', 'B10', 'B11' to atom densities in atoms/(b·cm).

    Raises
    ------
    MaterialError
        If any argument is invalid, non-numeric, non-finite, or out of range.
    """
    ppm = _check_number("boron_ppm", boron_ppm, min_val=0.0, max_val=1e6, max_exclusive=True)
    sol_density = _check_number("solution_density_g_cm3", solution_density_g_cm3, min_val=0.0, min_exclusive=True)
    f = _check_number("deuterium_fraction", deuterium_fraction, min_val=0.0, max_val=1.0)
    b = _check_number("b10_atom_fraction", b10_atom_fraction, min_val=0.0, max_val=1.0)

    # 1. wB = boron_ppm * 1e-6; water mass fraction is 1 - wB
    wB = ppm * 1e-6
    w_water = 1.0 - wB

    # 2. Hydrogen molar mass M_H = (1 - f) * M_H1 + f * M_H2; water molar mass M_w = 2 * M_H + M_O16
    M_H = (1.0 - f) * M_H1 + f * M_H2
    M_w = 2.0 * M_H + M_O16

    # 3. Boron molar mass M_B = b * M_B10 + (1 - b) * M_B11
    M_B = b * M_B10 + (1.0 - b) * M_B11

    # 4. Mass fractions
    mf_b10 = (wB * b * M_B10 / M_B) if (wB > 0.0 and b > 0.0) else 0.0
    mf_b11 = (wB * (1.0 - b) * M_B11 / M_B) if (wB > 0.0 and (1.0 - b) > 0.0) else 0.0
    mf_h1 = (w_water * 2.0 * (1.0 - f) * M_H1 / M_w) if (1.0 - f) > 0.0 else 0.0
    mf_h2 = (w_water * 2.0 * f * M_H2 / M_w) if f > 0.0 else 0.0
    mf_o16 = w_water * M_O16 / M_w

    # 5. density_g_cm3 = solution_density_g_cm3; atom densities = density * mass_fraction * N_A / M_nuclide * 1e-24
    density_g_cm3 = sol_density
    ad_h1 = density_g_cm3 * mf_h1 * N_A / M_H1 * 1e-24 if mf_h1 > 0.0 else 0.0
    ad_h2 = density_g_cm3 * mf_h2 * N_A / M_H2 * 1e-24 if mf_h2 > 0.0 else 0.0
    ad_o16 = density_g_cm3 * mf_o16 * N_A / M_O16 * 1e-24
    ad_b10 = density_g_cm3 * mf_b10 * N_A / M_B10 * 1e-24 if mf_b10 > 0.0 else 0.0
    ad_b11 = density_g_cm3 * mf_b11 * N_A / M_B11 * 1e-24 if mf_b11 > 0.0 else 0.0

    return {
        "density_g_cm3": density_g_cm3,
        "mass_fractions": {
            "H1": mf_h1,
            "H2": mf_h2,
            "O16": mf_o16,
            "B10": mf_b10,
            "B11": mf_b11,
        },
        "atom_density_per_b_cm": {
            "H1": ad_h1,
            "H2": ad_h2,
            "O16": ad_o16,
            "B10": ad_b10,
            "B11": ad_b11,
        },
    }
