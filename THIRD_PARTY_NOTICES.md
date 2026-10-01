# Third-party notices

Studio's LICENSE covers original Studio code. Existing upstream notices must
remain with copied or adapted code. Dependencies and third-party documents,
images, example source material, and nuclear data retain their own terms.
This file is not an exhaustive dependency inventory or a license grant for
third-party assets.

## OpenMC

Source: https://github.com/openmc-dev/openmc

OpenMC is an external simulation dependency. The following MIT notice is from
the installed OpenMC 0.15.3 distribution; preserve the notice shipped with any
other version you redistribute.

Copyright (c) 2011-2025 Massachusetts Institute of Technology, UChicago Argonne
LLC, and OpenMC contributors

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

## NuCoMP MCNPy and MetaPy

Sources:
- https://github.rpi.edu/NuCoMP/mcnpy
- https://github.rpi.edu/NuCoMP/metapy

These are the RPI NuCoMP projects used by the MCNP conversion environment, not
unrelated packages with similar names. Both local source distributions carry
the following MIT notice.

Copyright (c) 2023 NuCoMP

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

## openmc_mcnp_adapter

Source: https://github.com/openmc-dev/openmc_mcnp_adapter (commit 80fda5a, version 0.1.0).
Used by `studio/openmc_studio/mcnp_import.py`; included in the optional offline Windows runtime.

Copyright (c) 2022-2025 UChicago Argonne, LLC and contributors

Permission is hereby granted, free of charge, to any person obtaining a copy of
this software and associated documentation files (the "Software"), to deal in
the Software without restriction, including without limitation the rights to
use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of
the Software, and to permit persons to whom the Software is furnished to do so,
subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS
FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR
COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER
IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN
CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.

## Companion and CAD tools

https://github.com/bluetyde/openmc-mcnp-project supplies remediation and validation
for Studio's MCNP workflow. The packaged revision bfa0d88 carries its own MIT
LICENSE, copyright 2026 John William Noyes and openmc-mcnp-project contributors.
Its full notice is preserved in the runtime and package's licenses directory.

FreeCAD and GEOUNED support CAD conversion. The optional Windows runtime includes
the pinned conda-forge FreeCAD distribution (LGPL-2.1-or-later) and GEOUNED 1.6.2
(EUPL-1.2), along with their dependencies. Studio's MIT license does not replace
these licenses. Preserve the component notices and corresponding source references.

## Offline Windows package

The assembled package's `licenses/` directory contains dependency inventories,
the available conda license files and build recipes with source URLs, Ubuntu
copyright records, and the companion's notices. Ubuntu Base, Miniforge, OpenJDK,
Qt, OCCT, and other dependencies retain their respective licenses. The runtime
contains unmodified third-party binaries reinstalled from pinned package archives.
No licensed MCNP transport executable is included.

Build recipes and upstream links are provenance records, not a blanket grant to
redistribute every dependency. Preserve source and source-offer notices supplied
by the original distributors, including OpenJDK's notices. For public binary
releases, confirm that the release supplies any corresponding source required
by the included copyleft components. Nuclear data retains its publisher's terms.
