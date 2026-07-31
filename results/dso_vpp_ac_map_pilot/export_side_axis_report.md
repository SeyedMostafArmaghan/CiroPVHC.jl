# Export-side AC axis scan

- Computation base commit: `ae24e08180cf154c3c49b136d5babc5f190b6a0c` (Phase-A repair).
- Implementation: `CiroPVHC.DSOVPPExportSideAxisScan.radial_bfs.v1`.
- Command: `julia --project=. scripts/run_dso_vpp_export_side_axis_scan.jl --overwrite`.
- Canonical window: 2012-10-15 00:00:00 through 2012-10-16 23:30:00.
- Fixed reference PV: H = 850.0 kW at bus 13, P_PV(t)=H*f_t; all PV/VPP reactive commands are zero.
- Voltage limits: 0.9-1.05 p.u.; no thermal or transformer limit; upstream exchange unconstrained.
- Binding sets use two separate rules with tau_bind=1.0e-5 p.u.: distance from the observed maximum, and absolute distance from the 1.05-p.u. upper limit.

## Algorithm

Baseline is evaluated first. Positive commands begin at 58.046875 kW (total canonical nominal active load / 64), double up to 12 times, and refine only a safe-to-upper-voltage bracket. Refinement stops when width <= 1.0 kW and both endpoint voltage distances <= 1.0e-5 p.u. Nonconvergence is unresolved, never physical infeasibility. Every point receives an independent replay.

## Results

- Capacity rows: 192; scan evaluations: 3691; valid refined bounds: 192.
- Measured wall time (excluded from scientific reproducibility): 15.349860 s.
- P13_VPP: minimum safe endpoint 681.370544434 kW at 2012-10-15 13:00:00; safe/violating maximum sets `13`/`13`.
- P30_VPP: minimum safe endpoint 1739.59228516 kW at 2012-10-15 13:00:00; safe/violating maximum sets `30`/`30`.

These are one-axis-at-a-time bounds. Their Cartesian product is not a certified simultaneous feasible region, not a DOE, and not a two-dimensional map. No LinDistFlow model is implemented here.
