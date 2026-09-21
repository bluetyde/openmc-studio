# TRISO fuel particle

Open `triso-particle.openmc-studio.json` using Studio's Export > Open project.
Use the XY slice at Z = 0 to see all five layers. Use Fit if needed after
opening; in 3D the outer coating naturally hides the inner layers.

This is an educational example, not a specific BWXT fuel specification.
All dimensions, densities and kernel composition below are illustrative.
Studio stores lengths in centimeters; the particle's outer diameter is 0.092 cm
(920 micrometers). The geometry is actual size, not enlarged.

| Region | Outer radius (cm) | Thickness (micrometers) | Density (g/cm3) |
|---|---:|---:|---:|
| UCO kernel | 0.0250 | 250 radius | 10.5 |
| Porous carbon buffer | 0.0350 | 100 | 1.0 |
| Inner pyrocarbon (IPyC) | 0.0390 | 40 | 1.9 |
| Silicon carbide (SiC) | 0.0425 | 35 | 3.2 |
| Outer pyrocarbon (OPyC) | 0.0460 | 35 | 1.9 |

Kernel composition is a simple illustrative atomic mixture U:1, O:1.5, C:0.5
with natural uranium; it does not represent commercial fuel enrichment or
resolved UCO phases. Carbon regions have distinct materials and colors.
SiC uses a 1:1 Si:C atomic ratio. No thermal-scattering tables are assigned.

The five concentric spheres are ordered from inside to outside. Studio's
overlap priority turns them into a kernel and four nonoverlapping shells.
Keep this order when editing. The surrounding vacuum world has radius 0.06 cm.

A 2 MeV isotropic point source at the center and a cell flux tally are included
as demonstration inputs. Fission neutron production is disabled for this
simple fixed-source setup. They are not a reactor operating condition. No
transport results are supplied or claimed.

Layer names follow BWXT's public April 2023 presentation, slide 16:
https://nuclearnh.energy/wp-content/uploads/2023/04/BWXT-New-Hampshire-April-2023.pdf
Additional public context: https://www.bwxt.com/sectors/nuclear-fuel/triso/
