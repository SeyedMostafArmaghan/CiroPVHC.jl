# Validation decision rules

This campaign is a dense deterministic falsification mesh, not a mathematical proof over the continuous DOE. All substantive points receive exactly one primary status: `CONVERGED_FEASIBLE`, `CONVERGED_INFEASIBLE`, or `UNRESOLVED_NONCONVERGENCE`. Authoritative code feasibility semantics apply with no post-hoc tolerance.

1. Any converged-infeasible substantive point: `MAIN_COUPLED_DOE_GEOMETRIC_CANDIDATE_FALSIFIED_BY_AC_COUNTEREXAMPLE`. Complete the fixed mesh unless operationally impossible. Do not tune, contract, repair, or adapt the mesh during the run.
2. Zero converged-infeasible points and at least one unresolved point: `AC_INTERIOR_VALIDATION_INCONCLUSIVE_DUE_TO_NONCONVERGENCE`.
3. Zero infeasible and zero unresolved substantive points with all controls passing: `NO_AC_COUNTEREXAMPLE_DETECTED_AT_PREREGISTERED_MESH_RESOLUTION`.

Finite-mesh success is not continuous AC certification or proof. VMAX-associated inter-ray edges are a diagnostic hypothesis only; VMIN failure remains possible, and geometric concavity depth is not AC sagitta. Guard-related results and failure distributions are reported neutrally. No adaptive failure-localization points may be added; that requires a separate preregistration.

Converged rows record Vmin/bus, Vmax/bus, and primary mechanism. Infeasible rows additionally record violation magnitude, category, timestamp, all cell IDs, boundary theta/edge provenance when applicable, and VMAX/VMIN side. Substantive interpretation is blocked by configuration-control failure.

Pocket-fallback membership is recorded only to reuse the same future AC observations. The Main-mesh outcome alone cannot promote the fallback, and no separate fallback AC campaign is part of this preregistration.
