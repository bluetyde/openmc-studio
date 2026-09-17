"""Check OpenMC Studio's material library (static/materials.jsonl), and add new batches to it.

    python studio/tools/check_materials.py                      check the library
    python studio/tools/check_materials.py --add batch.txt      check a batch, then merge it into the library

The library is JSON Lines, one material per line:
    {"num": 354, "name": "Water, Liquid", "density": 0.998207, "category": "Water and liquids",
     "comps": "H:0.111894, O:0.888106"}
num       PNNL-15870 Rev. 1 entry number. Leave it out for a material of your own.
name      as in the compendium heading.
density   g/cm3.
category  one of CATEGORIES below.
comps     Symbol:fraction, comma separated. O or Fe is the natural element; U235 or H2 is one nuclide.
Optional: "frac" ("wo" weight, the default, or "ao" atom), "sab" (thermal scattering table, e.g.
"c_H_in_H2O"; left out, Studio picks one for water, polyethylene, paraffin, graphite and beryllium),
"color" ("#rrggbb"; left out, Studio colors by category), "ref" (source note for your own materials).

Entries with a num are compared with the text of the PNNL-15870 Rev. 1 PDF (pnnl-15870-rev1.txt next
to this script) when that file is there: name, density, the component list and every weight fraction.
A batch can be pasted as JSON Lines or as objects run together on one line.
--nuclear-data (run where OpenMC is installed, e.g. the openmc-mcnp conda env in WSL) also builds each
material with OpenMC and checks that every nuclide and S(a,b) table it needs is in OPENMC_CROSS_SECTIONS.
Exit code 0 = no errors (warnings allowed), 1 = errors.
"""
import os
import warnings
import argparse
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
LIBRARY = HERE.parent / "openmc_studio" / "static" / "materials.jsonl"
PDF_TEXT = HERE / "pnnl-15870-rev1.txt"
PNNL_COUNT = 372

CATEGORIES = ["Gases", "Water and liquids", "Plastics and polymers", "Concrete and building materials",
              "Metals and alloys", "Steels", "Nuclear fuel", "Neutron absorbers and shielding",
              "Tissue and dosimetry", "Minerals, rocks and soils", "Detectors and scintillators", "Other compounds"]
ELEMENTS = set("""H He Li Be B C N O F Ne Na Mg Al Si P S Cl Ar K Ca Sc Ti V Cr Mn Fe Co Ni Cu Zn Ga Ge As Se Br Kr
Rb Sr Y Zr Nb Mo Tc Ru Rh Pd Ag Cd In Sn Sb Te I Xe Cs Ba La Ce Pr Nd Pm Sm Eu Gd Tb Dy Ho Er Tm Yb Lu Hf Ta W Re
Os Ir Pt Au Hg Tl Pb Bi Po At Rn Fr Ra Ac Th Pa U Np Pu Am Cm Bk Cf""".split())
# Elements with no natural isotopic abundance in OpenMC (openmc.data.NATURAL_ABUNDANCE, 0.15.3):
# add_element fails for them, so they must be listed as nuclides.
NO_NATURAL = {"Tc", "Pm", "Po", "At", "Rn", "Fr", "Ra", "Ac", "Np", "Pu", "Am", "Cm", "Bk", "Cf"}
# Same pattern Studio's parseComps accepts.
COMP = re.compile(r"^([A-Z][a-z]?)(\d{1,3}(?:_m\d)?)?\s*:\s*([0-9]*\.?[0-9]+(?:[eE][-+]?\d+)?)$")
# Entries that are wrong in the PDF itself, so a faithful transcription still shouldn't be used.
KNOWN_PDF_ERRORS = {155: "the PDF prints Concrete, Rocky Flats' composition and density (#100) under Inconel-625; "
                         "leave it out or use a composition from another source"}
KNOWN_KEYS = {"num", "name", "density", "category", "comps", "frac", "sab", "color", "ref"}


def pdf_reference(path):
    """Material number -> name, density and (symbol, weight fraction) rows, read from the PDF text."""
    lines = path.read_text(encoding="utf-8").split("\n")
    ref = {}
    for i, line in enumerate(lines):
        m = re.match(r"^(\d{1,3}) (\S.*\S)$", line.strip())
        if not m or not any(x.startswith("Formula =") for x in lines[i + 1:i + 3]):
            continue
        dens, rows, in_table = None, [], False
        for w in lines[i + 1:i + 200]:
            t = w.strip()
            if dens is None:
                d = re.search(r"Density \(g/cm3\) = ([0-9.Ee+-]+)", t)
                if d:
                    dens = float(d.group(1))
            if not in_table:
                in_table = t.startswith("Element Neutron ZA")
                continue
            if t.startswith("Total"):
                break
            p = t.split()
            # symbol (U-235 for a nuclide; one entry writes AL), neutron ZA ("-" when there is no
            # elemental evaluation), photon ZA, weight fraction, atom fraction, atom density.
            # Page headers inside a table don't match this shape and are skipped.
            if len(p) == 6 and re.match(r"^[A-Z][A-Za-z]?(-\d+)?$", p[0]) and (p[1].isdigit() or p[1] == "-"):
                el, _, mass = p[0].partition("-")
                rows.append((el[0] + el[1:].lower() + mass, p[3]))
        if dens is not None and rows:
            ref[int(m.group(1))] = {"name": m.group(2), "density": dens, "rows": rows}
    return ref


def read_objects(path, strict_lines):
    """[(line number, object or error text)]. strict_lines: the library must be one object per line."""
    text = path.read_text(encoding="utf-8-sig")
    out, dec = [], json.JSONDecoder()
    for ln, line in enumerate(text.split("\n"), 1):
        s, i = line.strip(), 0
        count = 0
        while i < len(s):
            while i < len(s) and s[i] in " \t\r,":
                i += 1
            if i >= len(s):
                break
            try:
                obj, i = dec.raw_decode(s, i)
            except json.JSONDecodeError as e:
                out.append((ln, f"not valid JSON ({e.msg} at column {e.colno + i})"))
                break
            count += 1
            if strict_lines and count == 2:
                out.append((ln, "more than one material on this line; put each on its own line"))
            out.append((ln, obj))
    return out


def check(entries, ref, whole_library):
    """Returns (errors, warnings) as lists of strings."""
    errors, warnings = [], []
    nums, names = {}, {}
    for ln, m in entries:
        if isinstance(m, str):
            errors.append(f"line {ln}: {m}")
            continue
        if not isinstance(m, dict):
            errors.append(f"line {ln}: not a JSON object")
            continue
        n = m.get("num")
        tag = f"line {ln} (#{n} {m.get('name', '?')})" if n is not None else f"line {ln} ({m.get('name', '?')})"
        E = lambda msg: errors.append(f"{tag}: {msg}")
        W = lambda msg: warnings.append(f"{tag}: {msg}")

        unknown = set(m) - KNOWN_KEYS
        if unknown:
            W(f"unknown field(s) {sorted(unknown)} are ignored")
        if n is not None:
            if not isinstance(n, int) or not 1 <= n <= PNNL_COUNT:
                E(f"num must be a whole number from 1 to {PNNL_COUNT}")
            elif n in nums:
                E(f"num {n} already used on line {nums[n]}")
            else:
                nums[n] = ln
        name = m.get("name")
        if not isinstance(name, str) or not name.strip():
            E("name is missing")
        elif name.strip().lower() in names:
            W(f"same name as line {names[name.strip().lower()]}")
        else:
            names[name.strip().lower()] = ln
        dens = m.get("density")
        if isinstance(dens, bool) or not isinstance(dens, (int, float)) or not dens > 0:
            E(f"density must be a number above 0 (got {dens!r})")
        cat = m.get("category")
        if cat not in CATEGORIES:
            (E if whole_library or cat is not None else W)(f"category {cat!r} is not one of the {len(CATEGORIES)} categories")
        frac = m.get("frac", "wo")
        if frac not in ("wo", "ao"):
            E('frac must be "wo" or "ao"')
        sab = m.get("sab")
        if sab not in (None, "") and not (isinstance(sab, str) and re.match(r"^c_\w+$", sab)):
            E("sab must look like c_H_in_H2O")
        color = m.get("color")
        if color is not None and not (isinstance(color, str) and re.match(r"^#[0-9a-fA-F]{6}$", color)):
            E('color must look like "#3f86d6"')

        comps = m.get("comps")
        parsed, total, sum_off = [], 0.0, False
        if not isinstance(comps, str) or not comps.strip():
            E("comps is missing")
        else:
            for tok in [t.strip() for t in comps.split(",") if t.strip()]:
                cm = COMP.match(tok)
                if not cm:
                    E(f"can't read component {tok!r} (write Symbol:amount, like O:0.888106 or U235:0.03)")
                    continue
                el, mass, amt = cm.group(1), cm.group(2) or "", float(cm.group(3))
                if el not in ELEMENTS:
                    E(f"{el!r} is not an element symbol")
                if amt < 0:
                    E(f"{tok}: amount can't be negative")  # 0 is allowed: the PDF lists e.g. Am241:0.000000; Studio drops it
                if not mass and el in NO_NATURAL:
                    W(f"{el} has no natural isotopes in OpenMC; list nuclides (e.g. {el}239) or the model won't run")
                parsed.append((el + mass, cm.group(3)))
            syms = [p[0] for p in parsed]
            dup = sorted({s for s in syms if syms.count(s) > 1})
            if dup:
                E(f"component(s) listed twice: {dup}")
            total = sum(float(p[1]) for p in parsed)
            sum_off = bool(parsed) and frac == "wo" and abs(total - 1) > 2e-5
        r =ref.get(n) if ref and isinstance(n, int) else None
        matches_pdf = False
        if ref and isinstance(n, int) and 1 <= n <= PNNL_COUNT and not r:
            W("not found in the PDF text, so it wasn't compared")
        if r:
            if n in KNOWN_PDF_ERRORS:
                W(KNOWN_PDF_ERRORS[n])
            if isinstance(name, str) and " ".join(name.split()) != " ".join(r["name"].split()):
                E(f"name differs from the PDF: {r['name']!r}")
            if isinstance(dens, (int, float)) and abs(dens - r["density"]) > 1e-9 * max(1.0, r["density"]):
                E(f"density {dens} differs from the PDF: {r['density']}")
            if frac != "wo":
                E('PNNL entries use weight fractions; remove "frac"')
            if parsed:
                got, want = [p[0] for p in parsed], [w[0] for w in r["rows"]]
                if got != want:
                    E(f"components {got} differ from the PDF: {want}")
                else:
                    off = [(sym, v, wv) for (sym, v), (_, wv) in zip(parsed, r["rows"]) if abs(float(v) - float(wv)) > 5e-7]
                    for sym, v, wv in off:
                        E(f"{sym} weight fraction {v} differs from the PDF: {wv}")
                    matches_pdf = not off
        if sum_off and not matches_pdf:  # a few PNNL entries themselves total 1.0001
            (E if abs(total - 1) > 1e-3 else W)(f"weight fractions add up to {total:.6f}, not 1")
    if whole_library and nums:
        missing = [k for k in range(1, PNNL_COUNT + 1) if k not in nums and k not in KNOWN_PDF_ERRORS]
        if missing:
            warnings.append(f"{len(missing)} of {PNNL_COUNT} PNNL entries not in the library yet: {span(missing)}")
    return errors, warnings


SAB_RULES = [(r"^water, liquid", "c_H_in_H2O"), (r"^water, heavy", "c_D_in_D2O"),
             (r"^polyethylene(, (non-)?borated)?$|^polyethylene, borated \(|^wax, paraffin|paraffin wax", "c_H_in_CH2"), (r"graphite", "c_Graphite"), (r"^beryllium$", "c_Be")]


def sab_for(m):
    """Same rule as Studio's sabFor: the table a material gets when its line doesn't name one."""
    if isinstance(m.get("sab"), str):
        return m["sab"]
    name = m.get("name", "").lower()
    return next((t for rx, t in SAB_RULES if re.search(rx, name)), "")


def check_nuclear_data(entries):
    """Errors for materials OpenMC can't build or whose data isn't in OPENMC_CROSS_SECTIONS."""
    try:
        import openmc
        import openmc.data
    except ImportError:
        return ["--nuclear-data needs OpenMC (run it in the openmc-mcnp environment)"]
    xs = os.environ.get("OPENMC_CROSS_SECTIONS")
    if not xs or not Path(xs).is_file():
        return ["OPENMC_CROSS_SECTIONS is not set or the file is missing"]
    have = set()
    for lib in openmc.data.DataLibrary.from_xml(xs).libraries:
        have.update(lib["materials"])
    errors = []
    for ln, m in entries:
        if not isinstance(m, dict):
            continue
        tag = f"line {ln} (#{m.get('num')} {m.get('name')})" if m.get("num") else f"line {ln} ({m.get('name')})"
        try:
            mat = openmc.Material()
            for tok in [t.strip() for t in str(m.get("comps", "")).split(",") if t.strip()]:
                cm = COMP.match(tok)
                sym, amt = cm.group(1) + (cm.group(2) or ""), float(cm.group(3))
                if amt == 0:
                    continue
                before = len(mat.nuclides)
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")  # OpenMC only warns, then adds nothing, for Pu and the like
                    (mat.add_nuclide if cm.group(2) else mat.add_element)(sym, amt, m.get("frac", "wo"))
                if len(mat.nuclides) == before:
                    errors.append(f"{tag}: OpenMC added nothing for {sym} (no natural isotopes; list nuclides)")
            missing = sorted(set(mat.get_nuclides()) - have)
            if missing:
                errors.append(f"{tag}: not in the nuclear data: {missing}")
        except Exception as e:  # e.g. an element OpenMC has no natural abundances for
            errors.append(f"{tag}: OpenMC can't build it: {e}")
        sab = sab_for(m)
        if sab and sab not in have:
            errors.append(f"{tag}: S(a,b) table {sab} is not in the nuclear data")
    return errors


def span(ns):
    out, i = [], 0
    while i < len(ns):
        j = i
        while j + 1 < len(ns) and ns[j + 1] == ns[j] + 1:
            j += 1
        out.append(str(ns[i]) if i == j else f"{ns[i]}-{ns[j]}")
        i = j + 1
    return ", ".join(out)


def report(title, errors, warnings):
    print(title)
    for e in errors:
        print("  ERROR  ", e)
    for w in warnings:
        print("  warning", w)
    print(f"  {len(errors)} error(s), {len(warnings)} warning(s)")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--library", type=Path, default=LIBRARY, help="library file (default: static/materials.jsonl)")
    ap.add_argument("--add", type=Path, metavar="BATCH", help="check this batch and merge it into the library")
    ap.add_argument("--replace", action="store_true", help="with --add: replace library entries that have the same num")
    ap.add_argument("--nuclear-data", action="store_true", help="also build each material with OpenMC and check its data exists")
    ap.add_argument("--pdf-text", type=Path, default=PDF_TEXT, help="PNNL-15870 Rev. 1 text (default: next to this script)")
    args = ap.parse_args()

    ref = pdf_reference(args.pdf_text) if args.pdf_text.exists() else None
    print(f"PDF text: {args.pdf_text} ({len(ref)} entries)" if ref else
          f"PDF text not found at {args.pdf_text}; only format checks are done.")
    lib_entries = read_objects(args.library, strict_lines=True) if args.library.exists() else []

    if not args.add:
        errors, warnings = check(lib_entries, ref, whole_library=True)
        if args.nuclear_data:
            errors += check_nuclear_data(lib_entries)
        report(f"{args.library}: {sum(1 for _, o in lib_entries if isinstance(o, dict))} materials", errors, warnings)
        return 1 if errors else 0

    batch = read_objects(args.add, strict_lines=False)
    errors, warnings = check(batch, ref, whole_library=False)
    if args.nuclear_data:
        errors += check_nuclear_data(batch)
    report(f"{args.add}: {sum(1 for _, o in batch if isinstance(o, dict))} materials", errors, warnings)
    if errors:
        print("Nothing was added. Fix the errors and run again.")
        return 1
    lib_errors = [ln for ln, o in lib_entries if not isinstance(o, dict)]
    if lib_errors:
        print(f"The library has unreadable lines ({lib_errors}); fix it before adding. Nothing was added.")
        return 1
    library = [o for _, o in lib_entries]
    have = {o.get("num"): k for k, o in enumerate(library) if o.get("num") is not None}
    clash = [o["num"] for _, o in batch if o.get("num") in have]
    if clash and not args.replace:
        print(f"Already in the library: {span(sorted(clash))}. Nothing was added (use --replace to overwrite them).")
        return 1
    added = replaced = 0
    for _, o in batch:
        if o.get("num") in have:
            library[have[o["num"]]] = o
            replaced += 1
        else:
            library.append(o)
            added += 1
    # PNNL entries in number order, your own materials after them in the order they were added
    library.sort(key=lambda o: (o.get("num") is None, o.get("num") or 0))
    errors, _ = check([(k + 1, o) for k, o in enumerate(library)], ref, whole_library=True)
    if errors:
        report("The merged library would have errors:", errors, [])
        print("Nothing was added.")
        return 1
    order = ["num", "name", "density", "category", "comps", "frac", "sab", "color", "ref"]
    text = "".join(json.dumps({k: o[k] for k in order if k in o}, ensure_ascii=False) + "\n" for o in library)
    args.library.write_text(text, encoding="utf-8", newline="\n")
    print(f"Added {added}, replaced {replaced}. {args.library} now has {len(library)} materials.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
