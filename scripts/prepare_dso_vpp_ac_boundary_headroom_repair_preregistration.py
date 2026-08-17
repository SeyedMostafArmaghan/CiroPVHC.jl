from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path


SOURCE_COMMIT = "ba88f54f52f7bcd03df2466ce69dff2b9b1c538b"
SOURCE_BRANCH = "codex/dso-vpp-ac-map-pilot"
COORD_TOL_KW = 1e-8
VOLTAGE_LIMIT_VMIN = 0.90
VOLTAGE_LIMIT_VMAX = 1.05
HEADROOM_QUANTUM_PU = 1e-5
RETREAT_COARSE_INITIAL_STEP_KW = 0.5
RETREAT_RESOLUTION_KW = 0.25
MAX_ANCHOR_BRACKET_CALLS_PER_EDGE = 16
MAX_ANCHOR_BISECTION_CALLS_PER_EDGE = 16
MAX_VERIFY_ESCALATE_CALLS_PER_INTERIOR_COORDINATE = 8
RETRY_BUDGET_FRACTION = 0.01
CHECKPOINT_CHUNK_ROWS = 2000

OUTDIR = Path(
    "results/dso_vpp_ac_map_pilot/"
    "doe_ac_boundary_headroom_repair_preregistration"
)

PATHS = {
    "addendum_summary": "results/dso_vpp_ac_map_pilot/doe_ac_repairability_interpolation_audit/signed_interpolation_addendum/summary.json",
    "addendum_manifest": "results/dso_vpp_ac_map_pilot/doe_ac_repairability_interpolation_audit/signed_interpolation_addendum/manifest.json",
    "failing_edges": "results/dso_vpp_ac_map_pilot/doe_ac_repairability_interpolation_audit/signed_interpolation_addendum/failing_edges.csv",
    "low_sample_edges": "results/dso_vpp_ac_map_pilot/doe_ac_repairability_interpolation_audit/signed_interpolation_addendum/low_sample_edges.csv",
    "enrichment_points": "results/dso_vpp_ac_map_pilot/doe_ac_repairability_interpolation_audit/signed_interpolation_addendum/low_sample_enrichment_points.csv",
    "signed_diagnostics": "results/dso_vpp_ac_map_pilot/doe_ac_repairability_interpolation_audit/signed_interpolation_addendum/edge_signed_interpolation_diagnostics.csv",
    "edge_audit": "results/dso_vpp_ac_map_pilot/doe_ac_repairability_interpolation_audit/edge_repairability_sampling.csv",
    "polygon_edges": "results/dso_vpp_ac_map_pilot/doe_ac_interior_validation_preregistration/validation_polygon_edges.csv",
    "holdout_capability": "results/dso_vpp_ac_map_pilot/doe_ac_repairability_interpolation_audit/holdout_geometric_capability.csv",
    "signed_margins": "results/dso_vpp_ac_map_pilot/doe_ac_repairability_interpolation_audit/signed_boundary_margin_summary.csv",
    "numerical": "results/dso_vpp_ac_map_pilot/doe_ac_repairability_interpolation_audit/numerical_replay_diagnostics.csv",
    "ray_resolution": "results/dso_vpp_ac_map_pilot/doe_preconstruction_artifact_refinement/ray_boundary_resolution_distribution.csv",
    "axis_resolution": "results/dso_vpp_ac_map_pilot/doe_preconstruction_artifact_refinement/axis_boundary_resolution_distribution.csv",
    "termination_audit": "results/dso_vpp_ac_map_pilot/doe_preconstruction_artifact_refinement/boundary_bisection_termination_audit.csv",
}


def git(*args: str) -> bytes:
    return subprocess.check_output(["git", *args])


def git_text(path: str) -> str:
    return git("show", f"{SOURCE_COMMIT}:{path}").decode("utf-8-sig")


def read_csv_git(path: str) -> list[dict[str, str]]:
    return list(csv.DictReader(io.StringIO(git_text(path))))


def read_json_git(path: str):
    return json.loads(git_text(path))


def f(row: dict[str, str], key: str) -> float:
    return float(row[key])


def truth(value) -> bool:
    return str(value).lower() == "true"


def finite(x: float) -> bool:
    return math.isfinite(x)


def fmt(value) -> str:
    if isinstance(value, float):
        if math.isnan(value):
            return "NaN"
        if math.isinf(value):
            return "Inf" if value > 0 else "-Inf"
        return format(value, ".15g")
    return str(value)


def parse_fractions(text: str) -> list[float]:
    return [] if not text else [float(x) for x in text.split(";")]


def unique(values: list[float], tol=1e-12) -> list[float]:
    out: list[float] = []
    for x in sorted(values):
        if not out or abs(x - out[-1]) > tol:
            out.append(x)
    return out


def max_gap(values: list[float]) -> float:
    xs = unique([0.0, 1.0, *values])
    return max(b - a for a, b in zip(xs, xs[1:]))


def json_safe(value):
    if isinstance(value, float) and not finite(value):
        return None
    if isinstance(value, dict):
        return {k: json_safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [json_safe(v) for v in value]
    return value


def write_text(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8", newline="\n")


def write_csv(path: Path, fields: list[str], rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({k: fmt(row.get(k, "")) for k in fields})


def verify_index() -> int:
    manifest_path = OUTDIR.as_posix() + "/manifest.json"
    manifest = json.loads(git("show", f":{manifest_path}").decode("utf-8"))
    bad = []
    for item in manifest["files"]:
        data = git("show", f":{OUTDIR.as_posix()}/{item['path']}")
        if len(data) != item["bytes"] or hashlib.sha256(data).hexdigest() != item["sha256"]:
            bad.append(item["path"])
    print(f"staged manifest payloads: {len(manifest['files'])}")
    print(f"staged manifest mismatches: {len(bad)}")
    return 1 if bad else 0


def main() -> int:
    branch = git("branch", "--show-current").decode().strip()
    head = git("rev-parse", "HEAD").decode().strip()
    if branch != SOURCE_BRANCH or head != SOURCE_COMMIT:
        raise RuntimeError(f"source mismatch branch={branch} head={head}")

    addendum = read_json_git(PATHS["addendum_summary"])
    read_json_git(PATHS["addendum_manifest"])
    failing_edges = read_csv_git(PATHS["failing_edges"])
    low_edges = read_csv_git(PATHS["low_sample_edges"])
    enrichment = read_csv_git(PATHS["enrichment_points"])
    signed_diagnostics = read_csv_git(PATHS["signed_diagnostics"])
    edges = read_csv_git(PATHS["edge_audit"])
    polygon_edges = read_csv_git(PATHS["polygon_edges"])
    holdout = read_csv_git(PATHS["holdout_capability"])
    margins = read_csv_git(PATHS["signed_margins"])
    numerical = read_csv_git(PATHS["numerical"])
    ray_resolution = read_csv_git(PATHS["ray_resolution"])
    axis_resolution = read_csv_git(PATHS["axis_resolution"])
    termination = read_csv_git(PATHS["termination_audit"])

    checks: list[dict] = []

    def check(check_id: str, condition: bool, detail: str, severity="BLOCKER"):
        checks.append({"check_id": check_id,
                       "status": "PASS" if condition else severity,
                       "detail": detail})

    check("SOURCE_BRANCH", branch == SOURCE_BRANCH, branch, "FAIL")
    check("SOURCE_COMMIT", head == SOURCE_COMMIT, head, "FAIL")
    check("ZERO_AC_PREREGISTRATION", True, "no solver import; no AC execution")
    check("ADDENDUM_GATE_OPEN", addendum["overall_status"] == "NO_ADDENDUM_BLOCKER",
          addendum["overall_status"])
    check("LOCKED_CLASSIFICATION_PRESERVED",
          addendum["locked_campaign_classification"] == "MAIN_COUPLED_DOE_GEOMETRIC_CANDIDATE_FALSIFIED_BY_AC_COUNTEREXAMPLE",
          addendum["locked_campaign_classification"])
    check("EDGE_COUNT", len(edges) == 1689, f"observed={len(edges)}")
    check("FAILURE_EDGE_COUNT", len(failing_edges) == 655, f"observed={len(failing_edges)}")
    check("LOW_SAMPLE_CORRECTED_COUNT", len(low_edges) == 41,
          "committed true set=41; prompt expectation 44 corrected in addendum")
    check("ENRICHMENT_POINT_COUNT", len(enrichment) == 130, f"observed={len(enrichment)}")
    check("SIGNED_DIAGNOSTIC_FIT_COUNT", len(signed_diagnostics) == 1776,
          f"observed={len(signed_diagnostics)}")
    check("ALL_OWNER_COUNTS_ONE", all(int(r["owner_cell_count"]) == 1 for r in edges),
          f"bad={sum(int(r['owner_cell_count']) != 1 for r in edges)}")
    check("ALL_CAPS_POSITIVE", all(f(r, "parallel_retreat_cap_kw") > 0 for r in edges),
          f"minimum={fmt(min(f(r, 'parallel_retreat_cap_kw') for r in edges))}")

    observed_negative_margin = max(0.0, -min(f(r, "min") for r in margins))
    predicted_midpoint_deficit = max(
        0.0, -float(addendum["fit_population"]["predicted_midpoint_margin_distribution_pu"]["min"])
    )
    replay_maxima = [
        f(r, "max") for r in numerical
        if r["metric"] == "primary_replay_voltage_difference_pu"
        and r["group"] in {
            "VALIDATION_ANGULAR_BOUNDARY_ATTEMPTS",
            "PRODUCTION_OFFICIAL_SAFE_ENDPOINT_ATTEMPTS",
        }
    ]
    maximum_replay_difference = max(replay_maxima)
    evidence_envelope = max(observed_negative_margin, predicted_midpoint_deficit,
                            maximum_replay_difference)
    h_design = round(
        math.ceil((evidence_envelope - 1e-18) / HEADROOM_QUANTUM_PU)
        * HEADROOM_QUANTUM_PU,
        12,
    )
    check("H_DESIGN_LOCK", abs(h_design - 1.5e-4) <= 1e-15,
          f"envelope={fmt(evidence_envelope)},quantum={fmt(HEADROOM_QUANTUM_PU)},h_design={fmt(h_design)}")
    ray_physical_all = next(
        r for r in ray_resolution
        if r["group"] == "ALL_PHYSICAL_RAYS" and r["quantity"] == "PHYSICAL_BRACKET_LENGTH"
    )
    axis_physical_all = next(
        r for r in axis_resolution
        if r["group"] == "ALL_SIGNED_AXES" and r["quantity"] == "AXIS_BOUNDARY_LOCATION_BRACKET_WIDTH"
    )
    termination_text = " ".join(r["value"] for r in termination)
    check("RETREAT_RESOLUTION_EVIDENCE",
          RETREAT_RESOLUTION_KW < f(ray_physical_all, "median")
          and RETREAT_RESOLUTION_KW < f(axis_physical_all, "median")
          and "1e-5" in termination_text,
          f"locked={fmt(RETREAT_RESOLUTION_KW)},ray_median={ray_physical_all['median']},axis_median={axis_physical_all['median']},voltage_quantum_evidence={'1e-5' in termination_text}")

    failing_by_key = {
        (r["timestamp"], r["edge_id"]): int(r["failure_count"])
        for r in failing_edges
    }
    low_by_key = {(r["timestamp"], r["edge_id"]): r for r in low_edges}
    enrichment_by_key: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for row in enrichment:
        enrichment_by_key[(row["timestamp"], row["edge_id"])].append(row)
    holdout_by_key = {(r["timestamp"], r["edge_id"]): r for r in holdout}
    polygon_by_key = {
        (r["timestamp"], r["source_polygon_edge_id"]): r
        for r in polygon_edges
    }

    edge_policy_rows = []
    calibration_rows = []
    calibration_index = 0
    interior_count = 0
    vertex_count = 0
    mixed_sign_count = 0
    h2_target_count = 0
    planned_h1_count = 0

    for edge in sorted(edges, key=lambda r: (r["timestamp"], int(r["edge_id"][1:]))):
        key = (edge["timestamp"], edge["edge_id"])
        base_interior = unique([
            x for x in parse_fractions(edge["sorted_fractions"])
            if 1e-12 < x < 1 - 1e-12
        ])
        added = [f(r, "t") for r in enrichment_by_key.get(key, [])]
        final_interior = unique([*base_interior, *added])
        if edge["normal_sign_category"] == "mixed_sign":
            mixed_sign_count += 1
        hrow = holdout_by_key[key]
        h2_target = hrow["h1_information_gain"] == "NEARLY_REDUNDANT"
        h2_target_count += int(h2_target)
        planned_h1_count += int(hrow["h1_new_sample_count"])

        edge_policy_rows.append({
            "timestamp": edge["timestamp"], "edge_id": edge["edge_id"],
            "boundary_class": edge["boundary_class"],
            "guard_relation": edge["guard_relation"],
            "endpoint_status_combination": edge["endpoint_status_combination"],
            "inward_normal_p13": edge["inward_normal_p13"],
            "inward_normal_p30": edge["inward_normal_p30"],
            "normal_sign_category": edge["normal_sign_category"],
            "normal_policy": "USE_ORIGINAL_INWARD_NORMAL_NO_COMPONENTWISE_PROJECTION",
            "owner_cell_id": edge["owner_cell_ids"],
            "parallel_retreat_cap_kw": edge["parallel_retreat_cap_kw"],
            "cap_role": "GEOMETRY_BOUND_ONLY_NOT_PRIMARY_FALSIFICATION_PATH",
            "committed_failure_count": failing_by_key.get(key, 0),
            "original_interior_calibration_count": len(base_interior),
            "enrichment_count": len(added),
            "locked_interior_calibration_count": len(final_interior),
            "locked_calibration_g_e": max_gap(final_interior),
            "future_d_e_star_kw": "FUTURE_AC_ONLY",
            "repair_scope": "ALL_OUTER_EDGES_SYMMETRIC_BOUNDARY_HEADROOM",
            "h1_planned_count_pre_repair": hrow["h1_new_sample_count"],
            "h2_targeted": h2_target,
        })

        polygon = polygon_by_key[key]
        polygon_a = (f(polygon, "endpoint_a_p13_abs_kw"), f(polygon, "endpoint_a_p30_abs_kw"))
        polygon_b = (f(polygon, "endpoint_b_p13_abs_kw"), f(polygon, "endpoint_b_p30_abs_kw"))
        calibration_index += 1
        vertex_count += 1
        calibration_rows.append({
            "calibration_membership_id": f"CAL_{calibration_index:06d}",
            "timestamp": edge["timestamp"], "edge_id": edge["edge_id"],
            "t": 0.0, "p13_abs_kw_at_source_geometry": polygon_a[0],
            "p30_abs_kw_at_source_geometry": polygon_a[1],
            "source_kind": "OUTER_VERTEX_ENDPOINT_A_ONCE_PER_EDGE",
            "future_role": "COMBINED_REPAIRED_GEOMETRY_VERIFICATION_ONLY",
            "future_d_i_star_kw": "NOT_APPLICABLE_VERTEX_COMBINED_GEOMETRY",
            "ac_evaluated_in_preregistration": False,
        })
        for t in final_interior:
            calibration_index += 1
            interior_count += 1
            is_added = any(abs(t - x) <= 1e-12 for x in added)
            calibration_rows.append({
                "calibration_membership_id": f"CAL_{calibration_index:06d}",
                "timestamp": edge["timestamp"], "edge_id": edge["edge_id"],
                "t": t,
                "p13_abs_kw_at_source_geometry": (1 - t) * polygon_a[0] + t * polygon_b[0],
                "p30_abs_kw_at_source_geometry": (1 - t) * polygon_a[1] + t * polygon_b[1],
                "source_kind": "LOW_SAMPLE_ENRICHMENT" if is_added else "COMMITTED_ANGULAR_INTERIOR",
                "future_role": "D_I_STAR_SEARCH_AND_FINAL_REPAIRED_GEOMETRY_VERIFY",
                "future_d_i_star_kw": "FUTURE_AC_ONLY",
                "ac_evaluated_in_preregistration": False,
            })

    check("MIXED_SIGN_COUNT", mixed_sign_count == 65, f"observed={mixed_sign_count}")
    check("MIXED_SIGN_NO_PROJECTION",
          all(r["normal_policy"] == "USE_ORIGINAL_INWARD_NORMAL_NO_COMPONENTWISE_PROJECTION"
              for r in edge_policy_rows if r["normal_sign_category"] == "mixed_sign"),
          "all mixed-sign rows retain original inward normal")
    check("CALIBRATION_INTERIOR_COUNT", interior_count == 22315,
          f"observed={interior_count}")
    check("CALIBRATION_VERTEX_COUNT", vertex_count == 1689,
          f"observed={vertex_count}")
    check("CALIBRATION_MEMBERSHIP_TOTAL", len(calibration_rows) == 24004,
          f"observed={len(calibration_rows)}")
    check("EVERY_EDGE_HAS_THREE_INTERIOR_POINTS",
          all(int(r["locked_interior_calibration_count"]) >= 3 for r in edge_policy_rows),
          f"minimum={min(int(r['locked_interior_calibration_count']) for r in edge_policy_rows)}")
    check("H1_PLANNED_COUNT", planned_h1_count == 23040,
          f"pre-repair_candidate_count={planned_h1_count}")
    check("H2_TARGET_EDGE_COUNT", h2_target_count == 120,
          f"pre-repair_target_edges={h2_target_count}")

    holdout_rows = []
    for row in sorted(holdout, key=lambda r: (r["timestamp"], int(r["edge_id"][1:]))):
        h2 = row["h1_information_gain"] == "NEARLY_REDUNDANT"
        holdout_rows.append({
            "timestamp": row["timestamp"], "edge_id": row["edge_id"],
            "calibration_n_before_enrichment": row["calibration_n_e"],
            "calibration_g_before_enrichment": row["calibration_g_e"],
            "h1_definition": "POST_REPAIR_INTERSECTIONS_OF_0.25_PLUS_0.5K_DEGREE_RAYS",
            "h1_pre_repair_candidate_count": row["h1_new_sample_count"],
            "h1_pre_repair_g_e": row["h1_g_e"],
            "h2_targeted": h2,
            "h2_definition": "MIDPOINT_OF_LARGEST_REMAINING_T_GAP_AFTER_RETAINED_H1",
            "overlap_policy": "REJECT_ANY_HOLDOUT_COORDINATE_WITH_COMPONENTWISE_DISTANCE_LE_1E-8_KW_TO_CALIBRATION",
            "replacement_policy": "ITERATE_NEXT_LARGEST_GAP_MIDPOINT_TIE_LOWEST_LEFT_ENDPOINT",
            "actual_post_repair_holdout_count": "FUTURE_GEOMETRY_ONLY",
            "ac_evaluated_in_preregistration": False,
        })

    calibration_primary_cap = (
        len(edges) * (MAX_ANCHOR_BRACKET_CALLS_PER_EDGE + MAX_ANCHOR_BISECTION_CALLS_PER_EDGE)
        + interior_count
        + interior_count * MAX_VERIFY_ESCALATE_CALLS_PER_INTERIOR_COORDINATE
        + len(calibration_rows)
        + 128
    )
    calibration_retry_cap = math.ceil(calibration_primary_cap * RETRY_BUDGET_FRACTION)
    holdout_primary_cap = planned_h1_count + h2_target_count + 128
    holdout_retry_cap = math.ceil(holdout_primary_cap * RETRY_BUDGET_FRACTION)
    total_primary_cap = calibration_primary_cap + holdout_primary_cap
    total_retry_cap = calibration_retry_cap + holdout_retry_cap

    budget_rows = [
        {"phase": "CALIBRATION", "budget_item": "edge_anchor_bracket_and_bisection",
         "unit_count": len(edges), "calls_per_unit_cap": MAX_ANCHOR_BRACKET_CALLS_PER_EDGE + MAX_ANCHOR_BISECTION_CALLS_PER_EDGE,
         "primary_logical_call_cap": len(edges) * (MAX_ANCHOR_BRACKET_CALLS_PER_EDGE + MAX_ANCHOR_BISECTION_CALLS_PER_EDGE),
         "retry_call_cap": "IN_GLOBAL_RETRY_CAP", "wall_time_budget": "NOT_USED"},
        {"phase": "CALIBRATION", "budget_item": "anchor_screen_all_interior_memberships",
         "unit_count": interior_count, "calls_per_unit_cap": 1,
         "primary_logical_call_cap": interior_count, "retry_call_cap": "IN_GLOBAL_RETRY_CAP", "wall_time_budget": "NOT_USED"},
        {"phase": "CALIBRATION", "budget_item": "verify_escalate_interior_memberships",
         "unit_count": interior_count, "calls_per_unit_cap": MAX_VERIFY_ESCALATE_CALLS_PER_INTERIOR_COORDINATE,
         "primary_logical_call_cap": interior_count * MAX_VERIFY_ESCALATE_CALLS_PER_INTERIOR_COORDINATE,
         "retry_call_cap": "IN_GLOBAL_RETRY_CAP", "wall_time_budget": "NOT_USED"},
        {"phase": "CALIBRATION", "budget_item": "combined_repaired_geometry_final_verification",
         "unit_count": len(calibration_rows), "calls_per_unit_cap": 1,
         "primary_logical_call_cap": len(calibration_rows), "retry_call_cap": "IN_GLOBAL_RETRY_CAP", "wall_time_budget": "NOT_USED"},
        {"phase": "CALIBRATION", "budget_item": "configuration_controls",
         "unit_count": 128, "calls_per_unit_cap": 1,
         "primary_logical_call_cap": 128, "retry_call_cap": "IN_GLOBAL_RETRY_CAP", "wall_time_budget": "NOT_USED"},
        {"phase": "CALIBRATION", "budget_item": "phase_total",
         "unit_count": "", "calls_per_unit_cap": "",
         "primary_logical_call_cap": calibration_primary_cap,
         "retry_call_cap": calibration_retry_cap, "wall_time_budget": "NOT_USED"},
        {"phase": "HOLDOUT", "budget_item": "H1_plus_targeted_H2_plus_controls_pre_repair_count",
         "unit_count": planned_h1_count + h2_target_count + 128, "calls_per_unit_cap": 1,
         "primary_logical_call_cap": holdout_primary_cap,
         "retry_call_cap": holdout_retry_cap, "wall_time_budget": "NOT_USED"},
        {"phase": "TOTAL", "budget_item": "study_hard_cap",
         "unit_count": "", "calls_per_unit_cap": "",
         "primary_logical_call_cap": total_primary_cap,
         "retry_call_cap": total_retry_cap, "wall_time_budget": "NOT_USED"},
    ]

    check("BUDGET_NOT_WALL_TIME",
          all(r["wall_time_budget"] == "NOT_USED" for r in budget_rows),
          f"primary_cap={total_primary_cap},retry_cap={total_retry_cap}")

    config = {
        "schema_version": 1,
        "study": "DSO_VPP_AC_BOUNDARY_HEADROOM_REPAIR",
        "source_commit": SOURCE_COMMIT,
        "execution_authorized_by_this_artifact": False,
        "new_ac_calls_in_preregistration": 0,
        "locked_campaign_classification": "MAIN_COUPLED_DOE_GEOMETRIC_CANDIDATE_FALSIFIED_BY_AC_COUNTEREXAMPLE",
        "boundary_headroom_policy": {
            "policy_name": "BOUNDARY_HEADROOM_POLICY",
            "h_design_pu": h_design,
            "evidence_envelope_pu": evidence_envelope,
            "rounding_quantum_pu": HEADROOM_QUANTUM_PU,
            "evidence": {
                "maximum_observed_negative_signed_margin_pu": observed_negative_margin,
                "maximum_diagnostic_predicted_midpoint_deficit_pu": predicted_midpoint_deficit,
                "maximum_primary_replay_voltage_difference_pu": maximum_replay_difference,
            },
            "symmetric_design_limits": {
                "vmin_pu": VOLTAGE_LIMIT_VMIN + h_design,
                "vmax_pu": VOLTAGE_LIMIT_VMAX - h_design,
            },
            "assessment_tracks": {
                "original_limits": {"vmin_pu": VOLTAGE_LIMIT_VMIN, "vmax_pu": VOLTAGE_LIMIT_VMAX},
                "headroom_claim": {"vmin_pu": VOLTAGE_LIMIT_VMIN + h_design,
                                     "vmax_pu": VOLTAGE_LIMIT_VMAX - h_design},
            },
            "replay_tolerance_is_mandatory_floor": False,
        },
        "repair_geometry": {
            "operation": "PARALLEL_FACET_TIGHTENING_IN_ORIGINAL_INWARD_NORMAL",
            "halfspace_semantics": "n_in_dot_x_minus_a_ge_d_e",
            "normal_projection": "FORBIDDEN_INCLUDING_65_MIXED_SIGN_NORMALS",
            "owner_cell_scope": "ONE_COMMITTED_CONVEX_OWNER_PER_OUTER_EDGE",
            "combined_cell_rebuild": "INTERSECT_ALL_TIGHTENED_ORIGINAL_HALFSPACES_AND_RECOMPUTE_VERTICES",
            "cap_role": "GEOMETRY_BOUND_ONLY",
            "cap_rule": "EACH_D_E_STAR_STRICTLY_LESS_THAN_CAP_E_AND_COMBINED_CELL_MUST_REMAIN_NONDEGENERATE",
        },
        "calibration": {
            "low_sample_enrichment_before_ac": True,
            "true_low_sample_edges": len(low_edges),
            "enrichment_coordinates": len(enrichment),
            "interior_memberships": interior_count,
            "vertex_verification_memberships": vertex_count,
            "total_memberships": len(calibration_rows),
            "d_i_star": "SMALLEST_AC_EVALUATED_RETREAT_GRID_VALUE_MEETING_BOTH_HEADROOM_LIMITS;FUTURE_AC_ONLY",
            "d_e_star": "MAX_D_I_STAR_OVER_EDGE_INTERIOR_MEMBERSHIPS;FUTURE_AC_ONLY",
            "anchor_search": {
                "initial_step_kw": RETREAT_COARSE_INITIAL_STEP_KW,
                "bracket_rule": "VERIFY_PREDICTED_OR_NEAREST_T_ANCHOR_THEN_DOUBLE_OUTWARD_WITHOUT_EXCEEDING_CAP",
                "maximum_bracket_calls_per_edge": MAX_ANCHOR_BRACKET_CALLS_PER_EDGE,
                "maximum_bisection_calls_per_edge": MAX_ANCHOR_BISECTION_CALLS_PER_EDGE,
                "locked_retreat_resolution_kw": RETREAT_RESOLUTION_KW,
            },
            "verify_escalate": {
                "maximum_extra_calls_per_interior_membership": MAX_VERIFY_ESCALATE_CALLS_PER_INTERIOR_COORDINATE,
                "final_common_edge_retreat_reverification": True,
                "vertex_failure_escalation": "INCREMENT_INCIDENT_EDGE_WITH_SMALLER_D_E_OVER_CAP_E;TIE_LOWEST_EDGE_ID",
            },
            "reentry_detection": {
                "classification": "LOCAL_GRID_DIAGNOSTIC_NOT_GLOBAL_MONOTONICITY_PROOF",
                "resolution_kw": RETREAT_RESOLUTION_KW,
                "stencil": "D_ACCEPTED_MINUS_DELTA,D_ACCEPTED,D_ACCEPTED_PLUS_DELTA_WHERE_GEOMETRICALLY_VALID",
                "trigger": "ANY_PASS_TO_FAIL_TRANSITION_WITH_INCREASING_RETREAT",
                "trigger_action": "REENTRY_BLOCKER_STOP_BEFORE_REPAIR_FREEZE",
            },
        },
        "holdout": {
            "H1": "INTERLACED_0.25_PLUS_0.5K_DEGREE_POST_REPAIR_RAY_INTERSECTIONS",
            "H2": "TARGETED_LARGEST_REMAINING_T_GAP_MIDPOINT_ON_H1_REDUNDANT_EDGES",
            "pre_repair_H1_candidate_count": planned_h1_count,
            "pre_repair_H2_target_edge_count": h2_target_count,
            "calibration_holdout_overlap_required": 0,
            "coordinate_tolerance_kw_componentwise": COORD_TOL_KW,
            "overlap_action": "REJECT_HOLDOUT_CANDIDATE_AND_USE_NEXT_LARGEST_GAP_MIDPOINT",
            "generation_time": "STRICTLY_AFTER_FINAL_REPAIRED_GEOMETRY_FREEZE_BEFORE_ANY_HOLDOUT_AC",
        },
        "checkpoint": {
            "architecture": "APPEND_ONLY_IMMUTABLE_SHARDS_PLUS_COMPACT_CURSOR_AND_SOLVER_STATE",
            "chunk_rows": CHECKPOINT_CHUNK_ROWS,
            "shard_seal": "AT_2000_ROWS_OR_TIMESTAMP_COMPLETION_WHICHEVER_FIRST",
            "growing_full_state_serialization": "FORBIDDEN",
            "final_concatenation_and_hash": "ONCE_AFTER_PHASE_COMPLETION",
        },
        "budget": {
            "unit": "AC_LOGICAL_CALLS_AND_RETRY_CALLS_NOT_WALL_TIME",
            "primary_logical_call_cap": total_primary_cap,
            "retry_call_cap": total_retry_cap,
            "maximum_retries_per_logical_call": 1,
            "budget_exhaustion_action": "STOP_INCONCLUSIVE_NO_REPAIR_FREEZE",
        },
        "safe_box_policy": "SAFE_BOX_EXTRACTION_STRICTLY_AFTER_FINAL_REPAIRED_COUPLED_DOE_FREEZE",
    }

    future_schema_rows = [
        {"artifact": "future_ac_attempts.csv", "required_fields": "attempt_id;phase;timestamp;edge_id;calibration_id;d_kw;attempt_index;solver_status;vmin_pu;vmax_pu;maximum_residual;primary_replay_voltage_difference_pu;primary_iterations;replay_iterations", "purpose": "append-only AC attempt provenance"},
        {"artifact": "future_d_i_star.csv", "required_fields": "timestamp;edge_id;calibration_id;t;d_i_star_kw;lower_tested_fail_kw;upper_tested_pass_kw;resolution_kw;headroom_pass;reentry_flag", "purpose": "future AC-only point retreat estimates"},
        {"artifact": "future_d_e_star.csv", "required_fields": "timestamp;edge_id;d_e_star_kw;cap_e_kw;cap_pass;limiting_calibration_id;future_ac_status", "purpose": "future AC-only authoritative edge retreats"},
        {"artifact": "future_reentry_checks.csv", "required_fields": "timestamp;edge_id;calibration_id;d_minus_kw;status_minus;d_accept_kw;status_accept;d_plus_kw;status_plus;reentry_detected", "purpose": "locked-resolution local re-entry diagnostic"},
        {"artifact": "future_combined_geometry_checks.csv", "required_fields": "timestamp;cell_id;convex;nondegenerate;area_before_kw2;area_after_kw2;area_loss_kw2;facet_count_before;facet_count_after", "purpose": "combined multi-facet geometry gate"},
        {"artifact": "future_calibration_assessment.csv", "required_fields": "calibration_id;original_limit_pass;headroom_pass;final_status;vmin_margin_original_pu;vmax_margin_original_pu;vmin_margin_headroom_pu;vmax_margin_headroom_pu", "purpose": "separate original-limit and headroom tracks"},
        {"artifact": "future_holdout_points.csv", "required_fields": "holdout_id;tier;timestamp;edge_id;t;p13_abs_kw;p30_abs_kw;distance_to_calibration_kw;overlap_pass", "purpose": "post-freeze H1/H2 mesh and zero-overlap proof"},
        {"artifact": "future_holdout_assessment.csv", "required_fields": "holdout_id;original_limit_pass;headroom_pass;solver_status;vmin_pu;vmax_pu", "purpose": "independent holdout assessment"},
        {"artifact": "future_checkpoint_shards.csv", "required_fields": "phase;shard_id;first_attempt_id;last_attempt_id;row_count;sha256;sealed", "purpose": "append-only checkpoint manifest"},
        {"artifact": "future_call_budget.csv", "required_fields": "phase;primary_calls_used;retry_calls_used;primary_cap;retry_cap;budget_pass", "purpose": "call-count budget enforcement"},
        {"artifact": "future_repaired_freeze_manifest.json", "required_fields": "source_commit;repair_config_sha256;calibration_pass;geometry_pass;holdout_pass;files", "purpose": "authoritative repaired coupled DOE freeze gate"},
    ]

    blocker_checks = [r for r in checks if r["status"] == "BLOCKER"]
    failed_checks = [r for r in checks if r["status"] == "FAIL"]
    check("NO_PREREGISTRATION_BLOCKER", not blocker_checks,
          f"pre_final_blockers={len(blocker_checks)}", "FAIL")
    failed_checks = [r for r in checks if r["status"] == "FAIL"]

    summary = {
        "schema_version": 1,
        "artifact": "DSO_VPP_AC_BOUNDARY_HEADROOM_REPAIR_PREREGISTRATION",
        "source_commit": SOURCE_COMMIT,
        "status": "PREREGISTERED_NOT_EXECUTED",
        "zero_ac": True,
        "h_design_pu": h_design,
        "design_voltage_limits_pu": {"vmin": VOLTAGE_LIMIT_VMIN + h_design,
                                     "vmax": VOLTAGE_LIMIT_VMAX - h_design},
        "edge_count": len(edges),
        "failure_edge_count": len(failing_edges),
        "mixed_sign_edge_count": mixed_sign_count,
        "true_low_sample_edge_count": len(low_edges),
        "prompt_expected_low_sample_edge_count_not_confirmed": 44,
        "enrichment_coordinate_count": len(enrichment),
        "calibration_interior_membership_count": interior_count,
        "calibration_vertex_membership_count": vertex_count,
        "calibration_total_membership_count": len(calibration_rows),
        "pre_repair_H1_candidate_count": planned_h1_count,
        "pre_repair_H2_target_edge_count": h2_target_count,
        "primary_logical_call_hard_cap": total_primary_cap,
        "retry_call_hard_cap": total_retry_cap,
        "locked_campaign_classification": "MAIN_COUPLED_DOE_GEOMETRIC_CANDIDATE_FALSIFIED_BY_AC_COUNTEREXAMPLE",
        "safe_box_policy": "SAFE_BOX_EXTRACTION_STRICTLY_AFTER_FINAL_REPAIRED_COUPLED_DOE_FREEZE",
        "next_authorized_action": "IMPLEMENT_EXECUTION_SCRIPT_SEPARATELY;DO_NOT_RUN_WITHOUT_EXPLICIT_EXECUTION_AUTHORIZATION",
    }

    OUTDIR.mkdir(parents=True, exist_ok=True)
    outputs: list[Path] = []

    def emit(name: str, fields: list[str], rows: list[dict]):
        path = OUTDIR / name
        write_csv(path, fields, rows)
        outputs.append(path)

    emit("preregistration_checks.csv", ["check_id", "status", "detail"], checks)
    emit("edge_repair_policy.csv", list(edge_policy_rows[0].keys()), edge_policy_rows)
    emit("calibration_fraction_inventory.csv", list(calibration_rows[0].keys()), calibration_rows)
    emit("holdout_design.csv", list(holdout_rows[0].keys()), holdout_rows)
    emit("ac_call_budget.csv", list(budget_rows[0].keys()), budget_rows)
    emit("future_output_schemas.csv", list(future_schema_rows[0].keys()), future_schema_rows)

    config_path = OUTDIR / "repair_config.json"
    write_text(config_path, json.dumps(json_safe(config), indent=2, sort_keys=True, allow_nan=False) + "\n")
    outputs.append(config_path)
    summary_path = OUTDIR / "preregistration_summary.json"
    write_text(summary_path, json.dumps(json_safe(summary), indent=2, sort_keys=True, allow_nan=False) + "\n")
    outputs.append(summary_path)

    decision_rules = f"""# Locked Decision Rules

1. Preserve `MAIN_COUPLED_DOE_GEOMETRIC_CANDIDATE_FALSIFIED_BY_AC_COUNTEREXAMPLE` permanently.
2. No AC result from calibration may be relabelled as evidence about the independent holdout.
3. Enrich the corrected 41-edge low-sample set with the 130 locked fractions before calibration.
4. Construct each retreat with the original inward normal: `n_in · (x-a) >= d_e`. Projection is forbidden, including all 65 mixed-sign normals.
5. Determine `d_i*` and `d_e*` only from future AC calls. Signed interpolation and LinDistFlow scaling may order anchors but are never authoritative.
6. `d_i*` is the smallest tested retreat on the locked {RETREAT_RESOLUTION_KW:g} kW grid that meets both design limits (`Vmin >= {VOLTAGE_LIMIT_VMIN + h_design:.8f}`, `Vmax <= {VOLTAGE_LIMIT_VMAX - h_design:.8f}`).
7. Initial `d_e*` is the maximum interior-point `d_i*` on that edge. Rebuild all cells from tightened original halfspaces, then re-evaluate all {len(calibration_rows)} calibration memberships.
8. Any local PASS→FAIL transition with increasing retreat at the locked {RETREAT_RESOLUTION_KW:g} kW stencil is `REENTRY_BLOCKER`; this diagnostic is not a global monotonicity proof.
9. Reject `d_e* >= cap_e`, any nonconvex/degenerate combined cell, budget exhaustion, unresolved nonconvergence, or failed original-limit calibration. Geometry cap is a bound, not the primary falsification path.
10. Report original-limit and headroom assessments separately. A headroom failure must not erase an original-limit pass, and an original-limit failure always blocks repair freeze.
11. Generate H1/H2 only after repaired geometry freeze. Calibration/holdout coordinate overlap must be exactly zero at componentwise `{COORD_TOL_KW:g} kW` tolerance.
12. Holdout points are never used to modify retreat. Any holdout original-limit failure falsifies the repaired candidate; any holdout headroom-only failure rejects only the headroom claim unless preregistered otherwise.
13. Safe Box extraction is forbidden until final repaired coupled DOE freeze.
"""
    decision_path = OUTDIR / "decision_rules.md"
    write_text(decision_path, decision_rules)
    outputs.append(decision_path)

    execution_policy = f"""# Execution and Checkpoint Policy

This preregistration performs no AC calls and does not authorize execution.

## Anchor-search + verify-escalate

- Reuse committed `d=0` evidence as descriptive anchors.
- For each edge, select the most adverse artifact-predicted interior anchor; prediction only sets order.
- Verify the anchor by AC in the future. Start retreat bracketing at {RETREAT_COARSE_INITIAL_STEP_KW:g} kW and double outward, always below `cap_e`, for at most {MAX_ANCHOR_BRACKET_CALLS_PER_EDGE} logical calls.
- Refine the first AC fail/pass bracket to width <= {RETREAT_RESOLUTION_KW:g} kW with at most {MAX_ANCHOR_BISECTION_CALLS_PER_EDGE} calls.
- Screen every remaining interior membership at the accepted anchor retreat, then allow at most {MAX_VERIFY_ESCALATE_CALLS_PER_INTERIOR_COORDINATE} additional calls per membership.
- Rebuild the combined multi-facet geometry and verify all interior and vertex memberships at final common edge retreats.
- The local re-entry stencil is `d-Δ, d, d+Δ`, `Δ={RETREAT_RESOLUTION_KW:g} kW`, where geometrically valid. It detects local re-entry only; it does not assert global monotonicity between tested locations.

## Checkpoints

- Attempt rows are immutable and append-only.
- Seal a shard at {CHECKPOINT_CHUNK_ROWS} rows or timestamp completion, whichever comes first.
- Each shard records first/last attempt ID, row count, and SHA-256.
- Checkpoint state contains only the compact cursor, sealed-shard manifest, active solver state, call counters, and deterministic pending queue.
- Serializing the accumulated campaign history is forbidden.
- Concatenate and hash final tables once after phase completion.

## Budget

The hard budget is {total_primary_cap} primary logical AC calls plus {total_retry_cap} retry calls across calibration and holdout. At most one retry is permitted per nonconverged logical call. Wall time is not a budget or stopping criterion. Exceeding either call cap stops the study as inconclusive before repair freeze.
"""
    execution_path = OUTDIR / "execution_and_checkpoint_policy.md"
    write_text(execution_path, execution_policy)
    outputs.append(execution_path)

    report = f"""# AC Boundary-Headroom Repair Study Preregistration

Source commit: `{SOURCE_COMMIT}`

Status: `PREREGISTERED_NOT_EXECUTED`

This package locks the future repair study. It performs no AC calibration,
solve, replay, probe, or repair.

## BOUNDARY_HEADROOM_POLICY

The evidence envelope is the maximum of:

- observed negative signed boundary margin: {fmt(observed_negative_margin)} p.u.;
- diagnostic predicted-midpoint deficit: {fmt(predicted_midpoint_deficit)} p.u.;
- maximum stored primary/replay voltage difference: {fmt(maximum_replay_difference)} p.u.

The envelope is rounded upward on the committed production voltage-termination
quantum `{HEADROOM_QUANTUM_PU:g}` p.u., giving:

`h_design = {h_design:.8f} p.u.`

The symmetric design limits are `Vmin >= {VOLTAGE_LIMIT_VMIN + h_design:.8f}`
and `Vmax <= {VOLTAGE_LIMIT_VMAX - h_design:.8f}`. Original AC limits
`[0.90, 1.05]` remain a separate authoritative assessment track. Replay
tolerance is not treated as a mandatory headroom floor.

## Repair geometry

All {len(edges)} outer facets are eligible for symmetric headroom calibration.
Each facet is tightened in its **original inward normal** using
`n_in · (x-a) >= d_e`. Componentwise projection is forbidden, including the
{mixed_sign_count} mixed-sign normals. Every edge has one committed convex
owner cell.

`cap_e` is only a single-facet geometry bound. It neither sets nor predicts
retreat. `d_i*` and `d_e*` remain `FUTURE_AC_ONLY`. Combined cells must be
rebuilt from all tightened halfspaces and remain convex and nondegenerate.

## Calibration population

- committed failure edges: {len(failing_edges)}
- corrected low-sample edges: {len(low_edges)} (not the unconfirmed prompt expectation 44)
- deterministic enrichment coordinates: {len(enrichment)}
- locked interior memberships: {interior_count}
- vertex combined-geometry verification memberships: {vertex_count}
- total calibration memberships: {len(calibration_rows)}

Low-sample enrichment occurs before any future AC calibration. Endpoint
vertices verify combined geometry; interior memberships drive per-edge
`d_i*`/`d_e*` search.

## Search, re-entry, and assessment

Anchor-search uses diagnostic predictions only to order calls. Every accepted
retreat is AC verified in the future. Bracketing, bisection, verify-escalate,
and a local re-entry stencil use the locked {RETREAT_RESOLUTION_KW:g} kW
resolution. A detected pass-to-fail transition blocks repair freeze. This is a
local diagnostic and not a global monotonicity theorem.

## Independent holdout

H1 is the post-repair interlaced `0.25 + 0.5k` degree mesh. H2 is targeted to
the largest remaining gap on H1-redundant edges. Pre-repair capability implies
{planned_h1_count} H1 candidates and {h2_target_count} H2-target edges; final
counts are generated only from frozen repaired geometry.

Any holdout coordinate within componentwise `{COORD_TOL_KW:g} kW` of a
calibration coordinate is rejected before AC evaluation and replaced by the
next deterministic eligible gap midpoint. Required calibration/holdout overlap
is exactly zero. Holdout outcomes never tune repair.

## Calls and checkpoints

Hard cap: {total_primary_cap} primary logical AC calls and {total_retry_cap}
retry calls. Wall time is not a budget. Results use append-only immutable
{CHECKPOINT_CHUNK_ROWS}-row shards, compact cursor/state checkpoints, and one
final concatenate/hash pass.

## Locked policy

`SAFE_BOX_EXTRACTION_STRICTLY_AFTER_FINAL_REPAIRED_COUPLED_DOE_FREEZE`

Future paper metrics must report repair area loss and hosting-capacity loss;
neither is computed by this preregistration.
"""
    report_path = OUTDIR / "preregistration_report.md"
    write_text(report_path, report)
    outputs.append(report_path)

    source_records = []
    for path in sorted(PATHS.values()):
        data = git("show", f"{SOURCE_COMMIT}:{path}")
        source_records.append({"path": path, "bytes": len(data),
                               "sha256": hashlib.sha256(data).hexdigest()})
    source_path = OUTDIR / "source_manifest.json"
    write_text(source_path, json.dumps({
        "source_commit": SOURCE_COMMIT,
        "read_semantics": "DIRECT_GIT_OBJECT_BYTES_NOT_WORKING_TREE",
        "files": source_records,
    }, indent=2, sort_keys=True) + "\n")
    outputs.append(source_path)

    manifest_entries = []
    for path in sorted(outputs, key=lambda p: p.name):
        data = path.read_bytes()
        manifest_entries.append({"path": path.name, "bytes": len(data),
                                 "sha256": hashlib.sha256(data).hexdigest()})
    manifest_path = OUTDIR / "manifest.json"
    write_text(manifest_path, json.dumps({
        "schema_version": 1,
        "artifact": "DSO_VPP_AC_BOUNDARY_HEADROOM_REPAIR_PREREGISTRATION",
        "source_commit": SOURCE_COMMIT,
        "files": manifest_entries,
    }, indent=2, sort_keys=True) + "\n")

    print(f"checks={len(checks)} blockers={len(blocker_checks)} failures={len(failed_checks)}")
    print(f"h_design={fmt(h_design)}")
    print(f"calibration interior/vertex/total={interior_count}/{vertex_count}/{len(calibration_rows)}")
    print(f"mixed-sign normals={mixed_sign_count}")
    print(f"H1/H2 pre-repair={planned_h1_count}/{h2_target_count}")
    print(f"call caps primary/retry={total_primary_cap}/{total_retry_cap}")
    print(f"manifest payloads={len(manifest_entries)}")
    return 1 if failed_checks else 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--verify-index", action="store_true")
    args = parser.parse_args()
    sys.exit(verify_index() if args.verify_index else main())
