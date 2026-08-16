# Pre-execution diagnostic hypotheses for AC interior validation

This human-readable memo was written before execution of the preregistered substantive AC interior-validation campaign. It records diagnostic hypotheses and heuristic conditional estimates; it does not modify the validation design or its interpretation.

Authoritative branch: `codex/dso-vpp-ac-map-pilot`

Pre-validation preregistration commit: `8ac219fbb9ae9e58eabde91eb361005ead6239da` (`preregister: lock AC interior validation design`)

**NO SUBSTANTIVE AC INTERIOR VALIDATION HAD BEEN EXECUTED AT THE TIME THESE HYPOTHESES WERE RECORDED.** This statement does not deny the already-existing benchmark evaluations of controls and cell centroids.

## PRE_EXECUTION_DIAGNOSTIC_HYPOTHESES

### H1 — VMAX concentration hypothesis

If AC counterexamples exist, their incidence is expected to be higher on VMAX-associated inter-ray boundary points than on VMIN-associated boundary points.

The basis is observed geometry: 717 of 851 VMAX boundary vertices are reflex/concave, versus 2 of 838 VMIN vertices, and VMAX accounts for essentially all resolvable hull-deficit nonconvexity. This is a directional empirical hypothesis, not a proof. It does not state that VMIN cannot fail or that VMAX must fail.

### H2 — Boundary concentration hypothesis

If inter-ray polygon interpolation is the dominant source of geometric/AC mismatch, AC counterexamples should be more concentrated on inter-ray boundary points and near-boundary cell-mesh points than at deep cell-interior points. This is diagnostic only. No new distance threshold is defined here.

### H3 — Deep-interior surprise hypothesis

A converged-infeasible point that is strictly interior and materially separated from the angular polygon boundary would be a scientifically stronger and less expected finding than a shallow near-boundary failure. This memo does not introduce a post-hoc definition of “materially separated.” Later analysis must use whatever deterministic geometric distance metrics can be reconstructed after execution.

### H4 — Quantitative predictions are not acceptance criteria

Failure count, violation magnitude, VMAX/VMIN ratio, and spatial concentration are diagnostic predictions only. They do **not** alter the validation pass/fail rules, mesh, retry policy, or stopping rule. No result may be reclassified because it matches or fails to match the heuristic forecast.

### H5 — VMAX concentration does not prove a physical mechanism

Even if failures are strongly concentrated on VMAX geometry, that alone does **not** establish loss-induced curvature, global voltage concavity, or convexity of the AC violation set. Any such physical mechanism requires separate evidence.

## HEURISTIC_CONDITIONAL_MODEL_ESTIMATE

**NOT_AN_ACCEPTANCE_CRITERION**

### E1 — Violation-magnitude heuristic

If VMAX-side inter-ray failures occur, shallow voltage violations on the rough order of `1e-5` to `1e-4` p.u. are considered plausible. This is **not a derived bound**. Its basis is only a heuristic extrapolation from observed geometric concavity scales, existing topology/sensitivity scales, and the fact that stored inward endpoints terminate very close to voltage limits. The range is not mathematically derived from DistFlow.

### E2 — Failure-count heuristic

A broad pre-execution heuristic expectation is more than isolated failures but substantially fewer than the entire 23,040-point boundary mesh. “Order of thousands” is a **HEURISTIC FORECAST — NOT A DERIVED BOUND** and is not used in any acceptance criterion.

### E3 — VMIN rarity heuristic

VMIN-associated failures are expected to be much rarer than VMAX-associated failures because VMIN geometric nonconvexity was not resolvable above the current boundary-search resolution. A VMIN failure count of zero is not a requirement.

## CORRECTIONS_LOGGED_BEFORE_VALIDATION_EXECUTION

### Correction 1 — GEOMETRIC_POCKET != AC_VIOLATION_SET

`conv(P_t) \ P_t` is a geometric object constructed from sampled polygon geometry. It is **not** the same object as an AC-defined violation set such as `{P : Vmax(P) > 1.05}`. The convexity or nonconvexity of the geometric pocket therefore does not establish convexity or nonconvexity of the true AC violation set.

Before conservative hulling, 14 of 64 VMAX pockets were themselves geometrically nonconvex.

### Correction 2 — CONCAVITY_DERIVATION_WITHDRAWN

The earlier informal claim that “`v_b` is concave in PCC injections because the DistFlow loss term enters with negative sign” was incorrect.

In the standard branch-flow form,

`v_j = v_i - 2(rP + xQ) + (r^2 + x^2)ℓ`,

with

`v_i ℓ = P^2 + Q^2`,

the loss-related term appears with positive sign in that equation, and the branch variables are endogenous nonlinear functions of injections. Therefore, global concavity of bus voltage in `(P13, P30)` has **not** been established, and convexity of the AC VMAX violation region has **not** been established. The observed VMAX/VMIN asymmetry remains empirical.

### Correction 3 — LOCAL_DEPTH_OVER_FOUR_IS_HEURISTIC_ONLY

A relationship such as `edge sagitta ≈ local concavity depth / 4` can arise under a local quadratic/uniform-spacing approximation. However, production angular spacing is not uniformly sampled everywhere, adaptive rays exist, the AC boundary is not known to be quadratic, and local polygon concavity depth is not AC sagitta. Therefore, no quantitative AC-edge retreat is derived from this relation.

## EXISTING_EMPIRICAL_CONTEXT_CLASSIFICATION_PRESERVED

Existing committed findings used only as empirical context include:

- 717 VMAX reflex vertices and 2 VMIN reflex vertices;
- local geometric concavity depth with median approximately 1.1745 kW and maximum approximately 9.0225 kW;
- VMAX-pocket internal nonconvexity depth of 0.0121–3.6331 kW; and
- `DOE_BENCHMARK_CELL_CENTROIDS_3_OF_3_AC_FEASIBLE`, classified strictly as `CELL_CENTROID_POINTS_ONLY`, `SMALL_N`, and `NO_INTERIOR_SAFETY_INFERENCE`.

These facts retain their existing classifications and are not reinterpreted here.

## NO_PREREGISTERED_VALIDATION_PARAMETER_CHANGED

- 0.5° boundary spacing unchanged
- `q=5` unchanged
- 65,494 substantive points unchanged
- 128 controls unchanged
- retry policy unchanged
- decision rules unchanged
- execution order unchanged
- serial execution unchanged
- checkpoint policy unchanged
- 120,000 cap unchanged

This hypotheses memo is diagnostic context only. Failure count, violation magnitude, constraint-side ratio, and spatial concentration do not change the locked decision rules.

## PREREGISTRATION_INTEGRITY_AND_MANIFEST_SCOPE

Before this memo was added, the existing preregistration manifest verified successfully against all 14 files in its immutable payload. The committed structure records 65,494 unique substantive validation points, 128 controls, 23,040 raw boundary points, 66,633 raw cell-lattice memberships, `q=5`, and 0.5° angular spacing (720 directions for each of 32 timestamps).

The existing generated `manifest.json` is intentionally immutable. This later provenance memo is adjacent to, but outside, its payload set; neither the manifest nor any preregistered mesh, configuration, policy, or generated artifact is modified by adding this file.

**NO_AC_VALIDATION_EXECUTED**  
**NO_PREREGISTRATION_PARAMETER_CHANGED**
