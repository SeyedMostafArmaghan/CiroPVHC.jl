# Postproduction result audit

Final classification: `POSTPRODUCTION_RESULT_AUDIT_COMPLETE_WITH_DOCUMENTED_LIMITATIONS`

## Provenance and reconciliation

The audit used only committed production and historical artifacts. It performed zero new AC solves. The run manifest records execution base commit `972e934b44e9e8c7004517618c8f5bee727b0760`; implementation and result commits `166a182` and `fed6d528611d9c55a04f49a8b353cf4ad015dc9c` are descendants in the verified local lineage. The scientific config hash is `18530df3a6aad54c619e061b9c9f40136509cebe135fd42ee2e3c032383cb06d`. Counts reconcile to 32 timestamps, 128 axes, 1,634 rays, 482 adaptive directions, 73 guard truncations, 143 retries, 87,229 logical evaluations, and 87,372 actual attempts.

## Binding structure

Primary VMAX bindings are bus 13: 429 (50.411281%) and bus 30: 422 (49.588719%). Primary VMIN bindings are bus 18: 435 (51.909308%) and bus 33: 403 (48.090692%). No fifth primary reported binding bus exists. `CO_BINDING_NOT_RESOLVABLE_FROM_STORED_ARTIFACTS`: full voltage vectors/all-bus margins are not retained.

## Coordinate/sensitivity check

The first-order prediction is ΔP30=334.004374831 kW versus observed 341.032714840 kW; absolute discrepancy 7.028340009 kW (2.060899%). Both historical and production primary VMAX records bind at bus 30. This is only `FIRST_ORDER_COORDINATE_AND_SENSITIVITY_CONSISTENCY_CHECK`.

## Retry and timing

All 143 retries failed: rescue rate 0/143 = 0%. Every retry occurred in an axis coarse sweep after doubling had already established a provisional converged feasible/violating bracket, before bisection, and beyond the final certified axis boundary; none defines a physical limit. Production aggregate rates are 0.625721 ms/logical evaluation and 0.624697 ms/actual attempt. Exact timer inclusions/exclusions are in `timing_provenance.json`; causal attribution remains `TIMING_RATE_DIFFERENCE_CAUSE_UNRESOLVED`.

## Geometry and guards

Centered-production and hypothetical origin-radial angular geometry was reconstructed without solves. The 73 ray guards are `CERTIFIED_FEASIBLE_GUARD_TRUNCATION`, never AC boundaries or unbounded directions. Across them, the largest displacement component is below the 20 MW per-axis numerical guard, supporting `RAY_GUARD_PHYSICALLY_TIGHTER_THAN_AXIS_NUMERICAL_GUARD`.

## Adaptive refinement

All 482 intervals reconcile. Marginal and exact-combination counts are in `adaptive_trigger_summary.json`; marginal counts intentionally overlap.

## Analytical corner and anchor

The analytical corner was transformed into centered normalized coordinates and bracketed by stored production directions. No AC inference was made: `NO_NEW_AC_CORNER_VALIDATION_PERFORMED`. The anchor classifier used only total axis width and median base-ray radius; the exact causing metric(s) are listed in `anchor_near_extreme_summary.json`.

## Corrected cardinal geometry and coupling diagnostic

All 128/128 deterministic cardinal identities pass at tolerance 1.0e-09 kW. At r=1 the centered construction maps 0 degrees to `(P13_max, center_P30)`, 180 degrees to `(P13_min, center_P30)`, 90 degrees to `(center_P13, P30_max)`, and 270 degrees to `(center_P13, P30_min)`. These are generally not the absolute-axis AC probe points because the orthogonal center coordinate need not be zero. Therefore `PREVIOUS_CARDINAL_R_EQ_1_AUDIT_RULE_INVALID_FOR_CENTERED_RADIAL_GEOMETRY`.

The actual certified boundary radii retain their scientific value as `CARDINAL_CENTERLINE_COUPLING_DIAGNOSTIC`; delta_r = r_boundary - 1 is summarized by direction:

- 0 degrees: mean -0.076644897, median -0.026074219, min -0.388281250, q25 -0.179833984, q75 0.023657227, max 0.052148438; fraction r>1 0.437500, fraction r<1 0.562500; largest positive 0.052148438 at 2013-04-17 05:30:00, largest negative -0.388281250 at 2011-02-05 18:00:00.
- 90 degrees: mean -0.056253052, median -0.020703125, min -0.275585938, q25 -0.129248047, q75 0.014526367, max 0.034960937; fraction r>1 0.437500, fraction r<1 0.562500; largest positive 0.034960937 at 2013-04-17 05:30:00, largest negative -0.275585938 at 2011-02-05 18:00:00.
- 180 degrees: mean 0.065338135, median 0.022216797, min -0.044433594, q25 -0.020117187, q75 0.153173828, max 0.331250000; fraction r>1 0.562500, fraction r<1 0.437500; largest positive 0.331250000 at 2011-02-05 18:00:00, largest negative -0.044433594 at 2013-04-17 05:30:00.
- 270 degrees: mean 0.049172974, median 0.018066406, min -0.030566406, q25 -0.012744141, q75 0.113012695, max 0.240820312; fraction r>1 0.562500, fraction r<1 0.437500; largest positive 0.240820312 at 2011-02-05 18:00:00, largest negative -0.030566406 at 2013-04-17 05:30:00.

This diagnostic alone does not measure convexity, anisotropy, or global coupling strength. All 128 cardinal certified boundaries satisfy the normal safe/violating endpoint contract, and none was guard-limited (r_guard=2).

## Limitations

- `CO_BINDING_NOT_RESOLVABLE_FROM_STORED_ARTIFACTS`.
- Historical analytical corner has no exact independent AC replay evidence.
- Timing rate difference cause is unresolved because scopes/workloads differ.
