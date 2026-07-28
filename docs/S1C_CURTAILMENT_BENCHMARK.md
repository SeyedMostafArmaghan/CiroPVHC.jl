# S1-C strict no-export curtailment benchmark

## Result

Under strict no-export, unity-power-factor PV operation, and the modeled
voltage constraints without validated thermal ratings, siting had a
non-material effect on annual-curtailment hosting capacity across the 11
screened single-bus and equal-share multi-bus configurations.

Every screened configuration satisfies

`r_i(810 kW) < 1% < r_i(850 kW)`.

Assuming annual curtailment is monotone over that interval, every 1%
annual-curtailment HC lies in `(810, 850) kW`. The resulting
monotonicity-based bracket bound on the set-level relative spread is

`40 / 810 × 100% = 4.938271605%`,

which is below the project's 5% materiality threshold.

## Descriptive estimates

Linear interpolation between each configuration's measured 810 and 850 kW
annual-curtailment values gives:

| Rank | Screened configuration | Estimated 1% HC (kW) |
|---:|:---|---:|
| 1 | `13+20+24+30` | 833.434562 |
| 2 | `24+30` | 834.782604 |
| 3 | `20+30` | 835.872559 |
| 4 | `13+24` | 836.065495 |
| 5 | `13+20` | 837.071342 |
| 6 | `13+30` | 837.281996 |
| 7 | `20+24` | 837.372855 |
| 8 | `24` | 838.355665 |
| 9 | `30` | 841.006778 |
| 10 | `20` | 842.238741 |
| 11 | `13` | 847.159545 |

The minimum is approximately 833.4346 kW, the maximum approximately
847.1595 kW, the mean approximately 838.2402 kW, and the relative spread
approximately 1.6374%.

These values are descriptive interpolation estimates. They are not exact
threshold solutions. The 4.9383% monotonicity-based bracket bound, rather than
the interpolated spread, is the formal decision basis.

## Zero-curtailment benchmark

The bus-13 zero-curtailment benchmark is 644.0430 kW in the screened-siting H0
table; the earlier dense bus-13 sweep begins at 644.0813217 kW. The small
difference reflects the separate search/reporting paths and their resolution.
Across all screened configurations, H0 ranges from 635.0586 to 644.0430 kW.
The binding mechanism is strict no-export at the PCC, not voltage.

The paper-level approximately 644.0813 kW value remains the bus-13
zero-curtailment benchmark from the dense sweep. It must not be confused with
the 1% annual-curtailment HC estimates.

## Scope

The evidence covers 52,608 half-hour intervals from three Ausgrid-derived
years and exactly 11 pre-specified configurations over candidate buses 13, 20,
24, and 30. Multi-bus configurations use equal PV sharing. PV operates at
unity power factor. The optimization enforces strict no-export and the modeled
0.90–1.05 p.u. voltage band. No validated transformer or branch thermal
ratings are imposed.

Within this screened set, all single-bus configurations rank above all
equal-share multi-bus configurations, and the four-bus equal-share
configuration ranks lowest. Higher electrical losses under strict no-export
are a physically plausible interpretation, not a universal theorem. The result
does not extend to arbitrary unequal allocations or global siting
optimization.

## Monotonicity and unresolved limitation

Annual curtailment increases at the sampled capacities H0, 810, 850, 975, and
1075 kW for every screened configuration. This empirically supports the
bracket assumption, but continuous monotonicity has not been mathematically
proved. The configuration-specific 1% crossing also has not been solved
directly. Therefore:

- the interpolated HC values remain descriptive;
- the common-bracket spread bound remains conditional on monotonicity; and
- the lack of a continuous-monotonicity proof must be carried forward as a
  methodological limitation.

## Relationship to the export-allowed result

The export-allowed AC study found a best stable AC-feasible local solution of
approximately 10.680484846 MW under modeled voltage constraints and
unconstrained upstream exchange. Because no defensible transformer or branch
thermal ratings were available, it is a voltage-only result with unconstrained
upstream exchange, not a complete thermal hosting-capacity result. The
available archived active-constraint evidence does not support a stronger
claim that voltage was necessarily the active limit.

Under strict no-export, hosting capacity instead behaves primarily as a PCC
power-balance quantity. Voltage constraints remain relevant to feasibility but
do not determine the approximately 644.0813 kW zero-curtailment benchmark.

## Paper decision and next stage

Siting variation in this restricted screen does not pass the 5% materiality
threshold. Within the paper's assumptions, further hosting-capacity
enhancement will therefore be studied through operational flexibility:
unmanaged EV charging, coordinated EV flexibility, BESS, and DOE/TVPP with
robust coordination. This is the selected mechanism within this paper, not a
claim that flexibility is the only possible enhancement mechanism in every
network.

## Audit trail

The compact tables are in `results/s1c_curtailment_benchmark/`.
`scripts/validate_s1c_curated.jl` independently recomputes their row counts,
brackets, interpolations, statistics, and checksums without running numerical
optimization. `docs/S1C_REPRODUCIBILITY.md` describes the execution
configuration and external evidence retention. The exact external artifact
sizes and SHA-256 values are in
`results/s1c_curtailment_benchmark/evidence_manifest.csv`.
