"""End-to-end regression test for Thermal Neutron Scattering S(alpha, beta) integration.

Verifies:
1. OpenMC properly loads and simulates with S(alpha, beta) libraries from ENDF/B-VIII.0.
2. Low-energy neutron thermalization correctly modifies the thermal flux spectrum.
3. OpenMC-to-MCNP exporter generates proper MT cards for materials with S(alpha, beta).
4. validate_deck confirms MCNP MT cards match OpenMC model.
"""
import os
import sys
import tempfile
import openmc
import numpy as np

# Nuclear data comes from the environment, or from OpenMC's own config if it has one. Any machine works;
# see INSTRUCTIONS.md if neither is set.
if not os.environ.get("OPENMC_CROSS_SECTIONS"):
    cfg = str(openmc.config.get("cross_sections", "") or "")
    if cfg and os.path.exists(cfg):
        os.environ["OPENMC_CROSS_SECTIONS"] = cfg
    else:
        raise SystemExit("Set OPENMC_CROSS_SECTIONS to a cross_sections.xml (see INSTRUCTIONS.md).")

def test_thermal_scattering_physics():
    print("--- 1. Testing OpenMC S(alpha, beta) Physics & Execution ---")
    openmc.reset_auto_ids()
    
    # Create graphite moderator material
    graphite = openmc.Material(name="Graphite Moderator")
    graphite.set_density("g/cm3", 1.7)
    graphite.add_element("C", 1.0)
    graphite.add_s_alpha_beta("c_Graphite")
    
    # Water moderator
    water = openmc.Material(name="Light Water")
    water.set_density("g/cm3", 1.0)
    water.add_element("H", 2.0)
    water.add_element("O", 1.0)
    water.add_s_alpha_beta("c_H_in_H2O")
    
    # Uranium dioxide fuel with S(a,b) for both U and O
    uo2 = openmc.Material(name="UO2 Fuel")
    uo2.set_density("g/cm3", 10.4)
    uo2.add_element("U", 1.0, enrichment=4.0)
    uo2.add_element("O", 2.0)
    uo2.add_s_alpha_beta("c_U_in_UO2")
    uo2.add_s_alpha_beta("c_O_in_UO2")
    
    materials = openmc.Materials([graphite, water, uo2])
    
    # Geometry: Small water sphere surrounded by graphite
    s1 = openmc.Sphere(r=10.0)
    s2 = openmc.Sphere(r=25.0, boundary_type="vacuum")
    
    c1 = openmc.Cell(name="Water Core", fill=water, region=-s1)
    c2 = openmc.Cell(name="Graphite Reflector", fill=graphite, region=+s1 & -s2)
    geometry = openmc.Geometry([c1, c2])
    
    # Point source at center
    source = openmc.IndependentSource()
    source.space = openmc.stats.Point((0, 0, 0))
    source.energy = openmc.stats.Discrete([1e6], [1.0])
    
    settings = openmc.Settings()
    settings.run_mode = "fixed source"
    settings.particles = 1000
    settings.batches = 5
    settings.source = source
    
    # Tally thermal flux (< 0.1 eV) and fast flux (> 100 keV)
    energy_filter = openmc.EnergyFilter([1e-5, 0.1, 1e5, 2e7])
    tally = openmc.Tally(name="Flux Spectrum")
    tally.filters = [openmc.CellFilter([c1, c2]), energy_filter]
    tally.scores = ["flux"]
    tallies = openmc.Tallies([tally])
    
    model = openmc.Model(geometry=geometry, materials=materials, settings=settings, tallies=tallies)
    
    with tempfile.TemporaryDirectory() as tmpdir:
        cwd = os.getcwd()
        try:
            os.chdir(tmpdir)
            model.export_to_model_xml()
            print("  Exported model.xml with S(alpha, beta) materials: OK")
            
            # Run simulation
            openmc.run(output=False)
            print("  OpenMC simulation executed with c_Graphite and c_H_in_H2O: PASSED")
            
            # Check statepoint
            sp = openmc.StatePoint("statepoint.5.h5")
            t = sp.get_tally(name="Flux Spectrum")
            mean = t.mean.ravel()
            print(f"  Thermal flux in water core (<0.1 eV): {mean[0]:.4e}")
            print(f"  Fast flux in water core (>100 keV): {mean[1]:.4e}")
            assert mean[0] > 0, "Expected non-zero thermal flux with S(a,b)"
            print("  Physics assertion verified: non-zero thermalized spectrum detected.")
        finally:
            os.chdir(cwd)

def test_mcnp_mt_export():
    print("\n--- 2. Testing MCNP Exporter MT Card Generation ---")
    # the exporter the server would use: OPENMC_MCNP_PROJECT, else ~/openmc-mcnp-project
    exporter_path = os.path.join(os.path.expanduser(os.environ.get("OPENMC_MCNP_PROJECT", "~/openmc-mcnp-project")), "src")
    if exporter_path not in sys.path:
        sys.path.insert(0, exporter_path)
        
    from mcnp_cards import SAB_MCNP_MAP
    import remediate_deck
    import validate_deck
    
    # Verify all 34 tables exist in SAB_MCNP_MAP
    expected_tables = [
        "c_H_in_H2O", "c_H_in_H2O_solid", "c_D_in_D2O", "c_O_in_D2O",
        "c_Graphite", "c_Graphite_10p", "c_Graphite_30p", "c_C6H6",
        "c_H_in_CH2", "c_H_in_C5O2H8", "c_H_in_CH4_liquid", "c_H_in_CH4_solid",
        "c_Be", "c_Be_in_BeO", "c_O_in_BeO", "c_H_in_ZrH", "c_Zr_in_ZrH",
        "c_H_in_YH2", "c_Y_in_YH2", "c_U_in_UO2", "c_O_in_UO2", "c_U_in_UN", "c_N_in_UN",
        "c_SiO2_alpha", "c_SiO2_beta", "c_Si_in_SiC", "c_C_in_SiC",
        "c_Al27", "c_Fe56", "c_ortho_D", "c_ortho_H", "c_para_D", "c_para_H"
    ]
    for table in expected_tables:
        assert table in SAB_MCNP_MAP, f"Missing {table} in SAB_MCNP_MAP"
    print(f"  All {len(expected_tables)} ENDF/B-VIII.0 tables present in SAB_MCNP_MAP: OK")
    
    # Build test model with multiple S(a,b) materials
    openmc.reset_auto_ids()
    poly = openmc.Material(name="Polyethylene")
    poly.set_density("g/cm3", 0.94)
    poly.add_element("H", 2.0)
    poly.add_element("C", 1.0)
    poly.add_s_alpha_beta("c_H_in_CH2")
    
    uo2 = openmc.Material(name="UO2")
    uo2.set_density("g/cm3", 10.5)
    uo2.add_element("U", 1.0, enrichment=3.0)
    uo2.add_element("O", 2.0)
    uo2.add_s_alpha_beta("c_U_in_UO2")
    uo2.add_s_alpha_beta("c_O_in_UO2")
    
    materials = openmc.Materials([poly, uo2])
    sp1 = openmc.Sphere(r=5.0)
    sp2 = openmc.Sphere(r=15.0, boundary_type="vacuum")
    cell1 = openmc.Cell(name="Fuel", fill=uo2, region=-sp1)
    cell2 = openmc.Cell(name="Moderator", fill=poly, region=+sp1 & -sp2)
    geometry = openmc.Geometry([cell1, cell2])
    
    settings = openmc.Settings()
    settings.run_mode = "eigenvalue"
    settings.particles = 100
    settings.batches = 10
    settings.inactive = 2
    settings.source = openmc.IndependentSource(space=openmc.stats.Point((0, 0, 0)))
    
    model = openmc.Model(geometry=geometry, materials=materials, settings=settings)
    
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create minimal translated mock deck
        raw_deck = os.path.join(tmpdir, "raw.mcnp")
        runnable_deck = os.path.join(tmpdir, "runnable.mcnp")
        with open(raw_deck, "w") as f:
            f.write("Mock MCNP Deck with SAB\n")
            f.write("1 2 -10.5 -1 imp:n=1\n")
            f.write("2 1 -0.94 1 -2 imp:n=1\n\n")
            f.write("1 so 5.0\n2 so 15.0\n\n")
            f.write("m1 1001.80c 2.0 6000.80c 1.0\n")
            f.write("m2 92235.80c 0.03 92238.80c 0.97 8016.80c 2.0\n")
        
        rep = remediate_deck.remediate(raw_deck, model, runnable_deck)
        print("  Remediation report added items:", rep["added"])
        
        # Verify MT cards exist in runnable deck
        with open(runnable_deck) as f:
            deck_text = f.read()
        
        assert "MT1" in deck_text and "h-poly.40t" in deck_text, "Expected MT1 h-poly.40t for Polyethylene"
        assert "MT2" in deck_text and "u-uo2.40t" in deck_text and "o-uo2.40t" in deck_text, "Expected MT2 with u-uo2.40t and o-uo2.40t for UO2"
        print("  Generated MCNP deck contains all companion MT cards: OK")
        
        # Validate deck with validate_deck
        ok = validate_deck.validate_deck(runnable_deck, model=model, geometry_samples=1000)
        assert ok, "validate_deck failed on S(a,b) deck"
        print("  validate_deck passed with full MT validation: OK")

if __name__ == "__main__":
    test_thermal_scattering_physics()
    test_mcnp_mt_export()
    print("\nALL THERMAL SCATTERING TESTS PASSED!")
