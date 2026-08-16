# DSO VPP AC interior validation preregistration

This package deterministically materializes the validation mesh and policies before validation. It performed **no AC evaluation** and did not start validation.

The authoritative later path is `DSOVPPProductionProbe.evaluate_physical! -> DSOVPPACMapStage0.evaluate_point -> radial primary AC power flow + CiroPVHC.replay_s1b_interval`, with absolute physical P13/P30 kW, buses 13/30, `N_P=2`, zero interface Q, zero reference-PV capacity, 0.90--1.05 p.u., positive P injection/export, and nonconvergence unresolved.

The boundary mesh has 23040 raw points (720 angles per timestamp, 0:0.5:359.5 degrees) on the unperturbed angular polygon. The cell mesh has 66633 raw q=5 barycentric memberships from centroid fans over all 749 cells. At `1e-8` kW L-infinity canonicalization tolerance, 89673 raw substantive memberships become 65494 unique substantive points after removing 24179 duplicates. There are 128 controls and 65622 total first attempts. Guard-related points are retained and labeled; fallback membership is geometric reuse only.

At 0.625720804888803 ms/evaluation, substantive first attempts are 40.980958395387 s, controls 0.080092263026 s, all first attempts 41.061050658413 s, and a retry for every substantive point adds 40.980958395387 s. With 22.382838 s fixed setup, totals excluding checkpoint/I/O are 63.443888658413 s without retries and 104.424847053800 s in the stated worst substantive-retry case. Checkpoint/I/O is `NOT_MEASURED`. The evidence classification remains `SAFE_ON_PERSONAL_LAPTOP_WITH_CHECKPOINTING` for serial one-process/one-thread execution.

All mesh integrity checks and all entries in five required source manifests pass. The generator SHA-256 is `1edbc5c1ff03a1375a832f48f469f23c019dd4c1ca1d9bc9eadd6f02977219fe`. Generated artifact hashes are in `manifest.json`; its external file SHA-256 is reported after generation because a manifest cannot contain its own hash without circularity.

The only success conclusion permitted after a future complete run is `NO_AC_COUNTEREXAMPLE_DETECTED_AT_PREREGISTERED_MESH_RESOLUTION`. This is not continuous-set proof or certification.

`NO_NEW_AC_EVALUATIONS_PERFORMED`  
`VALIDATION_NOT_STARTED`
