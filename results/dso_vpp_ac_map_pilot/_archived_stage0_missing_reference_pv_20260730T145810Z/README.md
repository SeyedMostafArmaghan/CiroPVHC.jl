# DSO-VPP sampled AC voltage-feasible injection map: Stage 0

This directory contains only the audit and 1,000-evaluation timing pilot.
The complete 96-interval map has not been launched.

## Scope and authority

- Boundary variables are direct active-power injections at buses 13 and 30.
- Positive values inject into the network; negative values consume from it.
- Controllable reactive power is zero at both VPP connection points.
- The primary calculation is the repository's exact radial backward/forward AC solve.
- Every point is separately replayed with `replay_s1b_interval` and its branch-flow residual audit.
- The voltage band is 0.90-1.05 p.u., root voltage is 1.00 p.u., base power is 10 MVA, and base voltage is 12.66 kV.
- Upstream exchange is unconstrained. No thermal or transformer limit is applied.

## Timestamp audit

- Interval count: 96; unique intervals: 96; missing intervals: 0.
- Window: 2012-10-15 00:00:00 through 2012-10-16 23:30:00.
- Interpretation: timezone-naive local wall-clock labels; no UTC conversion; fixed 48 source slots per local-data day; DST behavior inherited from Ausgrid source format.
- Load and PV factors are finite: true.

## Benchmark

- Wall time for 1000 evaluations: 2.961380 s.
- Per-point solve time: median 0.0003547 s, p90 0.00057106 s, maximum 0.0520471 s.
- Counts: FEASIBLE=266, INFEASIBLE_VOLTAGE=734, UNKNOWN_SOLVER=0.
- Peak process RSS: 696.070 MiB.
- Average CPU: 1.000 logical cores (8.33% of 12-core logical capacity).
- Linear estimate for 21,600 evaluations: 63.966 s; raw table 6.204 MiB.
- Linear estimate for 240,000 evaluations: 710.731 s; raw table 68.930 MiB.

The timing estimates are linear extrapolations from this Stage-0 sample and exclude plotting and adaptive-bound discovery.
No complete map or refinement was run. Explicit user approval is required before Stage 1.
