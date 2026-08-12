# Final production DOE probe preregistration

Final classification: **`PRODUCTION_PROBE_PREREGISTERED_READY_FOR_REMOTE_BACKUP`**.

The production probe is deliberately disabled and was not executed. This preregistration supersedes the earlier hierarchical 8-dense/24-sparse and 24-direction recommendation while preserving that audit as scientific history.

## Locked temporal selection

- Exactly 32 unique timestamps are selected from 52,608 half-hourly profile rows.
- All 32 timestamps are dense (`ALL_32_TIMESTAMPS_DENSE`).
- The 32 slots are season x daypart x stress mode: four seasons, four dayparts, and one export plus one import selection per stratum.
- `2012-10-15 13:00:00` deterministically replaces the nominal ranked pick in the `SPRING/AFTERNOON/EXPORT` slot before any other slot is selected. Its natural rank is irrelevant. The other 31 slots exclude the anchor and use only load, PV, season, daypart, and timestamp tie-breaking; simple deduplication is not the replacement mechanism.
- Export ranking is PV factor descending, load multiplier ascending, timestamp ascending. Import ranking is load multiplier descending, PV factor ascending, timestamp ascending.
- The committed profile column `pv_profile` is the preregistered `pv_factor` input. No AC result, axis bound, binding bus, or boundary radius enters selection.
- `semantic_category` separates the ranking label from scientific interpretation. In particular, a NIGHT export-ranked row with exactly zero PV is `LOW_LOAD_ZERO_PV`, not PV export stress.

The anchor has load multiplier `0.15594037439888725` and PV factor `0.91495687390211622` in the committed profile.

## Same-timestamp S0 origin evidence

Every selected timestamp has an extracted root-voltage-1.0 S0 row at absolute `P_PCC=(0,0)`. The evidence table preserves the source numerical-validation and historical 0.95-1.05 operational-feasibility flags, and separately recomputes the locked production band 0.90-1.05 from the written voltages.

- production-band feasible: 32/32
- source numerical-validation flag true: 32/32
- historical S0 0.95-1.05 operational flag true: 23/32

The historical 0.95 flag is evidence metadata only and is not the production voltage limit.

## Locked search and geometry policy

- G1: four signed absolute axes, 100 kW initial numerical step, doubling, 20 MW absolute per-axis numerical guard, full axis coarse sweep at `S_axis/20` through at least `2*S_axis` or the guard.
- C1: signed-axis midpoint, then up to 20 dyadic contractions, then the same-timestamp S0 origin fallback.
- S1: centered radial search with `delta_r=0.05`, `r_guard=2.0`, and a retained full coarse sweep before bisection.
- Direction grid: 36 base directions at 10 degrees for every timestamp, one adaptive midpoint level, at most 36 adaptive and 72 total directions per timestamp.
- B1/V1: nonconvergence is never infeasibility. Bisection requires a converged-feasible lower endpoint and a converged-infeasible upper endpoint with an actual 0.90/1.05 voltage violation. A feasible-to-nonconverged transition is unresolved and cannot fabricate a bound.
- Only `AXIS_CERTIFIED_BOUNDARY` is finite-valid. Guard-limited, unresolved, and re-entry-contaminated axes are finite-invalid and cannot enter a Tier-1 midpoint.
- Retry changes initialization from flat start to the nearest accepted neighbor. If no accepted neighbor exists, an identical flat-start retry is forbidden and the failed search remains unresolved.
- Both bracket endpoints retain coordinate/r, absolute P13/P30, voltage extrema and buses, and solver status. The official coordinate is the last converged-feasible endpoint; the violating endpoint supports binding classification.
- `BINDING_VMIN` and `BINDING_VMAX` require a converged violating endpoint, an actual threshold violation, a non-null binding bus, and the stored violating voltage.
- A1: every cross-time aggregation or intersection is performed in physical absolute `P_PCC` coordinates. Direction indices and normalized angles are not comparable across timestamps.
- Absence of observed re-entry is reported only at the retained sweep resolution. Monotonicity, convexity, and star-shapedness remain unproven. Feasible sampled ray endpoints do not certify interpolated edges or polygons; later DOE construction requires independent conservative validation.
- Mandatory near-axis refinement remains a candidate only. The four axes and their adjacent base-grid endpoints are sampled directly, while the existing mechanism/bus/radius/unresolved adaptive triggers remain active.

## Updated resource estimate

The base-only plan is 66,304 fixed AC evaluations. Triggering all adaptive midpoints gives 125,056 evaluations; a planning allowance of 25% for deterministic retries gives 156,320. The 4.1587 ms/evaluation input is empirical aggregate throughput: 15.3498603 seconds divided by 3,691 evaluations from the serial, one-process, one-Julia-thread Phase-B orchestration benchmark. It is not a directly measured single-worker solve latency. Applying that aggregate rate gives equivalent elapsed times of about 4.6, 8.7, and 10.8 minutes; ideal eight-worker figures of about 35, 65, and 81 seconds are shown only as non-guaranteed scaling references.

The original 5-15 minute end-to-end estimate on the 12-CPU/32-GB VM is retained. It does not require an assumed parallel speedup because the hard-cap aggregate-rate extrapolation is about 8.7 minutes; eight one-thread workers are the execution plan but their speedup is uncertain. Expected RAM remains below 8 GB from the observed roughly 743 MiB process footprint. Plan for 20-50 MB of retained raw/checkpoint artifacts. The benchmark mixture may overrepresent feasible/easy evaluations and need not capture near-boundary, retry-heavy, or nonconvergent cost.

These are estimates, not an executed benchmark of the production probe.

## Gate

The selector, S0 extraction, transition state machine, machine-readable policies, deterministic regeneration check, and focused tests must pass before remote backup. Production execution, DOE construction, coupled/box optimization, EV/BESS optimization, centralized optimization, and push are outside this commit.
