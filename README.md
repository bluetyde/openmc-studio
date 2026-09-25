# OpenMC Studio

A local app for building OpenMC models, running them and exporting MCNP decks: a small Python server and a
browser page. It runs on macOS, Linux and Windows (through WSL2), from wherever you put it — an internal
disk or an external drive.

**Setting up for the first time? See [INSTRUCTIONS.md](INSTRUCTIONS.md)**: conda environment, nuclear data
download, and how to start the app.

## Start OpenMC Studio

- **Windows:** double-click `Start OpenMC Studio.cmd`
- **Mac:** double-click `Start OpenMC Studio.command`

A window opens with the server, and Studio opens in your browser. Build a model,
press **Run**, and results appear on the viewport (flux map, neutron tracks) and
under **Results**. Click a neutron track, then **Replay neutron** to rerun exactly
that neutron with the same seed.

**Export for ParaView…** (in Results, or Export > ParaView (VTK)) saves a finished run as a zip that
ParaView or VisIt opens directly: each flux map as a VTK file (mean, standard deviation and relative error
per voxel, and per energy bin), the particle tracks coloured by energy, and the geometry as one STL per
material. A README inside gives the units and how to open it.

To stop Studio, close that window or press Ctrl+C in it. Runs are saved on the
computer (not a removable drive) in `~/OpenMC-runs`, one folder per run with `model.py`,
the statepoint, tracks and the log. Past runs are under **Runs**.

It needs a conda env named `openmc-mcnp` with OpenMC installed; nothing else to
install. If your env has another name, start it from a terminal:
`OPENMC_STUDIO_ENV=<name> bash studio/start.sh`.
If the env has no nuclear data set, Studio uses a library sitting beside this repository, if there is one.

If macOS says the `.command` file can't be opened, run it once from Terminal:
`bash "Start OpenMC Studio.command"` from the repository folder.

## Moving, scaling and rotating parts

**Tools** (Home and Model tabs, or keys **1–4**): **Select**, **Move**, **Scale**, **Rotate**.
Select a part, pick a tool, and drag its handles in the slice view or the 3D view:

- **Move**: drag a red / green / blue arrow to slide along x / y / z. In the slice
  view, drag the white center ring to move freely in that plane. Sources can be moved too.
- **Scale**: drag a ball on a face. That face moves and the opposite face stays put,
  along the part's own (possibly rotated) axes. On a cylinder the side balls change the
  radius and the end balls change the height; a sphere has radius balls.
- **Rotate**: drag a ring to turn the part about that axis (boxes and cylinders).
  In 3D the angle follows the pointer around the ring from any viewing angle.
  Rotation is also in Properties as degrees about x, then y, then z.
- **Snap to grid** (Home and Model tabs, like Roblox Studio): a checkbox and a step for **Rotate**
  (degrees) and **Move** (cm, or inches with imperial units; Scale uses the same step). Type a value
  and press Enter; untick the box to drag freely while keeping the value. Remembered in this
  browser. Esc cancels a drag in progress.
- **Undo / Redo**: **Ctrl+Z** and **Ctrl+Y** (or Ctrl+Shift+Z; Cmd on the Mac), or the
  buttons on the Home tab. Each drag, code-tab edit or burst of typing is one step
  (the last 100 are kept). In a text box, Ctrl+Z undoes the typing instead.

Rotations in 90° steps are written as ordinary planes and cylinders. Other angles are
written as tilted planes (MCNP `P`) and general quadrics (MCNP `GQ`); the MCNP export
and its geometry check handle both. In the code tabs a tilted plane's position (`d=`
in model.py, the last number on a `P` card) can be edited like any other plane; the
normal and the `GQ` coefficients are read-only, so change the rotation for those.

## Metric or imperial

Run ▸ Settings ▸ Display ▸ **Units** switches what Studio shows and accepts between metric (cm,
g/cm³) and imperial (inches, lb/ft³). It changes Properties, the Explorer, the material lists, the
viewport's axis ticks and slice box, the coordinate and drag readouts, and the Move/scale snap step
(each system keeps its own step: 1 cm, 0.25 in by default, so drags land on round inches). The
choice is saved in this browser.

The model is always stored in cm and g/cm³, and **model.py and model.mcnp stay in cm and g/cm³**
because OpenMC and MCNP need them; with imperial on, both code tabs say so. Typing 12 in stores
30.48 cm exactly. Energies (MeV) and angles are the same in both.

## Selecting several parts, and groups

- **Select several**: Ctrl+click (Cmd+click on the Mac) adds or removes a part or source; Shift+click
  in the Explorer selects everything between the last click and this one. Ctrl+click in the viewport
  works too. Duplicate, Delete, Move, Rotate and the shared Material work on the whole selection.
- **Group** (Ctrl+G, or Home/Model ▸ Group) turns the selection into a folder in the Explorer.
  **Ungroup** is Ctrl+Shift+G. A group's parts always stay next to each other, so the group is one
  priority block: drag the folder (or Alt+↑/↓) to move the block. Dragging a part out of the block
  removes it from the group; dropping a part between two members adds it.
- **Selecting a group**: click its folder, or click one of its parts in the viewport. Click that part
  again to select just the part. Click the folder's arrow to show or hide its parts.
- **Pivot**: every group has a pivot point (Properties ▸ Pivot). It starts at the center of the group
  and moves when you move the group. **Center pivot on parts** puts it back in the middle.
- **Rotating a group or selection**:
  - **Pivot: Group** (the default) turns everything as one piece: each part orbits the pivot and
    turns with it, so the assembly keeps its shape. A selection that isn't a group turns about the
    center of the selection.
  - **Pivot: Each** turns every part about its own center; nothing moves.
  - Properties ▸ **Rotate by** applies a typed turn (degrees about x, then y, then z).
  - Sources in a group move with it and a beam direction turns too. A box source can only turn in
    90° steps and a cylinder source only about z; other turns are refused with a message.
- **Groups inside groups**: drag a group onto another group's folder. Moving or rotating the outer
  group moves everything inside it.
- **In the outputs** groups change nothing in the geometry. model.py lists them as
  `groups = {"Shield": {"pivot": (...), "cells": [cell_source_cavity, ...], "sources": [...], "groups": {...}}}`
  and model.mcnp as comment cards, `c Group: Core/Shield | pivot: 0 0 0 = cells 2 3 4`. The project
  file keeps each group and its pivot.

Faces that should touch are written as one shared surface even after rotations leave tiny rounding
differences (surfaces closer than 1e-7 cm are merged), so rotated assemblies don't create nearly
coincident surfaces.

## Arrays and lattices

**Array…** (Home or Model ribbon) repeats the selection on a grid (nx × ny × nz with a spacing) or in
hexagonal rings. With **RectLattice** / **HexLattice** ticked (later: the array group's Properties ▸
**Export as RectLattice**), model.py writes the array as an `openmc.RectLattice` or
`openmc.HexLattice` (one unit universe, repeated), which keeps model.py short for big arrays.

- A lattice needs every member to be the **same single part** (shape, size, rotation, material) on
  the array's grid. Deleted sites are fine (they're filled with the surrounding material). If you
  move, resize or change one member, model.py writes the array cell by cell instead and the Problems
  panel says why; the geometry is the same either way.
- **model.mcnp** writes a rectangular lattice as MCNP `LAT=1` with `FILL`, like a hand-written deck:
  - The element [0,0,0] is a box around the origin.
  - `FILL=u` when every site holds the same part; a FILL list when some sites are empty.
  - The cell that holds the lattice gets `FILL=L (x y z)` to place element [0,0,0].
  - openmc-mcnp-project rewrites the cards MCNPy produces (MCNPy's own were wrong), and its geometry check follows the lattice down to each element.
  - A hexagonal array becomes MCNP `LAT=2`: a hexagonal prism element with its 8 faces in the manual's
    order, and a FILL list over the rings (sites outside the rings are the surrounding material).
- **Cell tallies on parts inside a lattice work in model.py.** Such a part has no cell of its own, so its
  tally bin is the lattice's unit cell in that part's element (`openmc.CellInstanceFilter`). In model.mcnp
  each bin is a path through the lattice, `(unit cell < lattice cell[i j k] < filled cell)` (manual
  p. 452-455), and the export checks that each path holds the same points as its OpenMC bin.
- **A lattice's box has to sit inside one other part (or the world) that nothing else overlaps**, because
  the box is filled with that part's material. A cell tally on that surrounding part also isn't allowed,
  since in lattice form it would miss the space between the array's parts. If either rule is broken, the
  array is written cell by cell and Problems says why.

## Detector responses

A tally can report a detector's reaction rate instead of plain flux (Properties ▸ Detector response):
**He-3** (n,p), MT 103; **B-10** (n,α), MT 107; or a custom material and reaction. The detector gas
doesn't need to be in the geometry: model.py multiplies the flux by the gas's cross section with an
`openmc.EnergyFunctionFilter` (cross sections at 294 K).

- **Macroscopic** (default): N·σ(E), summed over the target nuclide (or every nuclide with that
  reaction), in 1/cm. **Microscopic**: σ(E) of one nuclide, in barns.
- model.mcnp writes the matching `FM (C m R)` card, with C the detector gas's atom density
  (macroscopic) or 1 / the nuclide's atom fraction (microscopic). MCNP sums reaction R over every
  nuclide in material m, so the export notes when the gas has other nuclides.

## Other options

- **Parts**: sphere, cylinder, box, wedge (right triangular prism), hexagonal prism, cone
  (truncated) and ellipsoid.
- **Sources**: energy as lines, Watt, Maxwell, uniform, tabulated (paste MCNP SI/SP cards) or a
  Muir fusion spectrum (MCNP `SP -4`).
- **Tallies**: cells, Cartesian or cylindrical mesh, and surface current (the current leaving the
  chosen parts). OpenMC signs it by the surface's sense: + through a part's +x/+y/+z faces, - through the
  others. In model.mcnp each (surface, part) bin is its own F1 tally, with a `C 0 1` card for the direction and
  an `FS` card that cuts the surface down to the part's face (manual p. 459-460, 474-475). The FC comment
  ends with where OpenMC's number is, e.g. `[S 14 C 2 SEG 12-17 COS 2 X+1]`: add FS segments 12-17 in cosine
  bin 2 and keep the sign. Tick parts that don't overlap: a part carved out of another ticked part is refused.
- **Physics tab**: the sources and tallies you can add (cell, mesh and surface), toggles for run mode,
  photon transport and fission neutrons, Delete and Clear for the lists, and the seed.
- **Fission neutrons** (fixed source only): off treats fission as capture, so neutron chains die out. Without
  it, a fixed-source run containing fuel stops with "secondary particle bank appears to be growing without
  bound" once k reaches 1. model.py gets `settings.create_fission_neutrons = False` and model.mcnp a `NONU`
  card (manual p. 319). Problems warns before you run either way: fuel in a fixed-source model, or an
  eigenvalue run with fission neutrons off.
- **Settings**: photon transport, material temperatures, eigenvalue runs with a k and Shannon entropy
  convergence chart, and vacuum, reflective, white or periodic (box world only) boundaries.

## 3D view

Switch **Slice / 3D** in the viewport toolbar. The 3D view draws the real geometry (same
overlap rules as the model, void parts see-through) with the transform handles, sources,
neutron tracks and the world boundary.

- Drag to orbit, right-drag or Shift+drag to pan, wheel to zoom, **F** to focus on the
  selection, **Fit** to reset. Click a part to select it.
- **Cutaway** cuts the model open at the slice plane (XY / XZ / YZ and the position box),
  removing the half facing you, so cross-sections show their materials.
- After a run, the **Flux map** is painted on the slice plane and **Tracks** are drawn
  bright where nothing is in front of them and faint behind geometry. Turn on Cutaway
  to see the flux map across the whole cut.
- The 3D view needs WebGL 2. Part data sits in a texture and a bounding-volume hierarchy picks the
  parts each ray can hit, so there is no fixed part limit; the 134-part graphite pile draws smoothly,
  and much larger models haven't been timed yet. The slice view and the exports always use every part.

## Editing in the code tabs

The tabs above the viewport are **Viewport**, **model.py** and **model.mcnp**.
**Split** (right end of the tab bar) keeps the viewport on the left and shows
model.py or model.mcnp on the right.

- **model.py** is the OpenMC script Studio writes, updated as you edit.
- **model.mcnp** is the MCNP input from openmc-mcnp-project (MCNPy translation,
  remediation, validation and the geometry check), refreshed about a second after
  you stop editing. Edits to geometry or materials take about 10 s, because MCNPy
  has to translate again; other edits reuse the last translation and take about
  1 s. The status line says **✓ Validated**, what to fix, or why a model can't be
  exported. It needs openmc-mcnp-project on the computer. Studio uses
  `OPENMC_MCNP_PROJECT` if set, then the folder it found last time, then looks in
  `~/openmc-mcnp-project` and `~/Developer`, `~/Projects`, `~/Documents`, `~/code`,
  `~/git` or `~/repos`. A folder set once with `OPENMC_MCNP_PROJECT` is remembered
  (in the runs folder), so each computer only needs it once.
- **Numbers with a dotted underline can be edited in place.** Click one, type,
  press Enter (Esc cancels). The change goes to the part, material, source, tally
  or setting it came from, and the viewport and both tabs update. Moving a plane
  moves every face on it, including a touching part or the world boundary.
- **Click any line** to select what it belongs to in the Explorer and Properties.
  Selecting something highlights its lines in both tabs.
- Derived numbers (MCNP isotope fractions, NPS, normalized beam directions) aren't
  editable; change their source in Properties.
- While model.mcnp is refreshing it's dimmed and not editable, so an edit never
  lands on an out-of-date line.

## Material library

**Picking a material**: click the **Material** field of a part (or of a selection or group, or the
world's **Fill**). The list shows the materials already in the project, then every material you can
add. Pick one and it's assigned; a library material is added to the project the first time you use
it, and picking it again for another part reuses that copy. The Explorer's Materials section follows
along:

- A library material that nothing uses any more and that you haven't edited is removed on its own
  (the Log says so; Ctrl+Z brings it back).
- A material you've edited, or a Custom material, stays even when nothing uses it. The Explorer shows
  it as **unused**, and model.py leaves it out.
- **Model ▸ Material ▾** gives the material to the selected parts. With no parts selected it adds the
  material and opens it in Properties; if you then neither use nor edit it, it's removed when you
  select something else.

**Model ▸ Material ▾** and the field's list are both searchable. **Common** is the 18 built-in materials. Below it,
the library in `studio/openmc_studio/static/materials.jsonl` is grouped by category (click a
category to open it). Type to search by name, category or PNNL number (`#354`), press **Enter** to
add the first match, or use the arrow keys. Without the file, only the common materials are listed.

The file has one material per line:

```json
{"num": 354, "name": "Water, Liquid", "density": 0.998207, "category": "Water and liquids", "comps": "H:0.111894, O:0.888106"}
```

- `num` is the PNNL-15870 Rev. 1 entry number. Leave it out for a material of your own.
- `comps` is `Symbol:weight fraction`. `O` is natural oxygen; `U235` or `H2` is a single nuclide.
- Optional: `"frac": "ao"` for atom fractions, `"sab"`, `"color"`, `"ref"`. Water, heavy water,
  polyethylene, paraffin, graphite and beryllium get their thermal scattering table automatically.
- Elements with no natural isotopes (Tc, Pm, Po, At, Rn, Fr, Ra, Ac, Np, Pu, Am, Cm, Bk, Cf) must be
  written as nuclides, like `Pu239`. Studio shows an error for a material that doesn't.

Check the file, or add a batch to it (a batch can be pasted as one long line):

```
python studio/tools/check_materials.py
python studio/tools/check_materials.py --add batch.txt
```

The checker compares every numbered entry with the PDF text (`studio/tools/pnnl-15870-rev1.txt`, kept
beside the repository but not in git): name, density, components and each weight fraction. `--add` merges only
if the batch has no errors and doesn't repeat numbers already in the library (`--replace` overwrites
them). In WSL or on the Mac inside the `openmc-mcnp` environment, add `--nuclear-data` to also check
that OpenMC can build each material from the installed ENDF/B-VIII.0 data.

The library has 371 of the 372 entries. #155 Inconel-625 is left out on purpose: the PDF prints
Concrete, Rocky Flats' composition and density under that name.

## What's here

```
OpenMC/
├── Start OpenMC Studio.cmd       Windows launcher (runs Studio in WSL)
├── Start OpenMC Studio.command   Mac launcher
├── studio/
│   ├── start.sh                  shared start script: finds conda, activates the env, starts the server
│   └── openmc_studio/            the local server (Python standard library + OpenMC), the page,
│                                 and mcnp_worker.py (keeps MCNPy loaded for the live model.mcnp tab)
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

This folder is the repo [`github.com/bluetyde/openmc-studio`](https://github.com/bluetyde/openmc-studio). The nuclear
data is not in git (see `.gitignore`); `nuclear_data/archives/SHA256SUMS` records
which archive it came from.

- Git refuses repos on drives it thinks belong to another user (exFAT, for instance) until you mark the
  path safe, once per computer: `git config --global --add safe.directory /path/to/openmc-studio`
- Setting up another computer: clone the repo and follow [INSTRUCTIONS.md](INSTRUCTIONS.md). To keep the
  data beside the repository instead, download ENDF/B-VIII.0 from https://openmc.org/data/, check it against
  `nuclear_data/archives/SHA256SUMS`, and extract it into `nuclear_data/`.

## Nuclear data setup (optional)

Full instructions, including the download, are in [INSTRUCTIONS.md](INSTRUCTIONS.md). Studio finds a library
that sits beside this repository by itself. To use OpenMC outside Studio (your own scripts), point the conda
env at it once:

### If the library sits beside this repository

```bash
bash setup/point_conda_env_here.sh openmc-mcnp      # use your env's name if it differs
conda deactivate && conda activate openmc-mcnp      # the setting lives in the env
python setup/verify.py
```

### If it lives somewhere else

```bash
conda env config vars set -n openmc-mcnp   OPENMC_CROSS_SECTIONS=/path/to/endfb-viii.0-hdf5/cross_sections.xml
conda deactivate && conda activate openmc-mcnp
```

Either way it is a one-time step per computer, and it survives moving or renaming the drive only if the path
still matches — run it again if the path changes. A copy on an internal disk loads faster than one on an
external drive; a copy beside the repository travels with it.

## Companion repository

[openmc-mcnp-project](https://github.com/bluetyde/openmc-mcnp-project) is a separate
dependency for MCNP export and live MCNP validation. Studio's geometry editor,
visualization, and OpenMC workflow do not require that repository. OpenMC runs
still require an installed OpenMC environment and suitable nuclear data.

For MCNP features, install the companion and its dependencies as described in
[INSTRUCTIONS.md](INSTRUCTIONS.md). Set `OPENMC_MCNP_PROJECT` to its checkout when
it is outside the automatically searched locations. Studio's MCNP worker uses
the companion's remediation and validation modules together with NuCoMP MCNPy;
the companion is not bundled with Studio. MCNPy and MetaPy are distributed from RPI's GitHub
(`github.rpi.edu/NuCoMP`), which may need an RPI account; without them everything except the MCNP
export and the live `model.mcnp` tab still works.

## License

OpenMC Studio's original code is available under the [MIT License](LICENSE).
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) preserves notices for OpenMC and
NuCoMP MCNPy/MetaPy and explains the scope. Dependencies, third-party assets,
nuclear data, and the separate companion repository retain their own terms;
Studio's license does not relicense them.

## Notes

- **Studio security:** the server only accepts connections from this computer and
  needs the token the launcher puts in the browser link, because it runs the Python
  the page sends it. Don't share that link.
- **Eject before unplugging.** exFAT has no journal, so pulling the drive mid-write can
  corrupt files. On the Mac, eject in Finder; on Windows, use Safely Remove Hardware.
- If OpenMC says it can't find `cross_sections.xml`, the library is missing or the env points at another
  copy; if it lives on a removable drive, check the drive is connected. `setup/verify.py` says which.
- macOS may add hidden `._*` files next to the data. They're harmless; OpenMC only
  opens the files listed in `cross_sections.xml`.
- Running `test/shielding_demo.py` writes results into the current folder. Run it from a folder on an
  internal disk rather than a removable drive, e.g. `cd ~ && python /path/to/openmc-studio/test/shielding_demo.py`.
- To check the archive: `cd nuclear_data/archives && shasum -a 256 -c SHA256SUMS` (Mac) or
  `sha256sum -c SHA256SUMS` (WSL).
