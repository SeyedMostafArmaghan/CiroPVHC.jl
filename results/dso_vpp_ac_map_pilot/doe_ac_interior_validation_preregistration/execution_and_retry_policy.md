# Execution, retry, and checkpoint policy

## Authoritative execution contract

The later campaign must call `DSOVPPProductionProbe.evaluate_physical!`, which calls `DSOVPPACMapStage0.evaluate_point`, the radial primary AC power flow, and `CiroPVHC.replay_s1b_interval`. Coordinates are absolute physical PCC active powers `(P13, P30)` in kW at buses 13 and 30 (`N_P=2`); `Q13=Q30=0`, `reference_pv_capacity_kw=0`, voltage limits are 0.90--1.05 p.u., and positive P is injection/export. Historical command-space and reference-PV coordinate paths are prohibited.

## Locked execution order and mode

Execution is `SERIAL`: one Julia process and one Julia thread. Timestamps are chronological. Within each timestamp, controls execute first in their recorded order, then the 720 boundary points by increasing theta, then remaining cell-mesh points by canonical point ID. The order is immutable after results are observed.

## Configuration controls

All four controls at a timestamp must reproduce their exact committed expected primary status. Any contradiction is `VALIDATION_CONFIGURATION_CONTROL_FAILURE`; substantive execution must stop before interpreting or starting that timestamp's mesh until configuration is resolved.

## Retry and nonconvergence

Attempt 1 uses the authoritative flat start (`initial_voltage=nothing`, `warm_start_source=FLAT_START`) and unchanged production iteration/tolerance constants. On nonconvergence only, make at most one retry using the primary complex-voltage vector from the nearest previously converged point at the same timestamp among already executed controls and substantive points. Distance is Euclidean physical `(P13,P30)` kW; ties choose the lower execution order, then the lexicographically lower deterministic point/control ID. Converged-feasible and converged-infeasible points are both accepted seed candidates, matching production semantics. If no accepted neighbor exists, the retry is unavailable and the point is unresolved. No solver-tolerance change or additional rescue is allowed. A failed or unavailable retry is `UNRESOLVED_NONCONVERGENCE`, never infeasible.

## Checkpoint and resume

Checkpoint atomically after every 250 completed substantive points within a timestamp and write a separate atomic completed-timestamp checkpoint. Write a temporary file beside the destination, flush/close, hash it, then atomically replace the destination, following the production atomic-write/provenance pattern without serializing `TimestampWork`.

The checkpoint manifest key is `(validation_point_id, attempt_index)` and stores attempt status, retry seed ID, retry completion, primary point status, row hash, and timestamp completion hash. Resume verifies config, generator, mesh, source-manifest, and checkpoint hashes; loads completed point IDs and attempt rows; treats a point as completed only if its terminal primary status is present; resumes a first-attempt nonconvergence with the preregistered retry state; and derives pending IDs by ordered set difference. Completed timestamps require their atomic completion record. Appends are ID-guarded, so no attempt or result row is duplicated or reclassified.

Checkpoint/I/O overhead is `NOT_MEASURED` and is not included in the runtime totals.
