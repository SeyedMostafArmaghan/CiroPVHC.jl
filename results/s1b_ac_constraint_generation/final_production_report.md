# S1-B full-period AC constraint-generation production report

## Outcome

- Terminal status: `converged`; reason: `converged`.
- Constraint-generation iterations: 1; final active-set size: 3.
- Installed PV: 0.644081322 MW total (bus 13 0.644081322, bus 20 -0.000000000, bus 24 -0.000000000, bus 30 -0.000000000 MW).
- Separate full-period replay (the branch-flow forward/backward sweep in replay_s1b_interval, a different code path from the JuMP/Ipopt optimisation model but not an independent third-party AC solver): passed; 52608 intervals, 0 replay failures, 0 voltage violations beyond 1.0e-5 p.u.
- **Replay failures: 0 of 52608 intervals.** Voltage violations beyond tolerance: 0. Trustworthy intervals used for the extrema below: 52608 of 52608; any untrustworthy interval is excluded from every extreme so a failed solve cannot masquerade as a limiting point.
- **Export violations: 0 of 52608 intervals** (no-export active: true, tolerance 0.001 kW = 1.0e-7 p.u.). Intervals with upstream active power at the no-export bound: 7. Maximum upstream export observed: 9.999991879700021e-5 kW.
- Model traceability: a rebuilt one-interval model carries 1 no-export constraint row(s) on root branch(es) [1]; this is counted from the model object, not read from a configuration label.
- Binding summary: 1 interval is genuinely capacity-limiting; 6 further intervals are constraint-active but not capacity-limiting. The bare count of 7 constraint-active intervals is not reported without this split, because most of them cannot limit installed capacity.
  - capacity_limiting: gidx 40203, 2012-10-15 13:00:00, no_export constraint; PV factor 0.914956874, load multiplier 0.155940374. Raising installed capacity would violate this constraint here.
  - constraint_active only (6 intervals): sit exactly on the no-export bound with pv_factor <= 1.0e-6. In this run all such intervals are the DST-start transition slots (first Sunday of October, 02:00-02:30 local), where the source Ausgrid dataset records both load and PV as exactly zero, so no installed capacity can change their power flow. They do not limit hosting capacity.
- Capacity-limiting constraint: no_export at 2012-10-15 13:00:00; upstream P -9.999991880e-05 kW against the 0 kW bound; PV factor 0.914956874; load multiplier 0.155940374; Q 365.774042 kvar, apparent exchange 365.774042 kVA.
- Voltage extrema: minimum 0.918244838093 p.u. at bus 33 on 2011-02-05 18:00:00; maximum 1.014602378339 p.u. at bus 13 on 2012-12-05 13:00:00.
- Upstream active exchange: maximum export 0.000100 kW; maximum import 3803.922341 kW. Reactive extrema: 0.000000 to 2426.450566 kvar.
- Maximum bidirectional upstream apparent-power exchange: 4511.927252 kVA at 2011-02-05 18:00:00 (P 3803.922341 kW, Q 2426.450566 kvar).
- Separate-replay residual maxima: absolute 3.064216e-14; scaled 6.326422e-14.
- Final-iteration accepted-start dispersion: 3.837198894 kW across 13 accepted starts (640.244122803 to 644.081321697 kW).
- Recorded runtime: solver 1.487 s; production replay 4.354 s; separate full-period replay 5.417 s.
- Checkpoint allocation match: true; active-set monotonicity: true; binding-point reproduction: true.

## Iteration evidence

The compact `iteration_summary.csv` records counts, additions, every start's seed/type/status/replay gate, allocations, voltage and residual extrema, upstream P/Q/apparent exchange, timings, checkpoint status, and terminal reason for every iteration. Detailed start and interval tables remain local under the ignored `checkpoints/` directory.

## Limitations

This is nonconvex local optimization and makes no global-optimality or proven-bound claim. It makes no transformer or line thermal-capacity claim because no defensible ratings are documented. Upstream active export is prohibited: P_upstream >= 0 is enforced exactly in every interval, audited by the separate full-period replay at 0.001 kW. Curtailment and site caps are absent. The robust extension remains unresolved.

## Verification

Focused and complete test-suite counts, committed files, and audit-readiness status are recorded after the post-production repository verification.
