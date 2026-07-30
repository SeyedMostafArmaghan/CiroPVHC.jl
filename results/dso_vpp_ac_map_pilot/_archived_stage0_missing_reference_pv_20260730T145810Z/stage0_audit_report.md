# Stage-0 DSO–VPP AC-map audit

## 1. Repository and Git state

The audit was performed read-only with respect to every pre-existing file.

- Repository: `D:\CiroPVHC.jl`
- Branch before audit: `codex/dso-vpp-ac-map-pilot`
- HEAD before audit: `13f22d0e48e950ccf8a127bb3c97f891c2512e19`
- Branch and HEAD after packaging: unchanged.

`git status --short` before the audit was:

```text
 M results/s1b_ac_constraint_generation_smoke/iteration_summary.csv
 M results/s1b_ac_constraint_generation_smoke/smoke_report.md
 M test/runtests.jl
?? results/_archived_s1b_export_allowed_run_20260722/
?? results/_archived_s1b_no_export_checkpoints_20260723_173925/
?? results/_archived_s1b_prefix_run_20260722/
?? results/baseline_feasibility_summary.txt
?? results/baseline_load_voltage_sensitivity.csv
?? results/baseline_voltage_band/
?? results/dso_vpp_ac_map_pilot/
?? results/minimal_s1_snapshot_gamma_sensitivity.csv
?? results/minimal_s1_snapshot_summary.txt
?? results/pv_candidate_bus_screening.csv
?? results/pv_candidate_bus_screening_summary.txt
?? results/pv_candidate_bus_selection.csv
?? results/pv_candidate_bus_selection_summary.txt
?? results/pv_candidate_interactions.csv
?? results/pv_candidate_interactions_summary.txt
?? results/pv_site_capacity_policy.csv
?? results/pv_site_capacity_policy_summary.txt
?? scripts/analyze_baseline_feasibility.jl
?? scripts/analyze_pv_candidate_buses.jl
?? scripts/analyze_pv_candidate_interactions.jl
?? scripts/analyze_pv_site_capacity_policy.jl
?? scripts/baseline_voltage_band_evidence.jl
?? scripts/run_dso_vpp_ac_map_stage0.jl
?? scripts/run_minimal_s1_snapshot.jl
?? scripts/select_pv_candidate_buses.jl
?? src/benchmark/dso_vpp_ac_map_stage0.jl
?? test/test_dso_vpp_ac_map_stage0.jl
```

The same command after packaging has the same concise output because the allowed audit artifacts were added inside the already-untracked `results/dso_vpp_ac_map_pilot/` directory. No file was staged, committed, deleted, renamed, or overwritten.

## 2. Exact files inspected

Required evidence:

- `scripts/run_dso_vpp_ac_map_stage0.jl`
- `src/benchmark/dso_vpp_ac_map_stage0.jl`
- `results/dso_vpp_ac_map_pilot/stage0_data_audit.csv`
- `results/dso_vpp_ac_map_pilot/stage0_benchmark_points.csv`

Supporting evidence:

- `results/dso_vpp_ac_map_pilot/timing_benchmark.csv`
- `results/dso_vpp_ac_map_pilot/README.md`
- `src/benchmark/s1b_method_benchmark.jl`
- `src/solve/solve_s1b_central.jl`
- `src/validation/s1b_independent_replay.jl`
- `src/validation/s0_unconstrained.jl`
- `src/data/ieee33.jl`
- `src/data/types.jl`
- `src/CiroPVHC.jl`
- `scripts/prepare_ausgrid_profiles.py`
- `data_processed/ausgrid/ausgrid_halfhour_normalized.csv`

All four required evidence files existed before the audit. The Stage-0 evidence directory itself was already untracked; the original files were inspected and packaged byte-for-byte without regeneration.

## 3. Stage-0 call graph

The complete primary path is:

1. `main()` includes the Stage-0 module and invokes `run_stage0(repository_root)` (`scripts/run_dso_vpp_ac_map_stage0.jl:1-12`).
2. `run_stage0` calls `load_profile`, `select_pilot_indices`, `build_pilot_network`, and `evaluate_benchmark` (`src/benchmark/dso_vpp_ac_map_stage0.jl:590-602`).
3. `evaluate_benchmark` constructs the sample plan, performs one untimed warm-up, and then calls `evaluate_point` for each point (`src/benchmark/dso_vpp_ac_map_stage0.jl:419-459`).
4. `evaluate_point` calls `primary_power_flow` with the interval load multiplier and fixed `P13`/`P30` injections (`src/benchmark/dso_vpp_ac_map_stage0.jl:228-246`).
5. `primary_power_flow` constructs fixed complex net demand, then repeatedly calls `_s0_unconstrained_branch_currents` and `_s0_unconstrained_forward_voltage` (`src/benchmark/dso_vpp_ac_map_stage0.jl:86-148`).
6. `_s0_unconstrained_branch_currents` performs the backward current accumulation, and `_s0_unconstrained_forward_voltage` applies the radial voltage drops (`src/validation/s0_unconstrained.jl:99-135`).

The independent validation path starts inside `evaluate_point`: it calls `replay_s1b_interval` with the same load multiplier, a hard-coded availability of `1.0`, and capacities equal to the sampled `P13` and `P30` values (`src/benchmark/dso_vpp_ac_map_stage0.jl:247-263`). The replay independently repeats a flat-start current-injection backward/forward sweep and audits exact branch-flow residuals (`src/validation/s1b_independent_replay.jl:134-222,224-330`).

The canonical profile path is `load_profile` → `CiroPVHC.read_s1b_profile` → `_read_s1b_profile` (`src/benchmark/dso_vpp_ac_map_stage0.jl:33-41`; `src/CiroPVHC.jl:258-261`; `src/solve/solve_s1b_central.jl:45-96`).

Neither `src/benchmark/s1b_method_benchmark.jl` nor the central JuMP model-building path in `src/solve/solve_s1b_central.jl` is called by Stage 0.

## 4. Evaluator type: deterministic PF or OPF

**Conclusion: each point is a deterministic fixed-injection AC power flow, followed by an independent deterministic replay. It is not an OPF, feasibility NLP, or optimization model.**

There are no free operational decision variables and no objective function. The numerical state iterates are complex bus-voltage phasors and branch currents; these are power-flow unknowns, not optimized controls. Fixed inputs are the IEEE-33 bus/branch data, 10 MVA base, 1.00 p.u. root phasor, the interval load multiplier, fixed active injections at buses 13 and 30, and zero VPP reactive injection (`src/benchmark/dso_vpp_ac_map_stage0.jl:67-83,86-119,228-263,280-283`).

The solved equalities are:

\[
S_i^{d,\mathrm{pu}}
=\frac{(P_i^d m-P_i^{VPP})+jQ_i^d m}{10{,}000\ \mathrm{kW}},
\qquad
I_i=\overline{S_i^d/V_i},
\]

\[
I_{ij}=I_j+\sum_{j\to k}I_{jk},
\qquad
V_j=V_i-z_{ij}I_{ij},
\qquad
V_1=1+j0.
\]

These are implemented at `src/benchmark/dso_vpp_ac_map_stage0.jl:104-119,123-147` and `src/validation/s0_unconstrained.jl:99-135`. There are no solver-enforced inequality constraints. The 0.90–1.05 p.u. voltage band is checked only after both calculations converge and match; branch ratings are required to be zero/missing and no thermal or transformer bound is applied (`src/benchmark/dso_vpp_ac_map_stage0.jl:9-11,79-83,264-271`).

The “solver” is the repository’s custom damped radial backward/forward sweep, with damping `0.70`, primary update tolerance `1e-11` p.u. and 2,000-iteration limit, followed by a flat-start replay with tolerance `1e-12` p.u. and 4,000-iteration limit (`src/benchmark/dso_vpp_ac_map_stage0.jl:14-20,86-95,123-148,248-263`). No Ipopt, Clarabel, or other optimization solver is on this call path.

Primary termination is `CONVERGED` only when the undamped fixed-point update is at most the primary tolerance. Otherwise the point is `UNKNOWN_SOLVER`. A converged replay must also be phasor-recoverable, meet absolute and scaled residual tolerances, and match primary voltage and substation active power; otherwise it is also `UNKNOWN_SOLVER` (`src/benchmark/dso_vpp_ac_map_stage0.jl:143-166,212-225,264-270,285-303`). All 1,000 recorded points are primary-converged and replay-passed (`results/dso_vpp_ac_map_pilot/timing_benchmark.csv:2`).

Warm starts feed only the primary voltage iteration. The replay always starts flat (`src/benchmark/dso_vpp_ac_map_stage0.jl:91-119,239-263`; `src/validation/s1b_independent_replay.jl:184-222`). A warm start can alter runtime and numerical convergence. Nonlinear PF equations can in general have multiple roots, so code inspection alone does not prove mathematical uniqueness; however, any primary state differing beyond the explicit voltage/substation tolerances from the flat replay becomes `STATE_MISMATCH` and cannot receive a voltage-feasibility label (`src/benchmark/dso_vpp_ac_map_stage0.jl:212-225,264-270`). Thus reported `FEASIBLE`/`INFEASIBLE_VOLTAGE` voltages are anchored to the order-independent flat replay. In a pathological case, traversal could still change whether the warm-started primary converges and therefore change a label to `UNKNOWN_SOLVER`; no such status appears in the existing data.

`INFEASIBLE_VOLTAGE` is technically meaningful only as “the converged, replay-validated fixed-injection operating point violates the declared voltage band.” It is not proof that the AC equations have no solution and is not global optimization infeasibility. Numerical nonconvergence is separately labeled `UNKNOWN_SOLVER` (`src/benchmark/dso_vpp_ac_map_stage0.jl:264-271`); a less ambiguous label would be `VOLTAGE_VIOLATION`.

## 5. Exact AC formulation and branch-flow convention

The primary implementation is an exact radial complex-phasor current-injection backward/forward sweep. Voltages are rectangular complex phasors \(V=e+jf\); it is neither a polar nodal formulation nor a branch-flow optimization model (`src/validation/s0_unconstrained.jl:99-135`; `src/benchmark/dso_vpp_ac_map_stage0.jl:114-147`).

For later decomposition, the replay’s branch quantities use these exact conventions:

- \(I_{ij}\) points from the rooted parent \(i\) to child \(j\), constructed by accumulating downstream positive-demand currents (`src/validation/s1b_independent_replay.jl:164-181,184-209,224-237`).
- \(S_{ij}=P_{ij}+jQ_{ij}=V_i\overline{I_{ij}}\) is **sending-end** power (`src/validation/s1b_independent_replay.jl:239-247`).
- \(\ell_{ij}=|I_{ij}|^2\), \(v_i=|V_i|^2\), and \(v_i\) is the **sending-end squared voltage** (`src/validation/s1b_independent_replay.jl:239-247,277-286`).
- Receiving-end power is \(S_{ij}^{recv}=S_{ij}-z_{ij}\ell_{ij}\).
- Losses enter before the downstream load/child-flow balance:

\[
P_{ij}-r_{ij}\ell_{ij}=p_j+\sum_{j\to k}P_{jk},
\qquad
Q_{ij}-x_{ij}\ell_{ij}=q_j+\sum_{j\to k}Q_{jk}.
\]

This is audited directly at `src/validation/s1b_independent_replay.jl:249-271`.

- The exact voltage equation is

\[
v_j=v_i-2(r_{ij}P_{ij}+x_{ij}Q_{ij})
       +(r_{ij}^2+x_{ij}^2)\ell_{ij},
\]

and the exact current equality is

\[
\ell_{ij}v_i=P_{ij}^2+Q_{ij}^2.
\]

Both use sending-end \(P,Q,v_i\) and are audited at `src/validation/s1b_independent_replay.jl:274-305`.

- Branch active and reactive losses are \(r_{ij}\ell_{ij}\) and \(x_{ij}\ell_{ij}\) in per unit, multiplied by 10,000 kW/kvar for reported totals (`src/validation/s1b_independent_replay.jl:317-321`). The primary reconstructs the same sending-end power and \(z|I|^2\) losses (`src/benchmark/dso_vpp_ac_map_stage0.jl:181-207`).

This convention must not be mixed with receiving-end flow in a later linear-voltage decomposition.

## 6. Time window and profile-reader behavior

The actual Stage-0 window is exactly:

- first timestamp: `2012-10-15 00:00:00`
- last timestamp: `2012-10-16 23:30:00`
- intervals: 96
- duration: 30 minutes
- calendar dates: `2012-10-15`, `2012-10-16`
- unique intervals: 96
- missing/non-half-hour intervals: 0
- duplicate intervals: 0

These facts are enforced by the runner (`src/benchmark/dso_vpp_ac_map_stage0.jl:7-8,43-64`) and recorded from the CSV at `results/dso_vpp_ac_map_pilot/stage0_data_audit.csv:2`.

Timestamps are timezone-naive `DateTime` values parsed from `yyyy-mm-dd HH:MM:SS`; no timezone or UTC conversion is performed (`src/solve/solve_s1b_central.jl:14-20,45-80`). The source preparation builds exactly 48 local labels per parsed source date by adding `30*slot` minutes and later identifies a complete day as slots 0–47 (`scripts/prepare_ausgrid_profiles.py:106-119,122-157,318-329`). There is no explicit DST disambiguation or missing/repeated-hour policy. Stage 0 therefore inherits naive local wall-clock source labels and requires 48 records per selected date; DST is not represented as timezone-aware elapsed time (`src/benchmark/dso_vpp_ac_map_stage0.jl:45-63,465-487`).

The canonical reader maps each CSV row’s `datetime`, `load_multiplier`, and `pv_profile` fields into parallel vectors at the same index, checks uniqueness, sorting, and 30-minute spacing, and records the source hash (`src/solve/solve_s1b_central.jl:45-96`). Source preparation normalizes aggregate load and PV shapes by their respective global maxima (`scripts/prepare_ausgrid_profiles.py:277-322`). Stage 0 selects indices by calendar date and passes the indexed load factor to the evaluator, but it does **not** pass the indexed PV factor (`src/benchmark/dso_vpp_ac_map_stage0.jl:43-64,239-263`).

The five largest PV factors, read through that canonical reader, are:

| timestamp | pv_factor | load_factor |
|---|---:|---:|
| 2012-10-15 12:30:00 | 0.9282211452522351 | 0.16840754554067183 |
| 2012-10-15 12:00:00 | 0.9269950294058865 | 0.17540383992708716 |
| 2012-10-15 13:00:00 | 0.9149568739021162 | 0.15594037439888725 |
| 2012-10-15 11:30:00 | 0.9107599944168605 | 0.17430294890090783 |
| 2012-10-15 13:30:00 | 0.8875029793258973 | 0.15483228800652382 |

## 7. Active- and reactive-power sign conventions

- Positive `P13_VPP` and `P30_VPP` are injection/export into the feeder; negative values add consumption. They are subtracted from positive demand (`src/benchmark/dso_vpp_ac_map_stage0.jl:104-111`).
- Bus `pd_kw` and `qd_kvar` are positive consumption. The IEEE-33 values are stored in kW and kvar (`src/data/types.jl:1-6`; `src/data/ieee33.jl:4-38`).
- PV generation is positive and is subtracted from demand. Replay defines \(P^{PV}=Hf\) and unity power factor (`src/validation/s1b_independent_replay.jl:126-132,167-174`).
- Positive `P_sub` and `Q_sub` are downstream import/supply from the ideal root. Negative `P_sub` is upstream export (`src/validation/s1b_independent_replay.jl:126-132,317-321`).
- Positive branch \(P_{ij},Q_{ij}\) are sending-end flows from parent to child, normally serving downstream demand; negative active flow is upstream export (`src/validation/s1b_independent_replay.jl:239-271`).

Both active and reactive bus loads are multiplied by the same interval load multiplier (`src/benchmark/dso_vpp_ac_map_stage0.jl:104-111`; `src/validation/s1b_independent_replay.jl:167-174`). Therefore each nonzero-load bus preserves its case33bw \(P/Q\) ratio and power factor. PV/VPP injection has no reactive component: the primary net-demand imaginary part contains load only, and output explicitly records both VPP Q values as zero (`src/benchmark/dso_vpp_ac_map_stage0.jl:104-111,280-283`). The replay also treats PV as unity-power-factor active injection (`src/validation/s1b_independent_replay.jl:126-132,167-174`).

Slack-bus active and reactive exchange are unconstrained outputs of the ideal 1.00 p.u. source, not controls with bounds (`src/benchmark/dso_vpp_ac_map_stage0.jl:114-119,189-207`). The Stage-0 network contains only `Bus` load/base-voltage fields and series `Branch` impedance/rating fields; no capacitor, shunt, tap, Volt–VAr, inverter-Q, or other reactive-control object is constructed or used (`src/data/types.jl:1-15`; `src/benchmark/dso_vpp_ac_map_stage0.jl:67-83,104-112`).

Internally voltage, impedance, current, power, and residual calculations are per unit on 10 MVA and 12.66 kV bases (`src/benchmark/dso_vpp_ac_map_stage0.jl:12-13,67-83,104-112`; `src/validation/s1b_independent_replay.jl:153-181`). CSV injections, substation active power, and active losses are kW; reactive quantities are kvar; voltage magnitudes and voltage differences are p.u.; iteration counts and bus IDs are dimensionless (`src/benchmark/dso_vpp_ac_map_stage0.jl:275-303,389-416`).

## 8. Stage-0 sampling ranges, seed, and generation rule

The intended coordinate domain is \([-2500,6500]\) kW on each axis (`src/benchmark/dso_vpp_ac_map_stage0.jl:22-24`). The actual recorded extrema, verified directly from `results/dso_vpp_ac_map_pilot/stage0_benchmark_points.csv:2-1001`, are:

| coordinate | minimum kW | maximum kW | unique values |
|---|---:|---:|---:|
| `P13` | -2491.2109375 | 6482.421875 | 905 |
| `P30` | -2495.88477366 | 6487.65432099 | 905 |

There are 96 unique timestamps and 905 unique sampled coordinate pairs. Negative injections are present on both axes (253 rows on each axis).

This is not a rectangular grid and is not random or stratified sampling. It is a deterministic two-dimensional Halton sequence in bases 2 and 3, affinely mapped by

\[
P_{13}=-2500+9000\,h_2(n),\qquad
P_{30}=-2500+9000\,h_3(n),
\]

for sequence indices \(n=1,\ldots,904\), after 96 zero-reference rows (`src/benchmark/dso_vpp_ac_map_stage0.jl:308-345`). There is no random seed and no random-number generator.

Point order is ascending `sample_id`. The interval index is `mod1(sample_id,96)`, so samples cycle through the 96 timestamps in chronological order. Samples 1–96 are exactly one `(0,0)` reference per interval; sample 97 returns to the first interval (`src/benchmark/dso_vpp_ac_map_stage0.jl:322-345`; `results/dso_vpp_ac_map_pilot/stage0_benchmark_points.csv:2-98`).

Warm starts are maintained separately by timestamp. A point uses the closest previously found `FEASIBLE` primary voltage at the same interval; only `FEASIBLE` states enter that pool (`src/benchmark/dso_vpp_ac_map_stage0.jl:348-360,419-458`). Thus the primary numerical initialization depends on point ordering, while the independent replay does not.

The 734/1,000 voltage-violation count is unsurprising for this deliberately broad box: sampled net consumption extends to about 2.5 MW at either VPP bus while sampled export approaches 6.5 MW at either bus. Direct CSV inspection shows 678 overvoltage cases, 56 undervoltage cases, and no cases violating both limits. This is an empirical fraction over a joint timestamp/coordinate sequence with 96 repeated `(0,0)` references, not a certified area or volume of a continuous feasible region. The runner itself reports only sample counts and explicitly describes later map sizes as estimates, not completed maps (`src/benchmark/dso_vpp_ac_map_stage0.jl:508-545`; `results/dso_vpp_ac_map_pilot/timing_benchmark.csv:2`; `results/dso_vpp_ac_map_pilot/README.md:23-34`).

## 9. Reference-PV presence test

**Result: failed. The Stage-0 evaluator does not contain the requested 850 kW reference PV driven by the canonical profile.**

The canonical peak interval is `2012-10-15 12:30:00`, with \(f=0.9282211452522351\). The same canonical reader used by Stage 0 supplied this factor (`src/benchmark/dso_vpp_ac_map_stage0.jl:33-41`; `src/solve/solve_s1b_central.jl:45-96`).

At `P13_VPP=0`, `P30_VPP=0`, the existing evaluator has no `H` or reference-PV argument. Its primary calculation uses only the load multiplier and the two VPP injections; its replay supplies availability `1.0` to capacities equal to those same VPP coordinates (`src/benchmark/dso_vpp_ac_map_stage0.jl:86-112,228-263`). Consequently, an audit request of `H=850` cannot affect the existing Stage-0 AC state. The diagnostic ran the exact zero-VPP evaluator twice, recorded `H` as requested audit metadata, and truthfully recorded `actual_PV_kW=0` in both rows of `stage0_pv_presence_check.csv`.

Both rows have:

- total active load: 625.6340316835958 kW
- total reactive load: 387.33735474354523 kvar
- `P_sub`: 630.7432007391333 kW
- `Q_sub`: 390.7379371898343 kvar
- active loss: 5.109169055540568 kW
- reactive loss: 3.4005824462913106 kvar
- `V13`: 0.9874775564651168 p.u.
- `V20`: 0.9988356926902174 p.u.
- `Vmax`: 1.0 p.u. at bus 1
- primary/replay: `CONVERGED`/`PASSED`
- maximum replay residual: \(3.9968028886505635\times10^{-15}\)

The load totals follow the same common load multiplier applied to the IEEE-33 data (`src/benchmark/dso_vpp_ac_map_stage0.jl:104-111`; `src/data/ieee33.jl:4-38`). The state and residuals are recorded at `stage0_pv_presence_check.csv:2-3`.

With

\[
Hf=850(0.9282211452522351)=788.9879734643998\ \mathrm{kW},
\]

\[
\Delta P_{sub}=P^{sub}_{H=0}-P^{sub}_{H=850}=0,
\qquad
\Delta P_{loss}=P^{loss}_{H=850}-P^{loss}_{H=0}=0,
\]

the assertions are:

| assertion | result |
|---|---|
| \(Hf>10^{-9}\ \mathrm{kW}\) | **PASS** |
| \(|\Delta P_{sub}+\Delta P_{loss}-Hf|\le0.1\ \mathrm{kW}\) | **FAIL**; residual 788.9879734643998 kW |
| \(|\Delta P_{sub}|>0.5Hf\) | **FAIL**; 0 is not greater than 394.4939867321999 kW |

The 0.1 kW balance tolerance equals the configured \(10^{-5}\) p.u. residual tolerance on the 10,000 kW base and is conservative relative to the 0.05 kW primary/replay substation-match tolerance (`src/benchmark/dso_vpp_ac_map_stage0.jl:12-13,19-21,212-225`). The discriminating third assertion fails independently of any balance identity. This is a Stage-1 blocker.

## 10. Timing outlier investigation

The maximum recorded per-point time is sample 582 (`results/dso_vpp_ac_map_pilot/stage0_benchmark_points.csv:583`):

- timestamp: `2012-10-15 02:30:00`
- `P13`: 1138.671875 kW
- `P30`: -2475.30864198 kW
- label: `FEASIBLE`
- warm start: `nearest_feasible_sample_294_distance_518.549412_kw`
- primary iterations: 23
- replay iterations: 27
- runtime: 0.0520471 s
- minimum voltage: 0.919383801412 p.u. at bus 33
- maximum voltage: 1.00390611118 p.u. at bus 13
- replay: `PASSED`

It was not the first compiled call: the benchmark performs an explicit zero-injection warm-up before garbage collection and starts the benchmark clock only afterward (`src/benchmark/dso_vpp_ac_map_stage0.jl:419-428`). It is not especially close to the voltage boundary: its nearest voltage-band margin is 0.019383801412 p.u.; it is not the closest recorded point to a boundary. Its 23 primary and 27 replay iterations are also below the respective sample medians of 26 and 29, derived from `stage0_benchmark_points.csv:2-1001`.

The per-point timer includes the primary sweep, construction of replay inputs, the independent replay including residual audit, status/classification checks, and small bookkeeping (`src/benchmark/dso_vpp_ac_map_stage0.jl:228-272`). It stops before row merge/storage and all CSV writing, so CSV I/O did not dominate the recorded 52 ms (`src/benchmark/dso_vpp_ac_map_stage0.jl:272-305,444-460,603-607`). Existing timing data do not separately time primary solve, replay, residual audit, or internal bookkeeping. Therefore they cannot identify which of those components caused the outlier, nor distinguish runtime scheduling/GC effects from other transient effects. The data do not support attributing it to JIT compilation or to a difficult boundary point.

## 11. Conditional order-invariance results

No `stage0_order_invariance.csv` was generated. The condition for that test is not met: code inspection conclusively finds fixed injections and no free operational variables, objective, or feasibility/optimal-control choice (Sections 3–4; `src/benchmark/dso_vpp_ac_map_stage0.jl:86-210,228-305`).

The primary warm-start path is order-dependent numerically, but every physical voltage used for a `FEASIBLE` or `INFEASIBLE_VOLTAGE` label is independently reproduced from a flat start and must match the primary (`src/benchmark/dso_vpp_ac_map_stage0.jl:212-225,264-301`; `src/validation/s1b_independent_replay.jl:184-222`). All existing points passed that check (`results/dso_vpp_ac_map_pilot/timing_benchmark.csv:2`). No order-dependence problem was detected in the recorded evidence; reverse/random re-evaluation was intentionally not run under the audit’s deterministic-PF rule. This does not claim a formal uniqueness theorem for all AC power-flow roots.

## 12. Stage-1 blockers

1. The mandatory reference-PV presence test fails: `pv_profile` is read but not used by the Stage-0 point evaluator, and both response assertions fail (`src/benchmark/dso_vpp_ac_map_stage0.jl:239-263`; Section 9).
2. `INFEASIBLE_VOLTAGE` must be interpreted only as a converged voltage-band violation, not global infeasibility or physical nonexistence (`src/benchmark/dso_vpp_ac_map_stage0.jl:264-271`).
3. The timing table cannot separate primary, replay, residual-audit, and bookkeeping time, although it does exclude CSV I/O (`src/benchmark/dso_vpp_ac_map_stage0.jl:228-272,444-460,603-607`).
4. Stage 0 applies no thermal, transformer, shunt, capacitor, or reactive-control security constraints and cannot support claims about them (`src/benchmark/dso_vpp_ac_map_stage0.jl:79-83,104-112`; `src/data/types.jl:1-15`).
5. The 1,000-point fraction is not a certified continuous-region property (Section 8).

Because blocker 1 is decisive, this audit does not claim Stage-1 readiness and contains no Stage-1 design.

## 13. Files included in the audit ZIP

The ZIP contains these entries:

```text
scripts/run_dso_vpp_ac_map_stage0.jl
src/benchmark/dso_vpp_ac_map_stage0.jl
results/dso_vpp_ac_map_pilot/stage0_data_audit.csv
results/dso_vpp_ac_map_pilot/stage0_benchmark_points.csv
results/dso_vpp_ac_map_pilot/timing_benchmark.csv
results/dso_vpp_ac_map_pilot/README.md
stage0_audit_report.md
stage0_pv_presence_check.csv
SHA256SUMS.txt
```

`stage0_order_invariance.csv` is correctly absent because the evaluator is deterministic fixed-injection PF with no free operational variables.

## 14. SHA-256 hashes

Hashes of the immutable source evidence and generated PV check are:

```text
9242686ff87c30f061ea1d2182827a3a1d2be26440e95a77ca09a4b0bbe32a67  scripts/run_dso_vpp_ac_map_stage0.jl
0f0e68b7081c05b3199ee361a57b5f82f2fbbcacb5299df5b2c64ace0d95dbf2  src/benchmark/dso_vpp_ac_map_stage0.jl
263be8e5321ca59262adeda1317bf9c3c64188af65d2f9f29d10289fdb4ad72a  results/dso_vpp_ac_map_pilot/stage0_data_audit.csv
1c7016d5d35220775433b71a956d6e5bae467960cdadd7ee93e166e7eb87215e  results/dso_vpp_ac_map_pilot/stage0_benchmark_points.csv
34349fd26605b79e21c6cca30129109bc991c0a564a8b2feee580f470e553e86  results/dso_vpp_ac_map_pilot/timing_benchmark.csv
19899d9527ec80d6550bee4c6c5fa9e2bc7c06a5bad8215f35dfe5a2a885354e  results/dso_vpp_ac_map_pilot/README.md
52563b4c0d2e828d2bb481cfaa0a672bb52747cbe176a6947135dd411de8cd1a  stage0_pv_presence_check.csv
```

`SHA256SUMS.txt` contains the authoritative final hash for every ZIP entry except itself, including this report. Omitting the report’s self-hash from the report avoids a circular self-reference.
