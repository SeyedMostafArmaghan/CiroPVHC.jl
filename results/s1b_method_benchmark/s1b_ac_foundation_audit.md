# S1-B AC foundation and substation-rating audit

## External-review verdict

**PASS, with scope limitations.** At audited base commit `836ad7602a5405f763120a0f45006568f513a52f` on branch `codex/s1b-ac-vs-strengthened-socp`, no material formulation, sign, indexing, or unit bug was found in the one-day nonlinear model. The result is a **nonconvex branch-flow AC model for a balanced radial feeder**, not a full polar- or rectangular-voltage AC-OPF. The best stable AC-feasible local solution observed for the one-day problem is **10.680484846 MW**. It is not a proven global optimum or mathematical upper bound.

All 13 declared Ipopt starts terminated `LOCALLY_SOLVED`, and all 13 passed an independent phasor-domain replay. No 32-day optimization, three-year optimization/validation, multi-day constraint generation, or transformer sensitivity was run.

No defensible documented substation or transformer MVA rating exists in the repository or source case. The mandatory central label is therefore:

> **voltage-only hosting capacity with unconstrained upstream exchange.**

## Repository state and implementation scope

- Branch: `codex/s1b-ac-vs-strengthened-socp`.
- Audited starting HEAD: `836ad7602a5405f763120a0f45006568f513a52f` (the expected `836ad76`).
- The initial worktree contained pre-existing untracked S0/S1 analysis scripts and outputs. They were preserved and excluded from this audit commit.
- Nonlinear model and multi-start implementation: `src/benchmark/s1b_method_benchmark.jl`.
- Benchmark orchestration and CSV/report writing: `scripts/run_s1b_method_benchmark.jl`.
- Independent replay implementation: `src/validation/s1b_independent_replay.jl`, loaded and exported by `src/CiroPVHC.jl`.
- Validator tests and model-structure tests: `test/test_s1b_method_benchmark.jl`.
- The existing production central SOCP builder in `src/solve/solve_s1b_central.jl` was not changed or run as the source of achievable hosting capacity.

## Model classification and equation-to-code map

The optimization uses real sending-end branch powers (P_{ij,t},Q_{ij,t}), squared voltage magnitudes (v_{i,t}=|V_{i,t}|^2), and squared current magnitudes (ell_{ij,t}=|I_{ij,t}|^2). It has no voltage-angle variables and no rectangular real/imaginary voltage variables. Its exact current-power equality makes it nonconvex.

| Mathematical element | Code mapping | Audit result |
|---|---|---|
| Benchmark day, candidate buses, root and voltage limits | `src/benchmark/s1b_method_benchmark.jl:15-20` | PASS |
| Exactly 48 contiguous half-hours on 2010-12-21 | `src/benchmark/s1b_method_benchmark.jl:41-50` | PASS |
| Ohm-to-per-unit impedance, (Z_{base}=kV_{base}^2/MVA_{base}) | `src/benchmark/s1b_method_benchmark.jl:51-63` | PASS |
| Four time-invariant nonnegative capacity variables | `src/benchmark/s1b_method_benchmark.jl:306-313` | PASS |
| Fixed squared slack voltage (v_{1,t}=1.0^2) | `src/benchmark/s1b_method_benchmark.jl:314-315` | PASS |
| Branch orientation (i\rightarrow j) from rooted radial topology | `src/benchmark/s1b_method_benchmark.jl:317-321` | PASS |
| Voltage drop (v_j=v_i-2(rP+xQ)+(r^2+x^2)\ell) | `src/benchmark/s1b_method_benchmark.jl:322-324` | PASS |
| Exact nonlinear equality (P^2+Q^2=v_i\ell) | `src/benchmark/s1b_method_benchmark.jl:325` | PASS — equality, not a cone or inequality |
| Active balance (P_{in}-r\ell-\sum P_{child}=(P_{load}-P_{PV})/S_{base}) | `src/benchmark/s1b_method_benchmark.jl:328-342` | PASS |
| Reactive balance (Q_{in}-x\ell-\sum Q_{child}=Q_{load}/S_{base}) | `src/benchmark/s1b_method_benchmark.jl:343-345` | PASS |
| Zero-curtailment PV (P_{PV}=C_{bus}\times availability_t) | `src/benchmark/s1b_method_benchmark.jl:333-342` | PASS |
| Sole objective (max(C_{13}+C_{20}+C_{24}+C_{30})) | `src/benchmark/s1b_method_benchmark.jl:348` | PASS |
| Solver residuals plus mandatory independent replay gate | `src/benchmark/s1b_method_benchmark.jl:394-469` | PASS |
| Thirteen deterministic starts and per-start replay acceptance | `src/benchmark/s1b_method_benchmark.jl:247-295`, `473-521` | PASS |

## Formulation and unit audit

| Audit item | Result | Evidence and interpretation |
|---|---|---|
| Active nodal balance and sign | PASS | Positive branch (P) is sending-to-receiving flow. Incoming sending power minus (r\ell) loss and outgoing child powers equals positive net consumption. PV is subtracted from load; sufficiently large PV therefore produces negative upstream flow. |
| Reactive nodal balance and sign | PASS | The same convention applies to (Q), with (x\ell) reactive loss. PV has zero reactive injection (unity power factor). |
| Nonlinear branch equality | PASS | There are (32\times48) scalar quadratic equalities (P^2+Q^2=v_i\ell); the structure test verifies that count. |
| Voltage drop and bus orientation | PASS | The rooted topology supplies sending bus (i) and receiving bus (j); the loss correction has the positive ((r^2+x^2)\ell) sign. |
| Loss terms | PASS | (r\ell) and (x\ell) are deducted from incoming sending-end powers before satisfying downstream demand. |
| Slack-bus treatment | PASS | Bus 1 squared voltage is fixed at 1.0 in every interval. Slack P and Q are unconstrained consequences of root-branch flows, so import and export are both allowed. |
| Voltage bounds and units | PASS | The variable is squared magnitude and is bounded by (0.90^2=0.81) and (1.05^2=1.1025). Reported voltages take the square root. |
| Capacity shared across intervals | PASS | Only four capacity variables exist and none has a time index; the same variables enter all 48 intervals. |
| Availability and curtailment | PASS | Injection is capacity times the recorded interval availability. There is no curtailment variable or curtailment constraint. |
| Objective purity | PASS | The nonlinear objective contains only the sum of the four capacities; it has no loss, voltage, or regularization penalty. |
| Site/gamma/computational cap | PASS (absent) | Capacity variables have no finite upper bound. No site or gamma constraint is created. |
| Thermal/line/transformer cap | PASS (absent) | (P,Q) are unbounded and (ell) has only a nonnegative lower bound. No branch apparent-power, current, root-exchange, or transformer constraint is present. |
| No-export constraint | PASS (absent) | No restriction is placed on root-branch active power. Negative substation active power is reported as export. |
| Power and impedance bases | PASS | `baseMVA=10` maps to 10,000 kW/kvar base. Loads/PV in kW/kvar are divided by 10,000. (r,x) in ohms are divided by (12.66^2/10) ohms. Output powers multiply per-unit values by 10,000 kW. |
| Time and bus indexing | PASS | Julia local interval 25 maps to 2010-12-21 12:00. Contiguous IDs map directly to buses; the binding bus is bus 20, not a zero-based offset. |

No material formulation or unit defect was identified, so the central nonlinear equations were not altered. One non-formulation packaging defect was found during full testing: `Random` was used by the benchmark but missing from `Project.toml`. Its standard-library UUID was added so isolated `Pkg.test()` works.

## Independent physical replay

The validator constructs its own radial topology (`src/validation/s1b_independent_replay.jl:57-109`), independently converts units and builds net complex demands (`134-181`), solves the phasor state by a backward/forward sweep (`186-220`), and then recomputes currents and sending-end powers from the converged phasors (`224-247`). It does not call the optimization builder, JuMP constraints, `ac_solution_diagnostics`, or the S0 power-flow/residual helpers.

It explicitly checks P/Q balance (`249-272`), squared-voltage drop, exact current-power equality and phasor recovery (`274-305`), voltage bounds and root voltage (`307-316`), and substation exchange/losses (`317-321`). All 48 intervals converged, satisfied the voltage gate, and were phasor-recoverable.

Residual scaling divides the absolute equation residual by the largest magnitude among that equation’s evaluated terms, with a (10^{-12}) floor. Global maxima for the best observed solution are:

| Check | Maximum absolute residual | Maximum scaled residual at that point | Location |
|---|---:|---:|---|
| Active nodal balance | (5.4956039719\times10^{-15}) p.u. | (1.3977488292\times10^{-14}) | bus 20, 14:30 |
| Reactive nodal balance | (1.3619747691\times10^{-14}) p.u. | (5.6988226182\times10^{-12}) | bus 20, 14:30 |
| Squared-voltage drop | (3.1086244690\times10^{-14}) p.u.² | (2.8610011907\times10^{-14}) | branch 19 (19→20), 14:30 |
| (P^2+Q^2-v_i\ell) equality | (1.1102230246\times10^{-16}) p.u.² | (4.1765418456\times10^{-16}) | branch 2 (2→3), 12:00 |
| Phasor recovery (V_j-[V_i-z\overline{S/V_i}]) | (3.9245991950\times10^{-14}) p.u. | (3.7650452414\times10^{-14}) | branch 19 (19→20), 14:30 |
| Root complex voltage | 0 p.u. | 0 | all intervals |

The maximum absolute residual across all categories and intervals is (3.9245991950\times10^{-14}); the maximum scaled residual is (5.6988226182\times10^{-12}).

## Numerical findings and reference discrepancies

| Quantity | Reproduced value | Stated reference | Discrepancy | Finding |
|---|---:|---:|---:|---|
| Total installed PV | 10.680484846163 MW | approximately 10.680 MW | +0.000484846163 MW (+0.484846 kW) | Confirmed within stated rounding |
| Maximum voltage | 1.050000004762 p.u. | 1.05 p.u. | +(4.761917\times10^{-9}) p.u. | Confirmed within numerical tolerance |
| Reported binding point | bus 20, 12:00 | bus 20 around 12:00 | exact bus/time match | Confirmed |
| Minimum voltage | 0.974427788427 p.u., bus 18 at 20:30 | approximately 0.974 p.u. | +0.000427788427 p.u. versus the rounded reference | Confirmed within stated rounding |
| Maximum upstream export | 9.469200668489 MW at 12:30 | approximately 9.469 MW | +0.000200668489 MW (+0.200668 kW) | Confirmed within stated rounding |

The noon constraint is not the only numerically active upper-voltage point: bus 24 at 12:30 also reaches approximately 1.050000004762 p.u. Maximum export occurs at that 12:30 interval, whereas bus 20 at 12:00 is the reproduced maximum-voltage location by about (6\times10^{-15}) p.u.

The best observed allocation is (C_{13}=733.640257286), (C_{20}=4681.670271374), (C_{24}=3988.773998170), and (C_{30}=1276.400319333) kW.

## Thirteen-start evidence

- Starts run: 13; termination: 13 `LOCALLY_SOLVED`; primal status: 13 `FEASIBLE_POINT`.
- Independently replayed and accepted: 13 of 13.
- Objective range: 10,680.484846163065 to 10,680.484846163086 kW.
- Objective spread: (2.1827872843\times10^{-11}) kW.
- Maximum per-start independent replay absolute residual: (3.9245991950\times10^{-14}).
- Maximum per-start independent replay scaled residual: (5.6988226182\times10^{-12}).
- Maximum NLP/replay voltage difference across starts: (1.8207657604\times10^{-14}) p.u.

This is strong repeatability evidence for the declared starts. It is not a global-optimality proof.

## Substation and transformer rating decision

The repository-wide search covered source code, raw `case33bw`, documentation, existing decision files, and result inventories.

- `data_raw/case33bw.m:17` defines `baseMVA = 10`; lines 120-122 use it for per-unit conversion. It is a computational base, not equipment capacity.
- The raw branch `rateA/rateB/rateC` values are zero (`data_raw/case33bw.m:64-102`). `src/data/ieee33.jl:77-80` intentionally preserves that missing-rating convention as `smax_kva=0`.
- The project’s 4,000 kVA values belong to explicitly synthetic branch-rating study paths, not a source transformer datum.
- Baseline peak substation apparent power is an observed loading metric, not a rating, and is not used to synthesize one.
- No nameplate, utility planning document, transformer impedance/rating record, normal/emergency rating, or other defensible (S_{tr}) source was found.

**Decision 2 applies:** no defensible rating exists, so the central result must be labeled **“voltage-only hosting capacity with unconstrained upstream exchange.”** No central transformer constraint is supported.

If a future sensitivity is authorized, retain the unconstrained reference and sweep a predeclared set such as (S_{tr}\in\{4,6,8,10,12\}) MVA. Every value must be labeled **synthetic**, with no claim that 10 MVA follows from `baseMVA` or that any value reflects actual equipment. Apply the bidirectional apparent-power constraint in every interval:

\[
P_{sub,t}^2+Q_{sub,t}^2\le S_{tr}^2.
\]

Report import- and export-side binding intervals separately, capacity allocation, voltage extrema, replay residuals, and the difference from the unconstrained reference. This sensitivity was not run in this task.

## Method decision and risks

The existing S1-B SOCP relaxation and all nine tested loss-penalty variants failed the declared exactness and independent AC-feasibility gates on the benchmark day. SOCP may be retained for screening or clearly non-certified bounds, but not as achievable hosting capacity under the current formulation. S1-B therefore proceeds with the nonconvex branch-flow AC formulation, with mandatory independent replay.

Ipopt multi-start remains local-solution evidence. SOC-gap validation is not applicable as the central validation test after moving to the equality-constrained model, but validation is not optional.

Open risk #2 remains unresolved: the planned budgeted-robust R0–R3 extension was designed around SOCP. A nonconvex multi-scenario AC formulation may be computationally or methodologically infeasible. A small-case prototype is required before claiming that the original robust architecture remains viable.

## Test evidence and remaining limitations

- Full Julia package suite: **386 passed**.
- Python profile-pipeline suite: **5 passed**.
- One-day reproduction: **13/13** starts passed independent replay; **48/48** intervals passed.

Remaining limitations are material and explicit: one balanced radial feeder; constant-PQ, balanced representation; fixed ideal 1.0-p.u. root voltage; unity-power-factor PV; no phase unbalance, controls, regulators, transformer impedance, thermal ratings, protection, inverter capability, uncertainty, full-period validation, or global-optimality certificate. The 32-day and three-year studies remain intentionally unstarted.

## Deliverables

- `ac_multistart_results.csv`: 13-start solver and independent-replay results.
- `independent_replay_metrics.csv`: 48 interval-level physical and scaled replay metrics.
- `s1b_ac_foundation_audit.md`: this reviewer report.
- `src/validation/s1b_independent_replay.jl` and `test/test_s1b_method_benchmark.jl`: independent validator and tests.
- `METHODOLOGY_DECISIONS.md`: method, transformer-label, validation, and robust-risk decision record.
