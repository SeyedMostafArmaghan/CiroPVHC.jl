# TVPP interface architecture audit

## Scope and authoritative constraints

This is a read-only architecture audit of the current DSO–VPP AC-map pilot. It did not run an AC radial or direction probe, a two-dimensional map, DOE construction, EV/BESS/centralized optimization, constraint generation, a full-period campaign, Phase-B regeneration, analytical-audit regeneration, or provenance reinterpretation. The authoritative provenance verdict remains `ADJACENT_TIMESTAMP_HISTORICAL_TEXT_ERROR`.

The audit distinguishes the current fixed-injection pilot from the intended dispersed, multi-interface TVPP. Repository-relative evidence is inventoried in the accompanying CSV files.

## Primary classification

`CURRENT_PILOT_VALID_BUT_REQUIRES_NAMING_AND_GENERALIZATION`

The numerical pilot is internally coherent and does not model a microgrid boundary or a single common PCC. Its controlled-command API, schemas, analytical geometry, tests, and terminology are deliberately hard-coded to two experimental buses. Those historical two-coordinate paths are valid for Phase B, but they are not the final TVPP interface architecture.

## What the current code actually implements

### Buses 13 and 30

Buses 13 and 30 are two independent controlled-injection coordinates in the full IEEE 33-bus feeder. They are neither adjacent nor endpoints of a closed electrical region. Bus 13 also hosts the fixed reference PV and a nominal passive load of 60 kW/35 kvar. Bus 30 has a nominal passive load of 200 kW/600 kvar. Both passive loads are multiplied by the selected timestamp's common load multiplier.

The code provides no object representing a TVPP boundary, island, common PCC, aggregator, or meter around either bus. The Phase-B axis scan changes one bus command at a time. Buses 20 and 24 are not implemented as pilot controlled interfaces: their appearance in `S1B_CANDIDATE_BUSES=(13,20,24,30)` belongs to a separate centralized PV hosting-capacity study.

### Command, aggregate power, and physical interface power

The exact implemented active-power assembly is

```text
reference_PV_13 = 850 * pv_factor
command_injection_13 = p13_vpp_kw
command_injection_30 = p30_vpp_kw
p_net_i = passive_load_i - reference_PV_i - command_injection_i
```

after scaling passive load by the timestamp multiplier and dividing by the 10,000 kW base. Positive command means export/source injection into the feeder; negative command means added consumption. Phase B restricts the scanned commands to nonnegative values, while Stage 0 allowed both signs.

The variables named `p13_vpp_kw` and `p30_vpp_kw` are therefore `P_command`: externally supplied, additive, active-only experimental injections. The code does not calculate `P_agg` from controlled PV/EV/BESS resources and does not calculate a separately metered `P_PCC`.

The commands are not automatically equivalent to physical net bus/PCC power. If the physical interface meter includes local passive load and all generation at the bus, the current bus-net export relations are

```text
P_bus13_export = 850*f_t + P13_command - 60*load_multiplier
P_bus30_export = P30_command - 200*load_multiplier
```

and neither generally equals its command. A different meter boundary could make a command equal to a controlled device injection, but that boundary is absent from the repository and cannot be inferred. Consequently the confirmed Phase-B values 681.370544434 kW and 1739.59228516 kW remain AC axis bounds in command coordinates, not proven final TVPP PCC limits.

### Sign convention

Classification: `SIGN_CONVENTION_MATCHES_TARGET_ARCHITECTURE`.

The network convention matches the target relation structurally: positive `p_net` is consumption and positive source/interface injection is subtracted. The feeder-root `P_sub` uses a different but internally consistent measurement convention: positive means feeder import from upstream and negative means upstream export. The only defect is local naming ambiguity between a command injection and a physical PCC quantity; there is no sign or injection-assembly defect.

### Reactive power

The pilot implements active-only, unity-power-factor reference PV and commands:

```text
q_net_i = passive_q_i * load_multiplier
Q13_command = 0
Q30_command = 0
```

The primary assembler has no Q-command parameters. The replay treats its injection dictionary as unity-power-factor active injection. P and Q commands are not independently controllable, there is no fixed-power-factor policy in the pilot, and PV capacity affects only active reference PV. Passive Q keeps the positive-load sign, so there is no P/Q sign mixing.

The repository has a separate EV helper that computes lagging/leading Q from a charging power factor, but the Phase-B path never calls it. A P-only DOE with fixed Q(P) requires a generalized interface-Q policy and a replay API accepting resolved Q injections; this is a deferred architectural change, not a reason to modify the pilot.

### Voltage and equipment limits

The current pilot consistently uses `0.90 <= V <= 1.05` p.u. Stage 0 defines both constants, passes them explicitly to replay, and classifies voltage against them. The axis-scan config is rejected unless it matches Stage 0. The analytical audit is an upper-voltage diagnostic with `Vmax=1.05`; its baseline AC replay still uses the same 0.90 lower limit.

No current non-archived pilot Markdown report states 0.95 as the lower project limit. Values of 0.95 found elsewhere are confined to older S0 or paper/unmanaged-EV scenario defaults and unit-test fixtures. They are not universal project limits. Other separate generic fixtures also contain 1.10 upper limits; these do not enter Phase B.

Every IEEE-33 branch has `smax_kva=0.0`, explicitly documented as a missing MATPOWER rating rather than zero capacity. The pilot asserts that ratings remain missing and its AC sweep enforces no line, current, apparent-power, transformer, or upstream-exchange constraint. It does not read zero as a physical limit. Classification: `VOLTAGE_ONLY`.

## Complete production call paths

### Phase-B axis scan

The top-level runner constructs `ScanConfig`, loads the canonical IEEE-33 feeder and normalized profile, selects exactly 96 half-hour timestamps, and loops over the two `AXES`. Each scalar axis command is converted to `(p13,p30)` with the other coordinate zero. `Stage0.evaluate_point` reads the selected load multiplier and PV factor, calculates `850*f_t`, assembles scaled passive P/Q, subtracts reference PV and command injection from active demand, solves the full radial AC equations, replays the resolved injections through `replay_s1b_interval`, validates residual/state agreement, applies 0.90/1.05 voltage tests, and returns point metrics. The scan brackets/refines only an upper-voltage transition and writes capacity, point, timing, resource, report, topology-diagnostic, and manifest artifacts.

The exact step sequence and source locations are in `tvpp_interface_architecture_call_paths.csv`.

### Analytical audit

The analytical runner reads the provenance-locked Phase-B capacity CSV from its committed Git blob, loads the same canonical network/profile, selects the exact 2012-10-15 13:00:00 timestamp, and evaluates one zero-command AC baseline through the same Stage0 assembler/solver/replay path. It forms baseline squared voltages from primary AC phasors, calculates upper-voltage headroom at every bus, and constructs one shared-path resistance coefficient vector for a bus-13 command and another for bus 30. It ranks every bus inequality on each axis, builds a selected 2x2 command-coordinate intersection, and evaluates the resulting candidate against all 33 bus inequalities before writing its artifacts.

This is two-coordinate analytical linear algebra, not a radial/direction probe, DOE, TVPP optimization, or final PCC model.

## Final-architecture intent versus present implementation

The intended final system is a dispersed TVPP whose PV, EV, and BESS resources may occupy nonadjacent buses and whose controlled interfaces are explicitly mapped. The DSO must retain topology, passive/non-TVPP injections, AC equations, voltage limits, and only documented equipment ratings. The TVPP must retain resource capacities, availability, energy states, curtailment, and schedules. Coupled-DOE and box-DOE TVPP models must receive only an exogenous interface envelope and must not import full network equations.

The current pilot is a useful DSO-side fixed-injection acceptance oracle and contains no EV/BESS scheduling. However, final information separation is not yet implemented. Existing resource models are designed for centralized network-coupled optimization, and the legacy `DOE` type contains one `pcc_bus` plus independent import/export box vectors. That type is unused by Phase B and is insufficient for a dispersed multi-interface coupled DOE.

The intended nesting `E_box subset E_coupled subset A_AC` and hosting-capacity ordering `HC_box <= HC_coupled <= HC_central` are architectural targets only; this audit constructs or verifies none of those sets or results.

## Hard-coded two-dimensional assumptions

All identified production, test, report, and serialization assumptions are enumerated in `tvpp_interface_architecture_hardcoded_dimensions.csv`. The main groups are:

- two scalar function parameters (`p13_vpp_kw`, `p30_vpp_kw`);
- two literal bus-vector assignments and a two-key replay dictionary;
- two-coordinate Halton sampling and Euclidean warm-start distance;
- separate p13/p30 and q13/q30 output fields and CSV columns;
- the two-element Phase-B `AXES` tuple and bus validation;
- two-axis topology diagnostic dictionaries and report labels;
- provenance-locked two-bus capacity dictionaries;
- two coefficient vectors, a 2x2 matrix, two-element intersection/residual vectors, and a 2D angle;
- bus-numbered analytical filenames and summary fields;
- tests and committed schemas fixed to buses 13 and 30;
- the separate legacy single-`pcc_bus` DOE type.

Most are `PILOT_SPECIFIC_AND_ACCEPTABLE` because they preserve historical Phase-B/analytical results. Generalization should occur in new types and adapters, not by mutating committed scientific paths. Positional command APIs and the legacy DOE are `GENERALIZATION_REQUIRED_BEFORE_FINAL_TVPP`. Labels that call commands VPP injections or connection points without a physical boundary are `DOCUMENTATION_OR_NAMING_DEFECT`/`AMBIGUOUS`, not numerical defects.

No plotting implementation was found in the pilot path; there are therefore no pilot plot labels beyond Markdown/report and CSV labels.

## Terminology findings

No searched source, test, current pilot report, or project documentation describes buses 13 and 30 as one microgrid, an islandable or geographically contiguous region, or one common PCC. Uses of “contiguous” refer only to timestamp sequences or integer IDs. The pilot reports use plural “connection points,” but that phrase is ambiguous because no physical PCC meter is modeled. The most accurate current repository wording appears in the provenance audit: “VPP P13/P30 command.”

`PCC` occurrences in the separate S1-C no-export documents concern the feeder upstream balance, not either pilot coordinate. `DOSS` occurs only in a disclaimer that no equivalence is asserted. There is no implemented aggregator abstraction. Important occurrences and classifications are in `tvpp_interface_architecture_terminology.csv`.

## Separate classifications

| Topic | Classification | Meaning |
|---|---|---|
| Command versus PCC semantics | `COMMAND_IS_DIRECT_ADDITIVE_BUS_INJECTION_NOT_PROVEN_PHYSICAL_PCC_POWER` | P_command exists; P_agg and P_PCC do not. |
| Multi-interface extensibility | `EXACTLY_TWO_COMMAND_BUSES_IN_PILOT_GENERALIZATION_REQUIRED` | Network vectors are general, but command APIs/geometry/schemas are two-coordinate. |
| DSO–TVPP information separation | `PILOT_IS_DSO_FIXED_INJECTION_EVALUATOR_FINAL_SEPARATION_NOT_IMPLEMENTED` | Pilot has no resource optimizer; coupled/box module boundary is absent. |
| Active-power sign convention | `SIGN_CONVENTION_MATCHES_TARGET_ARCHITECTURE` | Positive command exports; positive p_net consumes. |
| Reactive-power convention | `ACTIVE_ONLY_UNITY_POWER_FACTOR_FIXED_Q_OF_P_NOT_SUPPORTED` | Q commands are fixed zero; passive Q remains positive load. |
| Voltage-limit consistency | `PILOT_CONSISTENT_0_90_TO_1_05` | 0.95 is scenario-specific elsewhere, not a current pilot limit. |
| Thermal/transformer validity | `VOLTAGE_ONLY` | Ratings are missing and correctly not enforced. |
| Terminology correctness | `AMBIGUOUS_VPP_LABELS_WITHOUT_MICROGRID_OR_SINGLE_PCC_CONFLATION` | Naming cleanup is needed; physical architecture is not wrongly bounded. |

## Deferred structural patch plan

`tvpp_interface_architecture_recommended_changes.csv` specifies affected files/modules, proposed types, backward compatibility, required tests, artifact implications, and scientific impact. The essential sequence is:

1. define first-class `P_command`, `P_agg`, and `P_PCC` semantics and meter boundaries;
2. introduce data-driven controlled-interface and resource-to-interface mappings;
3. add a named DSO conversion from interface P/Q to bus net demand;
4. separate DSO network modules from TVPP resource scheduling modules;
5. supersede the single-PCC DOE with multi-interface coupled and box envelope types;
6. add a fixed Q(P) policy interface while preserving unity-power-factor pilot behavior;
7. implement N-dimensional half-space geometry separately from the locked 2D audit;
8. enforce line/transformer limits only from documented ratings;
9. version final artifact schemas with long-form interface identifiers and quantity kinds.

No structural change above was implemented in this audit. Existing Phase-B and analytical artifacts require no regeneration. Future final-TVPP artifacts and scientific results will be new because they answer a different model question.

## Audit artifact generation and validation

These artifacts are generated deterministically by `results/dso_vpp_ac_map_pilot/tvpp_interface_architecture_audit/generate_audit.py`. The generator writes only this new directory, uses repository-relative scientific/code references, and asserts the exact required filenames and nonempty row sets. Running it twice must produce identical SHA-256 hashes.

Lightweight validation completed for this audit:

- six relevant Julia files passed 390 assertions: Stage-0 selection/classification, independent physical-input propagation, timestamp-keyed PV propagation, export-side axis scan, AC-anchored analytical audit, and operating-point provenance;
- all five existing Python profile-pipeline test functions passed using fresh temporary directories;
- two consecutive generator runs produced eight required artifacts with zero SHA-256 mismatches;
- no existing Phase-B, analytical-audit, provenance, or protected smoke artifact was regenerated or modified.
