#!/usr/bin/env python3
"""Build the artifact-only DSO/VPP DOE construction-policy preregistration.

This generator reads only committed production/audit artifacts.  It performs no
AC evaluation and no TVPP/HC optimization.  Output is deterministic: no wall
clock value, temporary path, or platform-specific newline enters an artifact.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable


SOURCE_HEAD = "c18021d9b981f2629e54f60e8c2fc5f33b00c1a2"
SOURCE_BRANCH = "codex/dso-vpp-ac-map-pilot"
POLICY_DATE = "2026-08-14"
CANONICAL_OUTPUT = Path("results/dso_vpp_ac_map_pilot/doe_construction_policy_preregistration")
SCRIPT_PATH = Path("scripts/prepare_dso_vpp_doe_construction_policy_preregistration.py")
GUARD_R = 2.0
GEOMETRY_EPS_KW = 1.0e-8

CLASS_ORDER = (
    "VMAX_BUS_13",
    "VMAX_BUS_30",
    "VMIN_BUS_18",
    "VMIN_BUS_33",
)
CLASS_KEY = {
    ("BINDING_VMAX", "13"): "VMAX_BUS_13",
    ("BINDING_VMAX", "30"): "VMAX_BUS_30",
    ("BINDING_VMIN", "18"): "VMIN_BUS_18",
    ("BINDING_VMIN", "33"): "VMIN_BUS_33",
}
TOPOLOGY_RAW = {
    "VMAX_BUS_13": (0.893822890071851, 0.268450094711859),
    "VMAX_BUS_30": (0.268450094711859, 0.625073311221421),
    "VMIN_BUS_18": (-0.893822890071851, -0.268450094711859),
    "VMIN_BUS_33": (-0.268450094711859, -0.625073311221421),
}

SOURCE_FILES = (
    "config/dso_vpp_production_probe_preregistration.toml",
    "src/benchmark/dso_vpp_production_probe.jl",
    "src/benchmark/dso_vpp_ac_map_stage0.jl",
    "results/dso_vpp_ac_map_pilot/absolute_pcc_coordinate_resolution/absolute_pcc_coordinate_resolution_report.md",
    "results/dso_vpp_ac_map_pilot/production_probe/run_manifest.toml",
    "results/dso_vpp_ac_map_pilot/production_probe/center_results.csv",
    "results/dso_vpp_ac_map_pilot/production_probe/signed_axis_results.csv",
    "results/dso_vpp_ac_map_pilot/production_probe/base_ray_results.csv",
    "results/dso_vpp_ac_map_pilot/production_probe/adaptive_ray_results.csv",
    "results/dso_vpp_ac_map_pilot/production_probe/boundary_endpoints.csv",
    "results/dso_vpp_ac_map_pilot/production_probe/evaluation_attempts.csv",
    "results/dso_vpp_ac_map_pilot/production_probe/unresolved_guard_cases.csv",
    "results/dso_vpp_ac_map_pilot/postproduction_result_audit/primary_binding_bus_audit.csv",
    "results/dso_vpp_ac_map_pilot/postproduction_result_audit/primary_binding_bus_summary.json",
    "results/dso_vpp_ac_map_pilot/postproduction_result_audit/ray_guard_truncation_audit.csv",
    "results/dso_vpp_ac_map_pilot/postproduction_result_audit/postproduction_result_audit_summary.json",
    "results/dso_vpp_ac_map_pilot/doe_preconstruction_artifact_refinement/sensitivity_topology_reconstruction.csv",
    "results/dso_vpp_ac_map_pilot/doe_preconstruction_artifact_refinement/boundary_input_reconciliation.csv",
    "results/dso_vpp_ac_map_pilot/doe_preconstruction_artifact_refinement/doe_preconstruction_artifact_refinement_summary.json",
    "results/dso_vpp_ac_map_pilot/monotonicity_falsification_screen/monotonicity_falsification_summary.json",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=CANONICAL_OUTPUT)
    return parser.parse_args()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, Any]], fields: Iterable[str] | None = None) -> None:
    if fields is None:
        if not rows:
            raise ValueError(f"fields required for empty CSV: {path}")
        fields = rows[0].keys()
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(fields), lineterminator="\n", extrasaction="raise")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: csv_value(row.get(key)) for key in writer.fieldnames})


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=True) + "\n", encoding="utf-8", newline="\n")


def write_text(path: Path, value: str) -> None:
    path.write_text(value.rstrip() + "\n", encoding="utf-8", newline="\n")


def csv_value(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        if math.isnan(value):
            return "NaN"
        return format(value, ".15g")
    return value


def f(value: str | float | int) -> float:
    return float(value)


def dot(a: tuple[float, float], p: tuple[float, float]) -> float:
    return a[0] * p[0] + a[1] * p[1]


def unit(a: tuple[float, float]) -> tuple[float, float]:
    norm = math.hypot(*a)
    return a[0] / norm, a[1] / norm


def angle_deg(vector: tuple[float, float]) -> float:
    return math.degrees(math.atan2(vector[1], vector[0])) % 360.0


def circular_distance(left: float, right: float) -> float:
    return abs((left - right + 180.0) % 360.0 - 180.0)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def endpoint_key(row: dict[str, str]) -> tuple[str, str, str, str]:
    return row["timestamp"], row["search_kind"], row["search_id"], row["level"]


def point(row: dict[str, str]) -> tuple[float, float]:
    return f(row["p13_abs_kw"]), f(row["p30_abs_kw"])


def class_id(row: dict[str, str]) -> str:
    try:
        return CLASS_KEY[(row["binding_mechanism"], row["binding_bus"])]
    except KeyError as exc:
        raise SystemExit(f"unexpected physical-boundary class: {exc.args[0]}") from exc


def signed_scales(axes: list[dict[str, str]], center: tuple[float, float]) -> dict[str, float]:
    by_axis = {row["axis"]: row for row in axes}
    required = {"P13_POSITIVE", "P13_NEGATIVE", "P30_POSITIVE", "P30_NEGATIVE"}
    if set(by_axis) != required or any(row["status"] != "AXIS_CERTIFIED_BOUNDARY" for row in axes):
        raise SystemExit("signed normalization requires exactly four certified axes")
    p13_max = f(by_axis["P13_POSITIVE"]["safe_p13_abs_kw"])
    p13_min = f(by_axis["P13_NEGATIVE"]["safe_p13_abs_kw"])
    p30_max = f(by_axis["P30_POSITIVE"]["safe_p30_abs_kw"])
    p30_min = f(by_axis["P30_NEGATIVE"]["safe_p30_abs_kw"])
    scales = {
        "s13_positive_kw": p13_max - center[0],
        "s13_negative_kw": center[0] - p13_min,
        "s30_positive_kw": p30_max - center[1],
        "s30_negative_kw": center[1] - p30_min,
    }
    if any(value <= 0 for value in scales.values()):
        raise SystemExit("nonpositive signed normalization scale")
    return scales


def normalized_point(p: tuple[float, float], center: tuple[float, float], scales: dict[str, float]) -> tuple[float, float, float, float]:
    dx, dy = p[0] - center[0], p[1] - center[1]
    sx = scales["s13_positive_kw"] if dx >= 0 else scales["s13_negative_kw"]
    sy = scales["s30_positive_kw"] if dy >= 0 else scales["s30_negative_kw"]
    x, y = dx / sx, dy / sy
    return x, y, math.hypot(x, y), angle_deg((x, y))


def intersect(left: dict[str, Any], right: dict[str, Any]) -> tuple[float, float] | None:
    det = left["a13"] * right["a30"] - left["a30"] * right["a13"]
    if abs(det) <= 1.0e-14:
        return None
    x = (left["b"] * right["a30"] - left["a30"] * right["b"]) / det
    y = (left["a13"] * right["b"] - left["b"] * right["a13"]) / det
    return x, y


def polygon_vertices(constraints: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for index, left in enumerate(constraints):
        for right in constraints[index + 1 :]:
            candidate = intersect(left, right)
            if candidate is None:
                continue
            maximum_violation = max(dot((item["a13"], item["a30"]), candidate) - item["b"] for item in constraints)
            if maximum_violation <= GEOMETRY_EPS_KW:
                rows.append({
                    "p13_abs_kw": candidate[0],
                    "p30_abs_kw": candidate[1],
                    "constraint_1": left["constraint_id"],
                    "constraint_2": right["constraint_id"],
                    "maximum_internal_enumeration_violation_kw": maximum_violation,
                })
    rows.sort(key=lambda row: angle_deg((row["p13_abs_kw"], row["p30_abs_kw"])))
    return rows


def fitted_normal(points: list[tuple[float, float]], topology: tuple[float, float]) -> dict[str, float]:
    # Exact coordinate duplicates are removed so storage duplication cannot reweight TLS.
    unique_points = sorted(set(points))
    if len(unique_points) < 2:
        raise SystemExit("TLS fit requires at least two unique points")
    mean_x = sum(p[0] for p in unique_points) / len(unique_points)
    mean_y = sum(p[1] for p in unique_points) / len(unique_points)
    sxx = sum((p[0] - mean_x) ** 2 for p in unique_points)
    syy = sum((p[1] - mean_y) ** 2 for p in unique_points)
    sxy = sum((p[0] - mean_x) * (p[1] - mean_y) for p in unique_points)
    tangent_angle = 0.5 * math.atan2(2.0 * sxy, sxx - syy)
    normal = (-math.sin(tangent_angle), math.cos(tangent_angle))
    if dot(normal, topology) < 0:
        normal = (-normal[0], -normal[1])
    alignment = max(-1.0, min(1.0, dot(normal, topology)))
    residuals = [abs(normal[0] * (p[0] - mean_x) + normal[1] * (p[1] - mean_y)) for p in unique_points]
    return {
        "fitted_a13_unit": normal[0],
        "fitted_a30_unit": normal[1],
        "fitted_normal_angle_deg": angle_deg(normal),
        "topology_normal_angle_deg": angle_deg(topology),
        "angular_deviation_deg": math.degrees(math.acos(alignment)),
        "tls_rms_orthogonal_residual_kw": math.sqrt(sum(value * value for value in residuals) / len(residuals)),
        "tls_max_orthogonal_residual_kw": max(residuals),
        "unique_point_count": len(unique_points),
        "exact_duplicate_count_removed": len(points) - len(unique_points),
    }


def coordinate_contract_rows() -> list[dict[str, Any]]:
    common = {
        "units": "kW for physical P; dimensionless for normalized coordinates",
        "reactive_policy": "Q_PCC=0 kvar (UNITY_POWER_FACTOR_INTERFACE_POLICY)",
    }
    return [
        {"point_family": "LEGACY_PHASE_B_COMMAND_POINT", "timestamp": "2012-10-15 13:00:00", "coordinate_semantics": "P_command, not a production DOE coordinate", "physical_origin_reference": "fixed command origin; P13 absolute base=777.7133428167988 kW, P30 base=0", "centering_transform": "P_command=P_PCC_abs-[777.7133428167988,0] kW", "normalization_scaling": "none", "source_artifact": "results/dso_vpp_ac_map_pilot/absolute_pcc_coordinate_resolution/absolute_pcc_coordinate_resolution_report.md", **common},
        {"point_family": "PRODUCTION_CENTER", "timestamp": "each of 32 timestamps", "coordinate_semantics": "absolute physical P_PCC at interfaces [13,30]", "physical_origin_reference": "P_PCC_abs=(0,0); positive export, negative import", "centering_transform": "none; c_t is stored directly", "normalization_scaling": "none", "source_artifact": "results/dso_vpp_ac_map_pilot/production_probe/center_results.csv", **common},
        {"point_family": "SIGNED_AXIS_SAFE_AND_VIOLATING_ENDPOINTS", "timestamp": "row timestamp", "coordinate_semantics": "absolute physical P_PCC; orthogonal interface coordinate exactly zero", "physical_origin_reference": "absolute P_PCC origin", "centering_transform": "none", "normalization_scaling": "none; axis coordinate is a signed physical coordinate/magnitude by axis contract", "source_artifact": "results/dso_vpp_ac_map_pilot/production_probe/signed_axis_results.csv; boundary_endpoints.csv", **common},
        {"point_family": "PHYSICAL_RAY_SAFE_AND_VIOLATING_ENDPOINTS", "timestamp": "row timestamp", "coordinate_semantics": "stored absolute physical P_PCC generated from centered normalized production ray", "physical_origin_reference": "absolute P_PCC origin; evaluation uses reference_pv_capacity_kw=0", "centering_transform": "P=c_t+r*[cos(theta)*s13_sign,sin(theta)*s30_sign]", "normalization_scaling": "theta and r use timestamp-specific sign-specific scales derived from four certified absolute axes", "source_artifact": "results/dso_vpp_ac_map_pilot/production_probe/base_ray_results.csv; adaptive_ray_results.csv; src/benchmark/dso_vpp_production_probe.jl:657-716", **common},
        {"point_family": "GUARD_TRAJECTORY_ENDPOINT", "timestamp": "row timestamp", "coordinate_semantics": "certified-feasible absolute physical P_PCC endpoint at production r_guard=2; not a physical boundary", "physical_origin_reference": "absolute P_PCC origin", "centering_transform": "same centered ray transform as physical rays", "normalization_scaling": "same timestamp/sign-specific production-ray scaling; cap is perpendicular to its normalized ray", "source_artifact": "results/dso_vpp_ac_map_pilot/postproduction_result_audit/ray_guard_truncation_audit.csv; evaluation_attempts.csv", **common},
        {"point_family": "CANDIDATE_FACET_VERTEX", "timestamp": "construction timestamp", "coordinate_semantics": "intersection in absolute physical P_PCC", "physical_origin_reference": "absolute P_PCC origin", "centering_transform": "subtract that timestamp's c_t only for guard-angle diagnostic", "normalization_scaling": "divide each centered component by its sign-specific production axis scale", "source_artifact": "generated candidate_vertex_guard_diagnostic.csv", **common},
        {"point_family": "FUTURE_NO_CONTROL_POINT", "timestamp": "future final TVPP/HC timestamp", "coordinate_semantics": "must be derived as absolute physical P_PCC from final accounting contract", "physical_origin_reference": "not assumed equal to command zero or P_PCC=(0,0)", "centering_transform": "none for Main Safe Box membership", "normalization_scaling": "none", "source_artifact": "UNRESOLVED_UNTIL_FINAL_TVPP_HC_ACCOUNTING_CONTRACT", **common},
    ]


def policy_config() -> dict[str, Any]:
    unresolved = [
        "AC mesh density", "physical-facet sampling density", "guard-cap sampling density",
        "interior sampling density", "angular-gap oversampling density", "guard-sector oversampling density",
        "candidate membership tolerance tau_membership_kw", "fitted-normal materiality threshold (if used)",
        "descending alpha schedule", "number of alpha levels m", "contraction stopping/numerical policy",
        "AC validation numerical tolerance",
        "checkpoint/resume batching", "parallel worker count",
    ]
    return {
        "schema_version": 1,
        "classification": "DOE_CONSTRUCTION_POLICY_PREREGISTERED_ARTIFACT_ONLY_AC_VALIDATION_NOT_EXECUTED",
        "policy_date": POLICY_DATE,
        "source_repository": {"branch": SOURCE_BRANCH, "head": SOURCE_HEAD},
        "coordinates": {
            "interfaces": [13, 30], "dimension": 2,
            "active_power": "ABSOLUTE_PHYSICAL_P_PCC_KW", "positive_sign": "EXPORT",
            "reactive_policy": "Q_PCC_EQUALS_ZERO", "pooling_across_timestamps": False,
            "production_ray_transform": "P=c_t+r*[cos(theta)*s13_sign,sin(theta)*s30_sign]",
        },
        "locked_evidence": {
            "physical_ray_boundaries": 1561, "signed_axis_boundaries": 128,
            "total_physical_boundaries": 1689, "guard_truncations": 73,
            "guard_semantics": "GUARD_TRUNCATION_NO_PHYSICAL_BOUNDARY_BRACKET",
            "binding_mechanism_counts": {"VMAX": 851, "VMIN": 838},
            "primary_classes": list(CLASS_ORDER),
            "co_binding_status": "CO_BINDING_STATUS_NOT_RESOLVABLE_FROM_STORED_ARTIFACTS",
            "source_spelling_of_co_binding_status": "CO_BINDING_NOT_RESOLVABLE_FROM_STORED_ARTIFACTS",
            "monotonicity": "NO_MONOTONICITY_COUNTEREXAMPLE_OBSERVED_IN_STORED_EVALUATIONS",
            "monotonicity_domain": "SAMPLED_RADIAL_AXIS_SKELETON",
            "angular_interior": "ANGULAR_INTERIOR_BETWEEN_SAMPLED_DIRECTIONS_NOT_DIRECTLY_EVALUATED",
            "boundary_semantics": "LAST_CONVERGED_FEASIBLE_INWARD_ENDPOINT_WITH_LOCAL_RADIAL_BRACKET",
            "boundary_interpretations": [
                "INWARD_ENDPOINT_HAS_NEGLIGIBLE_VOLTAGE_MARGIN_BUT_NONZERO_BOUNDARY_LOCATION_BRACKETING",
                "FINAL_BOUNDARY_WIDTHS_CONSISTENT_WITH_1_KW_STOPPING_RULE",
                "BOUNDARY_LOCATION_BRACKETING_IS_A_LOCAL_RADIAL_UNCERTAINTY",
                "FACET_INTERIOR_VALIDATION_RISK_IS_AN_INTER_DIRECTIONAL_GEOMETRIC_AND_AC_FEASIBILITY_UNCERTAINTY",
                "THE_TWO_ARE_NOT_INTERCHANGEABLE",
            ],
        },
        "candidate_physical_facets": {
            "authority": "CANDIDATE_FACET_GENERATOR_NOT_AC_FEASIBILITY_AUTHORITY",
            "topology_normals_raw": {key: list(TOPOLOGY_RAW[key]) for key in CLASS_ORDER},
            "normal_scaling": "positive Euclidean unit normalization; geometry unchanged; residual units kW",
            "orientation": "VMAX uses +c row; VMIN uses -c row; certified center must satisfy a_j^T c_t < b_j",
            "offset": "b_jt=max_{k in B_jt} a_j^T P_in_k",
            "input": "only certified SAFE physical boundary endpoints of same timestamp and primary class; guard rows excluded",
            "empty_class": "CONSTRUCTION_FAILURE_REQUIRING_POLICY_REVIEW",
        },
        "fitted_normal_diagnostic": {
            "role": "DIAGNOSTIC_FALSIFICATION_ONLY_CANNOT_REPLACE_TOPOLOGY_NORMAL",
            "method": "per-timestamp/class orthogonal total least squares via 2D PCA",
            "duplicate_policy": "remove exact duplicate physical coordinates before fit",
            "bracket_policy": "fit inward endpoints only; report paired radial-bracket length, do not convert it into facet margin",
            "materiality_threshold": None,
        },
        "guard_caps": {
            "rule": "ONLY_STORED_GUARD_LIMITED_TRAJECTORIES_CREATE_CAPS",
            "normalized_halfspace": "cos(theta)*z13+sin(theta)*z30<=2",
            "physical_conversion": "z_i=(P_i-c_i)/s_i_sign in the fixed sign sector of the stored ray",
            "semantic_class": "ARTIFICIAL_CONSERVATIVE_GUARD_TRUNCATION_NOT_PHYSICAL_AC_BOUNDARY",
        },
        "infeasible_endpoint_screen": {
            "role": "NECESSARY_FALSIFICATION_SCREEN_NOT_POLYTOPE_CERTIFICATION",
            "membership_rule": "outward endpoint is inside beyond tau iff max_j(a_j^T P-b_j)<=-tau_membership_kw",
            "membership_tolerance_kw": None,
            "action_on_failure": "contract; rerun screen; only then run full AC validation",
        },
        "contraction": {
            "family": "P_prime=c_t+alpha*(P-c_t)", "range": "0<alpha<=1",
            "schedule": "PREDECLARED_DESCENDING_CONTRACTION_SCHEDULE", "alpha_levels": None,
            "number_of_levels_m": None, "post_hoc_alpha_tuning": False,
            "ac_feasibility_monotone_in_alpha_claimed": False,
        },
        "ac_validation": {
            "execute_in_this_task": False, "purpose": "AC_MESH_FALSIFICATION_AND_EMPIRICAL_VALIDATION_NOT_PROOF",
            "mandatory_domains": ["all candidate vertices", "deterministic samples on every physical facet",
                                  "deterministic samples on every guard cap", "deterministic interior samples",
                                  "points between production rays", "largest angular-gap oversampling",
                                  "stored guard-sector oversampling", "all four final Main Safe Box corners"],
            "sequence": ["policy fixed", "limited runtime benchmark", "lock execution parameters",
                         "stored-infeasible endpoint screen", "substantive full AC validation"],
            "failure_action": "next predeclared contraction; rerun screen; rerun full validation; never hand-tune facets",
        },
        "main_safe_box": {
            "timing": "only after final Coupled DOE is fixed",
            "coordinates": "axis-aligned absolute physical P_PCC",
            "objective": "maximize (U13-L13)*(U30-L30)",
            "containment": "a13^+*U13+a13^-*L13+a30^+*U30+a30^-*L30<=b for every final halfspace",
            "continuous_optimization": True, "grid_allowed": False,
            "center_or_no_control_containment_required": False,
            "solver_form": "maximize log(U13-L13)+log(U30-L30) with strictly positive widths and exact linear whole-box containment",
            "lexicographic_tie_break": ["minimize L13", "minimize L30", "minimize U13", "minimize U30"],
            "numerical_tolerances": {"halfspace_feasibility_absolute_kw": 1.0e-8,
                                     "relative_primary_objective": 1.0e-10,
                                     "lexicographic_coordinate_absolute_kw": 1.0e-8},
            "later_checks": ["independent AC check of all four corners", "post-construction no-control membership diagnostic"],
        },
        "optional_box_diagnostics": {
            "no_control_anchored_box": "separate diagnostic only; cannot alter Main Safe Box",
            "hc_oriented_box": "separate diagnostic only; exact objective must be preregistered before viewing HC results",
        },
        "m_conditional_box": {
            "authority": "DIAGNOSTIC_ONLY_MUST_NOT_ENLARGE_AUTHORITATIVE_COUPLED_DOE",
            "construction": "choose stored certified VMIN lower diagonal and VMAX upper diagonal with componentwise order; maximize area over all such stored pairs",
            "tie_break": ["minimize L13", "minimize L30", "minimize U13", "minimize U30"],
            "assumption": "componentwise voltage monotonicity (M), empirical/conditional and not AC authority",
        },
        "unresolved_execution_parameters": unresolved,
        "forbidden_actions_confirmed_not_part_of_generator": ["new AC solve", "production probe", "annual TVPP optimization",
                                                               "HC optimization", "historical artifact regeneration",
                                                               "post-hoc facet or alpha tuning"],
    }


def build(root: Path, output: Path) -> None:
    prod = root / "results/dso_vpp_ac_map_pilot/production_probe"
    audit = root / "results/dso_vpp_ac_map_pilot/postproduction_result_audit"
    output.mkdir(parents=True, exist_ok=True)

    centers_rows = read_csv(prod / "center_results.csv")
    axis_rows = read_csv(prod / "signed_axis_results.csv")
    endpoint_rows = read_csv(prod / "boundary_endpoints.csv")
    guard_rows = read_csv(audit / "ray_guard_truncation_audit.csv")
    centers = {row["timestamp"]: point({"p13_abs_kw": row["p13_abs_kw"], "p30_abs_kw": row["p30_abs_kw"]}) for row in centers_rows}
    axes_by_time: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in axis_rows:
        axes_by_time[row["timestamp"]].append(row)
    guards_by_time: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in guard_rows:
        guards_by_time[row["timestamp"]].append(row)
    paired: dict[tuple[str, str, str, str], dict[str, dict[str, str]]] = defaultdict(dict)
    for row in endpoint_rows:
        paired[endpoint_key(row)][row["endpoint_side"]] = row
    if len(centers) != 32 or len(endpoint_rows) != 3378 or len(guard_rows) != 73:
        raise SystemExit("locked production counts do not reconcile")
    if any(set(sides) != {"SAFE", "VIOLATING"} for sides in paired.values()) or len(paired) != 1689:
        raise SystemExit("physical boundary endpoint pairing does not reconcile to 1689")

    safe_rows = [sides["SAFE"] for sides in paired.values()]
    violating_rows = [sides["VIOLATING"] for sides in paired.values()]
    if Counter(row["binding_mechanism"] for row in safe_rows) != Counter({"BINDING_VMAX": 851, "BINDING_VMIN": 838}):
        raise SystemExit("binding mechanism counts changed")
    if Counter(class_id(row) for row in safe_rows) != Counter({"VMAX_BUS_13": 429, "VMAX_BUS_30": 422, "VMIN_BUS_18": 435, "VMIN_BUS_33": 403}):
        raise SystemExit("primary binding class counts changed")

    topology_unit = {key: unit(TOPOLOGY_RAW[key]) for key in CLASS_ORDER}
    facets: list[dict[str, Any]] = []
    fits: list[dict[str, Any]] = []
    constraints_by_time: dict[str, list[dict[str, Any]]] = defaultdict(list)
    scales_by_time: dict[str, dict[str, float]] = {}
    construction_failures: list[str] = []
    for timestamp in sorted(centers):
        center = centers[timestamp]
        scales_by_time[timestamp] = signed_scales(axes_by_time[timestamp], center)
        for cid in CLASS_ORDER:
            selected = [row for row in safe_rows if row["timestamp"] == timestamp and class_id(row) == cid]
            if not selected:
                construction_failures.append(f"{timestamp}:{cid}:EMPTY_CLASS")
                continue
            normal = topology_unit[cid]
            offsets = [dot(normal, point(row)) for row in selected]
            b = max(offsets)
            center_slack = b - dot(normal, center)
            bracket_lengths = []
            for row in selected:
                pair = paired[endpoint_key(row)]
                bracket_lengths.append(math.dist(point(pair["SAFE"]), point(pair["VIOLATING"])))
            facets.append({
                "timestamp": timestamp, "class_id": cid, "constraint_type": "PHYSICAL_LIMIT_CANDIDATE_FACET",
                "raw_topology_a13": TOPOLOGY_RAW[cid][0], "raw_topology_a30": TOPOLOGY_RAW[cid][1],
                "a13_unit": normal[0], "a30_unit": normal[1], "b_kw": b,
                "center_p13_abs_kw": center[0], "center_p30_abs_kw": center[1], "center_strict_slack_kw": center_slack,
                "contributing_inward_point_count": len(selected),
                "support_tie_count_at_1e_9_kw": sum(abs(value - b) <= 1.0e-9 for value in offsets),
                "minimum_paired_bracket_length_kw": min(bracket_lengths),
                "maximum_paired_bracket_length_kw": max(bracket_lengths),
                "construction_status": "PASS_CENTER_STRICTLY_INTERIOR" if center_slack > 0 else "FAIL_CENTER_NOT_STRICTLY_INTERIOR",
                "semantic_class": "TOPOLOGY_NORMAL_PLUS_CLASSWISE_MAX_OFFSET_CANDIDATE_NOT_CERTIFIED_INNER_FACET",
            })
            constraints_by_time[timestamp].append({"constraint_id": cid, "constraint_type": "PHYSICAL_LIMIT_CANDIDATE_FACET", "a13": normal[0], "a30": normal[1], "b": b})
            fit = fitted_normal([point(row) for row in selected], normal)
            fits.append({
                "timestamp": timestamp, "class_id": cid, "stored_inward_point_count": len(selected), **fit,
                "minimum_paired_bracket_length_kw": min(bracket_lengths),
                "maximum_paired_bracket_length_kw": max(bracket_lengths),
                "materiality_threshold_deg": None,
                "materiality_classification": "UNRESOLVED_THRESHOLD_NOT_PREREGISTERED",
                "role": "DIAGNOSTIC_ONLY_DO_NOT_REPLACE_TOPOLOGY_NORMAL",
            })
    if construction_failures:
        raise SystemExit(";".join(construction_failures))
    if len(facets) != 128 or any(row["center_strict_slack_kw"] <= 0 for row in facets):
        raise SystemExit("per-timestamp physical candidate facet construction failed")

    guard_caps: list[dict[str, Any]] = []
    guard_constraints_by_time: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in sorted(guard_rows, key=lambda item: (item["timestamp"], f(item["normalized_angle_deg"]), item["level"])):
        timestamp = row["timestamp"]
        center, scales = centers[timestamp], scales_by_time[timestamp]
        theta = math.radians(f(row["normalized_angle_deg"]))
        cosine, sine = math.cos(theta), math.sin(theta)
        sx = scales["s13_positive_kw"] if cosine >= 0 else scales["s13_negative_kw"]
        sy = scales["s30_positive_kw"] if sine >= 0 else scales["s30_negative_kw"]
        raw_a = (cosine / sx, sine / sy)
        raw_b = GUARD_R + dot(raw_a, center)
        norm = math.hypot(*raw_a)
        a = (raw_a[0] / norm, raw_a[1] / norm)
        b = raw_b / norm
        endpoint = (f(row["p13_guard_endpoint_kw"]), f(row["p30_guard_endpoint_kw"]))
        cap_id = f"GUARD_CAP_{row['level']}_{format(f(row['normalized_angle_deg']), '.12g')}DEG"
        endpoint_residual = dot(a, endpoint) - b
        guard_caps.append({
            "timestamp": timestamp, "constraint_id": cap_id, "constraint_type": "ARTIFICIAL_GUARD_TRUNCATION_CAP",
            "level": row["level"], "normalized_angle_deg": f(row["normalized_angle_deg"]),
            "production_guard_radius": GUARD_R, "a13_unit": a[0], "a30_unit": a[1], "b_kw": b,
            "center_slack_kw": b - dot(a, center), "guard_endpoint_p13_abs_kw": endpoint[0],
            "guard_endpoint_p30_abs_kw": endpoint[1], "guard_endpoint_halfspace_residual_kw": endpoint_residual,
            "source_semantic_class": row["downstream_semantic_class"],
            "policy_semantic_class": "GUARD_CAP_NOT_PHYSICAL_BOUNDARY",
        })
        guard_constraints_by_time[timestamp].append({"constraint_id": cap_id, "constraint_type": "ARTIFICIAL_GUARD_TRUNCATION_CAP", "a13": a[0], "a30": a[1], "b": b})
    if len(guard_caps) != 73 or any(abs(row["guard_endpoint_halfspace_residual_kw"]) > 1.0e-7 for row in guard_caps):
        raise SystemExit("guard cap reconstruction failed")

    vertex_rows: list[dict[str, Any]] = []
    geometry_summary: list[dict[str, Any]] = []
    long_vertex_rows: list[dict[str, Any]] = []
    for timestamp in sorted(centers):
        center, scales = centers[timestamp], scales_by_time[timestamp]
        guard_angles = sorted(f(row["normalized_angle_deg"]) for row in guards_by_time[timestamp])
        for geometry_stage, constraints in (
            ("PHYSICAL_FACETS_BEFORE_GUARD_CAPS", constraints_by_time[timestamp]),
            ("COUPLED_CANDIDATE_AFTER_GUARD_CAPS", constraints_by_time[timestamp] + guard_constraints_by_time[timestamp]),
        ):
            vertices = polygon_vertices(constraints)
            if not vertices:
                raise SystemExit(f"empty candidate polygon at {timestamp} {geometry_stage}")
            enriched = []
            for vertex_index, vertex in enumerate(vertices, start=1):
                p = (vertex["p13_abs_kw"], vertex["p30_abs_kw"])
                nx, ny, radius, theta = normalized_point(p, center, scales)
                nearest_guard = min(guard_angles, key=lambda value: (circular_distance(theta, value), value)) if guard_angles else None
                row = {
                    "timestamp": timestamp, "geometry_stage": geometry_stage, "vertex_index": vertex_index,
                    **vertex, "center_p13_abs_kw": center[0], "center_p30_abs_kw": center[1],
                    "normalized_x": nx, "normalized_y": ny, "normalized_radius": radius,
                    "normalized_ray_angle_deg": theta, "physical_displacement_angle_deg": angle_deg((p[0] - center[0], p[1] - center[1])),
                    "stored_guard_direction_count": len(guard_angles), "nearest_stored_guard_angle_deg": nearest_guard,
                    "nearest_guard_angular_deviation_deg": None if nearest_guard is None else circular_distance(theta, nearest_guard),
                    "guard_alignment_threshold_deg": None,
                    "guard_alignment_classification": "RAW_DIAGNOSTIC_THRESHOLD_NOT_PREREGISTERED",
                }
                vertex_rows.append(row)
                enriched.append(row)
            angular_order = sorted(enriched, key=lambda item: (item["normalized_ray_angle_deg"], item["p13_abs_kw"], item["p30_abs_kw"]))
            edge_lengths = [
                math.dist(
                    (angular_order[index]["p13_abs_kw"], angular_order[index]["p30_abs_kw"]),
                    (angular_order[(index + 1) % len(angular_order)]["p13_abs_kw"], angular_order[(index + 1) % len(angular_order)]["p30_abs_kw"]),
                )
                for index in range(len(angular_order))
            ]
            maximum_radius = max(row["normalized_radius"] for row in enriched)
            longest = [row for row in enriched if abs(row["normalized_radius"] - maximum_radius) <= 1.0e-12]
            active_guards = sorted({
                identifier for row in enriched for identifier in (row["constraint_1"], row["constraint_2"])
                if identifier.startswith("GUARD_CAP_")
            })
            geometry_summary.append({
                "timestamp": timestamp, "geometry_stage": geometry_stage, "vertex_count": len(enriched),
                "minimum_edge_length_kw": min(edge_lengths), "maximum_edge_length_kw": max(edge_lengths),
                "maximum_to_minimum_edge_length_ratio": max(edge_lengths) / min(edge_lengths),
                "minimum_normalized_vertex_radius": min(row["normalized_radius"] for row in enriched),
                "maximum_normalized_vertex_radius": maximum_radius,
                "longest_radius_vertex_count": len(longest),
                "longest_radius_vertex_angles_deg": ";".join(format(row["normalized_ray_angle_deg"], ".15g") for row in longest),
                "nearest_guard_deviations_for_longest_vertices_deg": ";".join(
                    format(row["nearest_guard_angular_deviation_deg"], ".15g") for row in longest
                    if row["nearest_guard_angular_deviation_deg"] is not None
                ),
                "stored_guard_direction_count": len(guard_angles), "active_guard_cap_count": len(active_guards),
                "active_guard_cap_ids": ";".join(active_guards),
                "guard_alignment_threshold_deg": None,
                "guard_alignment_classification": "RAW_OFFSET_DEPENDENT_DIAGNOSTIC_THRESHOLD_NOT_PREREGISTERED",
            })
            if geometry_stage == "PHYSICAL_FACETS_BEFORE_GUARD_CAPS":
                long_vertex_rows.extend(longest)
    if sum(row["geometry_stage"] == "PHYSICAL_FACETS_BEFORE_GUARD_CAPS" for row in vertex_rows) != 128:
        raise SystemExit("physical candidate did not yield four vertices per timestamp")

    # Screen all paired converged-infeasible endpoints against physical facets plus stored guard caps.
    screen_rows: list[dict[str, Any]] = []
    screen_summary: list[dict[str, Any]] = []
    by_timestamp_screen: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in sorted(violating_rows, key=lambda item: (item["timestamp"], item["search_kind"], item["search_id"], item["level"])):
        timestamp, p = row["timestamp"], point(row)
        constraints = constraints_by_time[timestamp] + guard_constraints_by_time[timestamp]
        residuals = [(item["constraint_id"], dot((item["a13"], item["a30"]), p) - item["b"]) for item in constraints]
        maximum = max(residuals, key=lambda item: (item[1], item[0]))
        minimum_slack = -maximum[1]
        result = {
            "timestamp": timestamp, "search_kind": row["search_kind"], "search_id": row["search_id"], "level": row["level"],
            "binding_class": class_id(row), "violating_p13_abs_kw": p[0], "violating_p30_abs_kw": p[1],
            "maximum_constraint_violation_kw": maximum[1], "limiting_constraint_id": maximum[0],
            "minimum_inside_slack_kw": minimum_slack, "strictly_inside_at_zero_tolerance": minimum_slack > 0,
            "membership_tolerance_kw": None,
            "authoritative_screen_classification": "PENDING_PREREGISTERED_MEMBERSHIP_TOLERANCE",
        }
        screen_rows.append(result)
        by_timestamp_screen[timestamp].append(result)
    for timestamp in sorted(centers):
        selected = by_timestamp_screen[timestamp]
        strict = [row for row in selected if row["strictly_inside_at_zero_tolerance"]]
        largest = max((row["minimum_inside_slack_kw"] for row in strict), default=0.0)
        screen_summary.append({
            "timestamp": timestamp, "outward_infeasible_endpoint_count": len(selected),
            "strictly_inside_at_zero_tolerance_count": len(strict),
            "largest_strict_inside_margin_kw": largest, "membership_tolerance_kw": None,
            "conditional_failure_statement": f"FAIL_FOR_ANY_TAU_MEMBERSHIP_KW_LT_{format(largest, '.15g')}" if strict else "NO_STRICT_INSIDE_POINT_AT_ZERO_TOLERANCE",
            "authoritative_status": "PENDING_PREREGISTERED_MEMBERSHIP_TOLERANCE",
        })
    if len(screen_rows) != 1689:
        raise SystemExit("infeasible endpoint screen count changed")

    inward_rows: list[dict[str, Any]] = []
    for row in sorted(safe_rows, key=lambda item: (item["timestamp"], item["search_kind"], item["search_id"], item["level"])):
        timestamp, p = row["timestamp"], point(row)
        constraints = constraints_by_time[timestamp] + guard_constraints_by_time[timestamp]
        maximum = max(dot((item["a13"], item["a30"]), p) - item["b"] for item in constraints)
        inward_rows.append({
            "timestamp": timestamp, "search_kind": row["search_kind"], "search_id": row["search_id"], "level": row["level"],
            "binding_class": class_id(row), "maximum_constraint_violation_kw": maximum,
            "inside_at_internal_enumeration_tolerance": maximum <= GEOMETRY_EPS_KW,
            "interpretation": "CONSTRUCTION_SANITY_CHECK_NOT_AC_INTERIOR_CERTIFICATION",
        })

    # Conditional-M diagnostic: stored VMIN and VMAX inward points are diagonal corners.
    m_boxes: list[dict[str, Any]] = []
    for timestamp in sorted(centers):
        lower = [row for row in safe_rows if row["timestamp"] == timestamp and row["binding_mechanism"] == "BINDING_VMIN"]
        upper = [row for row in safe_rows if row["timestamp"] == timestamp and row["binding_mechanism"] == "BINDING_VMAX"]
        candidates = []
        for low in lower:
            lp = point(low)
            for high in upper:
                up = point(high)
                if lp[0] <= up[0] and lp[1] <= up[1]:
                    area = (up[0] - lp[0]) * (up[1] - lp[1])
                    candidates.append((area, lp, up, low, high))
        if not candidates:
            raise SystemExit(f"no M-conditional stored diagonal pair at {timestamp}")
        candidates.sort(key=lambda item: (-item[0], item[1][0], item[1][1], item[2][0], item[2][1], endpoint_key(item[3]), endpoint_key(item[4])))
        area, lp, up, low, high = candidates[0]
        m_boxes.append({
            "timestamp": timestamp, "L13_abs_kw": lp[0], "L30_abs_kw": lp[1], "U13_abs_kw": up[0], "U30_abs_kw": up[1],
            "area_kw2": area, "eligible_stored_diagonal_pair_count": len(candidates),
            "lower_source_search_kind": low["search_kind"], "lower_source_search_id": low["search_id"], "lower_source_level": low["level"],
            "lower_source_class": class_id(low), "upper_source_search_kind": high["search_kind"],
            "upper_source_search_id": high["search_id"], "upper_source_level": high["level"], "upper_source_class": class_id(high),
            "classification": "M_CONDITIONAL_BOX_CANDIDATE_DIAGNOSTIC_ONLY_NOT_AC_AUTHORITY",
        })

    unresolved_rows = [
        {"parameter": name, "current_status": "UNRESOLVED", "lock_timing": "AFTER_LIMITED_RUNTIME_BENCHMARK_BEFORE_SUBSTANTIVE_AC_VALIDATION", "reason": reason}
        for name, reason in (
            ("AC mesh density", "runtime-dependent solve budget"),
            ("physical-facet sampling density", "runtime-dependent solve budget"),
            ("guard-cap sampling density", "runtime-dependent solve budget"),
            ("interior sampling density", "runtime-dependent solve budget"),
            ("angular-gap oversampling density", "runtime-dependent solve budget"),
            ("guard-sector oversampling density", "runtime-dependent solve budget"),
            ("candidate membership tolerance tau_membership_kw", "must be fixed before the endpoint screen is authoritative"),
            ("fitted-normal materiality threshold (if used)", "raw deviations reported; no threshold was previously preregistered"),
            ("descending alpha schedule", "requires runtime budget but cannot use validation outcomes"),
            ("number of alpha levels m", "requires runtime budget but cannot use validation outcomes"),
            ("contraction stopping/numerical policy", "must define deterministic exhaustion of the predeclared finite schedule; no validation-driven bisection"),
            ("AC validation numerical tolerance", "must be fixed with solver/runtime contract"),
            ("checkpoint/resume batching", "depends on measured runtime and storage cadence"),
            ("parallel worker count", "depends on benchmarked CPU/RAM behavior"),
        )
    ]

    coordinate_rows = coordinate_contract_rows()
    write_json(output / "policy_config.json", policy_config())
    write_csv(output / "coordinate_contract.csv", coordinate_rows)
    write_csv(output / "candidate_facets.csv", facets)
    write_csv(output / "fitted_normal_diagnostic.csv", fits)
    write_csv(output / "guard_caps.csv", guard_caps)
    write_csv(output / "candidate_vertex_guard_diagnostic.csv", vertex_rows)
    write_csv(output / "candidate_geometry_timestamp_summary.csv", geometry_summary)
    write_csv(output / "infeasible_endpoint_exclusion_screen.csv", screen_rows)
    write_csv(output / "infeasible_endpoint_exclusion_timestamp_summary.csv", screen_summary)
    write_csv(output / "stored_inward_endpoint_containment_check.csv", inward_rows)
    write_csv(output / "m_conditional_box_candidates.csv", m_boxes)
    write_csv(output / "unresolved_execution_parameters.csv", unresolved_rows)

    max_angle = max(row["angular_deviation_deg"] for row in fits)
    max_angle_row = max(fits, key=lambda row: (row["angular_deviation_deg"], row["timestamp"], row["class_id"]))
    strict_total = sum(row["strictly_inside_at_zero_tolerance_count"] for row in screen_summary)
    failing_timestamps = sum(row["strictly_inside_at_zero_tolerance_count"] > 0 for row in screen_summary)
    largest_margin_row = max(screen_summary, key=lambda row: (row["largest_strict_inside_margin_kw"], row["timestamp"]))
    smallest_timestamp_max_margin = min(row["largest_strict_inside_margin_kw"] for row in screen_summary)
    inward_outside = [row for row in inward_rows if not row["inside_at_internal_enumeration_tolerance"]]
    guard_diffs = [row["nearest_guard_angular_deviation_deg"] for row in long_vertex_rows if row["nearest_guard_angular_deviation_deg"] is not None]
    physical_geometry = [row for row in geometry_summary if row["geometry_stage"] == "PHYSICAL_FACETS_BEFORE_GUARD_CAPS"]
    report = f"""# DOE construction policy preregistration (artifact only)

## Scope and locked provenance

- Starting branch: `{SOURCE_BRANCH}`
- Starting HEAD: `{SOURCE_HEAD}`
- Initial working tree: clean
- Generation performs no AC solve, production probing, annual TVPP optimization, HC optimization, historical-result regeneration, or validation-driven tuning.
- Coordinate authority: absolute physical `P_PCC=[P13,P30]` kW, positive export, with `Q_PCC=0`.

This package preregisters a deterministic candidate generator and diagnostics. `LINDISTFLOW_IS_NOT_DOE_FEASIBILITY_AUTHORITY`; topology normals are candidate-facet generators. Stored fitted normals are diagnostic/falsification evidence only. Finite future AC meshes are empirical falsification/validation, never proof of continuous feasibility.

## Coordinate contract

The previous `(156.8947,1610.2757)` versus `(934.6080,1610.2757)` discrepancy is resolved by source: the former is command space and the latter is absolute physical PCC space, with `P_PCC_13_abs=777.7133428167988+P_command_13` for that historical Phase-B timestamp. Production data do not apply that translation: the production evaluator passes stored absolute `P_PCC` directly with `reference_pv_capacity_kw=0`. Rays use the exact timestamp-specific production transform `P=c_t+r[cos(theta)s13_sign,sin(theta)s30_sign]`. See `coordinate_contract.csv`.

## Locked boundary reconciliation

The input contains 1,561 physical ray boundaries plus 128 signed-axis boundaries = 1,689 paired physical brackets, and 73 separate guard-limited trajectories. VMAX=851 and VMIN=838. The four primary reported classes are VMAX/13 (429), VMAX/30 (422), VMIN/18 (435), and VMIN/33 (403). No fifth primary reported bus exists. `CO_BINDING_STATUS_NOT_RESOLVABLE_FROM_STORED_ARTIFACTS` is preserved; the historical source spells this `CO_BINDING_NOT_RESOLVABLE_FROM_STORED_ARTIFACTS`.

Guard truncations are certified-feasible endpoints, not physical boundaries and not evidence of unboundedness. They never enter classwise offset or fitted-normal calculations.

## Per-timestamp candidate physical facets

All 32 timestamps produced all four required classes (128 facets total); every certified production center is strictly inside all four oriented facets. Normals are the preregistered topology rows, negated for VMIN and positively unit-normalized without changing geometry. Each offset is the same-timestamp, same-class maximum support over certified inward endpoints. No fitted quantity changes a normal or offset. These are candidates, not certified inner facets.

The topology identities `c18,.=c13,.` and `c33,.=c30,.` are retained. Point counts, offsets, center slacks, and paired local radial bracket lengths are in `candidate_facets.csv`.

## Fitted-normal falsification diagnostic

The deterministic fit is unweighted orthogonal total least squares (2D PCA) per timestamp/class after removing exact duplicate coordinates. Inward endpoints alone are fitted; bracket lengths are reported, not converted to facet contraction. Across 128 fits the maximum raw orientation deviation is {max_angle:.12g} degrees at `{max_angle_row['timestamp']}` / `{max_angle_row['class_id']}`. No materiality threshold was preregistered, so no success/failure label is invented. Raw results are in `fitted_normal_diagnostic.csv`.

## Candidate vertices and guard geometry

Each four-facet physical candidate yielded four actual offset-dependent intersections. Every vertex was transformed back to the exact centered/sign-normalized production-ray convention before angle/radius comparison. Guard caps were created only for the 73 stored guard trajectories as `cos(theta)z13+sin(theta)z30<=2`, then converted to unit-normal physical halfspaces. They are explicitly artificial guard caps.

For the longest-normalized-radius physical vertex or tied vertices, the nearest stored guard-direction deviations range from {min(guard_diffs):.12g} to {max(guard_diffs):.12g} degrees. Physical-candidate maximum/minimum edge-length ratios range from {min(row['maximum_to_minimum_edge_length_ratio'] for row in physical_geometry):.12g} to {max(row['maximum_to_minimum_edge_length_ratio'] for row in physical_geometry):.12g} across timestamps. Alignment remains a raw observation because no angular materiality threshold was preregistered. Pre-cap and post-cap vertices are in `candidate_vertex_guard_diagnostic.csv`; timestamp-dependent edge ratios, diagonal directions, and active guard caps are in `candidate_geometry_timestamp_summary.csv`; caps are in `guard_caps.csv`.

## Stored infeasible-endpoint exclusion screen

The screen evaluated all 1,689 paired converged-infeasible outward endpoints against the same-timestamp physical facets plus guard caps, without AC solves. At zero tolerance, {strict_total} endpoints are strictly inside and {failing_timestamps}/32 timestamps contain at least one such point. The largest strict-inside margin is {largest_margin_row['largest_strict_inside_margin_kw']:.12g} kW at `{largest_margin_row['timestamp']}`. Every uncontracted (`alpha=1`) timestamp candidate is therefore `CONDITIONAL_FAIL`: all 32 fail for any future `tau_membership_kw < {smallest_timestamp_max_margin:.12g}` kW, and each row records its exact (larger or equal) failure bound. This is an artifact-level falsification of the uncontracted candidates, not a contradiction of the locked topology-normal policy. The dependent final-Coupled/Box construction stops at the predeclared contraction gate; no alpha is selected here.

The authoritative screen status remains `PENDING_PREREGISTERED_MEMBERSHIP_TOLERANCE`, as required. Excluding endpoints would still be only a necessary falsification screen, never certification. Details are in `infeasible_endpoint_exclusion_screen.csv` and its timestamp summary.

As a construction sanity check, {len(inward_outside)} of 1,689 stored inward endpoints fall outside the full pre-contraction candidate (physical facets plus stored guard caps) beyond the generator's fixed 1e-8 kW enumeration tolerance. This check is not an AC-interior certification; rows are in `stored_inward_endpoint_containment_check.csv`.

## Contraction and future AC validation

The only allowed family is `P'=c_t+alpha(P-c_t)`, `0<alpha<=1`, under a predeclared descending schedule. There is no validation-driven alpha bisection and no manual facet tuning. Each selected level must first rerun the stored-outward-endpoint screen and then the full mandatory AC protocol. Mesh density, alpha levels, AC tolerance, and runtime/checkpoint/parallel settings remain unresolved until a limited benchmark conducted before substantive validation.

Mandatory future domains are all candidate vertices, deterministic physical-facet samples, guard-cap samples, deterministic interior samples, between-ray points, largest-gap oversampling, guard-sector oversampling, and later all four Main Safe Box corners.

## Main Safe Box policy

Only after the final Coupled DOE is fixed, solve continuously in absolute physical PCC coordinates:

`maximize (U13-L13)(U30-L30)`

subject to, for every final halfspace, `a13+ U13 + a13- L13 + a30+ U30 + a30- L30 <= b`. The implementation form maximizes the equivalent sum of log widths; no grid is allowed. Equal-area solutions use the complete hierarchy: minimize `L13`, then `L30`, then `U13`, then `U30`. Fixed optimization tolerances are 1e-8 kW absolute halfspace feasibility, 1e-10 relative primary objective, and 1e-8 kW lexicographic coordinate tolerance.

The Main Box is objective-independent and need contain neither the production center nor a no-control point. All four corners require later independent AC checks. The final timestamp-specific no-control absolute PCC point is derived later from the final accounting contract and tested afterward; zero command is not presumed to mean `(0,0)` PCC.

## Conditional monotonicity diagnostic

`m_conditional_box_candidates.csv` selects, per timestamp, the maximum-area componentwise-ordered pair of a stored certified VMIN inward point (lower diagonal) and VMAX inward point (upper diagonal), with the Main Box lexicographic hierarchy. This is `M_CONDITIONAL_BOX_CANDIDATE_DIAGNOSTIC_ONLY_NOT_AC_AUTHORITY`; Assumption (M) remains empirical on the sampled radial/axis skeleton and cannot enlarge the authoritative Coupled DOE.

## Unresolved execution parameters

See `unresolved_execution_parameters.csv`. In particular, membership tolerance and any fitted-normal materiality threshold are unresolved, so the raw diagnostics are not silently thresholded.

## Sources inspected

""" + "\n".join(f"- `{path}`" for path in SOURCE_FILES) + "\n"
    write_text(output / "preregistration_report.md", report)

    generated_names = sorted(path.name for path in output.iterdir() if path.is_file() and path.name != "artifact_manifest.csv")
    manifest_rows = []
    for name in generated_names:
        physical = output / name
        manifest_rows.append({"path": (CANONICAL_OUTPUT / name).as_posix(), "bytes": physical.stat().st_size, "sha256": sha256(physical)})
    script = root / SCRIPT_PATH
    manifest_rows.append({"path": SCRIPT_PATH.as_posix(), "bytes": script.stat().st_size, "sha256": sha256(script)})
    manifest_rows.sort(key=lambda row: row["path"])
    write_csv(output / "artifact_manifest.csv", manifest_rows)


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    output = parse_args().output
    if not output.is_absolute():
        output = root / output
    build(root, output)


if __name__ == "__main__":
    main()
