#!/usr/bin/env python3
"""Build the locked DOE production-probe preregistration artifacts.

This program performs deterministic data selection and evidence extraction only.
It never calls a power-flow evaluator, optimizer, or production-probe runner.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROFILE_PATH = ROOT / "data_processed" / "ausgrid" / "ausgrid_halfhour_normalized.csv"
S0_PATH = ROOT / "results" / "s0_full_period_baseline" / "s0_interval_metrics.csv"
OUTPUT_DIR = ROOT / "results" / "dso_vpp_ac_map_pilot" / "production_probe_preregistration"
CONFIG_PATH = ROOT / "config" / "dso_vpp_production_probe_preregistration.toml"
TEST_PATH = ROOT / "test_python" / "test_prepare_dso_vpp_production_probe_preregistration.py"
JULIA_CONTRACT_PATH = ROOT / "src" / "benchmark" / "dso_vpp_production_probe_contract.jl"
JULIA_CONTRACT_TEST_PATH = ROOT / "test" / "test_dso_vpp_production_probe_contract.jl"

ANCHOR = "2012-10-15 13:00:00"
ANCHOR_SLOT = ("SPRING", "AFTERNOON", "EXPORT")
SEASONS = ("SUMMER", "AUTUMN", "WINTER", "SPRING")
DAYPARTS = ("NIGHT", "MORNING", "AFTERNOON", "EVENING")
MODES = ("EXPORT", "IMPORT")
OBSERVED_MS_PER_EVALUATION = 4.1587


@dataclass(frozen=True)
class ProfilePoint:
    timestamp: datetime
    timestamp_text: str
    load_multiplier: float
    pv_factor: float
    season: str
    daypart: str
    source_row_sha256: str


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_normalized_text_file(path: Path) -> str:
    """Hash logical UTF-8 text independently of checkout newline policy."""
    text = path.read_text(encoding="utf-8-sig").replace("\r\n", "\n").replace("\r", "\n")
    return sha256_bytes(text.encode("utf-8"))


def row_sha256(row: dict[str, str], fieldnames: list[str]) -> str:
    payload = "\x1f".join(row[name] for name in fieldnames).encode("utf-8")
    return sha256_bytes(payload)


def read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        fieldnames = list(reader.fieldnames or [])
        return fieldnames, list(reader)


def csv_text(fieldnames: list[str], rows: list[dict[str, object]]) -> str:
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=fieldnames, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue()


def season_for(month: int) -> str:
    if month in (12, 1, 2):
        return "SUMMER"
    if month in (3, 4, 5):
        return "AUTUMN"
    if month in (6, 7, 8):
        return "WINTER"
    return "SPRING"


def daypart_for(timestamp: datetime) -> str:
    slot = 2 * timestamp.hour + timestamp.minute // 30
    if slot < 12:
        return "NIGHT"
    if slot < 24:
        return "MORNING"
    if slot < 36:
        return "AFTERNOON"
    return "EVENING"


def load_profile() -> list[ProfilePoint]:
    fieldnames, rows = read_csv(PROFILE_PATH)
    required = {"datetime", "load_multiplier", "pv_profile"}
    assert required.issubset(fieldnames), f"missing profile columns: {required - set(fieldnames)}"
    points: list[ProfilePoint] = []
    for row in rows:
        timestamp = datetime.strptime(row["datetime"], "%Y-%m-%d %H:%M:%S")
        points.append(
            ProfilePoint(
                timestamp=timestamp,
                timestamp_text=row["datetime"],
                load_multiplier=float(row["load_multiplier"]),
                pv_factor=float(row["pv_profile"]),
                season=season_for(timestamp.month),
                daypart=daypart_for(timestamp),
                source_row_sha256=row_sha256(row, fieldnames),
            )
        )
    assert len(points) == 52_608
    assert len({point.timestamp_text for point in points}) == 52_608
    return points


def rank_points(points: list[ProfilePoint], mode: str) -> list[ProfilePoint]:
    if mode == "EXPORT":
        return sorted(points, key=lambda point: (-point.pv_factor, point.load_multiplier, point.timestamp))
    if mode == "IMPORT":
        return sorted(points, key=lambda point: (-point.load_multiplier, point.pv_factor, point.timestamp))
    raise ValueError(f"unknown stress mode: {mode}")


def semantic_category(point: ProfilePoint, mode: str) -> str:
    """Describe the selected condition without overstating night PV export stress."""
    if mode == "IMPORT":
        return "HIGH_LOAD_IMPORT_ORIENTED"
    if point.daypart == "NIGHT" and point.pv_factor == 0.0:
        return "LOW_LOAD_ZERO_PV"
    if point.daypart == "NIGHT":
        return "NIGHT_NOMINAL_EXPORT_RANKING_NONZERO_PV"
    return "PV_AVAILABILITY_LOAD_EXPORT_ORIENTED"


def finite_valid_axis_status(status: str) -> bool:
    """Numerical guards, unresolved searches, and re-entry are not finite bounds."""
    return status == "AXIS_CERTIFIED_BOUNDARY"


def valid_voltage_bracket(lower: dict[str, object], upper: dict[str, object]) -> bool:
    """Require an ordered converged-feasible/converged-violating bracket."""
    return (
        float(lower["coordinate"]) < float(upper["coordinate"])
        and lower["solver_status"] == "CONVERGED_FEASIBLE"
        and float(lower["vmin_pu"]) >= 0.90
        and float(lower["vmax_pu"]) <= 1.05
        and upper["solver_status"] == "CONVERGED_INFEASIBLE"
        and (float(upper["vmin_pu"]) < 0.90 or float(upper["vmax_pu"]) > 1.05)
    )


def binding_invariant(mechanism: str, endpoint: dict[str, object]) -> bool:
    if endpoint["solver_status"] != "CONVERGED_INFEASIBLE":
        return False
    if mechanism == "BINDING_VMIN":
        return float(endpoint["vmin_pu"]) < 0.90 and endpoint.get("vmin_bus") is not None
    if mechanism == "BINDING_VMAX":
        return float(endpoint["vmax_pu"]) > 1.05 and endpoint.get("vmax_bus") is not None
    return False


def select_timestamps(points: list[ProfilePoint]) -> list[dict[str, object]]:
    by_timestamp = {point.timestamp_text: point for point in points}
    assert ANCHOR in by_timestamp
    anchor = by_timestamp[ANCHOR]
    assert (anchor.season, anchor.daypart, "EXPORT") == ANCHOR_SLOT

    selected: set[str] = {ANCHOR}
    slot_rows: list[dict[str, object]] = []
    slot_index = 0
    for season in SEASONS:
        for daypart in DAYPARTS:
            stratum = [point for point in points if point.season == season and point.daypart == daypart]
            assert stratum
            for mode in MODES:
                slot_index += 1
                slot = (season, daypart, mode)
                if slot == ANCHOR_SLOT:
                    choice = anchor
                    rank = 0
                    basis = "MANDATORY_REFERENCE_ANCHOR"
                else:
                    eligible = [point for point in stratum if point.timestamp_text != ANCHOR]
                    ranked = rank_points(eligible, mode)
                    choice = next(point for point in ranked if point.timestamp_text not in selected)
                    rank = ranked.index(choice) + 1
                    basis = (
                        "PV_FACTOR_DESC_LOAD_MULTIPLIER_ASC_TIMESTAMP_ASC"
                        if mode == "EXPORT"
                        else "LOAD_MULTIPLIER_DESC_PV_FACTOR_ASC_TIMESTAMP_ASC"
                    )
                assert choice.timestamp_text not in selected or choice.timestamp_text == ANCHOR
                selected.add(choice.timestamp_text)
                slot_rows.append(
                    {
                        "slot_index": slot_index,
                        "timestamp": choice.timestamp_text,
                        "season": season,
                        "daypart": daypart,
                        "stress_mode": mode,
                        "rank_within_slot": rank,
                        "load_multiplier": f"{choice.load_multiplier:.17g}",
                        "pv_factor": f"{choice.pv_factor:.17g}",
                        "selection_basis": basis,
                        "semantic_category": semantic_category(choice, mode),
                        "mandatory_anchor": str(choice.timestamp_text == ANCHOR).lower(),
                        "dense_probe": "true",
                        "profile_row_sha256": choice.source_row_sha256,
                    }
                )

    assert slot_index == 32
    assert len(slot_rows) == 32
    assert len(selected) == 32
    assert sum(row["mandatory_anchor"] == "true" for row in slot_rows) == 1
    assert all(row["dense_probe"] == "true" for row in slot_rows)
    anchor_row = next(row for row in slot_rows if row["mandatory_anchor"] == "true")
    ordered = [anchor_row] + [row for row in slot_rows if row is not anchor_row]
    for selection_index, row in enumerate(ordered, start=1):
        row["selection_index"] = selection_index
    return ordered


def extract_s0_evidence(selected: list[dict[str, object]]) -> list[dict[str, object]]:
    fieldnames, rows = read_csv(S0_PATH)
    required = {
        "root_voltage_pu", "timestamp", "primal_available", "numerical_validation_passed",
        "operational_voltage_feasible", "minimum_voltage_pu", "minimum_voltage_bus",
        "maximum_voltage_pu", "maximum_voltage_bus", "operational_solver_status", "solution_source",
    }
    assert required.issubset(fieldnames), f"missing S0 columns: {required - set(fieldnames)}"
    selected_set = {str(row["timestamp"]) for row in selected}
    root_one_rows = {
        row["timestamp"]: row
        for row in rows
        if row["timestamp"] in selected_set and abs(float(row["root_voltage_pu"]) - 1.0) <= 1e-12
    }
    assert set(root_one_rows) == selected_set
    source_hash = sha256_normalized_text_file(S0_PATH)
    evidence: list[dict[str, object]] = []
    for selected_row in selected:
        row = root_one_rows[str(selected_row["timestamp"])]
        vmin = float(row["minimum_voltage_pu"])
        vmax = float(row["maximum_voltage_pu"])
        production_feasible = (
            row["primal_available"].lower() == "true" and vmin >= 0.90 and vmax <= 1.05
        )
        evidence.append(
            {
                "selection_index": selected_row["selection_index"],
                "timestamp": row["timestamp"],
                "root_voltage_pu": row["root_voltage_pu"],
                "minimum_voltage_pu": row["minimum_voltage_pu"],
                "minimum_voltage_bus": row["minimum_voltage_bus"],
                "maximum_voltage_pu": row["maximum_voltage_pu"],
                "maximum_voltage_bus": row["maximum_voltage_bus"],
                "operational_solver_status": row["operational_solver_status"],
                "solution_source": row["solution_source"],
                "primal_available": row["primal_available"],
                "numerical_validation_passed": row["numerical_validation_passed"],
                "s0_operational_voltage_feasible_095_105": row["operational_voltage_feasible"],
                "production_voltage_feasible_090_105": str(production_feasible).lower(),
                "absolute_pcc_origin_p13_kw": "0",
                "absolute_pcc_origin_p30_kw": "0",
                "s0_source_sha256": source_hash,
                "s0_row_sha256": row_sha256(row, fieldnames),
            }
        )
    assert len(evidence) == 32
    assert all(row["production_voltage_feasible_090_105"] == "true" for row in evidence)
    return evidence


def classify_transition(statuses: list[str]) -> str:
    """Classify a retained coarse sweep without equating failure to infeasibility."""
    allowed = {
        "CONVERGED_FEASIBLE", "CONVERGED_INFEASIBLE", "NONCONVERGED_FIRST_ATTEMPT",
        "NONCONVERGED_AFTER_RETRY", "UNRESOLVED",
    }
    if not statuses or any(status not in allowed for status in statuses):
        return "INVALID_STATUS_SEQUENCE"
    if any(status.startswith("NONCONVERGED") or status == "UNRESOLVED" for status in statuses):
        return "UNRESOLVED"
    collapsed = [statuses[0]]
    for status in statuses[1:]:
        if status != collapsed[-1]:
            collapsed.append(status)
    if collapsed == ["CONVERGED_FEASIBLE"]:
        return "UNBOUNDED_WITHIN_GUARD"
    if collapsed == ["CONVERGED_FEASIBLE", "CONVERGED_INFEASIBLE"]:
        return "SINGLE_FEASIBLE_TO_INFEASIBLE_TRANSITION"
    if any(
        collapsed[index:index + 3]
        == ["CONVERGED_FEASIBLE", "CONVERGED_INFEASIBLE", "CONVERGED_FEASIBLE"]
        for index in range(max(0, len(collapsed) - 2))
    ):
        return "REENTRY_DETECTED"
    return "INVALID_STATUS_SEQUENCE"


def policy_toml() -> str:
    return f'''schema_version = 1
classification = "PRODUCTION_PROBE_PREREGISTERED_READY_FOR_REMOTE_BACKUP"
production_probe_execution_authorized = false
all_timestamps_dense = true

[coordinates]
active_power_coordinate = "ABSOLUTE_PHYSICAL_P_PCC_KW"
export_sign = "POSITIVE"
reactive_policy = "UNITY_POWER_FACTOR_INTERFACE_POLICY"
q_pcc_kvar = 0.0
resource_capability_defines_network_boundary = false

[timestamp_policy_t1]
selected_timestamp_count = 32
mandatory_anchor = "{ANCHOR}"
mandatory_anchor_slot = "SPRING_AFTERNOON_EXPORT"
mandatory_anchor_replaces_mode = "EXPORT"
mandatory_anchor_replacement_rule = "REPLACE_SPRING_AFTERNOON_EXPORT_RANKED_PICK_BEFORE_OTHER_SLOT_SELECTION"
anchor_natural_rank_irrelevant = true
anchor_removed_from_rankings = true
slot_count = 32
slot_definition = "SEASON_X_DAYPART_X_EXPORT_IMPORT"
all_timestamps_dense = true
selector_inputs = ["LOAD_MULTIPLIER", "PV_FACTOR", "SEASON", "DAYPART", "TIMESTAMP_TIEBREAK"]
forbidden_selector_inputs = ["AXIS_BOUND", "AC_RESULT", "BINDING_BUS", "BOUNDARY_RADIUS"]
export_ranking = ["PV_FACTOR_DESC", "LOAD_MULTIPLIER_ASC", "TIMESTAMP_ASC"]
import_ranking = ["LOAD_MULTIPLIER_DESC", "PV_FACTOR_ASC", "TIMESTAMP_ASC"]
semantic_category_field = "SEMANTIC_CATEGORY"
zero_pv_night_export_category = "LOW_LOAD_ZERO_PV"
summer_months = [12, 1, 2]
autumn_months = [3, 4, 5]
winter_months = [6, 7, 8]
spring_months = [9, 10, 11]
night_slots = [0, 11]
morning_slots = [12, 23]
afternoon_slots = [24, 35]
evening_slots = [36, 47]

[axis_search_g1]
axis_count_per_timestamp = 4
axes = ["P13_POSITIVE", "P13_NEGATIVE", "P30_POSITIVE", "P30_NEGATIVE"]
initial_step_pu = 0.01
initial_step_kw = 100.0
doubling_factor = 2.0
hard_guard_pu = 2.0
hard_guard_kw_absolute_per_axis = 20000.0
hard_guard_semantics = "NUMERICAL_SEARCH_CAP_ONLY"
coarse_step_divisor = 20
coarse_extent_multiplier = 2.0
coarse_sweep_required_before_bisection = true
no_reentry_label = "NO_RE_ENTRY_DETECTED_AT_SWEEP_RESOLUTION_DELTA"
reentry_label = "AXIS_REENTRY_DETECTED"
guard_label = "AXIS_UNBOUNDED_WITHIN_GUARD"
unresolved_label = "AXIS_UNRESOLVED"
monotonicity_proven = false
finite_valid_statuses = ["AXIS_CERTIFIED_BOUNDARY"]
finite_invalid_statuses = ["AXIS_UNBOUNDED_WITHIN_GUARD", "AXIS_UNRESOLVED", "AXIS_REENTRY_DETECTED"]

[center_policy_c1]
tier_1 = "CENTER_TIER_1_AXIS_MIDPOINT"
tier_1_requires_four_finite_valid_axes = true
tier_1_formula = "C_EQUALS_COMPONENTWISE_MIDPOINT_OF_SIGNED_AXIS_LIMITS"
tier_1_requires_ac_feasible = true
tier_2 = "CENTER_TIER_2_CONTRACTED"
tier_2_used_if_midpoint_infeasible = true
tier_2_contractions = 20
tier_2_formula = "C_J_EQUALS_2_POW_MINUS_J_TIMES_C0"
tier_3 = "CENTER_TIER_3_ORIGIN"
tier_3_used_if_no_contracted_center_is_feasible = true
tier_3_point_kw = [0.0, 0.0]
unresolved_label = "CENTER_UNRESOLVED"
same_timestamp_s0_evidence_required = true

[normalization]
kind = "SIGN_SPECIFIC_AXIS_HALF_WIDTHS"
angle_space = "NORMALIZED_COORDINATE_SPACE"
physical_point_formula = "P_EQUALS_C_PLUS_R_TIMES_V"
p13_positive_scale_formula = "P13_MAX_MINUS_C13"
p13_negative_scale_formula = "C13_MINUS_P13_MIN"
p30_positive_scale_formula = "P30_MAX_MINUS_C30"
p30_negative_scale_formula = "C30_MINUS_P30_MIN"

[ray_search_s1]
coarse_step_normalized_r = 0.05
guard_normalized_r = 2.0
full_coarse_sweep_required_before_bisection = true
no_reentry_label = "NO_RE_ENTRY_DETECTED_AT_SWEEP_RESOLUTION_DELTA"
reentry_label = "RAY_REENTRY_DETECTED"
method_review_label = "CENTERED_RADIAL_METHOD_REVIEW_REQUIRED"
star_shapedness = "NOT_PROVEN"
unresolved_label = "RAY_UNRESOLVED"

[direction_grid]
base_direction_count_per_timestamp = 36
base_spacing_degrees = 10.0
minimum_angle_degrees = 0.0
maximum_angle_exclusive_degrees = 360.0
adaptive_levels = 1
maximum_adaptive_directions_per_timestamp = 36
maximum_total_directions_per_timestamp = 72
adaptive_midpoint_triggers = ["BOUNDARY_MECHANISM_CHANGE", "BINDING_BUS_CHANGE", "NORMALIZED_RADIUS_DIFFERENCE_GT_10_PERCENT", "UNRESOLVED_NONCONVERGED_REENTRY_OR_GUARD_LIMITED_ENDPOINT"]
manual_posthoc_angles_allowed = false
near_axis_mandatory_refinement = false
near_axis_refinement_status = "CANDIDATE_PREPRODUCTION_AMENDMENT"
near_axis_intervals_degrees = ["350-0", "0-10", "80-90", "90-100", "170-180", "180-190", "260-270", "270-280"]
near_axis_decision = "BASE_AXES_AND_EXISTING_ADAPTIVE_TRIGGERS_RETAINED_NO_CONCRETE_BLOCKER_FOUND"

[boundary_policy_b1]
mechanisms = ["BINDING_VMAX", "BINDING_VMIN", "SWEEP_NONCONVERGED", "UNRESOLVED", "AXIS_UNBOUNDED_WITHIN_GUARD"]
solver_statuses = ["CONVERGED_FEASIBLE", "CONVERGED_INFEASIBLE", "NONCONVERGED_FIRST_ATTEMPT", "NONCONVERGED_AFTER_RETRY", "UNRESOLVED"]
required_diagnostics = ["BINDING_BUS", "BINDING_VOLTAGE", "VOLTAGE_MARGIN"]
nonconvergence_means_infeasible = false
valid_bracket_lower_status = "CONVERGED_FEASIBLE"
valid_bracket_upper_status = "CONVERGED_INFEASIBLE"
upper_endpoint_requires_actual_registered_constraint_violation = true
nonconverged_endpoint_allowed_in_bisection = false
feasible_to_nonconverged_axis_outcome = "AXIS_UNRESOLVED"
feasible_to_nonconverged_ray_outcome = "RAY_UNRESOLVED"
official_boundary_endpoint = "LAST_CONVERGED_FEASIBLE"
interpolated_region_requires_independent_conservative_validation = true
convexity_claimed = false

[boundary_endpoint_storage]
store_both_sides = true
safe_endpoint_status = "CONVERGED_FEASIBLE"
violating_endpoint_status = "CONVERGED_INFEASIBLE"
required_fields = ["COORDINATE_OR_R", "P13_ABS_KW", "P30_ABS_KW", "VMIN_PU", "VMIN_BUS", "VMAX_PU", "VMAX_BUS", "SOLVER_STATUS"]

[binding_invariants]
binding_vmin_requires = ["CONVERGED_INFEASIBLE", "VMIN_LT_0_90", "NON_NULL_VMIN_BUS", "STORED_VMIN"]
binding_vmax_requires = ["CONVERGED_INFEASIBLE", "VMAX_GT_1_05", "NON_NULL_VMAX_BUS", "STORED_VMAX"]
numerical_bisection_stop_alone_may_assign_binding = false

[voltage_policy_v1]
minimum_voltage_pu = 0.90
maximum_voltage_pu = 1.05

[aggregation_policy_a1]
coordinate_space = "PHYSICAL_ABSOLUTE_P_PCC_COORDINATES"
ray_by_ray_cross_timestamp_averaging_allowed = false
normalized_theta_cross_timestamp_averaging_allowed = false
direction_index_cross_timestamp_intersection_allowed = false
cross_timestamp_lambda_allowed = false
cross_timestamp_theta_star_allowed = false

[stopping_and_replay]
boundary_bracket_width_kw = 1.0
endpoint_voltage_distance_pu = 1.0e-5
replay_voltage_agreement_pu = 2.0e-5
residual_tolerance = 1.0e-5
maximum_bisection_refinements = 60
retry_order = ["FLAT_START", "NEAREST_ACCEPTED_NEIGHBOR_START"]
retry_operational_difference = "INITIALIZATION_STRATEGY"
retry_requires_nearest_accepted_neighbor = true
identical_flat_start_retry_allowed = false
retry_unavailable_without_neighbor_outcome = "UNRESOLVED_AFTER_FIRST_ATTEMPT"
primary_maximum_iterations_each_attempt = 2000
primary_damping_each_attempt = 0.70
primary_convergence_tolerance_each_attempt = 1.0e-11
independent_replay_initialization = "FLAT_START"
independent_replay_maximum_iterations = 4000
independent_replay_convergence_tolerance = 1.0e-12
physical_voltage_limits_changed_by_retry = false
unresolved_points_interpolated = false

[distribution_output_contract]
required_fields = ["P13_POSITIVE_AXIS", "P13_NEGATIVE_AXIS", "P30_POSITIVE_AXIS", "P30_NEGATIVE_AXIS", "AXIS_WIDTHS", "CENTERS", "CENTER_TIERS", "BINDING_MECHANISMS", "BINDING_BUSES", "BOUNDARY_RADII", "RETRIES", "UNRESOLVED_COUNTS"]
anchor_position_labels = ["EXTREME", "NEAR_EXTREME", "TYPICAL", "PLATEAU_REGION"]
axis_bounds_are_output_analysis_only = true

[execution]
production_probe_enabled = false
worker_processes = 8
threads_per_worker = 1
checkpoint_after_each_direction = true
checkpoint_after_each_timestamp = true
checkpoint_write = "ATOMIC"
resume_required = true
target_machine = "12_CPU_32_GB_RAM_VM"
cluster_required = false
'''


def cost_rows() -> list[dict[str, object]]:
    timestamps = 32
    axis_searches = timestamps * 4
    base_rays = timestamps * 36
    adaptive_rays = timestamps * 36
    axis_evaluations_per_search = 59
    ray_evaluations_per_search = 51
    axis_evaluations = axis_searches * axis_evaluations_per_search
    base_evaluations = base_rays * ray_evaluations_per_search
    adaptive_evaluations = adaptive_rays * ray_evaluations_per_search
    nominal = axis_evaluations + base_evaluations
    capped = nominal + adaptive_evaluations
    retry_allowance = (5 * capped + 3) // 4

    def row(stage: str, searches: int, per_search: int | str, evaluations: int, note: str) -> dict[str, object]:
        serial_seconds = evaluations * OBSERVED_MS_PER_EVALUATION / 1000.0
        return {
            "stage": stage,
            "search_count": searches,
            "estimated_evaluations_per_search": per_search,
            "estimated_ac_evaluations": evaluations,
            "empirical_aggregate_ms_per_evaluation": f"{OBSERVED_MS_PER_EVALUATION:.4f}",
            "estimated_aggregate_equivalent_seconds": f"{serial_seconds:.3f}",
            "ideal_eight_worker_kernel_seconds": f"{serial_seconds / 8.0:.3f}",
            "note": note,
        }

    return [
        row("SIGNED_AXIS_PREPASS", axis_searches, axis_evaluations_per_search, axis_evaluations, "10 expansion + 41 retained coarse-sweep + 8 typical refinement evaluations"),
        row("BASE_36_DIRECTIONS", base_rays, ray_evaluations_per_search, base_evaluations, "41 full coarse-sweep + 10 typical refinement evaluations"),
        row("MAXIMUM_36_ADAPTIVE_DIRECTIONS", adaptive_rays, ray_evaluations_per_search, adaptive_evaluations, "one preregistered midpoint level; no manual angles"),
        row("NOMINAL_BASE_ONLY_TOTAL", axis_searches + base_rays, "mixed", nominal, "all 32 timestamps dense; adaptive directions excluded"),
        row("HARD_DIRECTION_CAP_TOTAL", axis_searches + base_rays + adaptive_rays, "mixed", capped, "all 36 adaptive midpoints triggered at every timestamp"),
        row("HARD_CAP_PLUS_25_PERCENT_RETRY_ALLOWANCE", axis_searches + base_rays + adaptive_rays, "mixed", retry_allowance, "planning allowance only; nonconvergence remains unresolved, not infeasible"),
    ]


def report_text(selected: list[dict[str, object]], evidence: list[dict[str, object]]) -> str:
    numerical_valid = sum(row["numerical_validation_passed"] == "true" for row in evidence)
    operational_095 = sum(row["s0_operational_voltage_feasible_095_105"] == "true" for row in evidence)
    production_valid = sum(row["production_voltage_feasible_090_105"] == "true" for row in evidence)
    anchor = selected[0]
    return f'''# Final production DOE probe preregistration

Final classification: **`PRODUCTION_PROBE_PREREGISTERED_READY_FOR_REMOTE_BACKUP`**.

The production probe is deliberately disabled and was not executed. This preregistration supersedes the earlier hierarchical 8-dense/24-sparse and 24-direction recommendation while preserving that audit as scientific history.

## Locked temporal selection

- Exactly 32 unique timestamps are selected from 52,608 half-hourly profile rows.
- All 32 timestamps are dense (`ALL_32_TIMESTAMPS_DENSE`).
- The 32 slots are season x daypart x stress mode: four seasons, four dayparts, and one export plus one import selection per stratum.
- `{ANCHOR}` deterministically replaces the nominal ranked pick in the `SPRING/AFTERNOON/EXPORT` slot before any other slot is selected. Its natural rank is irrelevant. The other 31 slots exclude the anchor and use only load, PV, season, daypart, and timestamp tie-breaking; simple deduplication is not the replacement mechanism.
- Export ranking is PV factor descending, load multiplier ascending, timestamp ascending. Import ranking is load multiplier descending, PV factor ascending, timestamp ascending.
- The committed profile column `pv_profile` is the preregistered `pv_factor` input. No AC result, axis bound, binding bus, or boundary radius enters selection.
- `semantic_category` separates the ranking label from scientific interpretation. In particular, a NIGHT export-ranked row with exactly zero PV is `LOW_LOAD_ZERO_PV`, not PV export stress.

The anchor has load multiplier `{anchor['load_multiplier']}` and PV factor `{anchor['pv_factor']}` in the committed profile.

## Same-timestamp S0 origin evidence

Every selected timestamp has an extracted root-voltage-1.0 S0 row at absolute `P_PCC=(0,0)`. The evidence table preserves the source numerical-validation and historical 0.95-1.05 operational-feasibility flags, and separately recomputes the locked production band 0.90-1.05 from the written voltages.

- production-band feasible: {production_valid}/32
- source numerical-validation flag true: {numerical_valid}/32
- historical S0 0.95-1.05 operational flag true: {operational_095}/32

The historical 0.95 flag is evidence metadata only and is not the production voltage limit.

## Locked search and geometry policy

- G1: four signed absolute axes, 100 kW initial numerical step, doubling, 20 MW absolute per-axis numerical guard, full axis coarse sweep at `S_axis/20` through at least `2*S_axis` or the guard.
- C1: signed-axis midpoint, then up to 20 dyadic contractions, then the same-timestamp S0 origin fallback.
- S1: centered radial search with `delta_r=0.05`, `r_guard=2.0`, and a retained full coarse sweep before bisection.
- Direction grid: 36 base directions at 10 degrees for every timestamp, one adaptive midpoint level, at most 36 adaptive and 72 total directions per timestamp.
- B1/V1: nonconvergence is never infeasibility. Bisection requires a converged-feasible lower endpoint and a converged-infeasible upper endpoint with an actual 0.90/1.05 voltage violation. A feasible-to-nonconverged transition is unresolved and cannot fabricate a bound.
- Only `AXIS_CERTIFIED_BOUNDARY` is finite-valid. Guard-limited, unresolved, and re-entry-contaminated axes are finite-invalid and cannot enter a Tier-1 midpoint.
- Retry changes initialization from flat start to the nearest accepted neighbor. If no accepted neighbor exists, an identical flat-start retry is forbidden and the failed search remains unresolved.
- Both bracket endpoints retain coordinate/r, absolute P13/P30, voltage extrema and buses, and solver status. The official coordinate is the last converged-feasible endpoint; the violating endpoint supports binding classification.
- `BINDING_VMIN` and `BINDING_VMAX` require a converged violating endpoint, an actual threshold violation, a non-null binding bus, and the stored violating voltage.
- A1: every cross-time aggregation or intersection is performed in physical absolute `P_PCC` coordinates. Direction indices and normalized angles are not comparable across timestamps.
- Absence of observed re-entry is reported only at the retained sweep resolution. Monotonicity, convexity, and star-shapedness remain unproven. Feasible sampled ray endpoints do not certify interpolated edges or polygons; later DOE construction requires independent conservative validation.
- Mandatory near-axis refinement remains a candidate only. The four axes and their adjacent base-grid endpoints are sampled directly, while the existing mechanism/bus/radius/unresolved adaptive triggers remain active.

## Updated resource estimate

The base-only plan is 66,304 fixed AC evaluations. Triggering all adaptive midpoints gives 125,056 evaluations; a planning allowance of 25% for deterministic retries gives 156,320. The {OBSERVED_MS_PER_EVALUATION:.4f} ms/evaluation input is empirical aggregate throughput: 15.3498603 seconds divided by 3,691 evaluations from the serial, one-process, one-Julia-thread Phase-B orchestration benchmark. It is not a directly measured single-worker solve latency. Applying that aggregate rate gives equivalent elapsed times of about 4.6, 8.7, and 10.8 minutes; ideal eight-worker figures of about 35, 65, and 81 seconds are shown only as non-guaranteed scaling references.

The original 5-15 minute end-to-end estimate on the 12-CPU/32-GB VM is retained. It does not require an assumed parallel speedup because the hard-cap aggregate-rate extrapolation is about 8.7 minutes; eight one-thread workers are the execution plan but their speedup is uncertain. Expected RAM remains below 8 GB from the observed roughly 743 MiB process footprint. Plan for 20-50 MB of retained raw/checkpoint artifacts. The benchmark mixture may overrepresent feasible/easy evaluations and need not capture near-boundary, retry-heavy, or nonconvergent cost.

These are estimates, not an executed benchmark of the production probe.

## Gate

The selector, S0 extraction, transition state machine, machine-readable policies, deterministic regeneration check, and focused tests must pass before remote backup. Production execution, DOE construction, coupled/box optimization, EV/BESS optimization, centralized optimization, and push are outside this commit.
'''


def build_artifacts() -> dict[Path, str]:
    selected = select_timestamps(load_profile())
    evidence = extract_s0_evidence(selected)
    selected_fields = [
        "selection_index", "slot_index", "timestamp", "season", "daypart", "stress_mode",
        "rank_within_slot", "load_multiplier", "pv_factor", "selection_basis", "semantic_category", "mandatory_anchor",
        "dense_probe", "profile_row_sha256",
    ]
    evidence_fields = [
        "selection_index", "timestamp", "root_voltage_pu", "minimum_voltage_pu", "minimum_voltage_bus",
        "maximum_voltage_pu", "maximum_voltage_bus", "operational_solver_status", "solution_source",
        "primal_available", "numerical_validation_passed", "s0_operational_voltage_feasible_095_105",
        "production_voltage_feasible_090_105", "absolute_pcc_origin_p13_kw",
        "absolute_pcc_origin_p30_kw", "s0_source_sha256", "s0_row_sha256",
    ]
    cost_fields = [
        "stage", "search_count", "estimated_evaluations_per_search", "estimated_ac_evaluations",
        "empirical_aggregate_ms_per_evaluation", "estimated_aggregate_equivalent_seconds",
        "ideal_eight_worker_kernel_seconds", "note",
    ]
    artifacts = {
        CONFIG_PATH: policy_toml(),
        OUTPUT_DIR / "selected_32_timestamps.csv": csv_text(selected_fields, selected),
        OUTPUT_DIR / "s0_origin_evidence_32_timestamps.csv": csv_text(evidence_fields, evidence),
        OUTPUT_DIR / "production_probe_cost_estimate.csv": csv_text(cost_fields, cost_rows()),
        OUTPUT_DIR / "production_probe_preregistration_report.md": report_text(selected, evidence),
    }
    manifest_rows = [
        {"artifact": str(PROFILE_PATH.relative_to(ROOT)).replace("\\", "/"), "role": "LOCKED_INPUT_NORMALIZED_TEXT", "sha256": sha256_normalized_text_file(PROFILE_PATH)},
        {"artifact": str(S0_PATH.relative_to(ROOT)).replace("\\", "/"), "role": "LOCKED_INPUT_NORMALIZED_TEXT", "sha256": sha256_normalized_text_file(S0_PATH)},
        {"artifact": str(Path(__file__).resolve().relative_to(ROOT)).replace("\\", "/"), "role": "DETERMINISTIC_GENERATOR_NORMALIZED_TEXT", "sha256": sha256_normalized_text_file(Path(__file__).resolve())},
        {"artifact": str(TEST_PATH.relative_to(ROOT)).replace("\\", "/"), "role": "FOCUSED_TEST_NORMALIZED_TEXT", "sha256": sha256_normalized_text_file(TEST_PATH)},
        {"artifact": str(JULIA_CONTRACT_PATH.relative_to(ROOT)).replace("\\", "/"), "role": "PRODUCTION_BOUNDARY_CONTRACT_NORMALIZED_TEXT", "sha256": sha256_normalized_text_file(JULIA_CONTRACT_PATH)},
        {"artifact": str(JULIA_CONTRACT_TEST_PATH.relative_to(ROOT)).replace("\\", "/"), "role": "PRODUCTION_BOUNDARY_CONTRACT_TEST_NORMALIZED_TEXT", "sha256": sha256_normalized_text_file(JULIA_CONTRACT_TEST_PATH)},
    ]
    for path, content in artifacts.items():
        manifest_rows.append(
            {
                "artifact": str(path.relative_to(ROOT)).replace("\\", "/"),
                "role": "GENERATED_PREREGISTRATION_ARTIFACT",
                "sha256": sha256_bytes(content.encode("utf-8")),
            }
        )
    artifacts[OUTPUT_DIR / "production_probe_artifact_manifest.csv"] = csv_text(
        ["artifact", "role", "sha256"], manifest_rows
    )
    return artifacts


def write_or_check(artifacts: dict[Path, str], check: bool) -> None:
    mismatches: list[str] = []
    for path, expected in artifacts.items():
        if check:
            if not path.exists() or path.read_text(encoding="utf-8") != expected:
                mismatches.append(str(path.relative_to(ROOT)))
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(expected, encoding="utf-8", newline="")
    if mismatches:
        raise SystemExit("artifact mismatch: " + ", ".join(mismatches))
    action = "verified" if check else "wrote"
    print(f"{action} {len(artifacts)} production-probe preregistration artifacts")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="verify committed artifacts without writing")
    args = parser.parse_args()
    write_or_check(build_artifacts(), args.check)


if __name__ == "__main__":
    main()
