# DOE architecture-decision artifact audit

## Scope

Deterministic artifact-only analysis at committed HEAD `c18021d9b981f2629e54f60e8c2fc5f33b00c1a2` on `codex/dso-vpp-ac-map-pilot`. No AC solve, production probe, replay, optimization, benchmark, mesh validation, parameter tuning, staging, commit, or push was performed. All five source manifests verified `PASS` before calculation.

## Kernel retention by mechanism

The kernel retains **0/851 VMAX** points and **819/838 VMIN** points, aggregate **819/1689**.

- `VMAX_BUS_13`: 0/429.
- `VMAX_BUS_30`: 0/422.
- `VMIN_BUS_18`: 431/435.
- `VMIN_BUS_33`: 388/403.

Because every stored VMAX boundary point is excluded, area retention cannot establish mechanism fidelity. The artifact result is `KERNEL_NOT_CREDIBLE_AS_MAIN_COUPLED_DOE_FROM_EXISTING_BOUNDARY_MECHANISM_FIDELITY`. This is not an AC-safety claim, and the kernel is not known to be the maximum-area convex subset.

## Kernel radial-loss severity

For all 870 excluded points, physical radial loss is measured from the production center along the established centered/sign-normalized production-angle ray. Overall delta-r: min/Q1/median/Q3/max = 0.0187984957317/81.2641903534/120.60328323/195.628262171/2317.4018043 kW. VMAX: min/Q1/median/Q3/max = 42.2045909359/82.0016640082/120.233143754/193.358689499/1705.29571093 kW. VMIN: min/Q1/median/Q3/max = 0.0187984957317/2.89939528104/537.724341605/1349.57650049/2317.4018043 kW. Relative and bracket-normalized distributions, including family, bus class, ray/signed-axis, and every timestamp, are in `kernel_radial_loss_summary.csv`.

## Normalized hull-minus-polygon pockets

Across 32 timestamps, pocket fraction relative to polygon area is min/Q1/median/Q3/max = 0.0125701982907/0.0160931603668/0.0181934934591/0.0198967722064/0.0209738521229; relative to hull area it is min/Q1/median/Q3/max = 0.0124141499641/0.0158382034199/0.0178684018777/0.0195086135134/0.0205429865606. Aggregate ratios are 0.017766217183 and 0.0174560885231, respectively.

The all-pocket sum is **9187500.680124677718 kW^2**. The previously quoted 9,187,485.414 kW^2 is not the all-pocket sum: it is the rounded VMAX-only component (9187485.413888176903 kW^2). The additional VMIN-only component is 15.266236501514 kW^2; mixed is 0.000000000000 kW^2. Existing classification is preserved with no new threshold.

## VMAX local geometric concavity

There are 717 VMAX reflex vertices. Local neighbor-chord segment depth is min/Q1/median/Q3/max = 0.0220630657978/0.747525817102/1.17450150598/1.57948349867/9.02245431931 kW. This is a purely geometric local concavity-depth metric, labeled `GEOMETRIC_ONLY_NOT_AC_VALIDATED`; it is **not** an AC inter-ray sagitta and does not make an inward edge AC-feasible. Per-timestamp count/median/max and full distributions are in `vmax_concavity_summary.csv`.

## Piecewise complexity

The exact minimum within the existing production-center fan/consecutive-interval merge class is min/Q1/median/Q3/max = 21/22/23/24.25/28 cells. VMAX reflex counts are min/Q1/median/Q3/max = 20/21/22/23.25/27; total reflex counts are min/Q1/median/Q3/max = 20/22/22/23.25/27. At 32/32 timestamps the existing exact count equals VMAX-reflex-count plus one, including the two timestamps with a trace VMIN reflex vertex.

For a simple polygon partitioned by noncrossing diagonals without Steiner points, the generic optimum satisfies `ceil(r/2)+1 <= cells <= r+1`. Those generic bounds are recorded as a reference only: the existing exact DP minimizes a restricted center-fan class whose common production center is a Steiner point, so the theorem does not certify that restricted minimum. Correlations are in `audit_summary.json`.

Classification: `VMAX_ONLY_PIECEWISE_COMPLEXITY_REDUCTION_UNLIKELY_FROM_EXISTING_GEOMETRY`. This is strong empirical geometry evidence, not proof that every possible VMAX-focused architecture is mathematically impossible to simplify.

## Loss-mechanism diagnostic

`LOSS_MECHANISM_NOT_TESTABLE_FROM_STORED_ARTIFACTS`: the production boundary series does not store a branch-flow/loss quantity paired to each reflex vertex. No causal claim is made.

## Architecture decision

Retain the full exact convex partition as the credible **Main Coupled DOE candidate** from the existing geometry. Do not promote the polygon kernel: it removes 100% of stored VMAX boundary evidence. Do not invest in a VMAX-only simplification on the present evidence: the exact full-partition count already tracks VMAX reflex count plus one at every timestamp. The cells and angular polygon remain geometric references, not AC-certified interiors.

## Locked conclusions preserved

- `NAIVE_CONVEX_HULL_IS_NOT_ACCEPTABLE`
- `FOUR_FACET_PLUS_GLOBAL_HOMOTHETIC_CONTRACTION_IS_NOT_ACCEPTABLE`
- `UNIFORM_CONVEX_HULL_EROSION_IS_NOT_ACCEPTABLE`
- `NONCONVEXITY_IS_RESOLVABLY_LARGER_THAN_BOUNDARY_SEARCH_RESOLUTION`
- `VMAX_NONCONVEXITY_RESOLVABLY_STRUCTURAL`
- `VMIN_NONCONVEXITY_NOT_RESOLVABLE_ABOVE_BOUNDARY_SEARCH_RESOLUTION`
- `ANGULAR_POLYGON_IS_GEOMETRIC_REFERENCE_NOT_AC_CERTIFIED`
- `KERNEL_IS_NOT_KNOWN_TO_BE_MAXIMUM_AREA_CONVEX_SUBSET`

The audit does not claim VMIN mathematical convexity, kernel AC safety, angular-polygon AC safety, equivalence of local depth and AC sagitta, convexity from fitted-normal deviation, or fidelity from area retention alone.
