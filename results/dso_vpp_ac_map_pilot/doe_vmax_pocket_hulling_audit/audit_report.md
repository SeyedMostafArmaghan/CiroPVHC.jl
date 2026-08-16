# DSO VPP DOE VMAX pocket convex-hulling audit

## Scope and reproducibility

This deterministic artifact-only geometric audit at `aaa6a745dd428c3efd267214337f6cb583489ed3` performs no AC solve, power flow, optimization, production probing/replay, mesh validation, DOE construction, tuning, or runtime benchmark. All five required source manifests pass. Two independent generations from previously nonexistent output directories are byte-identical, including `manifest.json`; generated-manifest verification passes.

The operation is labeled **GEOMETRIC_CONSERVATIVE_FORBIDDEN_REGION_APPROXIMATION**. It is an outer approximation of each forbidden pocket and is **not** labeled AC-safe. Every angular polygon and derived representation remains **GEOMETRIC_ONLY;NOT_AC_INTERIOR_CERTIFIED**; the unresolved blind spot is **INTER_RAY_EDGE_AND_ANGULAR_INTERIOR_AC_FEASIBILITY**.

## Inventory and added forbidden area

The locked inventory reproduces exactly: 14 nonconvex VMAX pockets across 13 timestamps, comprising 5 VMAX/bus-13 and 9 VMAX/bus-30 components. Explicit vertex containment in each convex hull passes at 1e-08 kW distance tolerance.

Convex hulling adds 7499.407640637641 kW^2 of forbidden area in total. Per pocket, added area min/Q1/median/Q3/max is 1.21522841/7.52915804/249.451238/813.972484/2402.54361 kW^2; added area / polygon area is 7.6910604e-08/4.64366221e-07/1.5370508e-05/5.09066373e-05/0.000147735278; added area / true pocket area is 1.48283833e-05/7.35176701e-05/0.001348997/0.00596078351/0.0134418579.

## Sampled-boundary fidelity and radial retreat

Hulling newly excludes 23 of 1,689 inward boundary points across 13 timestamps and 14 pockets. Primary-class counts are {'VMAX_BUS_13': 8, 'VMAX_BUS_30': 15, 'VMIN_BUS_18': 0, 'VMIN_BUS_33': 0}; pocket-class counts are {'VMAX / bus 13': 8, 'VMAX / bus 30': 15}; search-kind counts are {'AXIS': 3, 'RAY': 20}. Aggregate fidelity is 23/851 VMAX points and 3/128 signed-axis endpoints newly excluded. Per-timestamp before/after sampled-ray angular coverage, retained ray counts, retained signed-axis counts, and per-pocket retreat distributions are in `hulled_pocket_boundary_loss_summary.csv`.

For newly excluded points, delta-r min/Q1/median/Q3/max is 0.0149386797/0.116365655/1.37728989/2.52381619/8.68227517 kW; delta-r/r-original is 6.43601619e-06/5.64324945e-05/0.000721751711/0.00153536099/0.00506215469; delta-r/paired-bracket is 0.0339242413/0.452636162/5.89178469/10.027389/21.767265. Bracket normalization is diagnostic only: **BOUNDARY_LOCATION_BRACKETING is not INTER_DIRECTION_GEOMETRIC_OR_AC_FEASIBILITY_MARGIN**.

## Complexity and architecture conclusion

After convexifying all VMAX pockets, each timestamp has one outer hull and exactly two VMAX forbidden-pocket disjunction groups. Outer-hull facets are 26/29/30/31/31; bus-13 pocket facets 12/12.75/13/13/17; bus-30 pocket facets 11/12.75/13/13/14; total VMAX pocket facets 23/25/26/26.25/31; total outer-plus-VMAX geometric inequalities 53/55/57/57/58. No Cartesian expansion or binary count is used as a solver-complexity metric.

The exact partition remains 21-28 convex cells, 93-109 inequalities, and 21-28 conceptual cell alternatives. **FULL_EXACT_CONVEX_PARTITION remains the Main candidate** because it is exact. **Pocket difference after geometric-conservative VMAX hulling is retained as a credible compact fallback** under the evidence label **POCKET_DIFFERENCE_REMAINS_CREDIBLE_COMPACT_GEOMETRIC_FALLBACK_WITH_NONZERO_LOCALIZED_SAMPLED_BOUNDARY_FIDELITY_COST**. No materiality threshold was preregistered or invented. The two tiny positive-area VMIN pockets remain separately classified **VMIN_NONCONVEXITY_NOT_RESOLVABLE_ABOVE_BOUNDARY_SEARCH_RESOLUTION**; this is not a claim of mathematical convexity or exact omission.

## Locked accounting and guardrails

Hull-minus-polygon accounting remains VMAX-only 9187485.413888 kW^2, VMIN-only 15.266237 kW^2, mixed 0.000000 kW^2, total 9187500.680125 kW^2. The VMAX-only value is not the total. VMAX nonconvexity remains resolvably structural; the kernel remains noncredible as Main Coupled DOE; no representation here is AC-interior certified.
