# DSO VPP DOE VMAX pocket architecture audit

## Scope and method

This is a deterministic, artifact-only geometric audit at `c18021d9b981f2629e54f60e8c2fc5f33b00c1a2`. It performs no AC solve, production probe, replay, HC/TVPP optimization, mesh validation, tuning, or runtime benchmark. Every representation remains **GEOMETRIC_ONLY; NOT_AC_INTERIOR_CERTIFIED**. The unresolved blind spot is **INTER_RAY_EDGE_AND_ANGULAR_INTERIOR_AC_FEASIBILITY**.

The package was generated independently in two previously nonexistent output directories. Every generated file, including `manifest.json`, was byte-identical across the runs. Generated-manifest verification and every source-manifest verification passed.

For each timestamp, `H_t` is the exact monotone-chain convex hull of the CCW angular inward polygon `P_t`. Each positive-area component of `H_t \ P_t` is constructed from one hull chord and its skipped CCW polygon boundary run. Vertex-only and zero-area contacts are not merged. Numerical tolerances are 1e-08 kW distance, 1e-06 kW^2 absolute area (with a per-timestamp `max(area_abs, hull_area*1e-14)` positivity check), and 1e-12 relative orientation.

## Exact topology and convexity

There are 66 positive-area components over 32 timestamps; per timestamp min/Q1/median/Q3/max=2/2/2/2/3. Per-class timestamp counts: VMAX / bus 13: min/Q1/median/Q3/max=1/1/1/1/1, VMAX / bus 30: min/Q1/median/Q3/max=1/1/1/1/1, VMIN / bus 18: min/Q1/median/Q3/max=0/0/0/0/1, VMIN / bus 33: min/Q1/median/Q3/max=0/0/0/0/1. Exact component geometry, boundary runs, normalized areas, and classifications are in `pocket_components.csv`.

Every timestamp has exactly two geometrically distinct VMAX components: one bus-13 pocket and one bus-30 pocket. Two timestamps have one additional VMIN component, giving 2-3 total components/timestamp. Zero-area boundary runs: 0; vertex-touch pairs between positive-area components: 8.

VMAX components: 64; convex: 50; nonconvex: 14 across 13 timestamps. Exact convex VMAX irredundant facet counts: min/Q1/median/Q3/max=12/13/13/13/17. Convexity, hull-area deficit, and deterministic nonconvexity depth are in `pocket_convexity.csv`; normalized exact halfspaces are in `pocket_exact_facets.csv`.

## Deterministic VMAX outer approximations

For k=3,4,5,8, a budget below the exact facet count retains the exact hull-chord support facet plus evenly indexed exact boundary support facets; this guarantees `C_true subset C_approx`. A sufficient budget reports the exact pocket. No inner forbidden-pocket approximation is constructed. These approximations exist only for the 50 convex VMAX components; timestamps containing a nonconvex VMAX pocket are explicitly marked unavailable as complete k-budget representations.

- k=3: POOR_WIDESPREAD_SAMPLED_BOUNDARY_FIDELITY_RELATIVE_TO_BEST_TESTED_BUDGET; 467 newly excluded inward boundary records (27.649497% of all 1,689 records; convex-component diagnostics, complete representation at 19/32 timestamps); delta-r min/Q1/median/Q3/max=0.616092/10.9827/22.235/37.5608/71.5287 kW; delta-r/r_in min/Q1/median/Q3/max=0.00046158/0.00524758/0.0111671/0.0180477/0.0461186; additional removed area/polygon min/Q1/median/Q3/max=0.00421148/0.00558653/0.00620914/0.0067026/0.00690914.
- k=4: POOR_WIDESPREAD_SAMPLED_BOUNDARY_FIDELITY_RELATIVE_TO_BEST_TESTED_BUDGET; 367 newly excluded inward boundary records (21.728834% of all 1,689 records; convex-component diagnostics, complete representation at 19/32 timestamps); delta-r min/Q1/median/Q3/max=0.0932708/2.29712/4.37916/9.02964/32.8723 kW; delta-r/r_in min/Q1/median/Q3/max=4.1035e-05/0.00116074/0.00257762/0.00494561/0.0152804; additional removed area/polygon min/Q1/median/Q3/max=0.0010525/0.00143366/0.00154025/0.00169774/0.00177658.
- k=5: POOR_WIDESPREAD_SAMPLED_BOUNDARY_FIDELITY_RELATIVE_TO_BEST_TESTED_BUDGET; 267 newly excluded inward boundary records (15.808171% of all 1,689 records; convex-component diagnostics, complete representation at 19/32 timestamps); delta-r min/Q1/median/Q3/max=0.0996046/1.63494/2.70053/3.873/19.6626 kW; delta-r/r_in min/Q1/median/Q3/max=6.27098e-05/0.000908908/0.00142249/0.0019851/0.00913999; additional removed area/polygon min/Q1/median/Q3/max=0.000522796/0.000722397/0.000822284/0.00090941/0.000937196.
- k=8: BEST_TESTED_BUDGET_WITH_LOCALIZED_NONZERO_BOUNDARY_LOSS; 9 newly excluded inward boundary records (0.532860% of all 1,689 records; convex-component diagnostics, complete representation at 19/32 timestamps); delta-r min/Q1/median/Q3/max=0.904409/1.19552/1.70951/1.87901/7.10419 kW; delta-r/r_in min/Q1/median/Q3/max=0.00085964/0.00115935/0.00121124/0.00127913/0.00292333; additional removed area/polygon min/Q1/median/Q3/max=0.00013614/0.000170319/0.000190478/0.000197651/0.00021217.


The fidelity labels are descriptive relative comparisons across the four tested budgets; no acceptance or materiality threshold was preregistered. `delta_r / paired_boundary_bracket` is reported only as a diagnostic and is not an acceptance or safety criterion. Per-point severity, bus/family, ray-versus-signed-axis, timestamp breakdowns, retained angular coverage, and signed-axis retention are in `pocket_outer_approx_boundary_loss.csv` and `pocket_outer_approx_summary.csv`. Area distributions above are per-timestamp union results for the 19 timestamps where all VMAX pockets are convex; partial component diagnostics remain machine-readable for the other timestamps.

## VMIN examination

VMIN positive-area components: 2; aggregate area 15.266236501514 kW^2. Diagnosis: **VMIN_POCKET_GEOMETRIC_EFFECT_NOT_RESOLVABLE_ABOVE_BOUNDARY_SEARCH_RESOLUTION**. `vmin_pocket_diagnostics.csv` reports every affected inward point, component area, affected angular interval, radial hull depth, local depth, and both bracket-normalized diagnostics. This is not a claim that VMIN is mathematically convex or that the pocket can be omitted exactly.

## Representation complexity and classification

`representation_complexity.csv` directly compares the 21-28-cell exact partition, exact hull-minus-pocket geometry, and k=3/4/5/8 VMAX support approximations while retaining non-VMAX pockets exactly. Simple convex-pocket difference representations are available at 19/32 timestamps and unavailable at the other 13 because at least one pocket is nonconvex. It separates outer facets, pocket facets, disjunction groups, fully expanded conceptual alternatives, and total geometric inequalities. No MIP binary count is asserted.

Architecture classification: **POCKET_TOPOLOGY_PRECLUDES_SIMPLE_COMPACT_DIFFERENCE_REPRESENTATION**. Approximation fidelity is classified separately above and makes no runtime or AC-safety claim.

## Locked results and reporting correction

All locked architecture guardrails in `audit_summary.json` remain in force. The aggregate pocket accounting is VMAX-only 9187485.413888178766 kW^2, VMIN-only 15.266236501514 kW^2, mixed 0.000000000000 kW^2, total 9187500.680124681443 kW^2. The historical 9,187,485.414 kW^2 wording referred to VMAX-only area, not total area.
