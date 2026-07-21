# S0 full-period baseline validation

## Scope

This report covers the zero-DER IEEE 33-bus baseline for every half-hour interval in the processed three-year Ausgrid load profile. PV, EV, BESS, DOE, curtailment, export policy, loss caps, thermal ratings, transformer ratings, and hosting-capacity decisions are absent.

Ausgrid supplies only the normalized temporal load multiplier. The original case33bw active and reactive bus loads remain the absolute values and are multiplied by the same interval multiplier.

## Coverage and method

- Input intervals: 52608
- Date range: 2010-07-01 00:00:00 to 2013-06-30 23:30:00
- Time step: 0.5 h
- Root voltages: 1.00, 1.03, and 1.05 p.u.; the model equality is `v[root] = V0^2`.
- SOCP strategy: reusable one-interval Clarabel models, partitioned deterministically across 4 Julia threads and streamed in 512-interval chunks.
- Operational voltage limits: 0.95–1.05 p.u. An interval infeasible under the hard band is solved again with diagnostic numerical bounds so the violating buses are recorded rather than silently skipped.
- SOCP objective: minimize modeled active losses; no loss cap is present.
- AC validation: independent nonlinear radial backward-forward sweep on four required critical selections per root-voltage case.

## Results

| V0 (p.u.) | Solved | Failed | Diagnostic fallbacks | Violation intervals | Vmin (p.u.) | Vmax (p.u.) | Peak branch / current (A) | Peak substation (kVA) | Max loss (kW) | Avg loss (%) | Max SOC gap | Fully validated |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|:---:|
| 1.00 | 52608 | 0 | 358 | 336 | 0.913090479 | 1.000000000 | 1 / 210.364352 | 4612.819703 | 202.677127 | 1.168841 | 2.278e-08 | no |
| 1.03 | 52608 | 0 | 29 | 5 | 0.946034954 | 1.030000000 | 1 / 203.527415 | 4596.787980 | 189.339473 | 1.099391 | 9.844e-08 | no |
| 1.05 | 52608 | 0 | 16 | 0 | 0.967881228 | 1.050000000 | 1 / 199.225796 | 4587.004887 | 181.199837 | 1.056513 | 7.225e-08 | no |

## Interpretation

The V0=1.03 p.u. case is **not** fully feasible over the complete three-year period under the stated 0.95–1.05 p.u. voltage criterion. See `s0_voltage_violations.csv` for the exact bus-time records.

All selected SOCP critical records passed the independent AC comparison tolerances.

Peak currents are baseline reference quantities derived from per-unit `ell` using the verified three-phase base-current formula. They are not real or final IEEE 33-bus ampacity ratings. Likewise, peak substation apparent power is a baseline reference, not a documented transformer rating.

No `κ_I` or `κ_tr` planning multiplier is selected here.

## Runtime

Total runtime: 898.669 s. Case solve runtimes: 265.809, 264.629, 268.849 s.
