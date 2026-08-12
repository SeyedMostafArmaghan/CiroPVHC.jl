# Final production DOE probe preregistration

Final classification: **`PRODUCTION_PROBE_PREREGISTERED_READY_FOR_REMOTE_BACKUP`**.

The production probe is deliberately disabled and was not executed. This preregistration supersedes the earlier hierarchical 8-dense/24-sparse and 24-direction recommendation while preserving that audit as scientific history.

## Locked temporal selection

- Exactly 32 unique timestamps are selected from 52,608 half-hourly profile rows.
- All 32 timestamps are dense (`ALL_32_TIMESTAMPS_DENSE`).
- The 32 slots are season x daypart x stress mode: four seasons, four dayparts, and one export plus one import selection per stratum.
- `2012-10-15 13:00:00` is forced into the `SPRING/AFTERNOON/EXPORT` slot and removed from every ranking. The other 31 slots use only load, PV, season, daypart, and timestamp tie-breaking.
- Export ranking is PV factor descending, load multiplier ascending, timestamp ascending. Import ranking is load multiplier descending, PV factor ascending, timestamp ascending.
- The committed profile column `pv_profile` is the preregistered `pv_factor` input. No AC result, axis bound, binding bus, or boundary radius enters selection.

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
- B1/V1: nonconvergence is never infeasibility; boundary mechanisms and solver statuses remain separate; voltage band is exactly 0.90-1.05 p.u.
- A1: every cross-time aggregation or intersection is performed in physical absolute `P_PCC` coordinates. Direction indices and normalized angles are not comparable across timestamps.
- Absence of observed re-entry is reported only at the retained sweep resolution. Monotonicity, convexity, and star-shapedness remain unproven.

## Updated resource estimate

The base-only plan is 66,304 fixed AC evaluations. Triggering all adaptive midpoints gives 125,056 evaluations; a planning allowance of 25% for deterministic retries gives 156,320. At the observed Phase-B orchestration rate of 4.1587 ms/evaluation, those correspond to about 4.6, 8.7, and 10.8 minutes of serial evaluator kernel time, or ideal eight-worker kernels of about 35, 65, and 81 seconds.

Allow 5-15 minutes end-to-end on the 12-CPU/32-GB VM for Julia startup, retained coarse samples, replay, atomic checkpoints, and deterministic merging. Use eight one-thread workers; expected RAM remains below 8 GB from the observed roughly 743 MiB worker footprint. The 31-core/126-GB cluster is not required. Plan for 20-50 MB of retained raw/checkpoint artifacts, with atomic direction- and timestamp-level resume points.

These are estimates, not an executed benchmark of the production probe.

## Gate

The selector, S0 extraction, transition state machine, machine-readable policies, deterministic regeneration check, and focused tests must pass before remote backup. Production execution, DOE construction, coupled/box optimization, EV/BESS optimization, centralized optimization, and push are outside this commit.
