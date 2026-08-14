# DOE preconstruction artifact refinement — final code inspection and wording correction

This is an artifact/code-inspection result. No AC power flow, backward/forward sweep, replay, production probing, multi-start test, or DOE construction was run.

## A. Repository provenance

- branch: `codex/dso-vpp-ac-map-pilot`
- HEAD: `44cdad078b9503dfef6617c3585b99e7b014cdd9`
- authoritative inputs hashed/schema-checked: 20
- pre-analysis `git status --short`:

```text
?? results/dso_vpp_ac_map_pilot/monotonicity_falsification_screen/
?? scripts/prepare_dso_vpp_monotonicity_falsification_screen.py
```

## B. Ray bisection implementation

- initial certified bracket: first adjacent converged-feasible/converged-infeasible pair in the retained full `r = 0:0.05:2` coarse sweep (`first_adjacent_bracket`, source lines 413–418 and `run_ray!`, lines 698–738)
- initial normalized-r width: `0.05` for every certified physical ray
- update: midpoint of the current coordinates; a converged-feasible midpoint replaces the safe endpoint, a converged-infeasible midpoint replaces the violating endpoint, and an unresolved midpoint aborts certification (`refine_boundary!`, lines 434–459)
- stop: `(violating_r-safe_r)*hypot(vx,vy) <= 1.0 kW` **and** both endpoints are within `1e-5 p.u.` of the active VMIN or VMAX limit (`endpoint_voltage_close`, lines 421–431)
- maximum bisection refinements: `60`; coordinate tolerance: none; normalized-r tolerance: none; relative tolerance: none; physical tolerance: `1.0 kW`; voltage-related tolerance: `1e-5 p.u.` at both endpoints
- serialization: production Float64 values are written with `@sprintf("%.12g")` after the in-memory inequalities have been evaluated; serialization does not control stopping

## C. Why ray widths have three discrete levels

All 1,561 certified physical rays start from `0.05`; exact halving therefore gives `0.05/2^7 = 0.000390625`, `0.05/2^8 = 0.0001953125`, and `0.05/2^9 = 0.00009765625`. Counts are 104, 771, and 686, respectively. Before the final halving, all 104 seven-step rays fail the physical-width condition; all 771 eight-step and all 686 nine-step rays already pass physical width but fail the endpoint-voltage conjunction.

| candidate | classification | code-level finding |
|---|---|---|
| fixed normalized-r tolerance | `RULED_OUT_BY_CODE` | No normalized-r stopping tolerance exists. |
| physical-coordinate/kW tolerance | `SUPPORTED_BY_CODE` | The shared stop requires physical width <= 1.0 kW. |
| relative tolerance | `RULED_OUT_BY_CODE` | No relative bracket tolerance exists. |
| voltage residual/margin tolerance | `SUPPORTED_BY_CODE` | Both active-limit endpoint distances must be <= 1e-5 p.u. |
| maximum-iteration cap | `NOT_RELEVANT` | Observed certified rays stop after 7/8/9, far below the cap of 60. |
| mechanism-specific termination | `RULED_OUT_BY_CODE` | Both families call refine_boundary!; endpoint_voltage_close selects the active limit but uses the same 1e-5 threshold. |
| different ray initial bracket widths | `RULED_OUT_BY_CODE` | Every certified ray starts from an adjacent 0.05 normalized-r sweep bracket. |
| different signed normalization scales | `SUPPORTED_BY_CODE` | Ray physical width is normalized-r width times hypot(vx, vy), but equal anchor scales do not imply equal steps. |
| floating-point threshold crossing | `NOT_RELEVANT` | Stored preceding/final values cross explicit 1 kW and 1e-5 p.u. inequalities without a borderline equality. |
| another explicit condition | `SUPPORTED_BY_CODE` | The endpoint-voltage-distance conjunction explains continued halving after the physical-width condition is met. |

Anchor threshold crossings (the physical-width condition is already true in every preceding state; the active endpoint-voltage condition determines the 8-versus-9 split):

| direction | scale (kW/r) | preceding step | preceding width (kW) | preceding safe/violating voltage distances (p.u.) | final step | final width (kW) | final safe/violating voltage distances (p.u.) |
|---:|---:|---:|---:|---|---:|---:|---|
| 0° | 1583.203125 | 7 | 0.618438720702 | 2.111441e-05 / 3.10127999992e-06 | 8 | 0.309219360351 | 9.00640000001e-06 / 3.10127999992e-06 |
| 90° | 2268.4375 | 7 | 0.886108398438 | 1.63985000001e-05 / 7.90149999985e-06 | 8 | 0.443054199219 | 4.24833000001e-06 / 7.90149999985e-06 |
| 180° | 1583.203125 | 8 | 0.309219360352 | 1.84000199999e-06 / 1.6027838e-05 | 9 | 0.154609680176 | 1.84000199999e-06 / 7.09379899999e-06 |
| 270° | 2268.4375 | 8 | 0.443054199218 | 3.49331000016e-07 / 1.75873880001e-05 | 9 | 0.221527099609 | 3.49331000016e-07 / 8.61890900006e-06 |

The equal 0°/180° scale of 1583.203125 kW/r and equal 90°/270° scale of 2268.4375 kW/r do not imply equal counts: the opposite directions cross the endpoint-voltage inequalities on different halvings.

## D. Signed-axis bisection implementation

- provisional transition scale: double from 100 kW until the first converged-infeasible point or the 20,000 kW guard (`run_axis!`, lines 486–499)
- initial certified bracket: first adjacent converged-feasible/converged-infeasible pair in the retained coarse sweep with `delta = transition_scale/20` (`run_axis!`, lines 499–525)
- initial bracket widths: 20, 40, 80, 160, or 320 kW in the completed certified searches
- update and stop: the same `refine_boundary!` midpoint update and conjunction used by rays, with physical width per coordinate equal to 1.0; no axis-specific coordinate or relative tolerance exists
- maximum refinements: 60; physical tolerance: 1.0 kW; both active-limit endpoint distances: at most 1e-5 p.u.; unresolved midpoint aborts

## E. Why axis widths have three discrete levels

The completed final widths are 0.15625, 0.3125, and 0.625 kW. They are dyadic descendants of the direction-specific coarse brackets, and every search stops on the first loop entry where both the physical-width and endpoint-voltage conditions are true.

- P13+: 13 at 0.15625 kW; 19 at 0.3125 kW.
- P13−: 27 at 0.15625 kW; 5 at 0.3125 kW.
- P30+: 29 at 0.3125 kW; 3 at 0.625 kW; none at 0.15625 kW.
- P30−: 16 at 0.15625 kW; 16 at 0.3125 kW.
P30+ initial brackets are 160 or 320 kW; the shared voltage condition becomes true at 0.625 or 0.3125 kW, so no P30+ search performs the additional halving needed to reach 0.15625 kW.
Positive signed axes are BINDING_VMAX and negative signed axes are BINDING_VMIN for all 128 completed certified searches.
There is no separate VMAX/VMIN refinement path. Axis initial-bracket geometry differs, and the shared voltage-distance conjunction determines whether additional halvings occur after width first reaches at most 1 kW.

## F. VMAX-versus-VMIN bracket asymmetry

- `VMAX_BOUNDARY_BRACKETS_COARSER_THAN_VMIN_IN_PRODUCTION`
- `VMAX_VMIN_BRACKET_ASYMMETRY_EXPLAINED_BY_BOTH_GEOMETRY_AND_TERMINATION`
The ray and signed-axis families call the same refinement function. For opposite anchor rays with identical physical scale, the VMAX directions stop at 8 and the VMIN directions at 9 because of the stored endpoint-voltage threshold crossings. For axes, differing initial coarse brackets also contribute. This is a code/history reconciliation, not a physical causal explanation of directional asymmetry.

## G. 0°/180° corrected cardinal interpretation

- symmetrized point estimate: 0.268569397544
- propagated interval: [0.26820149426, 0.269305204113]
- topology coefficient: 0.268450094712
- `RADIAL_LINEAR_MODEL_SYMMETRIZED_CROSS_CHECK_WITHIN_BOUNDARY_SEARCH_RESOLUTION`
- `SYMMETRIZED_DEVIATION_SIGN_UNRESOLVED_WITHIN_BOUNDARY_BRACKETS`
The coefficient lies inside the propagated interval; this is a resolution-aware cross-check, not a pass/fail accuracy test, and the deviation sign is unresolved.

## H. 90°/270° corrected cardinal interpretation

- propagated interval: [0.269377318338, 0.271050469383]
- topology coefficient: 0.268450094712
- `RADIAL_LINEAR_MODEL_SYMMETRIZED_CROSS_CHECK_RESOLVABLY_DIFFERENT`
- `SYMMETRIZED_DEVIATION_POSITIVE_OVER_ALL_STORED_BOUNDARY_BRACKET_POSITIONS`
The complete propagated interval lies above the topology coefficient. This directional statement is anchor-specific and is not generalized across 32 timestamps.

## I. Same-sign anchor observation

`SAME_SIGN_SYMMETRIZED_POINT_DEVIATION_AT_ANCHOR`

Descriptive anchor-only observation; no systematic bias or physical mechanism is inferred.

## J. Certified-feasible inward endpoint semantics

`CERTIFIED_FEASIBLE_INWARD_BRACKET_ENDPOINT`

The stored boundary cloud uses the certified-feasible side of each final AC bracket, yielding one-sided conservative boundary-location representatives along the individually searched trajectories.

This property does not certify line segments, facets, convex combinations, or unsampled angular interiors between those endpoints.

`BOUNDARY_LOCATION_BRACKETING != FACET_INTERIOR_VALIDATION_RISK`

## K. Candidate-facet implication

`CANDIDATE_FACET_GENERATOR`

The topology-consistent LinDistFlow structure may later generate candidate facets because its sensitivity matrix is exactly topology-consistent, its first-order geometry is useful, one anchor symmetrized pair agrees within search resolution, and the other is resolvably different but numerically close in absolute terms.

`LINDISTFLOW_IS_NOT_DOE_FEASIBILITY_AUTHORITY`

Every retained candidate facet requires nonlinear AC falsification/validation. No generic error percentage or 32-timestamp generalization is made.

## L. Files updated/created

- `results/dso_vpp_ac_map_pilot/doe_preconstruction_artifact_refinement/anchor_metric_percentiles.csv`
- `results/dso_vpp_ac_map_pilot/doe_preconstruction_artifact_refinement/artifact_manifest.csv`
- `results/dso_vpp_ac_map_pilot/doe_preconstruction_artifact_refinement/axis_boundary_resolution.csv`
- `results/dso_vpp_ac_map_pilot/doe_preconstruction_artifact_refinement/axis_boundary_resolution_distribution.csv`
- `results/dso_vpp_ac_map_pilot/doe_preconstruction_artifact_refinement/boundary_bisection_termination_audit.csv`
- `results/dso_vpp_ac_map_pilot/doe_preconstruction_artifact_refinement/boundary_input_reconciliation.csv`
- `results/dso_vpp_ac_map_pilot/doe_preconstruction_artifact_refinement/boundary_order_closure_summary.csv`
- `results/dso_vpp_ac_map_pilot/doe_preconstruction_artifact_refinement/cardinal_antisymmetry_by_timestamp.csv`
- `results/dso_vpp_ac_map_pilot/doe_preconstruction_artifact_refinement/cardinal_boundary_resolution.csv`
- `results/dso_vpp_ac_map_pilot/doe_preconstruction_artifact_refinement/cardinal_directional_effective_coupling.csv`
- `results/dso_vpp_ac_map_pilot/doe_preconstruction_artifact_refinement/cardinal_residual_scaling_regressions.csv`
- `results/dso_vpp_ac_map_pilot/doe_preconstruction_artifact_refinement/doe_preconstruction_artifact_refinement_report.md`
- `results/dso_vpp_ac_map_pilot/doe_preconstruction_artifact_refinement/doe_preconstruction_artifact_refinement_summary.json`
- `results/dso_vpp_ac_map_pilot/doe_preconstruction_artifact_refinement/duplicate_coordinate_reproducibility.csv`
- `results/dso_vpp_ac_map_pilot/doe_preconstruction_artifact_refinement/duplicate_provenance_combinations.csv`
- `results/dso_vpp_ac_map_pilot/doe_preconstruction_artifact_refinement/pair_class_summary.csv`
- `results/dso_vpp_ac_map_pilot/doe_preconstruction_artifact_refinement/percentile_audit.csv`
- `results/dso_vpp_ac_map_pilot/doe_preconstruction_artifact_refinement/ray_boundary_resolution.csv`
- `results/dso_vpp_ac_map_pilot/doe_preconstruction_artifact_refinement/ray_boundary_resolution_distribution.csv`
- `results/dso_vpp_ac_map_pilot/doe_preconstruction_artifact_refinement/sensitivity_topology_reconstruction.csv`
- `results/dso_vpp_ac_map_pilot/doe_preconstruction_artifact_refinement/separation_scale_summary.csv`
- `results/dso_vpp_ac_map_pilot/doe_preconstruction_artifact_refinement/timing_scope_comparison.csv`
- `results/dso_vpp_ac_map_pilot/doe_preconstruction_artifact_refinement/zero_delta_voltage_decomposition.csv`
- `scripts/prepare_dso_vpp_doe_preconstruction_artifact_refinement.py`

## M. Determinism/manifest verification

`BYTE_IDENTICAL_DOUBLE_REGENERATION_VERIFIED`

All authoritative inputs are manifest/hash checked. The output manifest hashes every generated file except the manifest itself; the finalized generator is run twice and the complete output directory is compared byte-for-byte.

## N. Final git status

```text
?? results/dso_vpp_ac_map_pilot/doe_preconstruction_artifact_refinement/
?? results/dso_vpp_ac_map_pilot/monotonicity_falsification_screen/
?? scripts/prepare_dso_vpp_doe_preconstruction_artifact_refinement.py
?? scripts/prepare_dso_vpp_monotonicity_falsification_screen.py
```

## Supporting evidence annex

### Boundary-input reconciliation

- purpose: `COMPLETE_DOE_FACET_INPUT_BOUNDARY_SET`
- physical_ray_boundaries: `1,561`
- signed_axis_boundaries: `128`
- total_physical_boundaries: `1,689`
- distinct_physical_coordinates: `1,689`
- ray_axis_coordinate_overlap_clusters: `0`
- guard_truncations: `73`
- VMAX_total: `851`
- VMIN_total: `838`

The signed-axis and centered-ray boundaries are distinct physical coordinates under the 1e-9 kW coordinate criterion. Future facet generation must deduplicate coordinates if this changes; search outcomes and physical coordinates are reported separately.

`BOUNDARY_ORDER_SCREEN_RESULT_IS_DERIVED_FROM_EXISTING_SCALAR_MONOTONICITY_SCREEN`. This reconciliation serves `COMPLETE_DOE_FACET_INPUT_BOUNDARY_SET`; it is not a new falsification experiment or independent monotonicity evidence.

### Zero-Delta Vmax decomposition

- zero_pairs_total: 9,255,817
- both_endpoints_bus_1: 9,255,817
- both_endpoints_value_exactly_1pu: 9,255,817
- both_bus_1_and_value_exactly_1pu: 9,255,817
- one_endpoint_bus_1_only: 0
- neither_endpoint_bus_1: 0
- same_non_slack_bus: 0
- different_non_slack_buses: 0
- Vmax_non_equality_pairs: 50,556,063
- Vmax_slack_pinned_zero_pairs: 9,255,817
- Vmax_non_slack_or_positive_response_pairs: 41,300,246
- exact criterion: parsed IEEE-754 float Vmax_a == Vmax_b; exactly 1 p.u. means parsed value == 1.0
- classification: `SLACK_PINNED_VMAX_NON_INFORMATIVE_FOR_RESPONSE_STRENGTH`

These pairs remain consistent with nondecreasing monotonicity but are not responsive evidence that Vmax changes with injection.

### Zero-Delta Vmin decomposition

- zero_pairs_total: 56,751
- same_bus: 56,751
- different_buses: 0
- both_endpoints_bus_1: 56,751
- both_endpoints_value_exactly_1pu: 56,751
- both_bus_1_and_value_exactly_1pu: 56,751
- same_non_slack_bus: 0
- different_non_slack_buses: 0
- unique_exact_stored_zero_pair_values: 1
- Vmin_non_equality_pairs: 50,556,063
- Vmin_slack_pinned_zero_pairs: 56,751
- Vmin_non_slack_or_positive_response_pairs: 50,499,312
- exact criterion: parsed IEEE-754 float Vmin_a == Vmin_b; exactly 1 p.u. means parsed value == 1.0
- classification: `SLACK_PINNED_VMIN_NON_INFORMATIVE_FOR_RESPONSE_STRENGTH`

All zero-Delta Vmin pairs have both endpoints pinned exactly at 1 p.u. on slack bus 1 in the stored representation. This structural origin was determined from the stored bus/value provenance rather than assumed from Vmax. Dominant combinations, including vmin_bus_a, vmin_bus_b, Vmin_a, and Vmin_b, are recorded in `zero_delta_voltage_decomposition.csv`.

### Vmax percentile/minimum audit

| statistic | positive N | exact minimum | count at minimum | requested label | probability | fractional index | ranks (1-based) | rank values | reported value | classification |
|---|---:|---:|---:|---|---:|---:|---|---|---:|---|
| Delta_Vmax | 41,300,246 | 2.26320000074e-07 | 435 | 0.001% | 1e-05 | 413.00245 | 414/415 | 2.26320000074e-07/2.26320000074e-07 | 2.26320000074e-07 | `PERCENTILE_RESULT_VALID_DUE_TO_TIES` |
| Delta_Vmin | 50,499,312 | 4.43980000542e-08 | 71 | 0.001% | 1e-05 | 504.99311 | 505/506 | 1.36064300005e-06/1.36064300005e-06 | 1.36064300005e-06 | `PERCENTILE_RESULT_VALID_AT_REQUESTED_RANK` |

The implementation is label-consistent: 0.001% uses probability 0.00001; probability 0.001 would be 0.1%. Type-7 linear interpolation is used.

### Cardinal direction-specific reinterpretation

- geometry classification: `CENTERED_CARDINAL_PARAMETERIZATION_IDENTITY_CHECK`
- residual classification: `CARDINAL_LINEAR_ANTISYMMETRY_RESIDUAL`
- `AXIS_RAY_CROSS_CERTIFICATION_NOT_PERFORMED`

| direction | active constraint | bus | effective coupling | matching stored coefficient | relative difference |
|---:|---|---:|---:|---:|---:|
| 0 deg | VMAX | 13 | 0.289907788034 | 0.268450094712 | 0.0799317778042 |
| 90 deg | VMAX | 30 | 0.287781979839 | 0.268450094712 | 0.0720129570001 |
| 180 deg | VMIN | 18 | 0.247231007054 | 0.268450094712 | 0.0790429509081 |
| 270 deg | VMIN | 33 | 0.252088090867 | 0.268450094712 | 0.0609498903798 |

VMAX-side and VMIN-side quantities are kept separate. No VMAX/VMIN pooling, sensitivity symmetry, or causal label is used.

### Stored sensitivity availability

| bus | coefficient wrt P13 | coefficient wrt P30 |
|---:|---:|---:|
| 13 | 0.893822890072 | 0.268450094712 |
| 30 | 0.268450094712 | 0.625073311221 |
| 18 | 0.893822890072 | 0.268450094712 |
| 33 | 0.268450094712 | 0.625073311221 |

All four direction-matched comparisons have corresponding stored coefficients. No unstored coefficient or symmetry assumption is introduced.

### Sensitivity convention reconstructed from code

- historical convention source: `src/benchmark/dso_vpp_export_side_axis_scan.jl: topology_coefficient`
- independent historical reconstruction source: `src/benchmark/dso_vpp_operating_point_provenance.jl: independent_coefficient`
- quantity: squared-voltage p.u. response per active-power p.u.
- formula: `c_ij = 2 * sum(r_ohm on shared root paths) / Zbase_ohm`
- base: 10 MVA, 12.66 kV; Zbase = 16.02756 ohm

The factor of 2 and the ohm-to-per-unit conversion were taken from the historical implementation and verified against its independent raw-case reconstruction; they were not supplied from memory.

### Root-path/topology reconstruction

- bus 13: branch IDs `1;2;3;4;5;6;7;8;9;10;11;12`; path `1->2;2->3;3->4;4->5;5->6;6->7;7->8;8->9;9->10;10->11;11->12;12->13`
- bus 18: branch IDs `1;2;3;4;5;6;7;8;9;10;11;12;13;14;15;16;17`; path `1->2;2->3;3->4;4->5;5->6;6->7;7->8;8->9;9->10;10->11;11->12;12->13;13->14;14->15;15->16;16->17;17->18`
- bus 30: branch IDs `1;2;3;4;5;25;26;27;28;29`; path `1->2;2->3;3->4;4->5;5->6;6->26;26->27;27->28;28->29;29->30`
- bus 33: branch IDs `1;2;3;4;5;25;26;27;28;29;30;31;32`; path `1->2;2->3;3->4;4->5;5->6;6->26;26->27;27->28;28->29;29->30;30->31;31->32;32->33`

### Stored-vs-topology sensitivity comparison

| coefficient | shared root-path branches | resistance sum (ohm) | resistance sum (p.u.) | topology coefficient | stored coefficient | absolute difference | relative difference |
|---|---|---:|---:|---:|---:|---:|---:|
| c_13_13 | 1:1->2;2:2->3;3:3->4;4:4->5;5:5->6;6:6->7;7:7->8;8:8->9;9:9->10;10:10->11;11:11->12;12:12->13 | 7.1629 | 0.446911445036 | 0.893822890072 | 0.893822890072 | 1.11022302463e-16 | 1.24210627962e-16 |
| c_13_30 | 1:1->2;2:2->3;3:3->4;4:4->5;5:5->6 | 2.1513 | 0.134225047356 | 0.268450094712 | 0.268450094712 | 1.66533453694e-16 | 6.20351629499e-16 |
| c_18_13 | 1:1->2;2:2->3;3:3->4;4:4->5;5:5->6;6:6->7;7:7->8;8:8->9;9:9->10;10:10->11;11:11->12;12:12->13 | 7.1629 | 0.446911445036 | 0.893822890072 | 0.893822890072 | 1.11022302463e-16 | 1.24210627962e-16 |
| c_18_30 | 1:1->2;2:2->3;3:3->4;4:4->5;5:5->6 | 2.1513 | 0.134225047356 | 0.268450094712 | 0.268450094712 | 1.66533453694e-16 | 6.20351629499e-16 |
| c_30_13 | 1:1->2;2:2->3;3:3->4;4:4->5;5:5->6 | 2.1513 | 0.134225047356 | 0.268450094712 | 0.268450094712 | 1.66533453694e-16 | 6.20351629499e-16 |
| c_30_30 | 1:1->2;2:2->3;3:3->4;4:4->5;5:5->6;25:6->26;26:26->27;27:27->28;28:28->29;29:29->30 | 5.0092 | 0.312536655611 | 0.625073311221 | 0.625073311221 | 1.11022302463e-16 | 1.77614850081e-16 |
| c_33_13 | 1:1->2;2:2->3;3:3->4;4:4->5;5:5->6 | 2.1513 | 0.134225047356 | 0.268450094712 | 0.268450094712 | 1.66533453694e-16 | 6.20351629499e-16 |
| c_33_30 | 1:1->2;2:2->3;3:3->4;4:4->5;5:5->6;25:6->26;26:26->27;27:27->28;28:28->29;29:29->30 | 5.0092 | 0.312536655611 | 0.625073311221 | 0.625073311221 | 1.11022302463e-16 | 1.77614850081e-16 |

Classification: `SENSITIVITY_MATRIX_TOPOLOGY_CONSISTENT`. This direct check is limited to the stored LinDistFlow sensitivity construction.

### Opposite-direction symmetrized cardinal cross-check

| pair | directions | estimate | interval lower | interval upper | half-width | stored/topology coefficient | point discrepancy | minimum discrepancy | maximum discrepancy | location | classification |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---|---|
| INTERFACE_13_ORIENTED | 0°/180° | 0.268569397544 | 0.26820149426 | 0.269305204113 | 0.00055185492646 | 0.268450094712 | 0.000119302832221 | 0 | 0.000855109400835 | `INSIDE_SYMMETRIZED_BOUNDARY_RESOLUTION_INTERVAL` | `RADIAL_LINEAR_MODEL_SYMMETRIZED_CROSS_CHECK_WITHIN_BOUNDARY_SEARCH_RESOLUTION` |
| INTERFACE_30_ORIENTED | 90°/270° | 0.269935035353 | 0.269377318338 | 0.271050469383 | 0.000836575522788 | 0.268450094712 | 0.00148494064101 | 0.00092722362582 | 0.0026003746714 | `OUTSIDE_SYMMETRIZED_BOUNDARY_RESOLUTION_INTERVAL` | `RADIAL_LINEAR_MODEL_SYMMETRIZED_CROSS_CHECK_RESOLVABLY_DIFFERENT` |

Classification: `PAIR_SPECIFIC_CARDINAL_BOUNDARY_RESOLUTION_CLASSIFICATION`.

### Anchor cardinal boundary-location brackets

| direction | search ID | feasible r | violating r | width r | steps | feasible P13/P30 (kW) | violating P13/P30 (kW) | binding | bus | physical components P13/P30 (kW) | physical length (kW) |
|---:|---|---:|---:|---:|---:|---|---|---|---:|---|---:|
| 0° | `0.000000` | 1.0384765625 | 1.038671875 | 0.0001953125 | 8 | 1519.97871399 / -187.8125 | 1520.28793335 / -187.8125 | BINDING_VMAX | 13 | 0.309219360352 / 0 | 0.309219360352 |
| 90° | `90.000000` | 1.0251953125 | 1.025390625 | 0.0001953125 | 8 | -124.140625 / 2137.7789917 | -124.140625 / 2138.2220459 | BINDING_VMAX | 30 | 1.89342249944e-17 / 0.443054199219 | 0.443054199219 |
| 180° | `180.000000` | 0.9671875 | 0.96728515625 | 9.765625e-05 | 9 | -1655.39489746 / -187.8125 | -1655.54950714 / -187.8125 | BINDING_VMIN | 18 | -0.154609680176 / 2.71292453461e-17 | 0.154609680176 |
| 270° | `270.000000` | 0.9779296875 | 0.97802734375 | 9.765625e-05 | 9 | -124.140625 / -2406.18487549 | -124.140625 / -2406.40640259 | BINDING_VMIN | 33 | -2.84013374917e-17 / -0.221527099609 | 0.221527099609 |

These are conservative boundary-location brackets between the stored converged-feasible endpoint and converged-infeasible endpoint. They are neither random noise nor a proven solver-error bound.

### Direction-specific effective-coupling resolution

| direction | feasible coupling | violating-coordinate mapped coupling | lower | upper | width | relative width (vs feasible) |
|---:|---:|---:|---:|---:|---:|---:|
| 0° | 0.289907788034 | 0.291379401171 | 0.289907788034 | 0.291379401171 | 0.00147161313723 | 0.00507614213197 |
| 90° | 0.287781979839 | 0.2900128479 | 0.287781979839 | 0.2900128479 | 0.00223086806077 | 0.0077519379845 |
| 180° | 0.247231007054 | 0.246495200486 | 0.246495200486 | 0.247231007054 | 0.000735806568614 | 0.00297619047619 |
| 270° | 0.252088090867 | 0.250972656836 | 0.250972656836 | 0.252088090867 | 0.00111543403038 | 0.00442477876106 |

The violating-coordinate value is an algebraic endpoint of the monotone linear map from the allowed r interval; it is not a claim that the violating endpoint itself is feasible or a direct coupling measurement.

### Whole-production ray-boundary resolution

| group | quantity | N | min | Q01 | Q05 | Q25 | median | Q75 | Q95 | Q99 | max | unit |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| ALL_PHYSICAL_RAYS | NORMALIZED_R_BRACKET_WIDTH | 1561 | 9.765625e-05 | 9.765625e-05 | 9.765625e-05 | 9.765625e-05 | 0.0001953125 | 0.0001953125 | 0.000390625 | 0.000390625 | 0.000390625 | normalized_r |
| ALL_PHYSICAL_RAYS | PHYSICAL_BRACKET_LENGTH | 1561 | 0.154510498047 | 0.15479888916 | 0.157598255136 | 0.202051108514 | 0.320329018244 | 0.411980934431 | 0.718813598372 | 0.812724348188 | 0.85415700925 | kW |
| BASE | NORMALIZED_R_BRACKET_WIDTH | 1118 | 9.765625e-05 | 9.765625e-05 | 9.765625e-05 | 9.765625e-05 | 0.0001953125 | 0.0001953125 | 0.0001953125 | 0.000390625 | 0.000390625 | normalized_r |
| BASE | PHYSICAL_BRACKET_LENGTH | 1118 | 0.154510498047 | 0.154719085693 | 0.157148763206 | 0.196656047553 | 0.309593200684 | 0.396384077109 | 0.452535942989 | 0.79816718102 | 0.83942497106 | kW |
| ADAPTIVE | NORMALIZED_R_BRACKET_WIDTH | 443 | 9.765625e-05 | 9.765625e-05 | 9.765625e-05 | 9.765625e-05 | 0.0001953125 | 0.0001953125 | 0.000390625 | 0.000390625 | 0.000390625 | normalized_r |
| ADAPTIVE | PHYSICAL_BRACKET_LENGTH | 443 | 0.159859506069 | 0.160078722281 | 0.162175546826 | 0.205796950031 | 0.359167152484 | 0.423032480101 | 0.776768083266 | 0.818256466884 | 0.85415700925 | kW |
| VMAX | NORMALIZED_R_BRACKET_WIDTH | 787 | 9.765625e-05 | 9.765625e-05 | 9.765625e-05 | 0.0001953125 | 0.0001953125 | 0.0001953125 | 0.000390625 | 0.000390625 | 0.000390625 | normalized_r |
| VMAX | PHYSICAL_BRACKET_LENGTH | 787 | 0.154708862305 | 0.15600982666 | 0.165372367283 | 0.314859060821 | 0.393246619685 | 0.436968807355 | 0.787052353089 | 0.827394970189 | 0.85415700925 | kW |
| VMIN | NORMALIZED_R_BRACKET_WIDTH | 774 | 9.765625e-05 | 9.765625e-05 | 9.765625e-05 | 9.765625e-05 | 9.765625e-05 | 0.0001953125 | 0.0001953125 | 0.0001953125 | 0.0001953125 | normalized_r |
| VMIN | PHYSICAL_BRACKET_LENGTH | 774 | 0.154510498047 | 0.154714431763 | 0.157137542456 | 0.17455563801 | 0.212617135067 | 0.340971676888 | 0.422520475915 | 0.440470554285 | 0.456268310547 | kW |

The 73 guard-limited rays are reported separately as `GUARD_TRUNCATION_NO_PHYSICAL_BOUNDARY_BRACKET` and are excluded from these physical-boundary statistics.

### Signed-axis boundary resolution

| group | N | min | Q01 | Q05 | Q25 | median | Q75 | Q95 | Q99 | max | unit |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| ALL_SIGNED_AXES | 128 | 0.15625 | 0.15625 | 0.15625 | 0.15625 | 0.3125 | 0.3125 | 0.3125 | 0.625 | 0.625 | kW |
| P13+ | 32 | 0.15625 | 0.15625 | 0.15625 | 0.15625 | 0.3125 | 0.3125 | 0.3125 | 0.3125 | 0.3125 | kW |
| P13- | 32 | 0.15625 | 0.15625 | 0.15625 | 0.15625 | 0.15625 | 0.15625 | 0.3125 | 0.3125 | 0.3125 | kW |
| P30+ | 32 | 0.3125 | 0.3125 | 0.3125 | 0.3125 | 0.3125 | 0.3125 | 0.625 | 0.625 | 0.625 | kW |
| P30- | 32 | 0.15625 | 0.15625 | 0.15625 | 0.15625 | 0.234375 | 0.3125 | 0.3125 | 0.3125 | 0.3125 | kW |

### Resolution interpretation and sensitivity correction

`FIRST_ORDER_BINDING_BUS_SENSITIVITY_MISMATCH_RULED_OUT_BY_TOPOLOGY`

The topology reconstruction rules out first-order LinDistFlow sensitivity mismatch between the opposite binding buses as the explanation for the directional spread. The remaining directional asymmetry is not causally identified.

No curvature, Taylor-order, odd/even, or other causal error mechanism is assigned to the remaining directional asymmetry.

`BOUNDARY_LOCATION_BRACKETING != FACET_INTERIOR_VALIDATION_RISK`

The bracket width quantifies unresolved outward distance between the stored certified-feasible endpoint and the first certified-infeasible endpoint after bisection. It is relevant to boundary-location precision but does not by itself determine the contraction required for facets connecting multiple feasible endpoints.

Bracket statistics can guide numerical tolerances, numerical indistinguishability, and the avoidance of meaningless sub-bracket refinement. They do not establish a mandatory DOE contraction distance and cannot substitute for AC validation of candidate facet interiors.

### Directional spread versus symmetrized agreement

Individual direction-specific estimates have several-percent signed spread around the corresponding stored linear coefficient. The opposite-direction point-estimate differences are descriptive only: the 0°/180° coefficient lies inside its propagated boundary-resolution interval, while the 90°/270° coefficient remains outside its interval.

This is a cross-consistency check between computational pathways, not axis↔ray boundary certification.

`AXIS_RAY_CROSS_CERTIFICATION_NOT_PERFORMED`

### Cardinal diagnostic-family consolidation

`CARDINAL_RESIDUAL_AND_BACK_CALCULATION_ARE_ONE_DIAGNOSTIC_FAMILY`.
`CARDINAL_DIRECTIONAL_AND_SYMMETRIZED_RESULTS_ARE_ONE_DIAGNOSTIC_FAMILY`.
The cardinal antisymmetry residual, direction-specific effective couplings, and symmetrized cross-checks are deterministic transforms of the same four stored cardinal displacement observations. They are one diagnostic family and are not double-counted as independent scientific findings.

Superseded wording: `the point-estimate percentages are descriptive differences only and must be interpreted through the propagated boundary-location brackets`. The earlier pooled heterogeneous-active-constraint estimate and its approximate 8% headline are retired.

### Anchor dependence and effect-size correction

- verified identity: `A_i = -c_i / s_i, where c_i is the Tier-1 midpoint center and s_i=(P_i^+ + |P_i^-|)/2`
- maximum absolute identity residual: 0
- `A_i_AND_NORMALIZED_CENTER_DISPLACEMENT_NOT_INDEPENDENT_METRICS`

- total-axis-width rank: 4 ascending / 29 descending
- anchor minus median: -29.84375 kW (-0.385920956922%)
- full range: 202.5 kW (2.61860502708% of median)
- `RANK_EXTREMENESS` is distinct from `EFFECT_SIZE`.

- number_of_adaptive_rays: 2 unique values [15;16], frequencies [15:30;16:2]; `LOW_CARDINALITY_DESCRIPTIVE_METRIC`
- number_of_guard_limited_rays: 3 unique values [2;3;4], frequencies [2:25;3:5;4:2]; `LOW_CARDINALITY_DESCRIPTIVE_METRIC`

Revised interpretation: signed-axis asymmetry is genuinely upper-tail and broad-distribution; total axis width has a low rank but small absolute effect size; median base-ray radius is typical; center displacement is algebraically linked to asymmetry; adaptive/guard counts are low-cardinality descriptors. The anchor is not described as multi-dimensionally extreme. `ANCHOR_SPECIFIC_CLAIMS_ONLY` is retained for claims tied to the locked anchor geometry, not because multiple independent extremeness dimensions were found.

### Sampled-skeleton limitation

- `MONOTONICITY_EVIDENCE_DOMAIN = SAMPLED_RADIAL_AXIS_SKELETON`
- `ANGULAR_INTERIOR_BETWEEN_SAMPLED_DIRECTIONS_NOT_DIRECTLY_EVALUATED`
- median of the 32 timestamp-specific median actual angular gaps: 6.63934332615 deg
- maximum actual angular gap observed: 63.5808596584 deg
- anchor median/maximum actual angular gaps: 6.64217571517/15.0621181357 deg
- guard-limited mixed-sign sectors: 73

Assumption (M) is strongly supported by the stored nonlinear-AC evaluations on the sampled radial/axis skeleton, including 49.83 million strictly two-dimensional comparable endpoint pairs with no observed scalar monotonicity counterexample. The angular interior between sampled directions is not directly covered by the existing AC campaign.

The 87,086 converged evaluations lie on signed-axis trajectories, 36 base radial directions per timestamp, adaptive radial directions, and coarse-sweep/bisection points. The 49.83 million count is a count of comparable endpoint pairs on that finite skeleton, not sampled interior points. Future box corners and arbitrary coupled-polytope interior points may not coincide with sampled trajectories. This limitation must carry forward into DOE Construction Policy.

### Corrected scientific interpretation

Stored attempts: 87,372; converged usable evaluations: 87,086; cross-trajectory comparable pairs: 50,641,519; equality-only: 85,456; non-equality principal pairs: 50,556,063; strict-2D pairs: 49,830,885. No raw negative Delta Vmin/Delta Vmax and no logical VMIN/VMAX contradictions were observed.

Finite skeleton evidence is not a theorem; comparable pairs are not sampled interior points; slack-pinned plateaus are not responsive Vmax evidence; rank extremeness is not effect size; algebraically linked metrics are not independent dimensions; all directional and symmetrized cardinal results are one diagnostic family; different active constraints do not share one pooled coefficient; and boundary reconciliation is not a new falsification experiment.

Current classification: `NO_MONOTONICITY_COUNTEREXAMPLE_OBSERVED_IN_STORED_EVALUATIONS`. Authoritative project classification: `POSTPRODUCTION_RESULT_AUDIT_COMPLETE_WITH_DOCUMENTED_LIMITATIONS`.
