# S1-B large-file preflight and constraint-generation control audit

## Large-file finding

The GitHub warning was triggered by the tracked file `results/s0_full_period_baseline/s0_interval_metrics.csv`: 72,882,880 bytes (69.5065 MiB) and 157,825 lines including its header. It is generated interval-level output, not source data. Commit `133c7b08505b50e664f108c816c81d59a9098329` (`Add S0 full-period baseline results`, 2026-07-21) introduced it.

The table is reproducible. `scripts/run_s0_full_period_baseline.jl` invokes the streamed writers in `src/validation/s0_baseline.jl`; `results/s0_full_period_baseline/s0_metadata.json` records 52,608 input half-hours, three root-voltage cases, and the normalized Ausgrid input SHA-256. The required normalized input remains tracked at `data_processed/ausgrid/ausgrid_halfhour_normalized.csv`. Future three-year iteration/replay tables can be similar or larger, so detailed constraint-generation checkpoints and solver scratch are now narrowly ignored. The existing large file was not deleted, edited, moved, or migrated to LFS.

## Equation and control-flow mapping

The central nonlinear model uses one nonnegative vector `(C13, C20, C24, C30)` for every active interval. For each branch and interval it enforces the branch-flow voltage drop and exact current equality `P^2 + Q^2 = v * ell`; nodal balances use recorded load multiplier and PV availability. Voltage is bounded by `0.90^2 <= v <= 1.05^2`. No curtailment, no-export rule, site cap, thermal limit, transformer limit, or computational capacity cap is present.

Direction construction is deterministic, nonnegative, normalized, and validated before boundary search. Boundary search begins from a replay-confirmed zero-PV point, doubles until it has a feasible/infeasible bracket, and bisects without swapping endpoints or returning the infeasible endpoint. Exact-zero and near-zero direction components are accepted safely; all-zero, negative, nonfinite, incorrectly sized, or incorrectly normalized vectors are rejected.

Each multistart value is applied only through JuMP start values; installed-capacity variables remain free. Every candidate selected as best must have local-solve termination, a finite kW objective, and a passed independent complex backward-forward-sweep replay. Objectives and capacity allocations remain in kW; MW is presentation-only. The active set is updated by sorted set union, so a newly added interval cannot remove an earlier interval. Full-validation replay failures rank ahead of finite voltage excesses, followed by decreasing excess and then increasing global interval index.

## Corrected bugs

1. A start initialization, solver, or diagnostic exception previously aborted the remaining multistart search. It is now recorded as `INITIALIZATION_FAILED`, `SOLVER_ERROR`, or `DIAGNOSTICS_ERROR`, rejected, and the search continues.
2. Best-result selection previously trusted `accepted` alone. It now independently requires a local-solve status, a finite objective, and the independent-replay-passed flag.
3. Direction boundary feasibility previously checked voltage feasibility without explicitly requiring the complete replay gate. It now requires both exact zero-tolerance voltage feasibility and the independent replay gate.

## Accepted foundation and limitations

The accepted one-day evidence remains a best stable AC-feasible local solution of 10.680484846 MW with 13/13 starts independently replayed and accepted. This is a **nonconvex branch-flow AC model for a balanced radial feeder** and is labeled **voltage-only hosting capacity with unconstrained upstream exchange.** It is not a global optimum, proven upper bound, full AC-OPF certificate, or thermal hosting capacity.

No defensible transformer/substation rating exists. No central `S_tr` constraint was introduced. A synthetic bidirectional transformer apparent-power limit remains deferred to an explicitly labeled sensitivity study.

Before a production run, the compact smoke report and iteration summary must show that the selected high-load and low-load/high-PV subset exercised replay/ranking and terminated as documented. Production remains local-solver evidence; its accepted objective may move non-monotonically as intervals are added. Full 52,608-interval replay was not performed in this task.

## Smoke and resume result

The deterministic smoke set contained 144 half-hours on 2010-12-21, the high-load day 2011-02-05, and the low-load/high-PV day 2012-10-15. Iteration 1 used 3 active points, accepted 13/13 starts at approximately 10,697.020591 kW, found one replay violation with 0.0003493273 p.u. excess, and added global interval 8330. Iteration 2 used 4 active points, accepted 14/14 starts (including the prior active-set warm start) at approximately 10,680.484846 kW, replayed all 144 intervals without failure or violation, and terminated `converged`.

All individual status/objective tuples are in the committed `iteration_summary.csv`. The focused interruption test produced the same active set, capacities, iteration history, and terminal status after resume as an uninterrupted run. The completed real smoke checkpoint was also reopened without re-solving to verify terminal-state resume.
