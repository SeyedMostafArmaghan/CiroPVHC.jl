# Stage-0 fixed-reference-PV repair report

## 1. Scope and repository state

This task repaired only the confirmed Stage-0 physical-input defect, archived the invalid evidence, added permanent regression coverage, and reran the same 1,000 archived points. No Stage-1 feature was implemented.

- Branch before and after: `codex/dso-vpp-ac-map-pilot`
- Base HEAD before the isolated repair commit: `13f22d0e48e950ccf8a127bb3c97f891c2512e19`
- Initial and final command outputs: `git_before.txt` and `git_after.txt`
- Phase A was prepared as one explicit-whitelist repair commit. The two pre-existing modified S1-B smoke files and all unrelated untracked paths were excluded. No push, merge, rebase, or unrelated overwrite occurred.

## 2. Exact root cause

The pre-repair Stage-0 runner loaded the canonical profile and validated that `pv_profile` was finite, but the point evaluator passed only `profile.load_multiplier[index]`, `P13_VPP`, and `P30_VPP` into `primary_power_flow`. There was no `H` argument, no reference-PV bus argument, and no read of `profile.pv_profile[index]` in the physical assembly. The original net-demand vector subtracted only the VPP command selected by bus ID. Replay likewise used capacities equal only to the two VPP coordinates with a hard-coded availability of `1.0`.

Therefore:

- `H` was not passed;
- `pv_factor` was read only for window/data audit, not for the point solve;
- `H × pv_factor` was never computed;
- no wrong PV bus, overwrite, or computed-then-discarded term was involved;
- fixed PV was effectively absent, not defaulted by a lower-level solver;
- fixed PV and `P13_VPP` were not separate concepts in the old evaluator.

The pre-repair call path and exact old lines are preserved in `stage0_audit_bundle.zip` and described in the archived `stage0_audit_report.md`, Sections 3, 4, and 9. The repaired path is explicit at `src/benchmark/dso_vpp_ac_map_stage0.jl:26-27,89-133,135-158,294-330`.

The backward/forward sweep itself was not defective. It consumed the exact vector it was given (`src/benchmark/dso_vpp_ac_map_stage0.jl:160-205`; `src/validation/s0_unconstrained.jl:99-135`).

## 3. Confirmatory S1-B/S1-C impact audit

The defect is isolated from the locked S1 paths.

S1-B constructs JuMP capacity variables and explicitly forms

\[
P^{PV}_{b,t}=f_t\,H_b
\]

before passing the per-bus JuMP expressions into the SOCP branch-flow constraints (`src/solve/solve_s1b_central.jl:166-193`). Its deterministic AC validation independently multiplies each capacity by `profile.pv_profile[index]` before constructing net load (`src/solve/solve_s1b_central.jl:241-267`).

S1-C uses `add_pv_hosting_variables!`: `pv_available_kw == pv_profile[t] * pv_capacity_kw`, injected plus curtailed power equals available power, and each PV-unit injection is added to its declared bus expression (`src/models/pv_model.jl:11-48`). Those expressions enter the network balance as `load - injection` (`src/models/socp_network.jl:191-213`). The S1-C paper model calls that path with free curtailment and adds its policy constraints (`src/solve/solve_s1_pv_only.jl:301-334`).

Stage 0 shares IEEE-33 feeder data and lower-level network equations with S1, but not a lower-level injection-assembly helper. Its fixed-parameter vector is separate (`src/benchmark/dso_vpp_ac_map_stage0.jl:89-133`).

A minimal two-bus S1 check changed installed capacity from 0 to 100 kW at `f=0.8`. The pre-solve available/injected expression changed from numerical zero to 80 kW; the model's substation-flow variable changed from 585.7095 to 881.0929 kW and its bus-voltage variable from 0.9981586 to 0.9977281 p.u. This ad-hoc relaxed SOCP check is evidence of variable propagation only, not a physical result or a new S1 conclusion.

No shared defective assembly was found, no full S1 campaign was rerun, and no locked S1 result was quarantined.

## 4. Exact code correction

The repaired Stage-0 assembly now:

1. declares `REFERENCE_PV_BUS = 13` and `REFERENCE_PV_CAPACITY_KW = 850.0` (`src/benchmark/dso_vpp_ac_map_stage0.jl:26-27`);
2. accepts `load_multiplier`, canonical `pv_factor`, `reference_pv_capacity_kw`, `P13_VPP`, and `P30_VPP` as separate primary inputs (`src/benchmark/dso_vpp_ac_map_stage0.jl:89-96`);
3. computes `reference_pv_kw = H * pv_factor` and places it only at bus 13 (`src/benchmark/dso_vpp_ac_map_stage0.jl:109-111`);
4. constructs a separate VPP vector with commands only at buses 13 and 30 (`src/benchmark/dso_vpp_ac_map_stage0.jl:112-114`);
5. adds the reference and VPP vectors without overwrite or double counting (`src/benchmark/dso_vpp_ac_map_stage0.jl:115-123`);
6. passes the resulting complex net-demand vector into the unchanged deterministic sweep (`src/benchmark/dso_vpp_ac_map_stage0.jl:150-160`);
7. passes the explicitly additive, time-resolved bus-13 total and independent bus-30 command into replay with availability `1.0` (`src/benchmark/dso_vpp_ac_map_stage0.jl:316-338`).

Reactive assumptions remain unchanged: fixed PV and both VPP commands are active-only; raw reactive load receives the same load multiplier as active load. Voltage limits, root voltage, tolerances, no-thermal assumption, no transformer constraint, and unconstrained upstream exchange are unchanged.

The corrected runner reads the archived point table as authoritative, validates point IDs 1–1000 and timestamps, and writes only `_corrected` outputs (`src/benchmark/dso_vpp_ac_map_stage0.jl:558-589,1048-1099`). It does not regenerate a random or replacement sample.

## 5. Permanent independent-verification rule

`CLAUDE.md:53-62` now requires physical-input verification to reconstruct the entire bus-injection vector independently from canonical source data and primary inputs, including `H`, `f_t`, raw load, and external VPP commands. It states that agreement between consumers of a shared assembly proves numerical consistency, not physical-input correctness, and that replay/residual checks do not replace independent reconstruction.

Existing `CLAUDE.md` content was preserved.

## 6. Independent pre-solve vector verification

The permanent test `test/test_dso_vpp_ac_map_stage0_physical_inputs.jl` now invokes `CiroPVHC.build_ieee33_network()` and `CiroPVHC.read_s1b_profile()` itself for every expected-value reconstruction. It creates a fresh timestamp-keyed profile representation and fresh bus objects, then independently reconstructs, for every bus:

- fixed reference PV;
- VPP injection;
- total active injection;
- real net demand in per unit;
- reactive net demand in per unit.

It does not receive the production network object, production profile object, profile index, assembled vector, or evaluator output as an expected value. It does not call the production assembly helper. A structural assertion inspects the lowered expected-path code and fails if that helper becomes reachable by name.

The two paths are:

- production: `evaluate_point` → `assemble_stage0_inputs` → `primary_power_flow` plus `replay_s1b_interval`;
- expected: `_independent_stage0_expected` → fresh `build_ieee33_network` plus fresh `read_s1b_profile` → timestamp lookup → direct raw-load/reference-PV/VPP arithmetic.

The paths share only canonical source readers, immutable input definitions/types, and constants such as the 10 MW base used by the physical model. They do not share profile instances, bus-vector instances, timestamp-index lookup objects, assembly helpers, expected arrays, or solver outputs.

Result: **maximum absolute discrepancy = 0.0** across all buses and components. No mismatching bus/component exists.

The file is registered in the standard suite at `test/runtests.jl:15`.

## 7. Focused physical-input regression results

All 87 assertions in `Stage-0 independent physical-input propagation` passed.

### Fixed reference PV

At `2012-10-15 12:30:00`:

- canonical \(f_t=0.928221145252\);
- \(H=850\) kW;
- expected and actual PV = 788.987973464 kW;
- `P_sub(H=0) - P_sub(H=850)` = 775.868715869 kW;
- `loss(H=850) - loss(H=0)` = 13.1192575953 kW;
- balance tolerance = 0.1 kW;
- nonzero, balance, discriminating response, and `actual_PV ≈ Hf_t` assertions all passed;
- both cases converged and replay passed.

The corrected evidence is in `stage0_pv_presence_check_corrected.csv`.

At the minimum/zero-factor night interval, `H=850` and `H=0` both produced zero fixed-PV injection and identical substation/voltage results within test tolerance. This proves time-profile multiplication rather than constant injection (`test/test_dso_vpp_ac_map_stage0_physical_inputs.jl:152-179`).

### VPP bus 13

With `H=0` and `P13_VPP=100` kW:

- the direct active-injection vector changed only at bus 13;
- the exact bus-13 change was +100 kW;
- every other bus change was zero;
- substation response plus active-loss change balanced the 100 kW command within 0.1 kW;
- voltage changed beyond numerical noise;
- replay passed.

### VPP bus 30

With `H=0` and `P30_VPP=100` kW, the same assertions passed with the direct change only at bus 30 (`test/test_dso_vpp_ac_map_stage0_physical_inputs.jl:181-219`).

### Combined inputs

At the daytime interval:

- `H=850`, `P13_VPP=100`, `P30_VPP=0` produced exactly 788.987973464 kW fixed PV plus 100 kW VPP at bus 13, total 888.987973464 kW;
- `H=850`, `P13_VPP=75`, `P30_VPP=125` produced 863.987973464 kW total at bus 13 and 125 kW at bus 30;
- independent reconstruction discrepancy remained zero;
- all evaluations converged, all replays passed, and the maximum residual stayed below `1e-5`.

Three representative old points were also reproduced with `H=0` to the archived substation and voltage tolerances, isolating the behavioral change to the missing fixed-PV term (`test/test_dso_vpp_ac_map_stage0_physical_inputs.jl:249-291`).

### Full 96-interval timestamp-keyed regression

The new permanent test `test/test_dso_vpp_ac_map_stage0_timestamp_vectors.jl` passed all 18 assertions. It independently rereads the canonical source, constructs the expected `H × f_t` vector keyed by timestamp, and compares it with values extracted from the corrected production evaluator for all 96 intervals.

It checks exact length, uniqueness, timestamp set, ordered first/last timestamps, full timestamp order, night zeros, non-constancy, and peak timestamp/value. Three discriminating negative controls all fail the comparator as required: a one-slot factor shift, reversed temporal order, and a constant-peak vector.

The expected path also checks the reactive sign convention explicitly: active injection is subtracted from raw active demand, while reactive demand retains the raw positive load sign and receives no PV/VPP reactive term.

## 8. Separate numerical and voltage statuses

Corrected point output now has:

- `power_flow_status`: `CONVERGED` or `NONCONVERGED`;
- `voltage_status`: `WITHIN_LIMITS`, `UPPER_VOLTAGE_VIOLATION`, `LOWER_VOLTAGE_VIOLATION`, `BOTH_LIMITS_VIOLATED`, or `NOT_EVALUATED`;
- `legacy_label`: compatibility only.

The implementation is at `src/benchmark/dso_vpp_ac_map_stage0.jl:276-291,341-371`. A primary nonconvergence maps to `UNRESOLVED_AC_NONCONVERGENCE`, not physical impossibility or voltage infeasibility. The old focused status test was updated accordingly (`test/test_dso_vpp_ac_map_stage0.jl:36-47`).

## 9. Invalid-run voltage classification and domain

The archived invalid 1,000-point run contained:

- converged: 1,000;
- nonconverged: 0;
- upper-voltage violations: 678;
- lower-voltage violations: 56;
- both limits: 0;
- total voltage violations: 734.

There were 253 rows with negative `P13_VPP` and 253 with negative `P30_VPP`. The domain was not all nonnegative and was not exclusively the export quadrant. Therefore the 734/1,000 fraction is neither an export-only statistic nor a continuous feasible-region metric.

## 10. Corrected 1,000-point rerun and before/after comparison

All archived point IDs, timestamps, `P13_VPP`, `P30_VPP`, and ordering matched the corrected output exactly.

Corrected counts:

- converged: 1,000;
- unresolved: 0;
- replay passed: 1,000;
- within voltage limits: 263;
- upper-voltage violations: 697;
- lower-voltage violations: 40;
- both limits: 0;
- maximum replay residual: \(6.41708908233\times10^{-14}\).

There were 35 changed voltage labels (3.5%):

- 19 `WITHIN_LIMITS → UPPER_VOLTAGE_VIOLATION`;
- 16 `LOWER_VOLTAGE_VIOLATION → WITHIN_LIMITS`;
- 965 unchanged.

Absolute before/after changes:

- median \(|\Delta V_{\max}|\): \(4.347418747\times10^{-6}\) p.u.;
- maximum \(|\Delta V_{\max}|\): 0.02711636669 p.u.;
- median \(|\Delta P_{sub}|\): 13.93145845705 kW;
- maximum \(|\Delta P_{sub}|\): 997.269982308 kW.

The point-level evidence is in `stage0_benchmark_points_corrected.csv` and `stage0_before_after_comparison.csv`.

## 11. Runtime, allocation, GC, RAM, and timer-scope audit

The corrected schema now records these separate per-point fields: `assembly_ms`, `primary_power_flow_ms`, `replay_ms`, `residual_audit_ms`, `classification_ms`, `bookkeeping_ms`, `total_evaluation_ms`, `allocated_bytes`, and `gc_time_ms`.

Standardized corrected benchmark measurements:

- batch wall time: 0.5563696 s;
- median/p90/maximum total evaluation: 0.1513 / 0.24998 / 23.2054 ms;
- median assembly: 0.0007 ms;
- median primary AC power flow: 0.07195 ms;
- median independent replay: 0.07065 ms;
- median residual audit: 0.0012 ms;
- median classification: 0.0002 ms;
- median bookkeeping: 0.0020 ms;
- maximum point: point 650 at 23.2054 ms;
- total measured per-point allocations: 176,741,040 bytes;
- maximum point allocation: 311,998 bytes;
- total and maximum GC time: 22.9235 ms;
- peak process RSS: 779,358,208 bytes (743.254 MiB);
- average process cores: 0.99934.

Point 650's maximum is again explained by the 22.9235 ms GC event, which occurred inside the primary-phase wall clock.

The original defective timer began at evaluator entry and ended after assembly-inside-primary, the primary sweep, replay, replay/residual checks, voltage classification, and limited evaluator bookkeeping. It excluded corrected-row construction and CSV I/O, used one flat-start warm-up, and did not expose allocation or GC fields. The earlier corrected rerun used an outer `@timed evaluate_point` scope and two warm-ups; it likewise excluded corrected-row construction and file I/O but did not separate phases.

The standardized timer now uses explicit phase clocks inside `evaluate_point`, with one flat-start and one warm-start specialization evaluation before GC and measurement. Allocation and GC retain the outer `@timed evaluate_point` scope. Because the old run omitted the fixed PV, had a different warm-up policy/schema, and did not expose phase or GC data, old and standardized corrected timings are not treated as strictly like-for-like. Future recalibration uses only the standardized scope.

Peak RAM remains below 1 GB and CPU remains approximately one core. The laptop-safety conclusion does not change.

## 12. Full test results

Pre-repair:

- Julia: 39 testsets, 497 passed, 0 failed, 0 skipped, 0 errored;
- Python: 5 passed, 0 failed, 0 skipped, 0 errored.

Post-repair:

- Julia: 41 testsets, 604 passed, 0 failed, 0 skipped, 0 errored;
- Python: 5 passed, 0 failed, 0 skipped, 0 errored.

The first post-repair full Julia attempt exposed an unnecessary `Statistics` import that was unavailable in the package-test sandbox. The import was removed and the existing local quantile helper used instead; the complete retry passed. No dependency was added and no test was weakened or removed.

Focused test files:

- modified: `test/test_dso_vpp_ac_map_stage0.jl`;
- new: `test/test_dso_vpp_ac_map_stage0_physical_inputs.jl`;
- new: `test/test_dso_vpp_ac_map_stage0_timestamp_vectors.jl`;
- standard registration: `test/runtests.jl`.

A large passing test count is evidence only for the behaviors actually covered by the tests. The previous suite did not cover propagation of fixed external parameters into the physical injection vector.

## 13. Invalid-output archive

Archive:

`results/dso_vpp_ac_map_pilot/_archived_stage0_missing_reference_pv_20260730T145810Z/`

It contains copies of every existing invalid Stage-0 evidence file requested, plus:

- `INVALID_FOR_SCIENTIFIC_USE.md`;
- `archive_manifest.csv`.

The manifest records original/archived paths, size, SHA-256, archival reason, commit, and UTC timestamp. Originals were not deleted or overwritten.

## 14. Files changed and created

Files already dirty before this task and left untouched:

- `results/s1b_ac_constraint_generation_smoke/iteration_summary.csv`;
- `results/s1b_ac_constraint_generation_smoke/smoke_report.md`;
- all pre-existing untracked paths listed in `git_before.txt` except the Stage-0 files explicitly listed below.

Files already dirty/untracked before this task and additionally modified by this task:

- `test/runtests.jl` — preserved its pre-existing Stage-0 registration and added the new physical-input test registration;
- `scripts/run_dso_vpp_ac_map_stage0.jl`;
- `src/benchmark/dso_vpp_ac_map_stage0.jl`;
- `test/test_dso_vpp_ac_map_stage0.jl`.

Previously clean tracked file modified by this task:

- `CLAUDE.md`.

Created by this task:

- `test/test_dso_vpp_ac_map_stage0_physical_inputs.jl`;
- `test/test_dso_vpp_ac_map_stage0_timestamp_vectors.jl`;
- `results/dso_vpp_ac_map_pilot/git_before.txt`;
- `results/dso_vpp_ac_map_pilot/git_after.txt`;
- the timestamped invalid-output archive and its two metadata files;
- `stage0_benchmark_points_corrected.csv`;
- `timing_benchmark_corrected.csv`;
- `stage0_data_audit_corrected.csv`;
- `stage0_pv_presence_check_corrected.csv`;
- `stage0_before_after_comparison.csv`;
- this `stage0_repair_report.md`;
- `SHA256SUMS_REPAIR.txt`;
- `stage0_repair_bundle.zip`.
- `RESULT_STATUS.md`;
- `result_status.csv`.

## 15. Sampling-domain conclusion and Phase A boundary

The corrected 1,000-point rerun is a controlled before/after regression on the same coordinates. It does not establish final sampling bounds.

The old domain is not reused or endorsed as a final Stage-1 domain. Phase A contains no direction probe, grid/radial map, LinDistFlow, AC Jacobian, Newton solver, DOE, internal VPP optimization, or Stage-1 runner. The separately authorized export-side axis recalibration begins only after the isolated Phase A commit and its generated outputs remain outside that commit.
