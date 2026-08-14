# Artifact-only componentwise voltage monotonicity falsification screen

## A. Repository provenance

- Branch: `codex/dso-vpp-ac-map-pilot`
- HEAD: `44cdad078b9503dfef6617c3585b99e7b014cdd9`
- Pre-analysis `git status --short`: clean.
- No AC power flow or production probe was run. This report was generated only from tracked artifacts.

## B. Production artifact(s) inspected

- Authoritative individual-evaluation cloud: `results/dso_vpp_ac_map_pilot/production_probe/evaluation_attempts.csv`.
- Signed normalization bounds: `signed_axis_results.csv`.
- Tier-1 centers: `center_results.csv`.
- Search/outcome context: `base_ray_results.csv`, `adaptive_ray_results.csv`, and `run_manifest.toml`.
- Completed checkpoint schema was inspected in code: completed segments retain attempt rows and scalar point summaries, not accepted-neighbor voltage vectors.

## C. Artifact schema and limitations

| requested per-evaluation field | stored? | exact artifact representation |
|---|---|---|
| timestamp | yes | `timestamp` |
| absolute P13 PCC | yes | `p13_abs_kw` |
| absolute P30 PCC | yes | `p30_abs_kw` |
| convergence status | yes | `primary_power_flow_status`, `replay_status`, and combined `solver_status` |
| feasibility status | yes | `solver_status` and `voltage_status` |
| Vmin / Vmax | yes | `vmin_pu`, `vmax_pu` |
| buses of Vmin / Vmax | yes | `vmin_bus`, `vmax_bus` |
| full all-bus voltage vector | no | omitted from CSV and completed checkpoint segment |
| search family/type | yes | `search_kind` |
| ray angle or signed axis direction | yes | exact `search_id` (`RAY` angle string or signed-axis name) |
| search/trajectory ID | yes | exact pair `(search_kind, search_id)` |
| retry metadata | yes | `attempt_index`, `initialization`, `initialization_source_logical_id` |
| mechanism | no direct field | conservatively derived only from stored `voltage_status`; official outcome mechanism exists in endpoint/result artifacts |
| coarse-sweep/bisection metadata | yes | `phase` |
| boundary/outcome metadata | no direct per-attempt field | stored separately in axis/ray/endpoint result artifacts |

Completed checkpoints retain attempt rows and scalar point summaries, not accepted-neighbor voltage vectors. The 73 `RAY_UNBOUNDED_WITHIN_GUARD` outcomes (`CERTIFIED_FEASIBLE_GUARD_TRUNCATION` in the post-production audit) contribute converged stored evaluations where available; they are safe observations and are not labeled as physical AC boundaries.
Mechanism below is conservatively derived from the stored `voltage_status`; no missing field is invented.
`FULL_BUS_MONOTONICITY_NOT_TESTABLE_FROM_STORED_ARTIFACTS`.
`CO_BINDING_NOT_RESOLVABLE_FROM_STORED_ARTIFACTS`.

## D. AC/model facts relevant to theorem applicability

- Radial, connected IEEE 33-bus topology (32 fixed branches), represented as a balanced single-phase equivalent.
- Exact radial AC backward/forward sweep with complex constant-PQ net demand (`conj(S/V)`); primary/replay convergence tolerances are 1e-11/1e-12 pu.
- Positive interface P is injection/export and is subtracted from bus demand at buses 13 and 30.
- Q13 PCC and Q30 PCC are fixed to zero (unity-power-factor interface policy); production explicitly disables reference PV (`reference_pv_capacity_kw=0.0`). Other reactive injections do not vary with P.
- Bus 1 is the ideal slack/root at fixed complex voltage 1+0j pu.
- Feasibility uses all-bus voltage magnitudes with the locked 0.90-1.05 pu band and zero feasibility-band tolerance; no thermal limit defines this probe.
- Bus active and reactive constant-power loads are both scaled by one canonical timestamp multiplier and remain fixed within a timestamp.
- The network data and probe path contain no tap changer, regulator, capacitor switching, or other discrete/state-dependent network control. Retry changes initialization only; independent flat-start replay must pass.
These are repository facts only, not a theorem or theorem-applicability conclusion.

## E. Usable evaluation population

- number_of_timestamps: 32
- total_stored_evaluations: 87,372
- converged_usable_evaluations: 87,086
- nonconverged_excluded: 286 ({'NONCONVERGED_AFTER_RETRY': 143, 'NONCONVERGED_FIRST_ATTEMPT': 143})
- duplicate_coordinates_detected: 2,114 excess rows in 448 coordinate groups (2,562 participating rows)
- duplicate_coordinates_deduplicated: 0. Distinct attempt/logical IDs and search provenance were preserved; equal-coordinate rows are separate recorded solver executions and both valid dominance directions are tested.

## F. Dominance/comparability statistics

- total_comparable_pairs: 51,682,917
- informative_comparable_pairs: 50,641,519
- same_trajectory_comparable_pairs: 1,041,398
- cross_trajectory_comparable_pairs: 50,641,519
Trajectory identity is the exact stored `(search_kind, search_id)` pair; no approximate-angle inference is used.

The implementation is a deterministic timestamp-local P13 sweep with vectorized P30 filters. The pre-run upper bound was 118,458,772 candidate unordered pairs, expected runtime was tens of seconds, expected RAM was below 256 MB, and parallelization was not used.

## G. Near-center comparability statistics

- informative_comparable_pairs: 17,089,194
- scalar_Vmin_violations: 0
- scalar_Vmax_violations: 0
- logical_VMIN_violations: 0
- logical_VMAX_violations: 0

## H. Farther/straddling comparability statistics

### STRADDLING

- informative_comparable_pairs: 22,673,415
- scalar_Vmin_violations: 0
- scalar_Vmax_violations: 0
- logical_VMIN_violations: 0
- logical_VMAX_violations: 0

### BOTH_FARTHER

- informative_comparable_pairs: 10,878,910
- scalar_Vmin_violations: 0
- scalar_Vmax_violations: 0
- logical_VMIN_violations: 0
- logical_VMAX_violations: 0

## I. Scalar Vmin monotonicity screen

The primary numerical threshold is the pre-existing production replay voltage-state agreement tolerance, 2e-05 pu, defined at `src/benchmark/dso_vpp_ac_map_stage0.jl:21` and locked as `replay_voltage_agreement_pu` in the preregistration TOML.
- classified violations (Delta Vmin < -2e-5 pu): 0
- negative Delta Vmin beyond 0e+00 pu: 0
- negative Delta Vmin beyond 1e-07 pu: 0
- negative Delta Vmin beyond 1e-06 pu: 0
- negative Delta Vmin beyond 1e-05 pu: 0

## J. Scalar Vmax monotonicity screen

- classified violations (Delta Vmax < -2e-5 pu): 0
- negative Delta Vmax beyond 0e+00 pu: 0
- negative Delta Vmax beyond 1e-07 pu: 0
- negative Delta Vmax beyond 1e-06 pu: 0
- negative Delta Vmax beyond 1e-05 pu: 0

## K. Logical VMIN/VMAX contradiction screen

- logical VMIN contradictions: 0
- logical VMAX contradictions: 0
Only converged feasible/infeasible rows participate; nonconvergence is never treated as infeasibility.

## L. Worst counterexamples, if any

- SCALAR_VMIN: 0 rows in `worst_scalar_vmin.csv`.
- SCALAR_VMAX: 0 rows in `worst_scalar_vmax.csv`.
- LOGICAL_VMIN: 0 rows in `worst_logical_vmin.csv`.
- LOGICAL_VMAX: 0 rows in `worst_logical_vmax.csv`.
No tolerance-classified or logical counterexample exists, so all four files contain headers only.

## M. Timestamp-by-timestamp table

| timestamp | usable_points | total_comparable_pairs | cross_trajectory_comparable_pairs | scalar_Vmin_violations | scalar_Vmax_violations | logical_VMIN_violations | logical_VMAX_violations |
|---|---:|---:|---:|---:|---:|---:|---:|
| 2010-07-01 07:30:00 | 2709 | 1616293 | 1583566 | 0 | 0 | 0 | 0 |
| 2010-07-02 17:30:00 | 2717 | 1619793 | 1587270 | 0 | 0 | 0 | 0 |
| 2010-07-02 18:00:00 | 2725 | 1624928 | 1592307 | 0 | 0 | 0 | 0 |
| 2010-07-03 00:00:00 | 2723 | 1608256 | 1575587 | 0 | 0 | 0 | 0 |
| 2010-11-26 18:00:00 | 2729 | 1616944 | 1584017 | 0 | 0 | 0 | 0 |
| 2010-12-21 11:30:00 | 2724 | 1603139 | 1570818 | 0 | 0 | 0 | 0 |
| 2010-12-21 12:00:00 | 2713 | 1594556 | 1562389 | 0 | 0 | 0 | 0 |
| 2011-01-21 18:00:00 | 2728 | 1615416 | 1582685 | 0 | 0 | 0 | 0 |
| 2011-02-05 11:30:00 | 2727 | 1629845 | 1597224 | 0 | 0 | 0 | 0 |
| 2011-02-05 17:30:00 | 2766 | 1712946 | 1679414 | 0 | 0 | 0 | 0 |
| 2011-02-05 18:00:00 | 2763 | 1710000 | 1676552 | 0 | 0 | 0 | 0 |
| 2011-02-06 00:00:00 | 2710 | 1617820 | 1585096 | 0 | 0 | 0 | 0 |
| 2011-03-04 18:00:00 | 2729 | 1615484 | 1582711 | 0 | 0 | 0 | 0 |
| 2011-03-08 11:30:00 | 2716 | 1598911 | 1566643 | 0 | 0 | 0 | 0 |
| 2011-03-08 12:30:00 | 2722 | 1603208 | 1570887 | 0 | 0 | 0 | 0 |
| 2011-05-11 17:30:00 | 2720 | 1619962 | 1587340 | 0 | 0 | 0 | 0 |
| 2011-05-11 18:00:00 | 2725 | 1625437 | 1592768 | 0 | 0 | 0 | 0 |
| 2011-05-16 07:30:00 | 2730 | 1621023 | 1588194 | 0 | 0 | 0 | 0 |
| 2011-09-11 00:00:00 | 2714 | 1593816 | 1561688 | 0 | 0 | 0 | 0 |
| 2011-09-30 05:30:00 | 2708 | 1595317 | 1563099 | 0 | 0 | 0 | 0 |
| 2011-09-30 11:30:00 | 2714 | 1594128 | 1562061 | 0 | 0 | 0 | 0 |
| 2011-11-14 17:30:00 | 2719 | 1620389 | 1587823 | 0 | 0 | 0 | 0 |
| 2011-11-14 19:30:00 | 2722 | 1621720 | 1588985 | 0 | 0 | 0 | 0 |
| 2011-12-15 05:30:00 | 2710 | 1597970 | 1565700 | 0 | 0 | 0 | 0 |
| 2012-08-04 03:30:00 | 2708 | 1594533 | 1562366 | 0 | 0 | 0 | 0 |
| 2012-08-05 23:30:00 | 2714 | 1595940 | 1563721 | 0 | 0 | 0 | 0 |
| 2012-08-24 12:00:00 | 2719 | 1600847 | 1568526 | 0 | 0 | 0 | 0 |
| 2012-08-31 11:30:00 | 2712 | 1593725 | 1561556 | 0 | 0 | 0 | 0 |
| 2012-09-03 07:00:00 | 2722 | 1608557 | 1575924 | 0 | 0 | 0 | 0 |
| 2012-10-15 13:00:00 | 2711 | 1598902 | 1566586 | 0 | 0 | 0 | 0 |
| 2013-04-07 02:00:00 | 2729 | 1614925 | 1582096 | 0 | 0 | 0 | 0 |
| 2013-04-17 05:30:00 | 2708 | 1598187 | 1565920 | 0 | 0 | 0 | 0 |

## N. Final classification

`NO_MONOTONICITY_COUNTEREXAMPLE_OBSERVED_IN_STORED_EVALUATIONS`

informative_comparable_pairs = 50641519

This is a finite-sample falsification result, not a proof, confirmation, or certification of monotonicity.
The authoritative production classification remains `POSTPRODUCTION_RESULT_AUDIT_COMPLETE_WITH_DOCUMENTED_LIMITATIONS`.

## O. Implications for DOE Construction Policy

The stored evidence supports continuing investigation of a monotonicity-based box certification, conditional on a later theorem/applicability review. The near/far decomposition quantifies whether a local claim appears more plausible than a global one. No DOE architecture is selected here.

Artifact-only runtime: 22.898 s; parallelization: none.
