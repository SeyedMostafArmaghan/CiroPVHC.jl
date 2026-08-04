"""Deterministically generate the TVPP interface architecture audit artifacts."""

from __future__ import annotations

import csv
from pathlib import Path


OUTPUT_DIR = Path(__file__).resolve().parent


def write_csv(name: str, header: tuple[str, ...], rows: list[tuple[object, ...]]) -> None:
    path = OUTPUT_DIR / name
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream, lineterminator="\n")
        writer.writerow(header)
        writer.writerows(rows)


INVENTORY_HEADER = (
    "file_path", "line_or_symbol", "variable_or_function", "current_semantic_meaning",
    "evidence", "classification", "required_action",
    "needed_before_next_radial_probe", "needed_only_before_final_tvpp",
)

INVENTORY_ROWS = [
    ("src/benchmark/dso_vpp_ac_map_stage0.jl", "8,36-67", "PILOT_DATES; load_profile; select_pilot_indices", "Selects exactly 96 half-hour profile rows for 2012-10-15 and 2012-10-16 by exact DateTime equality.", "Profile columns are load_multiplier and pv_profile; selection validates uniqueness, spacing, finiteness, and endpoints.", "PILOT_SPECIFIC_AND_ACCEPTABLE", "Preserve for Phase-B reproducibility; a final TVPP study should receive an explicit scenario horizon.", "no", "yes"),
    ("src/benchmark/dso_vpp_ac_map_stage0.jl", "26-27,109-111", "REFERENCE_PV_BUS; REFERENCE_PV_CAPACITY_KW; reference_pv_by_bus_kw", "A fixed 850 kW reference PV nameplate at bus 13 produces 850*f_t kW active injection.", "reference_pv_by_bus_kw[13] is assigned reference_capacity_kw*pv_factor.", "PILOT_SPECIFIC_AND_ACCEPTABLE", "Keep separate from controlled command and from any future TVPP resource aggregation.", "yes", "yes"),
    ("src/benchmark/dso_vpp_ac_map_stage0.jl", "70-86", "build_pilot_network", "Builds the full IEEE 33-bus radial DSO feeder; buses 13 and 30 do not define a subnetwork boundary.", "All 33 buses and 32 branches are loaded; topology root is bus 1.", "CORRECT", "No change for the pilot.", "no", "no"),
    ("src/data/ieee33.jl", "17,34,52-53,69-70", "load_data; branch_data", "Bus 13 has 60 kW/35 kvar nominal passive load; bus 30 has 200 kW/600 kvar nominal passive load. They are nonadjacent feeder buses on different downstream locations, not endpoints of a closed region.", "Branch 12 connects 12-13; branch 29 connects 29-30; no boundary construct joins them.", "CORRECT", "Treat passive loads independently from TVPP-controlled quantities.", "yes", "yes"),
    ("src/benchmark/dso_vpp_ac_map_stage0.jl", "89-116", "assemble_stage0_inputs(p13_vpp_kw,p30_vpp_kw)", "Accepts exactly two external active-power command scalars and inserts them as additive source injections at buses 13 and 30.", "vpp_injection_by_bus_kw[13]=p13; [30]=p30; the vector is added to reference PV.", "GENERALIZATION_REQUIRED_BEFORE_FINAL_TVPP", "Introduce a new map-based controlled-interface input for the final architecture; retain this signature as a Phase-B compatibility wrapper.", "no", "yes"),
    ("src/benchmark/dso_vpp_ac_map_stage0.jl", "117-123", "net_demand_pu", "Physical AC bus input uses scaled passive demand minus all active source injections; reactive input is scaled passive Q only.", "complex(pd*m-active_injection, qd*m)/10000.", "CORRECT", "Reuse the sign relation in a named interface conversion layer.", "yes", "yes"),
    ("src/benchmark/dso_vpp_ac_map_stage0.jl", "136-260", "primary_power_flow", "Solves the full radial constant-PQ AC feeder for the assembled net-demand vector and reports substation exchange and losses.", "Backward/forward sweep consumes net_demand_pu at every bus.", "CORRECT", "Keep on the DSO side; do not expose this function or topology to a coupled/box TVPP optimizer.", "no", "yes"),
    ("src/benchmark/dso_vpp_ac_map_stage0.jl", "297-359", "evaluate_point", "Looks up the selected profile row, assembles the reference PV and two commands, runs primary AC, then independently replays the same resolved active injections.", "Replay dictionary is {13: reference_pv+p13, 30: p30} with availability 1.0.", "PILOT_SPECIFIC_AND_ACCEPTABLE", "Preserve numerical behavior; add a future generalized evaluator rather than changing committed Phase-B semantics.", "no", "yes"),
    ("src/benchmark/dso_vpp_ac_map_stage0.jl", "369-440", "classify_voltage; evaluate_point result", "Voltage feasibility is replay-gated and based on 0.90/1.05 p.u.; result labels expose p13/p30 and fixed-zero q13/q30.", "classify_voltage compares replay extrema with VMIN_PU and VMAX_PU.", "DOCUMENTATION_OR_NAMING_DEFECT", "In new artifacts call these P13_command/P30_command; retain legacy field names as explicit aliases.", "yes", "yes"),
    ("src/validation/s1b_independent_replay.jl", "127-172", "replay_s1b_interval", "Treats dictionary values as unity-power-factor active injections and reconstructs net demand as passive P minus injection with passive Q unchanged.", "Docstring states PV unity power factor; lines 169-172 subtract active injection only.", "CORRECT", "A fixed-Q(P) final policy needs a replay API that accepts resolved P and Q interface vectors.", "no", "yes"),
    ("src/benchmark/dso_vpp_export_side_axis_scan.jl", "12,104-163", "AXES; evaluate_fixed_injection; evaluate_axis_point", "Defines exactly two one-at-a-time nonnegative experimental command axes at buses 13 and 30.", "AXES contains P13_VPP and P30_VPP; the inactive coordinate is set to zero.", "PILOT_SPECIFIC_AND_ACCEPTABLE", "Do not reinterpret the resulting limits as final PCC limits; use a new multi-interface DOE builder later.", "yes", "yes"),
    ("src/benchmark/dso_vpp_export_side_axis_scan.jl", "183-317,590-639", "adaptive_coarse_doubling; refine_bracket; scan_one_axis; run_scan", "Finds safe/upper-voltage brackets separately on each command coordinate for each timestamp and writes Phase-B artifacts.", "Only axis injection changes; reference PV and passive loads remain fixed for the timestamp.", "PILOT_SPECIFIC_AND_ACCEPTABLE", "No change or regeneration in this audit.", "no", "no"),
    ("src/benchmark/dso_vpp_export_side_axis_scan.jl", "459-472,515-545", "config_string; write_report", "Explicitly records Q_PV=Q_VPP13=Q_VPP30=0, no thermal/transformer limit, and warns that axis bounds are not a DOE or 2D feasible set.", "Resolved configuration and report text state all limitations.", "CORRECT", "Preserve; clarify command terminology only in new audit artifacts.", "yes", "no"),
    ("src/benchmark/dso_vpp_ac_anchored_linear_corner_audit.jl", "94-123", "committed_capacity_data", "Reads provenance-locked Phase-B axis command bounds for buses 13 and 30 from a committed Git blob.", "scales_kw is keyed only by 13 and 30; expected SHA-256 is enforced.", "PILOT_SPECIFIC_AND_ACCEPTABLE", "Never relabel these scales as PCC capacities without a separate semantic proof.", "yes", "yes"),
    ("src/benchmark/dso_vpp_ac_anchored_linear_corner_audit.jl", "318-365", "default_baseline_evaluator; run_analytical_audit", "Reuses the identical operating-point assembler at zero command, then derives all-bus voltage headroom and two topology coefficient vectors.", "Baseline path calls AxisScan.evaluate_fixed_injection(...,0,0); coefficients use injection_bus 13 and 30.", "CORRECT", "Preserve provenance-locked behavior.", "no", "no"),
    ("src/benchmark/dso_vpp_ac_anchored_linear_corner_audit.jl", "163-315", "analyze_envelope", "Evaluates all 33 bus upper-voltage inequalities but constructs a two-coordinate analytical geometry and a selected 2x2 bus-13/bus-30 intersection.", "Two coefficient vectors, 2x2 matrix, two-element P vector, and two-coordinate angle.", "PILOT_SPECIFIC_AND_ACCEPTABLE", "Do not generalize this historical audit in place; implement N-interface geometry separately for the final DOE.", "no", "yes"),
    ("src/data/types.jl", "97-101,240-246", "DOE", "Legacy generic data type represents one pcc_bus with independent time-varying import/export maxima.", "DOE contains one integer pcc_bus and two vectors; it is not used by the Phase-B pilot.", "GENERALIZATION_REQUIRED_BEFORE_FINAL_TVPP", "Replace or supersede with a multi-interface envelope type before coupled/box TVPP work.", "no", "yes"),
    ("src/data/resources.jl", "71-87", "build_default_doe", "Builds a synthetic single-bus DOE at bus 1 for generic scenarios, not a DSO-derived pilot interface region.", "Returns DOE(1, synthetic import maxima, synthetic export maxima).", "GENERALIZATION_REQUIRED_BEFORE_FINAL_TVPP", "Do not reuse as the final TVPP DOE; keep only as legacy fixture or mark deprecated.", "no", "yes"),
    ("src/solve/solve_s1b_central.jl", "6", "S1B_CANDIDATE_BUSES", "Defines buses 13,20,24,30 as centralized PV hosting-capacity candidate buses.", "The tuple is used by the S1-B centralized PV study, not by the Phase-B two-command pilot.", "NOT_APPLICABLE", "Do not infer that buses 20 and 24 are already TVPP interfaces.", "yes", "yes"),
    ("src/data/resources.jl", "1-68", "build_default_pv_units; build_default_evcs_units; build_default_bess_units", "Defines dispersed PV/EV/BESS fixtures at several buses, but no mapping from those resources to Phase-B interfaces or P_agg/P_PCC.", "PV buses 6/14/25/30, EV buses 18/22/25/33, BESS buses 14/30.", "GENERALIZATION_REQUIRED_BEFORE_FINAL_TVPP", "Create explicit resource-to-interface ownership/metering mappings; do not infer them from bus equality.", "no", "yes"),
    ("src/models/pv_model.jl", "11-48", "add_pv_hosting_variables!", "Aggregates PV decision variables by physical bus inside a network-coupled optimization model.", "Returns injection_by_bus_kw and requires full CaseData.", "GENERALIZATION_REQUIRED_BEFORE_FINAL_TVPP", "For coupled/box DOE, move resource scheduling behind a TVPP-side interface that has no topology/equations.", "no", "yes"),
    ("src/models/socp_network.jl", "103-217", "add_socp_network_constraints!", "Combines passive loads, optional load adders, controlled P/Q injections, voltage equations, and valid nonzero branch ratings in one central network model.", "Network variables and resource series meet in bus balance constraints.", "PILOT_SPECIFIC_AND_ACCEPTABLE", "Use only for the centralized benchmark; do not import this module into coupled/box TVPP models.", "no", "yes"),
    ("test/test_dso_vpp_ac_map_stage0_physical_inputs.jl", "8-146,266-350", "_independent_stage0_expected; physical-input tests", "Independently reconstructs fixed loads, reference PV, and the two command injection vectors and verifies bus-local effects.", "Tests assert deltas occur only at bus 13 or 30 and simultaneous injections add correctly.", "CORRECT", "Retain as the semantic regression anchor for Phase-B.", "yes", "no"),
    ("results/dso_vpp_ac_map_pilot/export_side_axis_capacity_bounds.csv", "header and axis rows", "axis; axis_bus; axis_capacity_kW", "Serializes safe endpoints of experimental command scans, not metered PCC powers.", "Schema has a generic axis_bus column but axis names and source fields remain P13_VPP/P30_VPP.", "DOCUMENTATION_OR_NAMING_DEFECT", "Consumers must label these P_command axis bounds and must not automatically publish them as PCC limits.", "yes", "yes"),
]


CALL_PATH_HEADER = (
    "path_id", "step_order", "file_path", "line_or_symbol", "call_or_operation",
    "input_semantics", "output_semantics",
)

CALL_PATH_ROWS = [
    ("PHASE_B_AXIS_SCAN", 1, "scripts/run_dso_vpp_export_side_axis_scan.jl", "55-123", "main -> ScanConfig -> load_canonical_data -> run_scan", "CLI/config values; defaults H=850, reference PV bus 13, V=0.90..1.05", "Validated Phase-B scan configuration"),
    ("PHASE_B_AXIS_SCAN", 2, "src/benchmark/dso_vpp_export_side_axis_scan.jl", "85-93", "load_canonical_data", "repository_root and pilot config", "IEEE-33 PilotNetwork, canonical S1BProfile, pilot indices"),
    ("PHASE_B_AXIS_SCAN", 3, "src/benchmark/dso_vpp_ac_map_stage0.jl", "36-43", "load_profile -> CiroPVHC.read_s1b_profile", "data_processed/ausgrid/ausgrid_halfhour_normalized.csv", "timestamps, load_multiplier, pv_profile"),
    ("PHASE_B_AXIS_SCAN", 4, "src/benchmark/dso_vpp_ac_map_stage0.jl", "46-67", "select_pilot_indices", "canonical timestamps", "96 exact half-hour indices over two locked dates"),
    ("PHASE_B_AXIS_SCAN", 5, "src/benchmark/dso_vpp_export_side_axis_scan.jl", "590-614", "run_scan loops data.indices and AXES", "each timestamp; axes bus 13 and bus 30", "one scan_one_axis result per timestamp/axis"),
    ("PHASE_B_AXIS_SCAN", 6, "src/benchmark/dso_vpp_export_side_axis_scan.jl", "183-317", "adaptive_coarse_doubling -> refine_bracket -> evaluate_axis_point", "nonnegative scalar command on one axis", "safe and upper-voltage-violating command endpoints"),
    ("PHASE_B_AXIS_SCAN", 7, "src/benchmark/dso_vpp_export_side_axis_scan.jl", "145-163", "evaluate_axis_point", "axis_bus, command_kw", "p13=command,p30=0 or p13=0,p30=command"),
    ("PHASE_B_AXIS_SCAN", 8, "src/benchmark/dso_vpp_export_side_axis_scan.jl", "104-115", "evaluate_fixed_injection -> Stage0.evaluate_point", "two active command scalars", "one fixed-injection AC/replay result"),
    ("PHASE_B_AXIS_SCAN", 9, "src/benchmark/dso_vpp_ac_map_stage0.jl", "297-317", "evaluate_point profile lookup -> assemble_stage0_inputs", "profile.load_multiplier[index], profile.pv_profile[index], H, p13, p30", "resolved physical bus input arrays"),
    ("PHASE_B_AXIS_SCAN", 10, "src/benchmark/dso_vpp_ac_map_stage0.jl", "109-116", "reference PV and command assembly", "reference PV=H*f_t; commands at buses 13/30", "active_injection_by_bus=reference_pv_by_bus+command_by_bus"),
    ("PHASE_B_AXIS_SCAN", 11, "src/benchmark/dso_vpp_ac_map_stage0.jl", "117-123", "load-vector and reactive-vector assembly", "IEEE bus pd/qd scaled by load multiplier", "net_demand=(pd*m-active_injection)+j(qd*m), divided by 10000 kW"),
    ("PHASE_B_AXIS_SCAN", 12, "src/benchmark/dso_vpp_ac_map_stage0.jl", "321-332,136-260", "primary_power_flow", "full 33-bus complex net demand", "AC voltage phasors, substation P/Q, losses, convergence/residual"),
    ("PHASE_B_AXIS_SCAN", 13, "src/benchmark/dso_vpp_ac_map_stage0.jl", "334-360", "replay_s1b_interval", "resolved injection dict {13:H*f_t+p13,30:p30}; Q commands absent", "independent replay voltages, residuals, and voltage-limit flag"),
    ("PHASE_B_AXIS_SCAN", 14, "src/benchmark/dso_vpp_ac_map_stage0.jl", "263-287,362-375", "replay validation and voltage testing", "primary/replay state plus VMIN=0.90, VMAX=1.05", "PASSED/nonconverged/residual/state status and voltage class"),
    ("PHASE_B_AXIS_SCAN", 15, "src/benchmark/dso_vpp_export_side_axis_scan.jl", "319-415,618-636", "row assembly and artifact writing", "capacity endpoints and every evaluated point", "capacity CSV, scan CSV, timing/resource report, topology diagnostic, manifest"),
    ("ANALYTICAL_AUDIT", 1, "scripts/run_dso_vpp_ac_anchored_linear_corner_audit.jl", "23-51", "main -> AuditConfig -> write_audit_artifacts", "locked timestamp and committed defaults", "analytical audit execution"),
    ("ANALYTICAL_AUDIT", 2, "src/benchmark/dso_vpp_ac_anchored_linear_corner_audit.jl", "94-123", "committed_capacity_data", "Phase-B Git blob and locked SHA-256", "two command-axis normalization scales and limiting rows"),
    ("ANALYTICAL_AUDIT", 3, "src/benchmark/dso_vpp_ac_anchored_linear_corner_audit.jl", "330-345", "run_analytical_audit -> load_canonical_data -> timestamp lookup", "exact DateTime 2012-10-15 13:00:00", "same network/profile index as Phase B"),
    ("ANALYTICAL_AUDIT", 4, "src/benchmark/dso_vpp_ac_anchored_linear_corner_audit.jl", "318-327,346-357", "default_baseline_evaluator -> evaluate_fixed_injection(0,0)", "zero p13/p30 command, H=850", "validated baseline AC/replay state and primary phasors"),
    ("ANALYTICAL_AUDIT", 5, "src/benchmark/dso_vpp_ac_map_stage0.jl", "297-359", "same operating-point assembly and AC/replay path", "same load row, PV row, fixed loads, Q assumptions", "same physical baseline input vector as Phase B"),
    ("ANALYTICAL_AUDIT", 6, "src/benchmark/dso_vpp_ac_anchored_linear_corner_audit.jl", "357-365", "baseline_v2, delta_v2, topology coefficient construction", "abs2(primary AC phasors); VMAX^2 headroom; injection buses 13/30", "33 headrooms and two 33-element coefficient vectors"),
    ("ANALYTICAL_AUDIT", 7, "src/benchmark/dso_vpp_export_side_axis_scan.jl", "716-737", "topology_coefficient", "candidate bus and experimental injection bus", "2*shared-path resistance coefficient"),
    ("ANALYTICAL_AUDIT", 8, "src/benchmark/dso_vpp_ac_anchored_linear_corner_audit.jl", "126-153,381-398", "axis_ranking and all_bus_rows", "all 33 upper-voltage inequalities", "per-bus linear command-axis limits and rankings"),
    ("ANALYTICAL_AUDIT", 9, "src/benchmark/dso_vpp_ac_anchored_linear_corner_audit.jl", "191-226", "selected 2x2 command-coordinate intersection", "bus-13 and bus-30 inequalities in P13/P30 command coordinates", "candidate command-coordinate intersection, condition number, residuals"),
    ("ANALYTICAL_AUDIT", 10, "src/benchmark/dso_vpp_ac_anchored_linear_corner_audit.jl", "230-315", "all-bus constraint evaluation", "candidate command intersection", "all-bus margins, near-binding/violated buses, classification, angles"),
    ("ANALYTICAL_AUDIT", 11, "src/benchmark/dso_vpp_ac_anchored_linear_corner_audit.jl", "616-633", "write_audit_artifacts", "analytical result", "all-bus, rankings, margins, summary, report, manifest"),
    ("FUTURE_INFORMATION_BOUNDARY", 1, "src/benchmark/dso_vpp_ac_map_stage0.jl", "89-260", "current DSO-side fixed-injection evaluator", "passive network data plus external injection commands", "network acceptance result; no EV/BESS scheduling"),
    ("FUTURE_INFORMATION_BOUNDARY", 2, "src/models/pv_model.jl; src/models/ev_model.jl", "module APIs", "current resource models", "full CaseData or TimeSeries plus resource definitions", "resource schedules presently designed for centralized use"),
    ("FUTURE_INFORMATION_BOUNDARY", 3, "src/data/types.jl", "97-101", "current legacy DOE", "one PCC bus and per-time box limits", "insufficient representation for dispersed multi-interface coupled DOE"),
]


DIMENSION_HEADER = (
    "file_path", "line_or_symbol", "assumption", "evidence", "classification",
    "required_action", "backward_compatibility", "artifact_regeneration",
    "scientific_results_change",
)

DIMENSION_ROWS = [
    ("src/benchmark/dso_vpp_ac_map_stage0.jl", "89-96", "Function signature has exactly p13_vpp_kw and p30_vpp_kw.", "Two scalar parameters, no collection of interfaces.", "GENERALIZATION_REQUIRED_BEFORE_FINAL_TVPP", "Add a new Dict/Vector-based interface API; keep wrapper.", "Keep existing positional signature for Phase-B replay.", "No existing artifacts; new final artifacts only.", "No for wrapper; final model results will be new."),
    ("src/benchmark/dso_vpp_ac_map_stage0.jl", "112-114", "Controlled injection vector writes only indices 13 and 30.", "Two literal assignments.", "GENERALIZATION_REQUIRED_BEFORE_FINAL_TVPP", "Assemble from explicit ControlledInterface entries.", "Preserve literal assignments in historical wrapper.", "No Phase-B regeneration.", "No for preserved pilot."),
    ("src/benchmark/dso_vpp_ac_map_stage0.jl", "136-160", "Primary power-flow wrapper takes exactly two command scalars.", "p13/p30 forwarded to assembler.", "GENERALIZATION_REQUIRED_BEFORE_FINAL_TVPP", "Generalized overload accepts resolved bus injection map.", "Old method delegates to generalized method.", "No Phase-B regeneration if byte-equivalent.", "None if behavior is identical."),
    ("src/benchmark/dso_vpp_ac_map_stage0.jl", "297-317", "Point evaluator takes exactly two command scalars.", "Fixed positional fields.", "GENERALIZATION_REQUIRED_BEFORE_FINAL_TVPP", "Add an interface-command record API.", "Keep old API as adapter.", "New schema version for final model.", "None for historical outputs."),
    ("src/benchmark/dso_vpp_ac_map_stage0.jl", "339-342", "Replay serialization contains keys 13 and 30 only.", "Literal Dict with two entries.", "GENERALIZATION_REQUIRED_BEFORE_FINAL_TVPP", "Pass resolved P/Q maps to a generalized replay.", "Preserve old dictionary in pilot wrapper.", "No Phase-B regeneration.", "None for pilot."),
    ("src/benchmark/dso_vpp_ac_map_stage0.jl", "397-400", "Returned fields are p13/p30 and q13/q30.", "Four bus-numbered fields.", "DOCUMENTATION_OR_NAMING_DEFECT", "Expose command_by_bus and q_command_by_bus in new API; aliases remain.", "Legacy field names retained.", "Final artifacts require new schema.", "No numerical change."),
    ("src/benchmark/dso_vpp_ac_map_stage0.jl", "458-479", "Stage-0 sampling is two-dimensional.", "Two Halton bases generate p13 and p30.", "PILOT_SPECIFIC_AND_ACCEPTABLE", "Do not reuse as N-dimensional DOE sampler.", "Freeze Phase-B plan.", "Never regenerate existing Stage-0 plan.", "Not applicable."),
    ("src/benchmark/dso_vpp_ac_map_stage0.jl", "484-496", "Warm-start distance is Euclidean hypot over two coordinates.", "hypot(p13 difference,p30 difference).", "PILOT_SPECIFIC_AND_ACCEPTABLE", "Use norm over ordered interface vector in a new implementation.", "Freeze existing behavior.", "No existing artifacts.", "Not applicable."),
    ("src/benchmark/dso_vpp_ac_map_stage0.jl", "525-552,638-676", "CSV schemas have separate p13/p30 and q13/q30 columns.", "Bus-numbered columns are serialized.", "PILOT_SPECIFIC_AND_ACCEPTABLE", "Version new generalized schemas; do not rewrite old CSVs.", "Readers keep legacy schema support.", "New final artifacts only.", "No."),
    ("src/benchmark/dso_vpp_ac_map_stage0.jl", "601-635", "Authoritative plan requires exactly p13_vpp_kw and p30_vpp_kw columns.", "Required tuple contains both literal names.", "PILOT_SPECIFIC_AND_ACCEPTABLE", "Freeze for provenance; new plans use long-form interface rows.", "Legacy reader unchanged.", "No regeneration.", "No."),
    ("src/benchmark/dso_vpp_ac_map_stage0.jl", "1096-1136", "Before/after comparison schema has P13_VPP and P30_VPP columns.", "Two parsed fields and two output columns.", "PILOT_SPECIFIC_AND_ACCEPTABLE", "Do not generalize historical repair artifact.", "Freeze.", "No regeneration.", "No."),
    ("src/benchmark/dso_vpp_export_side_axis_scan.jl", "12", "AXES is a hard-coded two-element tuple.", "P13_VPP bus 13; P30_VPP bus 30.", "PILOT_SPECIFIC_AND_ACCEPTABLE", "Final interface set must be data-driven in a separate module.", "Keep tuple for Phase B.", "No regeneration.", "No."),
    ("src/benchmark/dso_vpp_export_side_axis_scan.jl", "33-46,319-347", "Scan schema writes vpp_p13_kw and vpp_p30_kw.", "Two fixed output fields.", "PILOT_SPECIFIC_AND_ACCEPTABLE", "Use long-form interface command records for final studies.", "Retain legacy schema.", "New artifacts only.", "No."),
    ("src/benchmark/dso_vpp_export_side_axis_scan.jl", "145-152", "Axis validation permits only bus 13 or 30.", "axis_bus in (13,30); ternary assignments.", "PILOT_SPECIFIC_AND_ACCEPTABLE", "Do not expand historical scanner; implement generalized interface scans separately.", "Historical behavior unchanged.", "No regeneration.", "No."),
    ("src/benchmark/dso_vpp_export_side_axis_scan.jl", "470-472", "Manifest text names exactly two Q commands and two axes.", "Q_VPP13, Q_VPP30, axes=P13_VPP;P30_VPP.", "PILOT_SPECIFIC_AND_ACCEPTABLE", "Preserve as truthful Phase-B metadata.", "Freeze.", "No regeneration.", "No."),
    ("src/benchmark/dso_vpp_export_side_axis_scan.jl", "767-830", "Topology diagnostic loops and indexes buses 13 and 30.", "Two literal loops and dictionaries.", "PILOT_SPECIFIC_AND_ACCEPTABLE", "Treat as two-axis diagnostic only.", "Freeze.", "No regeneration.", "No."),
    ("scripts/run_dso_vpp_export_side_axis_scan.jl", "112-114", "Evaluation estimates multiply by exactly two axes.", "intervals*2.", "PILOT_SPECIFIC_AND_ACCEPTABLE", "Use length(config.interfaces) in any new runner.", "No change to Phase-B runner.", "No regeneration.", "No."),
    ("src/benchmark/dso_vpp_ac_anchored_linear_corner_audit.jl", "105-123", "Committed capacity parsing builds dictionaries for buses 13 and 30.", "Comprehensions use (13,30).", "PILOT_SPECIFIC_AND_ACCEPTABLE", "Keep provenance lock; do not generalize.", "Required for committed SHA semantics.", "Never regenerate Phase-B.", "No."),
    ("src/benchmark/dso_vpp_ac_anchored_linear_corner_audit.jl", "163-200", "Envelope accepts exactly two coefficient vectors and constructs a 2x2 matrix.", "coefficients_13, coefficients_30; selected rows i13/i30.", "PILOT_SPECIFIC_AND_ACCEPTABLE", "Build an N-interface polyhedral representation separately.", "Freeze analytical audit.", "No regeneration.", "No."),
    ("src/benchmark/dso_vpp_ac_anchored_linear_corner_audit.jl", "217-235", "Intersection, residual, and margins use two command coordinates.", "Two-element p_pu and residual; two contributions.", "PILOT_SPECIFIC_AND_ACCEPTABLE", "Use generic linear algebra for final coupled DOE.", "Freeze.", "No regeneration.", "No."),
    ("src/benchmark/dso_vpp_ac_anchored_linear_corner_audit.jl", "269-314", "Angles and cross-axis inequalities are two-dimensional.", "atan(y,x) and two named inequalities.", "PILOT_SPECIFIC_AND_ACCEPTABLE", "Do not represent N-D geometry with a single angle.", "Freeze.", "No regeneration.", "No."),
    ("src/benchmark/dso_vpp_ac_anchored_linear_corner_audit.jl", "427-439,448-515", "Artifact filenames and summary fields split axis 13 and axis 30.", "Separate ranking13/ranking30 and p13/p30 fields.", "PILOT_SPECIFIC_AND_ACCEPTABLE", "Keep historical artifact contract; version final artifacts.", "Legacy readers remain.", "No regeneration.", "No."),
    ("test/test_dso_vpp_ac_map_stage0_physical_inputs.jl", "266-350", "Fixtures assert bus-13-only, bus-30-only, and simultaneous two-command cases.", "findall(delta)!=0 equals [13] or [30].", "PILOT_SPECIFIC_AND_ACCEPTABLE", "Retain; add separate N-interface tests later.", "Tests remain stable.", "No.", "No."),
    ("test/test_dso_vpp_export_side_axis_scan.jl", "26-30,128-135", "Tests split rows13/rows30 and assert inactive coordinate zero.", "Two fixed row filters and topology checks.", "PILOT_SPECIFIC_AND_ACCEPTABLE", "Retain as Phase-B regression tests.", "Stable.", "No.", "No."),
    ("test/test_dso_vpp_ac_anchored_linear_corner_audit.jl", "121-190", "Expected rankings, intersection, and labels are bus-13/bus-30-specific.", "Checks EXPOSED_LINEAR_CORNER_13_30 and two axis capacities.", "PILOT_SPECIFIC_AND_ACCEPTABLE", "Retain provenance tests; add new generic geometry tests separately.", "Stable.", "No.", "No."),
    ("results/dso_vpp_ac_map_pilot/*.csv", "legacy headers", "Committed schemas encode p13/p30 or coefficient_13/coefficient_30.", "Headers in Stage-0, Phase-B, analytical, and provenance artifacts.", "PILOT_SPECIFIC_AND_ACCEPTABLE", "Never rewrite; new final artifacts need schema_version and long-form interface identifiers.", "Legacy artifacts remain authoritative.", "No existing regeneration.", "No."),
    ("src/data/types.jl", "97-101", "DOE represents exactly one pcc_bus.", "Single scalar bus plus import/export box vectors.", "GENERALIZATION_REQUIRED_BEFORE_FINAL_TVPP", "Supersede with multi-interface coupled/box envelope types.", "Keep DOE as deprecated legacy fixture if tests need it.", "Only new final artifacts.", "Final scientific results will be newly computed."),
]


TERMINOLOGY_HEADER = (
    "occurrence_path", "line_or_symbol", "term", "current_usage", "classification",
    "rationale", "required_change",
)

TERMINOLOGY_ROWS = [
    ("src/benchmark/dso_vpp_ac_map_stage0.jl", "module name and 868", "DSO-VPP", "Names the pilot fixed-injection study.", "PILOT_SHORTCUT_BUT_EXPLICIT", "The study contains no internal VPP resource model, but the report explicitly calls its coordinates direct bus injections.", "Prefer DSO-TVPP pilot in future documents; retain module name for compatibility."),
    ("src/benchmark/dso_vpp_ac_map_stage0.jl", "94-95,107,112-116", "VPP injection", "Labels the two external additive active command components.", "AMBIGUOUS", "No aggregation, ownership, schedule, or PCC meter is computed.", "Use command_injection or P_command in new APIs; legacy aliases remain."),
    ("src/benchmark/dso_vpp_ac_map_stage0.jl", "875-876", "boundary variables", "States that coordinates are direct active-power injections and gives their signs.", "CORRECT", "This accurately describes implemented numerical semantics.", "No change required."),
    ("src/benchmark/dso_vpp_ac_map_stage0.jl", "877", "VPP connection points", "Calls buses 13 and 30 VPP connection points.", "AMBIGUOUS", "They are pilot controlled-injection buses; physical PCC metering is not represented.", "Use controlled-injection buses or experimental interface buses in future text."),
    ("src/benchmark/dso_vpp_export_side_axis_scan.jl", "12,472", "P13_VPP/P30_VPP", "Names the two command axes.", "PILOT_SHORTCUT_BUT_EXPLICIT", "Axis report says they are one-axis commands and not a DOE.", "Add explicit P_command interpretation in consuming documents; do not rename committed fields."),
    ("src/benchmark/dso_vpp_export_side_axis_scan.jl", "544", "DOE", "Explicitly says the Cartesian product of axis bounds is not a DOE.", "CORRECT", "Prevents overclaiming.", "No change."),
    ("src/benchmark/dso_vpp_ac_anchored_linear_corner_audit.jl", "533-570", "VPP commands/P13/P30", "Describes zero baseline commands and a two-command analytical intersection.", "PILOT_SHORTCUT_BUT_EXPLICIT", "The report traces the exact command path and disclaims a complete 2D inclusion relation.", "Future summaries should say command-coordinate intersection."),
    ("src/benchmark/dso_vpp_operating_point_provenance.jl", "368-371,493", "VPP P/Q command", "Explicitly identifies P13/P30 and Q13/Q30 as commands.", "CORRECT", "This is the clearest current semantic label and matches the authoritative provenance audit.", "Reuse this terminology."),
    ("src/benchmark/dso_vpp_operating_point_provenance.jl", "509", "DOSS", "States that no DOSS equivalence is asserted.", "CORRECT", "Avoids conflating analytical area with a DOSS formulation.", "No change."),
    ("src/data/types.jl", "97-101", "PCC", "Legacy DOE type has one pcc_bus.", "AMBIGUOUS", "It may be suitable for a single-interface fixture but cannot express the intended dispersed multi-interface TVPP.", "Do not reuse unchanged for the final architecture."),
    ("src/data/resources.jl", "71-87", "DOE/PCC bus 1", "Creates a synthetic box at the feeder root.", "PILOT_SHORTCUT_BUT_EXPLICIT", "It is a generic fixture and is unused by Phase B, but it is not a DSO-derived multi-interface DOE.", "Deprecate or clearly mark fixture-only before final DOE work."),
    ("src/data/scenarios.jl", "5,7", "TVPP/DOE", "Scenario descriptions name future smart-EV TVPP and DOE cases.", "AMBIGUOUS", "Names exist without implemented DSO-TVPP information boundaries or multi-interface DOE types.", "Treat as roadmap labels, not evidence of implementation."),
    ("docs/S1C_CURTAILMENT_BENCHMARK.md", "55,100", "PCC", "Uses PCC for the feeder upstream strict no-export balance in a separate PV hosting study.", "CORRECT", "This is a different physical quantity from pilot bus commands.", "Keep studies explicitly separated."),
    ("docs/METHODOLOGY_DECISIONS_S1.md", "36,124,139", "PCC/DOE/TVPP", "Discusses feeder no-export balance and future scenario ordering.", "PILOT_SHORTCUT_BUT_EXPLICIT", "It does not claim buses 13 and 30 form one PCC or microgrid.", "Add final multi-interface definitions when that model is implemented."),
    ("repository search", "no occurrence", "microgrid/islandable/geographically contiguous/common PCC", "No source, test, current pilot report, or documentation statement models buses 13 and 30 as a microgrid boundary, islandable area, contiguous area, or one common PCC.", "CORRECT", "Absence confirmed by case-insensitive search; unrelated uses of contiguous refer to timestamps or numeric IDs.", "Maintain this distinction."),
    ("repository search", "no material occurrence", "aggregator/point of connection", "No implemented aggregator object or explicit point-of-connection metering abstraction exists for the pilot.", "AMBIGUOUS", "P_agg and P_PCC are therefore not represented as distinct first-class quantities.", "Add explicit types and equations before final TVPP coupling."),
    ("src/solve/solve_s1b_central.jl", "6", "buses 13,20,24,30", "Centralized PV hosting candidate-bus tuple.", "CORRECT", "It is not an interface mapping and must not be presented as one.", "Document this distinction in final architecture work."),
]


SIGN_HEADER = (
    "concept", "file_path", "line_or_symbol", "implemented_formula", "positive_meaning",
    "negative_meaning", "conversion_or_caveat", "classification",
)

SIGN_ROWS = [
    ("Network active net demand", "src/benchmark/dso_vpp_ac_map_stage0.jl", "117-123", "p_net_i=(pd_i*m-P_ref_i-P_command_i)/BASE_KW", "Consumption from the network", "Net export/injection into the network", "Matches the requested network convention exactly.", "SIGN_CONVENTION_MATCHES_TARGET_ARCHITECTURE"),
    ("Reference PV", "src/benchmark/dso_vpp_ac_map_stage0.jl", "109-116", "P_ref_13=H*f_t; active_injection=P_ref+P_command", "Positive source injection", "Negative reference PV is rejected by nonnegative H and f_t", "Reference PV is separate from the command and is not proven to be TVPP-controlled.", "SIGN_CONVENTION_MATCHES_TARGET_ARCHITECTURE"),
    ("P13/P30 command", "src/benchmark/dso_vpp_ac_map_stage0.jl", "112-116,397-398", "P_command_i is added to source injection and therefore subtracted from p_net", "Export/source injection into the feeder", "Import/additional consumption in Stage-0; Phase-B axis scan restricts commands to nonnegative", "Names say VPP but semantics are direct experimental commands.", "LOCAL_NAMING_AMBIGUITY_ONLY"),
    ("Bus-13 observed net active export", "src/data/ieee33.jl; src/benchmark/dso_vpp_ac_map_stage0.jl", "17;109-123", "P_bus13_export=H*f_t+P13_command-60*m", "Net export at bus 13", "Net import at bus 13", "This is not equal to P13_command unless reference PV and passive load cancel or are explicitly outside the PCC meter.", "SIGN_CONVENTION_MATCHES_TARGET_ARCHITECTURE"),
    ("Bus-30 observed net active export", "src/data/ieee33.jl; src/benchmark/dso_vpp_ac_map_stage0.jl", "34;112-123", "P_bus30_export=P30_command-200*m", "Net export at bus 30", "Net import at bus 30", "This is not equal to P30_command when local passive load is inside the observed interface.", "SIGN_CONVENTION_MATCHES_TARGET_ARCHITECTURE"),
    ("Replay active injection", "src/validation/s1b_independent_replay.jl", "127-172", "p_net=pd*m-capacity*availability", "Positive dictionary value is source injection", "Negative values are accepted as added demand if supplied", "Stage0 passes already time-resolved injections with availability 1.0.", "SIGN_CONVENTION_MATCHES_TARGET_ARCHITECTURE"),
    ("Substation active power", "src/benchmark/dso_vpp_ac_map_stage0.jl", "231-255", "P_sub=real(sum sending-end root branch power)", "Feeder import from upstream", "Feeder export to upstream", "Opposite sign to TVPP export-positive convention; it is a feeder-root measurement, not either pilot command.", "SIGN_CONVENTION_CONSISTENT_BUT_DIFFERENT_NOTATION"),
    ("Target TVPP interface mapping", "future architecture", "not implemented", "p_net=passive_load-P_PCC", "P_PCC export to network", "P_PCC import from network", "Structurally identical to current injection subtraction, but a meter/resource-boundary definition is required before identifying command with P_PCC.", "SIGN_CONVENTION_MATCHES_TARGET_ARCHITECTURE"),
    ("Reactive net demand", "src/benchmark/dso_vpp_ac_map_stage0.jl", "119-122,399-400", "q_net=qd*m; Q13_command=Q30_command=0", "Positive kvar is inductive/reactive consumption", "Negative kvar would be capacitive injection but no pilot command path exists", "No P-dependent interface Q is assembled.", "SIGN_CONVENTION_MATCHES_TARGET_ARCHITECTURE"),
]


VOLTAGE_HEADER = (
    "scope", "file_path", "line_or_symbol", "limit_or_rating", "actual_value",
    "enforcement", "scenario_specific", "classification", "evidence_or_required_action",
)

VOLTAGE_ROWS = [
    ("Phase-B/Stage-0 production", "src/benchmark/dso_vpp_ac_map_stage0.jl", "11-12,279-287,352-353", "Voltage band", "0.90 <= V <= 1.05 p.u.", "classify_voltage plus replay arguments", "pilot-wide locked values", "CONSISTENT", "Both primary classification and replay use the same constants."),
    ("Phase-B scan production", "src/benchmark/dso_vpp_export_side_axis_scan.jl", "53-54,67-72", "Voltage band", "0.90 <= V <= 1.05 p.u.", "Config is rejected unless equal to Stage0 constants", "pilot-wide locked values", "CONSISTENT", "No independent alternative limit can silently enter."),
    ("Phase-B runner", "scripts/run_dso_vpp_export_side_axis_scan.jl", "90-91", "CLI defaults", "Vmin=0.90; Vmax=1.05", "Passed into ScanConfig", "pilot runner", "CONSISTENT", "Matches production constants."),
    ("Analytical audit production", "src/benchmark/dso_vpp_ac_anchored_linear_corner_audit.jl", "29,47-49,357-360", "Upper-voltage headroom", "Vmax=1.05", "Validated against Stage0 VMAX; analytical inequalities are upper-only", "locked analytical audit", "CONSISTENT", "Lower limit is not part of this upper-voltage linear diagnostic; baseline AC replay still uses 0.90."),
    ("AC replay production", "src/validation/s1b_independent_replay.jl", "143-146,311-312", "Default voltage band", "0.90 <= V <= 1.05 p.u.", "voltage_limits_satisfied", "S1B/pilot default; caller-overridable", "CONSISTENT", "Stage0 passes explicit locked values."),
    ("Centralized S1B production", "src/solve/solve_s1b_central.jl", "11-12", "Voltage band", "0.90 <= V <= 1.05 p.u.", "centralized model/replay", "S1B scenario", "CONSISTENT", "Separate study but same project band."),
    ("S1B method benchmark production", "src/benchmark/s1b_method_benchmark.jl", "20-21", "Voltage band", "0.90 <= V <= 1.05 p.u.", "SOCP/NLP/replay", "one-day benchmark", "CONSISTENT", "Separate diagnostic."),
    ("Generic CaseData fixture", "src/data/resources.jl", "90-105", "Voltage band", "0.90 <= V <= 1.10 p.u.", "CaseData field values", "legacy generic fixture", "SCENARIO_SPECIFIC_NOT_PILOT", "Do not use to describe Phase B."),
    ("S0 baseline config production", "src/data/s0_types.jl", "159-162", "Operational/diagnostic bands", "0.95..1.05 operational; 0.80..1.10 diagnostic", "S0 baseline reporting config", "older baseline framework", "SCENARIO_SPECIFIC_NOT_PILOT", "The later project decision supersedes 0.95 for the current pilot."),
    ("S1 paper-study production", "src/solve/solve_s1_pv_only.jl", "118-120", "Paper defaults", "0.95 <= V <= 1.05 p.u.", "paper-case construction", "legacy paper scenario", "SCENARIO_SPECIFIC_NOT_PILOT", "Not a universal project limit."),
    ("S2 unmanaged-EV production", "src/CiroPVHC.jl", "51-58", "Scenario defaults", "0.95 <= V <= 1.05 p.u.", "S2 config", "legacy unmanaged-EV scenario", "SCENARIO_SPECIFIC_NOT_PILOT", "Not used by Phase B."),
    ("S1 paper runner", "scripts/run_s1_pv_only_paper.jl", "6-7", "Paper constants", "0.95 <= V <= 1.05 p.u.", "runner", "legacy paper scenario", "SCENARIO_SPECIFIC_NOT_PILOT", "No current pilot report cites this as universal."),
    ("S1 paper snapshot runner", "scripts/run_s1_pv_only_paper_snapshot.jl", "6-7", "Paper constants", "0.95 <= V <= 1.05 p.u.", "runner", "legacy paper snapshot", "SCENARIO_SPECIFIC_NOT_PILOT", "Not Phase B."),
    ("S1 paper lexical snapshot runner", "scripts/run_s1_pv_only_paper_snapshot_lexi.jl", "6-7", "Paper constants", "0.95 <= V <= 1.05 p.u.", "runner", "legacy paper snapshot", "SCENARIO_SPECIFIC_NOT_PILOT", "Not Phase B."),
    ("S1 paper final snapshot runner", "scripts/run_s1_pv_only_paper_snapshot_final.jl", "7-8", "Paper constants", "0.95 <= V <= 1.05 p.u.", "runner", "legacy paper snapshot", "SCENARIO_SPECIFIC_NOT_PILOT", "Not Phase B."),
    ("Pilot test", "test/test_dso_vpp_ac_map_stage0.jl", "5-46", "Production constants exercised", "0.90/1.05 through module", "evaluated classifications", "pilot test", "CONSISTENT", "No alternate pilot limit."),
    ("Axis-scan test", "test/test_dso_vpp_export_side_axis_scan.jl", "9-61,71-120", "Production config and synthetic 1.049/1.051 bracket", "around Vmax=1.05", "smoke plus refinement unit test", "pilot test", "CONSISTENT", "Synthetic points test stopping logic, not a new project limit."),
    ("Analytical-audit test", "test/test_dso_vpp_ac_anchored_linear_corner_audit.jl", "66-168", "Production AuditConfig", "Vmax=1.05", "baseline/headroom/corner assertions", "pilot test", "CONSISTENT", "No 0.95 lower-limit claim."),
    ("S1B centralized tests", "test/test_s1b_central.jl; test/test_s1b_method_benchmark.jl", "29-51", "Model bounds", "0.90 <= V <= 1.05 p.u.", "explicit JuMP bound assertions", "S1B tests", "CONSISTENT", "Supports the current project band in S1B."),
    ("S0 voltage-count unit test", "test/test_s0_baseline.jl", "42-45", "Synthetic function input", "0.95 and 1.05", "pure threshold-count test", "unit-test fixture", "SCENARIO_SPECIFIC_NOT_PILOT", "Does not define Phase-B policy."),
    ("S1 PV tests", "test/test_s1_pv_only.jl", "48-49,76-77,120-121,164-165,207-225,255-256", "Multiple fixture bands", "0.90..1.10 and 0.95..1.05", "scenario-specific model and classification tests", "legacy fixture tests", "SCENARIO_SPECIFIC_NOT_PILOT", "Do not cite as universal."),
    ("Branch ratings", "src/data/ieee33.jl", "76-81", "Line smax", "0.0 means missing", "not enforced as zero capacity", "IEEE-33 source data", "VALID_MISSING_DATA_HANDLING", "No documented line ratings exist."),
    ("Pilot network guard", "src/benchmark/dso_vpp_ac_map_stage0.jl", "84-85", "Line ratings", "requires every smax_kva == 0.0", "throws if nonzero ratings appear", "pilot-specific", "VOLTAGE_ONLY", "The AC sweep contains no thermal constraint."),
    ("Generic SOCP network", "src/models/socp_network.jl", "169-177", "Line ratings", "enforced only when smax_pu > 0", "SOC apparent-power and current bounds", "centralized models only", "VALID_MISSING_DATA_HANDLING", "Not invoked by the Phase-B AC sweep."),
    ("Transformer", "src/benchmark/dso_vpp_export_side_axis_scan.jl", "470-472,525-526", "Transformer rating", "none", "no constraint", "pilot", "VOLTAGE_ONLY", "No transformer object or documented rating is read."),
    ("Pilot reports", "results/dso_vpp_ac_map_pilot/README.md; results/dso_vpp_ac_map_pilot/export_side_axis_report.md", "15-16;7-8", "Voltage/equipment scope", "0.90..1.05; no thermal or transformer limit", "descriptive", "pilot", "CORRECT", "No current non-archived pilot Markdown report contains 0.95."),
]


RECOMMENDED_HEADER = (
    "priority", "change_type", "affected_files", "proposal", "proposed_types_or_structures",
    "backward_compatibility", "required_tests", "artifact_regeneration",
    "scientific_results_change", "required_before_next_radial_probe",
    "required_before_final_tvpp", "status",
)

RECOMMENDED_ROWS = [
    ("P0", "Semantic naming", "new interface module; future reports", "Define P_command, P_agg, and P_PCC independently and document meter boundaries.", "PowerCommand; AggregateResourcePower; InterfaceMeasurement", "Keep p13_vpp_kw/p30_vpp_kw as read-only legacy aliases.", "Unit tests for definitions, signs, and non-equivalence with local net load.", "Only new artifacts; never rewrite Phase-B.", "No for old results.", "yes", "yes", "DEFERRED_STRUCTURAL_CHANGE"),
    ("P0", "Multi-interface input", "new DSO interface evaluator; optional wrapper near src/benchmark/dso_vpp_ac_map_stage0.jl", "Replace positional p13/p30 in final code with an ordered map of controlled interfaces.", "ControlledInterface{id,bus,q_policy}; InterfaceCommand{interface_id,p_kw,q_kvar}", "Historical Stage0 methods delegate without changing bytes or values.", "1,2,4-interface assembly tests; duplicate bus/interface validation; legacy equivalence.", "New schema/version only.", "No if adapter-equivalent.", "no", "yes", "DEFERRED_STRUCTURAL_CHANGE"),
    ("P0", "Physical interface conversion", "new DSO-side assembly module", "Make p_net=passive_load+non_tvpp_load-non_tvpp_generation-P_PCC an explicit named conversion.", "DSOOperatingPoint; InterfaceInjectionVector", "Pilot adapter supplies reference PV and commands exactly as today.", "Independent reconstruction and power-balance tests at buses with local load/reference PV.", "No old regeneration.", "No for pilot; final results new.", "yes", "yes", "DEFERRED_STRUCTURAL_CHANGE"),
    ("P0", "Information separation", "new src/dso and src/tvpp modules; future solvers", "Keep AC topology/equations only on the DSO side; coupled/box TVPP receives only an exogenous envelope and resource data.", "DSOModel; TVPPPortfolio; CoupledDOE; BoxDOE", "Centralized benchmark may continue using combined CaseData as a separate architecture.", "Dependency-boundary test that TVPP modules do not import network equations/topology.", "New artifacts only.", "Creates new comparison results.", "no", "yes", "DEFERRED_STRUCTURAL_CHANGE"),
    ("P0", "DOE representation", "src/data/types.jl; src/data/resources.jl or successor", "Supersede the single-pcc DOE with multi-interface coupled and box envelopes.", "CoupledDOE(interface_ids,A,b); BoxDOE(interface_ids,p_min,p_max)", "Retain DOE as deprecated fixture; explicit conversion only for one interface.", "Dimension/order validation; E_box subset E_coupled tests; serialization round trip.", "Legacy DOE artifacts unchanged; final DOE artifacts new.", "Final scientific values will be newly computed.", "no", "yes", "DEFERRED_STRUCTURAL_CHANGE"),
    ("P1", "Resource aggregation", "future TVPP resource module; existing PV/EV/BESS adapters", "Map each PV/EV/BESS resource to a TVPP and metered interface without assuming bus contiguity.", "TVPPResourcePortfolio; ResourceInterfaceMap", "Existing centralized resource fixtures remain usable through adapters.", "Dispersed buses, multiple resources per interface, and resource on non-interface bus tests.", "New artifacts only.", "Final scheduling results new.", "no", "yes", "DEFERRED_STRUCTURAL_CHANGE"),
    ("P1", "Reactive policy", "new interface Q-policy module; generalized replay", "Support a fixed P-dependent Q policy for a P-only DOE; do not add Q as an independent DOE dimension unless separately authorized.", "abstract QPolicy; UnityPowerFactor; FixedPowerFactorPolicy", "Pilot uses UnityPowerFactor and remains Q=0.", "Lagging/leading/unity sign tests; P=0; saturation policy; replay equivalence.", "No Phase-B regeneration.", "No for pilot; final acceptance region may change when policy is applied.", "no", "yes", "DEFERRED_STRUCTURAL_CHANGE"),
    ("P1", "N-dimensional geometry", "new DOE construction module", "Represent all-bus interface inequalities in N dimensions; preserve historical 2x2 analytical audit unchanged.", "HalfSpaceEnvelope{interface_ids,A,b}; optional polytope utilities", "No changes to locked analytical artifacts.", "1D/2D/4D synthetic polytopes; all-bus constraint and ordering tests.", "New final artifacts only.", "New DOE/HC results.", "no", "yes", "DEFERRED_STRUCTURAL_CHANGE"),
    ("P1", "Equipment ratings", "network data types and DSO constraint builder", "Represent missing ratings explicitly and enforce only documented line/transformer ratings.", "Union{Missing,Float64} rating fields or validated rating registry", "Zero-as-missing legacy import adapter.", "Missing/zero/documented rating tests; no synthetic fallback.", "Existing pilot stays voltage-only.", "Only future results with valid ratings may change.", "no", "yes", "DEFERRED_STRUCTURAL_CHANGE"),
    ("P1", "Voltage policy", "scenario configuration and reports", "Use one explicit scenario voltage-band object; never infer 0.95 from legacy scripts.", "VoltageBand{vmin_pu,vmax_pu,provenance}", "Pilot adapter locks 0.90/1.05.", "Cross-path equality tests for primary, replay, DOE builder, and reports.", "No old regeneration.", "None if values unchanged.", "yes", "yes", "DEFERRED_STRUCTURAL_CHANGE"),
    ("P2", "Schema versioning", "future CSV/JSON artifacts", "Use long-form rows keyed by interface_id/bus and include quantity_kind=P_command/P_agg/P_PCC.", "schema_version; interface_id; quantity_kind; sign_convention", "Readers retain legacy two-column support.", "Round-trip and legacy-reader tests.", "Existing artifacts remain byte-identical.", "No.", "no", "yes", "DEFERRED_STRUCTURAL_CHANGE"),
    ("P2", "Terminology cleanup", "future comments, reports, plots, labels", "Use controlled-injection bus for Phase-B coordinates and reserve PCC for a defined physical meter.", "No structural type required.", "Do not rename committed artifact columns.", "Text regression search forbidding microgrid/common-PCC claims in final TVPP docs.", "Only future docs.", "No.", "yes", "yes", "DEFERRED_TERMINOLOGY_CHANGE"),
]


REPORT = """# TVPP interface architecture audit

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
"""


def main() -> None:
    write_csv("tvpp_interface_architecture_inventory.csv", INVENTORY_HEADER, INVENTORY_ROWS)
    write_csv("tvpp_interface_architecture_call_paths.csv", CALL_PATH_HEADER, CALL_PATH_ROWS)
    write_csv("tvpp_interface_architecture_hardcoded_dimensions.csv", DIMENSION_HEADER, DIMENSION_ROWS)
    write_csv("tvpp_interface_architecture_terminology.csv", TERMINOLOGY_HEADER, TERMINOLOGY_ROWS)
    write_csv("tvpp_interface_architecture_sign_conventions.csv", SIGN_HEADER, SIGN_ROWS)
    write_csv("tvpp_interface_architecture_voltage_and_ratings.csv", VOLTAGE_HEADER, VOLTAGE_ROWS)
    write_csv("tvpp_interface_architecture_recommended_changes.csv", RECOMMENDED_HEADER, RECOMMENDED_ROWS)
    report_path = OUTPUT_DIR / "tvpp_interface_architecture_audit_report.md"
    report_path.write_text(REPORT.rstrip() + "\n", encoding="utf-8", newline="\n")

    expected = {
        "tvpp_interface_architecture_audit_report.md",
        "tvpp_interface_architecture_inventory.csv",
        "tvpp_interface_architecture_call_paths.csv",
        "tvpp_interface_architecture_hardcoded_dimensions.csv",
        "tvpp_interface_architecture_terminology.csv",
        "tvpp_interface_architecture_sign_conventions.csv",
        "tvpp_interface_architecture_voltage_and_ratings.csv",
        "tvpp_interface_architecture_recommended_changes.csv",
    }
    missing = sorted(name for name in expected if not (OUTPUT_DIR / name).is_file())
    if missing:
        raise RuntimeError(f"missing audit artifacts: {missing}")
    for name in sorted(expected):
        if (OUTPUT_DIR / name).stat().st_size == 0:
            raise RuntimeError(f"empty audit artifact: {name}")


if __name__ == "__main__":
    main()
