# S1-B full-period AC constraint-generation production report

## Outcome

- Terminal status: `converged`; reason: `converged`.
- Constraint-generation iterations: 2; final active-set size: 4.
- Installed PV: 10.680484846 MW total (bus 13 0.733640257, bus 20 4.681670271, bus 24 3.988773998, bus 30 1.276400319 MW).
- Clean-process full-period replay: passed; 52608 intervals, 0 replay failures, 0 voltage violations beyond 1.0e-5 p.u.
- **Replay failures: 0 of 52608 intervals.** Voltage violations beyond tolerance: 0. Trustworthy intervals used for the extrema below: 52608 of 52608; any untrustworthy interval is excluded from every extreme so a failed solve cannot masquerade as a limiting point.
- Limiting electrical constraint: maximum_voltage at bus 20, 2010-12-21 12:00:00; voltage 1.050000004762 p.u. against 1.05 p.u.; PV factor 1.000000000; load multiplier 0.192329740; upstream P -9463.779446 kW, Q 817.533683 kvar, apparent exchange 9499.025356 kVA.
- Voltage extrema: minimum 0.921746739695 p.u. at bus 18 on 2011-02-05 19:00:00; maximum 1.050000004762 p.u. at bus 20 on 2010-12-21 12:00:00.
- Upstream active exchange: maximum export 9469.200668 kW; maximum import 3471.437938 kW. Reactive extrema: 0.000000 to 2399.537836 kvar.
- Maximum bidirectional upstream apparent-power exchange: 9503.039211 kVA at 2010-12-21 12:30:00 (P -9469.200668 kW, Q 801.244621 kvar).
- Independent residual maxima: absolute 4.723805e-14; scaled 9.000457e-12.
- Final-iteration accepted-start dispersion: 0.000000000 kW across 14 accepted starts (10680.484846153 to 10680.484846153 kW).
- Recorded runtime: solver 2.230 s; production replay 13.468 s; clean verification replay 7.719 s.
- Checkpoint allocation match: true; active-set monotonicity: true; binding-point reproduction: true.

## Iteration evidence

The compact `iteration_summary.csv` records counts, additions, every start's seed/type/status/replay gate, allocations, voltage and residual extrema, upstream P/Q/apparent exchange, timings, checkpoint status, and terminal reason for every iteration. Detailed start and interval tables remain local under the ignored `checkpoints/` directory.

## Limitations

This is nonconvex local optimization and makes no global-optimality or proven-bound claim. It makes no transformer or line thermal-capacity claim because no defensible ratings are documented. Upstream exchange is unconstrained. Curtailment and site caps are absent. The robust extension remains unresolved.

## Verification

Focused and complete test-suite counts, committed files, and audit-readiness status are recorded after the post-production repository verification.
