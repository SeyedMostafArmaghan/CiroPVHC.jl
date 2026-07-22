# S1-B AC constraint-generation smoke report

- Classification: nonconvex branch-flow AC model for a balanced radial feeder.
- Result label: **voltage-only hosting capacity with unconstrained upstream exchange.**
- Global optimum claimed: no.
- Transformer or thermal hosting capacity claimed: no; no defensible substation rating is available.
- Validation scope: 144 half-hour intervals on 2010-12-21, 2011-02-05, 2012-10-15.
- High-load day: 2011-02-05; low-load/high-PV day: 2012-10-15.
- Deterministic seed intervals: 8329=2010-12-21T12:00:00, 10549=2011-02-05T18:00:00, 40203=2012-10-15T13:00:00.
- Full 52,608-interval validation performed: no.
- Terminal status: `converged`.
- Completed iterations: 2.
- Final active interval count: 4.
- Resumed from the persisted checkpoint: yes.

All start statuses, acceptance flags, and objectives are retained in `iteration_summary.csv`; detailed per-start and per-interval evidence is retained in the ignored `checkpoints/` directory.
