# DSO-VPP AC runtime reconciliation audit

Decision: `MICROBENCHMARK_AND_PRODUCTION_TIMING_RECONCILED`

This is a deterministic source/artifact audit. `NO_NEW_AC_EVALUATIONS_PERFORMED`. It does not validate DOE interior safety.

## Authoritative production counts

- Logical point evaluations / first attempts: **87,229**.
- Retry attempts: **143**.
- Actual authoritative AC attempts and stored attempt rows: **87,372**.
- Numerically converged attempts added to `accepted_neighbors`: **87,086** (50,777 feasible; 36,309 infeasible).
- Nonconverged stored rows: **286** (143 first attempts plus 143 failed retries).
- Search objects: 128 signed-axis searches, 32 center units, 1,152 base rays, and 482 adaptive rays. Thus 1,634 ray searches, 1,762 axis-plus-ray boundary searches, and 1,794 axis/center/ray units.
- Full production run wall: **54.581000089645386 s**. The 32 timestamp runtimes are available individually in `production_timing_reconstruction.csv` and sum to **46.726999759680 s**.

`87,086` is a converged-attempt count, not a logical-evaluation count. `87,229` is a logical point-call count, not a ray/search count. `87,372` is the authoritative actual-attempt and stored-row count.

## Historical model reconstruction

The earlier 0.47 ms value came from the descriptive two-point fit `T = F + cN`:

- Phase-B: `N1=3,691`, `T1=15.3498603 s`.
- Production: `N2=87,229 logical evaluations`, `T2=54.581000089645386 s`.
- `c=(T2-T1)/(N2-N1)=0.469620290043398 ms/logical evaluation`.
- `F=T1-c*N1=13.616491809449817 s`.

This two-point model is underdetermined as causal evidence: Phase-B and production have different workloads, coordinate/reference-PV contexts, timer setup scopes, and checkpoint behavior. The production aggregate rates are independently derived as **0.625720804888803 ms/logical evaluation** and **0.624696700197379 ms/actual attempt**.

## What 65.9 microseconds measures

Precise label: `FULL_PRODUCTION_IN_MEMORY_LOGICAL_EVALUATION_NO_RETRY_EXCLUDING_SEARCH_ORCHESTRATION_AND_IO`.

The benchmark starts its timer immediately before `evaluate_physical!` and stops immediately after it returns. It includes scalar coordinate normalization, per-call injection/net-demand assembly, primary radial BFS, independent replay, voltage/replay classification, logical/attempt ID mutation, in-memory attempt-row construction, and accepted-neighbor voltage copying/storage. It excludes point selection, ray/axis coordinate derivation, post-return binding classification, benchmark timing-row construction, re-entry/adaptive logic, checkpoints, CSV output, and hashing. It is therefore neither `AC_CORE_ONLY` nor end-to-end production throughput. Exact itemization is in `timer_scope_inventory.csv`.

## State reuse

- `BENCHMARK_STATE_REUSE = PARTIAL`: network/profile objects and one mutable `EvaluationState` per timestamp persist. Every first attempt explicitly uses `initial_voltage=nothing` (`FLAT_START`). All 16 benchmark attempts converged first try, so no voltage warm start was reused; accepted-neighbor state merely accumulated.
- `PRODUCTION_STATE_REUSE = PARTIAL`: the same per-timestamp state persists across axes, center, and rays. Every logical evaluation first flat-starts. Only a nonconverged first attempt selects the nearest accepted neighbor and retries with its voltage. Production had 143 such retries; all 143 also failed. State resets with each timestamp's `TimestampWork`.

## Production overhead and broad reconciliation

The committed per-attempt `Stage0.evaluate_point` timer sums to **19.370204900 s**; median **0.1377 ms**, mean **0.221698 ms/actual attempt**. Expensive nonconvergent attempts raise the mean.

The measured run decomposes exactly at broad timer boundaries:

| Layer | Seconds | Evidence | Interpretation |
|---|---:|---|---|
| Stored Stage0 internal attempt timers | 19.370204900 | MEASURED/SUMMED | Assembly, primary solve, replay, Stage0 classification; excludes production wrapper tail. |
| Timestamp scopes minus Stage0 timers | 27.356794860 | DERIVED_REMAINDER | Wrapper/search allocations and bookkeeping, re-entry/refinement logic, growing in-memory state, and current-checkpoint serialization/I/O; not separately isolatable. |
| Full run minus summed timestamp scopes | 7.854000330 | DERIVED_REMAINDER | Preflight/profile work, completed-timestamp checkpoint work, logging, and other inter-scope gaps; not pure startup. |
| Full production timer | 54.581000090 | MEASURED | 54.581000089645386 s. |

Production performs 1,794 growing-current-work checkpoint writes plus 32 completed-timestamp writes. Final CSV/artifact serialization occurs after `finished_at` and is excluded from the 54.581 s production timer. Attempt IDs, attempt/result allocation, per-attempt provenance, accepted-neighbor updates, and in-memory rows are computation/allocation rather than disk I/O. Search-level safe/violating storage and re-entry/adaptive work occur outside `evaluate_physical!` but inside the production run.

The 65.9 microsecond median and 0.47-0.63 ms historical effective rates can both be correct because they measure different scopes and runs. The current benchmark isolates a short, warmed, converged/no-retry in-memory call. Production includes a materially larger workload, 286 expensive nonconvergent attempts, search orchestration, growing state, frequent checkpoints, and fixed run work. Historical host CPU/RAM identity is not recorded, so the remaining machine/run-condition difference is not causally decomposed.

## Ordered benchmark behavior

The first timed call was **114.7 microseconds** and was not the maximum. Call **2** was the maximum at **154.5 microseconds**. The first five-call anchor block averaged **98.220 microseconds** versus **64.610 microseconds** for calls 6-15. Later calls are descriptively more stable, but timestamp and category are confounded by execution order; no significance claim is made. See `benchmark_timing_order.csv` for all 15 rows.

## Rates for validation planning

- `AC_CORE_RATE = NOT_SEPARATELY_IDENTIFIABLE_FROM_CURRENT_ARTIFACTS`. The 65.9 microsecond result includes more than the AC core.
- `FULL_IN_MEMORY_EVALUATION_RATE = 0.0659 ms median; 0.0758133333333 ms mean` for the current laptop's converged/no-retry benchmark scope.
- `VALIDATION_PLANNING_RATE = 0.625720804888803 ms/evaluation` (conservative upper rate: historical production wall/logical count).
- Supporting planning interval: `0.469620290043398-0.625720804888803 ms/evaluation`, from the weak affine marginal fit to the measured production logical aggregate.

Projections separate workload from the measured current setup cost. Future validation checkpoint/I/O cost remains unmeasured and must receive a preregistered allowance rather than a fabricated value.

| Evaluations | Affine workload | Conservative workload | Fixed setup | Conservative + setup | Future checkpoint/I/O |
|---:|---:|---:|---:|---:|---|
| 1,000 | 0.470 s | 0.626 s | 22.383 s | 23.009 s | NOT_MEASURED |
| 5,000 | 2.348 s | 3.129 s | 22.383 s | 25.511 s | NOT_MEASURED |
| 10,000 | 4.696 s | 6.257 s | 22.383 s | 28.640 s | NOT_MEASURED |
| 50,000 | 23.481 s | 31.286 s | 22.383 s | 53.669 s | NOT_MEASURED |
| 100,000 | 46.962 s | 62.572 s | 22.383 s | 84.955 s | NOT_MEASURED |

The conservative rate already amortizes historical production setup/checkpoint activity, so adding both it and the 22.382838 s current setup is intentionally conservative rather than a fitted end-to-end prediction.

## Interior-centroid observation

`DOE_BENCHMARK_CELL_CENTROIDS_3_OF_3_AC_FEASIBLE`

Mandatory qualifier: `CELL_CENTROID_POINTS_ONLY; SMALL_N; NO_INTERIOR_SAFETY_INFERENCE`.

These were arithmetic vertex centroids of the largest committed exact convex cell at the three selected timestamps. Existing Stage0 artifacts and source already contain earlier two-dimensional non-axis AC points (for example corrected Stage0 point 97 at P13=2000 kW, P30=500 kW under a different reference-PV context), so no "first off-skeleton in the whole project" claim is made.

## Provenance and unchanged scientific scope

`c18021d9b981f2629e54f60e8c2fc5f33b00c1a2` (`audit: finalize DOE preconstruction artifact analysis`)

-> `aaa6a745dd428c3efd267214337f6cb583489ed3` (`checkpoint: preserve DOE architecture audits`)

-> `29e20ac5115806738c47b587c795c422a1297eee` (`checkpoint: preserve VMAX pocket hulling audit`)

-> current runtime benchmark and reconciliation (`UNCOMMITTED`).

Architecture remains unchanged: `FULL EXACT CONVEX PARTITION = MAIN CANDIDATE`; `CONVEX-HULLED POCKET-DIFFERENCE = COMPACT FALLBACK`. The unresolved issue remains `INTER_RAY_EDGE_AND_ANGULAR_INTERIOR_AC_FEASIBILITY`.
