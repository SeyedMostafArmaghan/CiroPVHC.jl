# DSO-VPP authoritative AC evaluation runtime benchmark

Classification: `RESOURCE_PLANNING_BENCHMARK_ONLY`; `NOT_DOE_INTERIOR_VALIDATION`.

## Locked evaluation path

`DSOVPPProductionProbe.evaluate_physical!` calls `DSOVPPACMapStage0.evaluate_point`, which assembles absolute physical P13/P30 injections, runs `primary_power_flow`, then independently replays with `CiroPVHC.replay_s1b_interval`. The benchmark uses `reference_pv_capacity_kw=0`, Q13=Q30=0, buses 13 and 30, VMIN=0.90 p.u., VMAX=1.05 p.u., and the production flat-start/retry semantics.

A point is `FEASIBLE` only when the production wrapper returns `CONVERGED_FEASIBLE`; `INFEASIBLE` means `CONVERGED_INFEASIBLE`; nonconvergence after the production retry policy is `UNRESOLVED`. Successful execution here does not certify any inter-ray edge or angular interior.

## Design

One untimed warm-up plus 15 timed logical point evaluations were run serially. Underlying AC attempts: 16, with a hard cap of 20. Timestamps were the mandatory anchor, committed production-runtime minimum excluding the anchor, and committed production-runtime maximum excluding the anchor.

Each timestamp contributes its committed certified center, the lowest-angle paired VMAX ray safe endpoint, the lowest-angle paired VMIN ray safe endpoint, the arithmetic vertex centroid of its largest committed exact convex cell, and the paired stored outward-infeasible endpoint from the selected VMAX ray.

## Warm-up and steady state

- In-script setup before warm-up: 22.382838 s.
- First-call/JIT warm-up: 0.207014 s (CONVERGED, FEASIBLE).
- Steady state (n=15): min 0.000059000, Q1 0.000062250, median 0.000065900, Q3 0.000073500, max 0.000154500, mean 0.000075813 s.
- Feasible (n=12): median 0.000068550 s, mean 0.000078600 s.
- Infeasible (n=3): median 0.000065500 s, mean 0.000064667 s.

These subgroup samples are deliberately tiny and are descriptive only.

## CPU and RAM

- Available logical CPUs: 12; Julia processes: 1; Julia threads: 1.
- Baseline current process RSS before warm-up: 728.652 MiB; approximate peak process RSS: 763.402 MiB.
- Timed-loop process CPU: 0.031000 s over 0.024120 s aggregate loop wall time (1.285 average process cores; coarse observation).
- Source inspection finds no threading in this call path; execution was serial and appears single-threaded. The short CPU sample is too small for an exact utilization claim.

## Projection and execution recommendation

Mean-rate serial projections (excluding startup and checkpoint I/O):

- 1000: 0.076 s
- 5000: 0.379 s
- 10000: 0.758 s
- 50000: 3.791 s

Four- and eight-worker rows in `runtime_projection.csv` are `IDEALIZED_PARALLEL_PROJECTION_NOT_MEASURED`. Perfect scaling is not assumed for planning.

Later point/timestamp evaluation is `TECHNICALLY_PARALLELIZABLE` with worker-owned network/evaluation state and deterministic result merging. The current production implementation is `CURRENT_IMPLEMENTATION_ALREADY_SUPPORTS_PARALLEL_EXECUTION = false`: it serially mutates evaluation IDs, accepted-neighbor warm starts, and attempt rows. Parallelizing that shared state directly would be unsafe and could change retry behavior.

Laptop classification: `SAFE_ON_PERSONAL_LAPTOP_WITH_CHECKPOINTING`. Use deterministic per-timestamp partitions, checkpoint every fixed 250 candidate points within a timestamp, finalize an atomic checkpoint per timestamp, and merge in preregistered timestamp/point order. Reuse production probing's atomic write and provenance-hash pattern, but not its schema-specific serialized `TimestampWork` objects.

## Reproducibility and guardrails

Timestamp selection, point selection, coordinates, configuration, and provenance are deterministic structural inputs. Wall times, CPU observations, and RSS are nondeterministic measurements and are not expected to reproduce byte-for-byte.

The locked architecture findings are unchanged: `FULL EXACT CONVEX PARTITION` remains the current main coupled DOE candidate; the convex-hulled VMAX pocket-difference representation remains the compact geometric fallback. Both remain `GEOMETRIC_ONLY` and `NOT_AC_INTERIOR_CERTIFIED`; `INTER_RAY_EDGE_AND_ANGULAR_INTERIOR_AC_FEASIBILITY` remains unresolved.

No validation mesh, boundary search, DOE construction, optimization, replay campaign, parameter tuning, parallel benchmark, staging, commit, push, or stash operation was performed.
## Runtime reconciliation correction
The original 65.9 microsecond median is preserved, but its precise scope is corrected to `FULL_PRODUCTION_IN_MEMORY_LOGICAL_EVALUATION_NO_RETRY_EXCLUDING_SEARCH_ORCHESTRATION_AND_IO`, not AC-core-only or end-to-end production throughput. Future validation preregistration should use 0.625720804888803 ms/evaluation as the conservative workload rate, state the 22.382838 s measured current setup separately, and budget future checkpoint/I/O explicitly. See `runtime_reconciliation_report.md` for the deterministic count, timer-scope, and production-runtime reconstruction. `NO_NEW_AC_EVALUATIONS_PERFORMED`.
