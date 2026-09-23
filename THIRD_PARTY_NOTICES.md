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

## Separate companion and optional CAD tools

https://github.com/bluetyde/openmc-mcnp-project supplies remediation and validation
for Studio's MCNP workflow. It is a separate repository, not covered by Studio's
LICENSE. No root license file was found in the reviewed companion checkout at
960c2f7; its licensing must be addressed separately before treating it as MIT.

FreeCAD is an external optional STEP-export dependency. GEOUNED integration is
planned, not currently implemented. Their respective licenses and the licenses
of their bundled components apply independently; Studio's MIT license does not
make those tools MIT-licensed. Review the exact distributions' notices before
bundling them.
