# Package verification — 2026-10-01

Runtime: `20261001-linux64-v1`, built from official Ubuntu Base and Miniforge
installers with their published SHA256 checksums. Both solver environments were
reinstalled from pinned package archives in a new WSL2 distribution.

Completed:
- Seven package contract tests and Windows PowerShell launcher helper checks.
- Imports of OpenMC 0.15.3, the MCNP adapter, FreeCAD 26.3.0 and GEOUNED 1.6.2.
- Bundled Java 8 starts successfully.
- All 690 nuclear-data library references resolve to nonempty packaged inputs.
- A real OpenMC fixed-source transport problem produces its expected statepoint.
- A real drilled-solid STEP conversion passes the CAD job manager's geometry probes.

Not exercised for this package:
- MCNP export through the Java gateway.
- Browser rendering, project save/reopen and port-conflict behavior end to end.
- First installation on a second clean Windows machine, an offline host, a
  changed drive letter, interrupted import, and upgrade/rollback.

The user approved the isolated OpenMC/CAD checks after initially asking to omit
testing. Broader testing was not performed. This is an assembled candidate, not
a fully acceptance-tested release. See `README.md` for remaining checks.
