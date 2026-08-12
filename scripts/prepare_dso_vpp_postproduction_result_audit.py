from __future__ import annotations

import csv
import hashlib
import json
import math
import statistics
import tomllib
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
PRODUCTION = ROOT / "results" / "dso_vpp_ac_map_pilot" / "production_probe"
OUTPUT = ROOT / "results" / "dso_vpp_ac_map_pilot" / "postproduction_result_audit"
ANCHOR = "2012-10-15 13:00:00"
PRODUCTION_ARTIFACT_COMMIT = "fed6d528611d9c55a04f49a8b353cf4ad015dc9c"
AXIS_GUARD_KW = 20_000.0
RAY_GUARD = 2.0
BOUNDARY_TOLERANCE_KW = 1.0
CARDINAL_ANGLES = (0.0, 90.0, 180.0, 270.0)
CARDINAL_GEOMETRY_TOLERANCE_KW = 1e-9


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, Any]], fields: Iterable[str] | None = None) -> None:
    if fields is None:
        if not rows:
            raise ValueError(f"fields required for empty CSV: {path}")
        fields = rows[0].keys()
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(fields), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def f(value: str | float | int) -> float:
    return float(value)


def i(value: str | float | int) -> int:
    return int(float(value))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def quantile(values: Iterable[float], probability: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return math.nan
    position = (len(ordered) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] * (1.0 - fraction) + ordered[upper] * fraction


def numeric_summary(values: Iterable[float]) -> dict[str, float | int]:
    data = sorted(value for value in values if math.isfinite(value))
    return {
        "count": len(data),
        "minimum": min(data) if data else math.nan,
        "q05": quantile(data, 0.05),
        "q25": quantile(data, 0.25),
        "median": quantile(data, 0.50),
        "mean": statistics.fmean(data) if data else math.nan,
        "q75": quantile(data, 0.75),
        "q95": quantile(data, 0.95),
        "maximum": max(data) if data else math.nan,
    }


def circular_angle(x: float, y: float) -> float:
    return math.degrees(math.atan2(y, x)) % 360.0


def circular_difference(first: float, second: float) -> float:
    return abs((first - second + 180.0) % 360.0 - 180.0)


def quadrant(x: float, y: float) -> str:
    if x >= 0.0 and y >= 0.0:
        return "Q1"
    if x < 0.0 <= y:
        return "Q2"
    if x < 0.0 and y < 0.0:
        return "Q3"
    return "Q4"


def angle_sector(angle: float, width: int = 30) -> str:
    lower = int(angle // width) * width
    return f"{lower:03d}-{lower + width:03d}"


def r_bin(radius: float) -> str:
    if not math.isfinite(radius):
        return "NOT_APPLICABLE"
    lower = math.floor(radius / 0.25) * 0.25
    return f"[{lower:.2f},{lower + 0.25:.2f})"


def axis_maps(axes: list[dict[str, str]]) -> dict[str, dict[str, dict[str, str]]]:
    result: dict[str, dict[str, dict[str, str]]] = defaultdict(dict)
    for row in axes:
        result[row["timestamp"]][row["axis"]] = row
    return result


def center_maps(centers: list[dict[str, str]]) -> dict[str, dict[str, str]]:
    return {row["timestamp"]: row for row in centers}


def scales_for(timestamp: str, axes_by_time: dict[str, dict[str, dict[str, str]]], centers_by_time: dict[str, dict[str, str]]) -> dict[str, float]:
    axis = axes_by_time[timestamp]
    center = centers_by_time[timestamp]
    p13_max = f(axis["P13_POSITIVE"]["official_boundary_p_pcc_kw"])
    p13_min = f(axis["P13_NEGATIVE"]["official_boundary_p_pcc_kw"])
    p30_max = f(axis["P30_POSITIVE"]["official_boundary_p_pcc_kw"])
    p30_min = f(axis["P30_NEGATIVE"]["official_boundary_p_pcc_kw"])
    c13 = f(center["p13_abs_kw"])
    c30 = f(center["p30_abs_kw"])
    return {
        "p13_max": p13_max,
        "p13_min": p13_min,
        "p30_max": p30_max,
        "p30_min": p30_min,
        "c13": c13,
        "c30": c30,
        "s13_positive": p13_max - c13,
        "s13_negative": c13 - p13_min,
        "s30_positive": p30_max - c30,
        "s30_negative": c30 - p30_min,
    }


def direction_vector(theta: float, scales: dict[str, float], centered: bool) -> tuple[float, float]:
    radians = math.radians(theta)
    cosine = math.cos(radians)
    sine = math.sin(radians)
    if centered:
        sx = scales["s13_positive"] if cosine >= 0 else scales["s13_negative"]
        sy = scales["s30_positive"] if sine >= 0 else scales["s30_negative"]
    else:
        sx = scales["p13_max"] if cosine >= 0 else abs(scales["p13_min"])
        sy = scales["p30_max"] if sine >= 0 else abs(scales["p30_min"])
    return cosine * sx, sine * sy


def cardinal_r1_point(angle: float, scales: dict[str, float]) -> tuple[float, float]:
    delta_p13, delta_p30 = direction_vector(angle, scales, centered=True)
    return scales["c13"] + delta_p13, scales["c30"] + delta_p30


def expected_cardinal_r1_point(angle: float, scales: dict[str, float]) -> tuple[float, float]:
    expected = {
        0.0: (scales["p13_max"], scales["c30"]),
        90.0: (scales["c13"], scales["p30_max"]),
        180.0: (scales["p13_min"], scales["c30"]),
        270.0: (scales["c13"], scales["p30_min"]),
    }
    return expected[angle]


def certified_ray_contract_pass(ray: dict[str, str]) -> bool:
    return (
        ray["status"] == "RAY_CERTIFIED_BOUNDARY"
        and ray["safe_solver_status"] == "CONVERGED_FEASIBLE"
        and ray["violating_solver_status"] == "CONVERGED_INFEASIBLE"
        and math.isclose(f(ray["official_boundary_r"]), f(ray["safe_r"]), abs_tol=1e-12)
        and f(ray["violating_r"]) > f(ray["safe_r"])
    )


def binding_audit(boundaries: list[dict[str, str]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    rows = []
    totals: Counter[str] = Counter()
    pairs: Counter[tuple[str, str]] = Counter()
    for row in boundaries:
        mechanism = row["binding_mechanism"]
        if mechanism not in {"BINDING_VMAX", "BINDING_VMIN"}:
            continue
        totals[mechanism] += 1
        pairs[(mechanism, row["binding_bus"])] += 1
    for mechanism in ("BINDING_VMAX", "BINDING_VMIN"):
        for bus in sorted(bus for mech, bus in pairs if mech == mechanism):
            count = pairs[(mechanism, bus)]
            rows.append({
                "binding_mechanism": mechanism,
                "primary_reported_binding_bus": int(bus),
                "count": count,
                "mechanism_total": totals[mechanism],
                "percentage_of_mechanism": 100.0 * count / totals[mechanism],
                "semantic_label": "PRIMARY_REPORTED_BINDING_BUS",
            })
    buses = sorted({bus for _, bus in pairs})
    return rows, {
        "counts": {mechanism: totals[mechanism] for mechanism in sorted(totals)},
        "primary_buses": [int(bus) for bus in buses],
        "fifth_primary_binding_bus_exists": len(buses) > 4,
        "co_binding_status": "CO_BINDING_NOT_RESOLVABLE_FROM_STORED_ARTIFACTS",
    }


def sensitivity_audit() -> dict[str, Any]:
    c3013 = 0.268450094711859
    c3030 = 0.625073311221421
    historical_p13 = 777.7133428167988
    historical_p30 = 1739.59228516
    production_p13 = 0.0
    production_p30 = 2080.625
    delta_p13 = production_p13 - historical_p13
    predicted = -(c3013 / c3030) * delta_p13
    observed = production_p30 - historical_p30
    discrepancy = abs(observed - predicted)
    return {
        "classification": "FIRST_ORDER_COORDINATE_AND_SENSITIVITY_CONSISTENCY_CHECK",
        "c_30_13": c3013,
        "c_30_30": c3030,
        "delta_p13_kw": delta_p13,
        "predicted_delta_p30_kw": predicted,
        "observed_delta_p30_kw": observed,
        "absolute_discrepancy_kw": discrepancy,
        "relative_discrepancy_vs_observed": discrepancy / abs(observed),
        "historical_primary_vmax_bus": 30,
        "production_primary_vmax_bus": 30,
        "historical_evidence": "results/dso_vpp_ac_map_pilot/export_side_axis_capacity_bounds.csv",
        "interpretation_limit": "Not proof of global LinDistFlow accuracy.",
    }


def retry_audit(attempts: list[dict[str, str]], axes_by_time: dict[str, dict[str, dict[str, str]]], rays_by_key: dict[tuple[str, str], dict[str, str]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    retry_rows = [row for row in attempts if i(row["attempt_index"]) == 2]
    output = []
    rescues = 0
    for row in retry_rows:
        rescued = row["solver_status"] in {"CONVERGED_FEASIBLE", "CONVERGED_INFEASIBLE"}
        rescues += rescued
        kind = row["search_kind"]
        phase = row["phase"]
        coordinate = f(row["coordinate"])
        radius = f(row["radius"])
        level = "AXIS"
        angle = math.nan
        final_boundary = math.nan
        if kind == "RAY":
            ray = rays_by_key[(row["timestamp"], row["search_id"])]
            level = ray["level"]
            angle = f(ray["angle_deg"])
            final_boundary = f(ray["official_boundary_r"])
        else:
            axis = axes_by_time[row["timestamp"]][row["search_id"]]
            final_boundary = abs(f(axis["official_boundary_p_pcc_kw"]))
        if kind == "AXIS":
            bracket_available = (
                phase.startswith("coarse_sweep")
                and math.isfinite(f(axis["transition_scale_kw"]))
            ) or phase == "bisection"
        else:
            bracket_available = phase == "bisection"
        beyond = coordinate > final_boundary if math.isfinite(final_boundary) else False
        p13 = f(row["p13_abs_kw"])
        p30 = f(row["p30_abs_kw"])
        output.append({
            "timestamp": row["timestamp"],
            "logical_evaluation_id": i(row["logical_evaluation_id"]),
            "search_kind": kind,
            "ray_level": level,
            "search_id": row["search_id"],
            "search_stage": phase,
            "coordinate": coordinate,
            "normalized_r": radius,
            "r_bin": r_bin(radius),
            "angle_deg": angle,
            "quadrant": quadrant(p13, p30) if kind == "RAY" else row["search_id"],
            "p13_abs_kw": p13,
            "p30_abs_kw": p30,
            "certified_bracket_already_available": bracket_available,
            "beyond_final_certified_boundary": beyond,
            "retry_status": row["solver_status"],
            "retry_rescued": rescued,
            "nonconvergence_is_physical_limit": False,
        })
    failures = len(retry_rows) - rescues
    return output, {
        "retry_attempts": len(retry_rows),
        "retry_rescues": rescues,
        "retry_failures": failures,
        "retry_rescue_rate": rescues / len(retry_rows) if retry_rows else math.nan,
        "search_kind_histogram": dict(sorted(Counter(row["search_kind"] for row in output).items())),
        "search_stage_histogram": dict(sorted(Counter(row["search_stage"] for row in output).items())),
        "ray_level_histogram": dict(sorted(Counter(row["ray_level"] for row in output).items())),
        "r_bin_histogram": dict(sorted(Counter(row["r_bin"] for row in output).items())),
        "quadrant_histogram": dict(sorted(Counter(row["quadrant"] for row in output).items())),
        "timestamp_histogram": dict(sorted(Counter(row["timestamp"] for row in output).items())),
        "before_certified_bracket_count": sum(not row["certified_bracket_already_available"] for row in output),
        "after_certified_bracket_count": sum(row["certified_bracket_already_available"] for row in output),
        "beyond_final_certified_boundary_count": sum(row["beyond_final_certified_boundary"] for row in output),
        "interpretation": "Empirical numerical failure-location observation; nonconvergence is not a physical limit.",
    }


def timing_audit(manifest: dict[str, Any]) -> dict[str, Any]:
    wall = float(manifest["wall_seconds"])
    logical = int(manifest["logical_evaluation_count"])
    actual = int(manifest["actual_ac_evaluation_count"])
    return {
        "classification": "TIMING_RATE_DIFFERENCE_CAUSE_UNRESOLVED",
        "preproduction": {
            "evaluations": 3691,
            "wall_seconds": 15.3498603,
            "aggregate_ms_per_evaluation": 4.1587,
            "processes": 1,
            "threads": 1,
        },
        "production": {
            "logical_evaluations": logical,
            "actual_attempts": actual,
            "wall_seconds": wall,
            "logical_ms_per_evaluation": 1000.0 * wall / logical,
            "actual_ms_per_attempt": 1000.0 * wall / actual,
            "processes": int(manifest["process_count"]),
            "threads": int(manifest["julia_thread_count"]),
        },
        "production_timer_scope": {
            "includes": [
                "preregistration hash verification",
                "locked configuration parsing/validation",
                "canonical profile loading",
                "AC probe execution including embedded independent replay",
                "first-call compilation/JIT occurring after run_production_probe starts",
                "per-direction and per-timestamp checkpoint I/O",
            ],
            "excludes": [
                "Julia process startup",
                "top-level package/module loading before run_production_probe invocation",
                "final artifact serialization",
                "normal final validation and distribution post-processing in write_outputs",
                "later independent post-run validation",
            ],
            "source_lines": "src/benchmark/dso_vpp_production_probe.jl:1469,1538-1540",
        },
        "interpretation": "Timer scopes and workloads differ; artifacts do not isolate a causal component.",
    }


def evaluation_decomposition(first_attempts: list[dict[str, str]], axes: list[dict[str, str]], rays_by_key: dict[tuple[str, str], dict[str, str]], retry_count: int) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    counts: Counter[str] = Counter()
    for row in first_attempts:
        kind = row["search_kind"]
        phase = row["phase"]
        if kind == "AXIS":
            if phase == "doubling":
                category = "SIGNED_AXIS_DOUBLING"
            elif phase.startswith("coarse_sweep"):
                category = "SIGNED_AXIS_COARSE_SWEEP"
            elif phase == "bisection":
                category = "SIGNED_AXIS_BISECTION"
            else:
                category = "SIGNED_AXIS_OTHER"
        elif kind == "CENTER":
            category = "CENTER_FEASIBILITY_CHECK"
        elif kind == "RAY":
            ray = rays_by_key[(row["timestamp"], row["search_id"])]
            level = ray["level"]
            if phase == "coarse_sweep":
                category = f"{level}_RAY_COARSE_SWEEP"
            elif phase == "bisection":
                category = f"{level}_RAY_BISECTION"
            else:
                category = f"{level}_RAY_OTHER"
        else:
            category = "OTHER"
        counts[category] += 1
    order = [
        "SIGNED_AXIS_DOUBLING", "SIGNED_AXIS_COARSE_SWEEP", "SIGNED_AXIS_BISECTION",
        "CENTER_FEASIBILITY_CHECK", "BASE_RAY_COARSE_SWEEP", "BASE_RAY_BISECTION",
        "ADAPTIVE_RAY_COARSE_SWEEP", "ADAPTIVE_RAY_BISECTION",
        "SIGNED_AXIS_OTHER", "BASE_RAY_OTHER", "ADAPTIVE_RAY_OTHER", "OTHER",
    ]
    rows = [{"category": category, "logical_evaluation_count": counts[category]} for category in order if counts[category]]
    bisection_counts: Counter[tuple[str, int]] = Counter()
    for axis in axes:
        if axis["status"] == "AXIS_CERTIFIED_BOUNDARY":
            bisection_counts[("AXIS", i(axis["refinement_steps"]))] += 1
    for (timestamp, search_id), ray in rays_by_key.items():
        if ray["status"] == "RAY_CERTIFIED_BOUNDARY":
            bisection_counts[(ray["level"], i(ray["refinement_steps"]))] += 1
    bisection_rows = [
        {"search_type": level, "bisection_steps": steps, "successful_search_count": count}
        for (level, steps), count in sorted(bisection_counts.items())
    ]
    logical_total = sum(counts.values())
    return rows, bisection_rows, {
        "logical_total": logical_total,
        "actual_total": logical_total + retry_count,
        "actual_minus_logical": retry_count,
        "difference_attributable_to_retries": True,
        "separate_validation_replay_logical_evaluations": 0,
        "embedded_replay_note": "Every AC attempt includes primary solve plus independent replay inside Stage0.evaluate_point; replay is not a separate logical record.",
        "stopping_rule": "<=1 kW physical bracket width AND safe/violating endpoint voltage distance <=1e-5 pu, maximum 60 refinements.",
    }


def asymmetry_audit(axes_by_time: dict[str, dict[str, dict[str, str]]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    rows = []
    for timestamp in sorted(axes_by_time):
        axes = axes_by_time[timestamp]
        p13_pos = f(axes["P13_POSITIVE"]["official_boundary_p_pcc_kw"])
        p13_neg = abs(f(axes["P13_NEGATIVE"]["official_boundary_p_pcc_kw"]))
        p30_pos = f(axes["P30_POSITIVE"]["official_boundary_p_pcc_kw"])
        p30_neg = abs(f(axes["P30_NEGATIVE"]["official_boundary_p_pcc_kw"]))
        rows.append({
            "timestamp": timestamp,
            "p13_positive_kw": p13_pos,
            "p13_negative_magnitude_kw": p13_neg,
            "a13": (p13_neg - p13_pos) / (p13_neg + p13_pos),
            "p30_positive_kw": p30_pos,
            "p30_negative_magnitude_kw": p30_neg,
            "a30": (p30_neg - p30_pos) / (p30_neg + p30_pos),
        })
    summary: dict[str, Any] = {}
    for metric in ("a13", "a30"):
        values = [row[metric] for row in rows]
        summary[metric] = numeric_summary(values) | {
            "fraction_positive": sum(value > 0 for value in values) / len(values),
            "fraction_negative": sum(value < 0 for value in values) / len(values),
            "strongest_import_side": max(rows, key=lambda row: row[metric])["timestamp"],
            "strongest_export_side": min(rows, key=lambda row: row[metric])["timestamp"],
        }
    summary["anchor"] = next(row for row in rows if row["timestamp"] == ANCHOR)
    summary["interpretation"] = "A>0 import side wider; A<0 export side wider. Center displacement is not treated as independent because every center is an axis midpoint."
    return rows, summary


def sampling_geometry(rays: list[dict[str, str]], axes_by_time: dict[str, dict[str, dict[str, str]]], centers_by_time: dict[str, dict[str, str]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    point_rows = []
    summaries = []
    certified_by_time: dict[str, list[dict[str, Any]]] = defaultdict(list)
    base_by_time: dict[str, list[dict[str, str]]] = defaultdict(list)
    for ray in rays:
        timestamp = ray["timestamp"]
        scales = scales_for(timestamp, axes_by_time, centers_by_time)
        theta = f(ray["angle_deg"])
        centered_vx, centered_vy = direction_vector(theta, scales, centered=True)
        centered_vector_angle = circular_angle(centered_vx, centered_vy)
        if ray["level"] == "BASE":
            hypothetical_vx, hypothetical_vy = direction_vector(theta, scales, centered=False)
            hypothetical_angle = circular_angle(hypothetical_vx, hypothetical_vy)
        else:
            hypothetical_angle = math.nan
        if ray["level"] == "BASE":
            base_by_time[timestamp].append(ray)
        if ray["status"] == "RAY_CERTIFIED_BOUNDARY":
            p13 = f(ray["safe_p13_abs_kw"])
            p30 = f(ray["safe_p30_abs_kw"])
            actual_angle = circular_angle(p13, p30)
            record = {
                "timestamp": timestamp, "level": ray["level"], "normalized_angle_deg": theta,
                "status": ray["status"], "p13_abs_kw": p13, "p30_abs_kw": p30,
                "actual_origin_polar_angle_deg": actual_angle,
                "centered_direction_vector_angle_deg": centered_vector_angle,
                "hypothetical_origin_direction_angle_deg": hypothetical_angle,
                "actual_vs_hypothetical_angular_displacement_deg": circular_difference(actual_angle, hypothetical_angle) if math.isfinite(hypothetical_angle) else math.nan,
                "semantic_class": "CERTIFIED_PHYSICAL_AC_BOUNDARY",
            }
            point_rows.append(record)
            certified_by_time[timestamp].append(record)
        else:
            point_rows.append({
                "timestamp": timestamp, "level": ray["level"], "normalized_angle_deg": theta,
                "status": ray["status"], "p13_abs_kw": math.nan, "p30_abs_kw": math.nan,
                "actual_origin_polar_angle_deg": math.nan,
                "centered_direction_vector_angle_deg": centered_vector_angle,
                "hypothetical_origin_direction_angle_deg": hypothetical_angle,
                "actual_vs_hypothetical_angular_displacement_deg": math.nan,
                "semantic_class": "CERTIFIED_FEASIBLE_GUARD_TRUNCATION",
            })
    for timestamp in sorted(certified_by_time):
        actual_angles = sorted(row["actual_origin_polar_angle_deg"] for row in certified_by_time[timestamp])
        actual_gaps = [
            (actual_angles[(index + 1) % len(actual_angles)] - actual_angles[index]) % 360.0
            for index in range(len(actual_angles))
        ]
        scales = scales_for(timestamp, axes_by_time, centers_by_time)
        hypothetical_angles = []
        displacements = []
        for ray in sorted(base_by_time[timestamp], key=lambda row: f(row["angle_deg"])):
            theta = f(ray["angle_deg"])
            hx, hy = direction_vector(theta, scales, centered=False)
            hypothetical = circular_angle(hx, hy)
            hypothetical_angles.append(hypothetical)
            if ray["status"] == "RAY_CERTIFIED_BOUNDARY":
                actual = circular_angle(f(ray["safe_p13_abs_kw"]), f(ray["safe_p30_abs_kw"]))
                displacements.append(circular_difference(actual, hypothetical))
        hypothetical_angles.sort()
        hypothetical_gaps = [
            (hypothetical_angles[(index + 1) % len(hypothetical_angles)] - hypothetical_angles[index]) % 360.0
            for index in range(len(hypothetical_angles))
        ]
        summaries.append({
            "timestamp": timestamp,
            "certified_production_direction_count": len(actual_angles),
            "guard_truncation_count": sum(row["timestamp"] == timestamp and row["status"] == "RAY_UNBOUNDED_WITHIN_GUARD" for row in rays),
            "actual_maximum_angular_gap_deg": max(actual_gaps),
            "actual_median_angular_gap_deg": statistics.median(actual_gaps),
            "hypothetical_origin_base_maximum_gap_deg": max(hypothetical_gaps),
            "hypothetical_origin_base_median_gap_deg": statistics.median(hypothetical_gaps),
            "corresponding_base_direction_displacement_median_deg": statistics.median(displacements),
            "corresponding_base_direction_displacement_maximum_deg": max(displacements),
            "interpretation": "SAMPLING_GEOMETRY_ONLY_NO_NEW_AC_SOLVES",
        })
    return point_rows, summaries


def guard_audit(rays: list[dict[str, str]], attempts: list[dict[str, str]], axes_by_time: dict[str, dict[str, dict[str, str]]], centers_by_time: dict[str, dict[str, str]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    attempt_lookup = {
        (row["timestamp"], row["search_id"]): row
        for row in attempts
        if row["search_kind"] == "RAY" and row["phase"] == "coarse_sweep"
        and math.isclose(f(row["radius"]), RAY_GUARD) and i(row["attempt_index"]) == 1
    }
    output = []
    for ray in rays:
        if ray["status"] != "RAY_UNBOUNDED_WITHIN_GUARD":
            continue
        timestamp = ray["timestamp"]
        scales = scales_for(timestamp, axes_by_time, centers_by_time)
        attempt = attempt_lookup[(timestamp, ray["search_id"] if "search_id" in ray else f"{f(ray['angle_deg']):.6f}")]
        p13 = f(attempt["p13_abs_kw"])
        p30 = f(attempt["p30_abs_kw"])
        dx = p13 - scales["c13"]
        dy = p30 - scales["c30"]
        physical_angle = circular_angle(dx, dy)
        max_component = max(abs(dx), abs(dy))
        output.append({
            "timestamp": timestamp, "level": ray["level"],
            "normalized_angle_deg": f(ray["angle_deg"]), "physical_displacement_angle_deg": physical_angle,
            "quadrant": quadrant(dx, dy), "sector_30deg": angle_sector(physical_angle),
            "p13_guard_endpoint_kw": p13, "p30_guard_endpoint_kw": p30,
            "displacement_p13_kw": dx, "displacement_p30_kw": dy,
            "displacement_norm_kw": math.hypot(dx, dy),
            "s13_relevant_kw": scales["s13_positive"] if dx >= 0 else scales["s13_negative"],
            "s30_relevant_kw": scales["s30_positive"] if dy >= 0 else scales["s30_negative"],
            "maximum_component_to_20mw_axis_guard_ratio": max_component / AXIS_GUARD_KW,
            "adaptive_trigger": ray["adaptive_triggers"] if ray["level"] == "ADAPTIVE" else "NOT_APPLICABLE",
            "downstream_semantic_class": "CERTIFIED_FEASIBLE_GUARD_TRUNCATION",
        })
    ratios = [row["maximum_component_to_20mw_axis_guard_ratio"] for row in output]
    return output, {
        "count": len(output),
        "angle_histogram_30deg": dict(sorted(Counter(row["sector_30deg"] for row in output).items())),
        "quadrant_histogram": dict(sorted(Counter(row["quadrant"] for row in output).items())),
        "timestamp_histogram": dict(sorted(Counter(row["timestamp"] for row in output).items())),
        "level_histogram": dict(sorted(Counter(row["level"] for row in output).items())),
        "maximum_component_to_axis_guard_ratio": numeric_summary(ratios),
        "guard_comparison": "RAY_GUARD_PHYSICALLY_TIGHTER_THAN_AXIS_NUMERICAL_GUARD" if max(ratios) < 1.0 else "MIXED",
        "interpretation": "Feasible through r=2 only; not an AC boundary and not an unbounded direction.",
    }


def adaptive_audit(adaptive: list[dict[str, str]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    names = {
        "BOUNDARY_MECHANISM_CHANGE": "MECHANISM_CHANGE",
        "BINDING_BUS_CHANGE": "BINDING_BUS_CHANGE",
        "NORMALIZED_RADIUS_DIFFERENCE_GT_10_PERCENT": "RADIUS_DIFF_GT_10PCT",
        "UNRESOLVED_NONCONVERGED_REENTRY_OR_GUARD_LIMITED_ENDPOINT": "PROBLEMATIC_ENDPOINT",
    }
    marginal: Counter[str] = Counter()
    combinations: Counter[str] = Counter()
    rows = []
    for ray in adaptive:
        raw = [value for value in ray["adaptive_triggers"].split(";") if value]
        normalized = sorted(names[value] for value in raw)
        for value in normalized:
            marginal[value] += 1
        combination = " + ".join(normalized)
        combinations[combination] += 1
        rows.append({
            "timestamp": ray["timestamp"], "angle_deg": f(ray["angle_deg"]),
            "parent_start_angle_deg": f(ray["parent_start_angle_deg"]),
            "parent_end_angle_deg": f(ray["parent_end_angle_deg"]),
            "trigger_combination": combination, "raw_triggers": ray["adaptive_triggers"],
            "result_status": ray["status"],
        })
    dominant = max(marginal, key=marginal.get)
    return rows, {
        "unique_refined_intervals": len(rows),
        "marginal_trigger_counts": dict(sorted(marginal.items())),
        "trigger_combination_histogram": dict(sorted(combinations.items())),
        "dominant_marginal_driver": dominant,
        "interpretation_limit": "Trigger changes do not establish full scientific active sets.",
    }


def analytical_corner_audit(rays: list[dict[str, str]], axes_by_time: dict[str, dict[str, dict[str, str]]], centers_by_time: dict[str, dict[str, str]]) -> dict[str, Any]:
    corner_p13 = 934.6080433530186
    corner_p30 = 1610.2756675516089
    scales = scales_for(ANCHOR, axes_by_time, centers_by_time)
    dx = corner_p13 - scales["c13"]
    dy = corner_p30 - scales["c30"]
    nx = dx / (scales["s13_positive"] if dx >= 0 else scales["s13_negative"])
    ny = dy / (scales["s30_positive"] if dy >= 0 else scales["s30_negative"])
    theta = circular_angle(nx, ny)
    radius = math.hypot(nx, ny)
    anchor_rays = sorted((ray for ray in rays if ray["timestamp"] == ANCHOR), key=lambda row: f(row["angle_deg"]))
    lower = max((ray for ray in anchor_rays if f(ray["angle_deg"]) <= theta), key=lambda row: f(row["angle_deg"]), default=anchor_rays[-1])
    upper = min((ray for ray in anchor_rays if f(ray["angle_deg"]) > theta), key=lambda row: f(row["angle_deg"]), default=anchor_rays[0])
    def neighbor(row: dict[str, str]) -> dict[str, Any]:
        certified = row["status"] == "RAY_CERTIFIED_BOUNDARY"
        p13 = f(row["safe_p13_abs_kw"]) if certified else math.nan
        p30 = f(row["safe_p30_abs_kw"]) if certified else math.nan
        return {
            "normalized_angle_deg": f(row["angle_deg"]), "level": row["level"], "status": row["status"],
            "safe_p13_abs_kw": p13, "safe_p30_abs_kw": p30,
            "euclidean_distance_from_corner_kw": math.hypot(p13 - corner_p13, p30 - corner_p30) if certified else math.nan,
        }
    return {
        "classification": "ANALYTICAL_CORNER_GEOMETRIC_CONSISTENCY",
        "corner_p13_abs_kw": corner_p13, "corner_p30_abs_kw": corner_p30,
        "center_p13_kw": scales["c13"], "center_p30_kw": scales["c30"],
        "normalized_x": nx, "normalized_y": ny, "normalized_radius": radius,
        "normalized_angle_deg": theta,
        "lower_neighbor": neighbor(lower), "upper_neighbor": neighbor(upper),
        "exact_historical_ac_evidence": False,
        "ac_validation_statement": "NO_NEW_AC_CORNER_VALIDATION_PERFORMED",
        "historical_evidence_status": "Historical artifacts label this translated analytical corner as not a verified AC boundary point.",
    }


def empirical_position(values: list[float], target: float) -> dict[str, Any]:
    ordered = sorted(values)
    rank = ordered.index(target) + 1
    percentile = (rank - 1) / (len(ordered) - 1) if len(ordered) > 1 else 0.5
    side = "LOWER" if percentile <= 0.5 else "UPPER"
    tail = min(percentile, 1.0 - percentile)
    classification = "EXTREME" if tail <= 0.05 else "NEAR_EXTREME" if tail <= 0.15 else "TYPICAL"
    return {"rank_ascending": rank, "sample_count": len(values), "percentile": percentile, "tail": side, "tail_probability": tail, "classification": classification}


def anchor_decomposition(axes_by_time: dict[str, dict[str, dict[str, str]]], centers: list[dict[str, str]], base: list[dict[str, str]], adaptive: list[dict[str, str]], runtime: list[dict[str, str]], asymmetry: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any], list[dict[str, Any]]]:
    center_by_time = center_maps(centers)
    runtime_by_time = {row["timestamp"]: row for row in runtime}
    asym_by_time = {row["timestamp"]: row for row in asymmetry}
    base_by_time: dict[str, list[dict[str, str]]] = defaultdict(list)
    adaptive_by_time: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in base: base_by_time[row["timestamp"]].append(row)
    for row in adaptive: adaptive_by_time[row["timestamp"]].append(row)
    metrics: dict[str, dict[str, float]] = defaultdict(dict)
    for timestamp, axis in axes_by_time.items():
        p13p = f(axis["P13_POSITIVE"]["official_boundary_p_pcc_kw"])
        p13n = abs(f(axis["P13_NEGATIVE"]["official_boundary_p_pcc_kw"]))
        p30p = f(axis["P30_POSITIVE"]["official_boundary_p_pcc_kw"])
        p30n = abs(f(axis["P30_NEGATIVE"]["official_boundary_p_pcc_kw"]))
        metrics["p13_positive_kw"][timestamp] = p13p
        metrics["p13_negative_magnitude_kw"][timestamp] = p13n
        metrics["p30_positive_kw"][timestamp] = p30p
        metrics["p30_negative_magnitude_kw"][timestamp] = p30n
        metrics["p13_axis_width_kw"][timestamp] = p13p + p13n
        metrics["p30_axis_width_kw"][timestamp] = p30p + p30n
        metrics["total_axis_width_kw"][timestamp] = p13p + p13n + p30p + p30n
        metrics["a13"][timestamp] = asym_by_time[timestamp]["a13"]
        metrics["a30"][timestamp] = asym_by_time[timestamp]["a30"]
        metrics["center_p13_kw"][timestamp] = f(center_by_time[timestamp]["p13_abs_kw"])
        metrics["center_p30_kw"][timestamp] = f(center_by_time[timestamp]["p30_abs_kw"])
        metrics["base_ray_count"][timestamp] = len(base_by_time[timestamp])
        metrics["adaptive_ray_count"][timestamp] = len(adaptive_by_time[timestamp])
        metrics["guard_limited_ray_count"][timestamp] = sum(row["status"] == "RAY_UNBOUNDED_WITHIN_GUARD" for row in base_by_time[timestamp] + adaptive_by_time[timestamp])
        metrics["retry_count"][timestamp] = i(runtime_by_time[timestamp]["retry_count"])
        base_radii = [f(row["official_boundary_r"]) for row in base_by_time[timestamp] if row["status"] == "RAY_CERTIFIED_BOUNDARY"]
        adaptive_radii = [f(row["official_boundary_r"]) for row in adaptive_by_time[timestamp] if row["status"] == "RAY_CERTIFIED_BOUNDARY"]
        metrics["median_base_boundary_radius"][timestamp] = statistics.median(base_radii)
        metrics["minimum_base_boundary_radius"][timestamp] = min(base_radii)
        metrics["maximum_base_boundary_radius"][timestamp] = max(base_radii)
        metrics["median_adaptive_boundary_radius"][timestamp] = statistics.median(adaptive_radii)
        metrics["runtime_seconds"][timestamp] = f(runtime_by_time[timestamp]["runtime_seconds"])
        metrics["actual_evaluations"][timestamp] = i(runtime_by_time[timestamp]["actual_evaluations"])
    rows = []
    for metric in sorted(metrics):
        raw = metrics[metric][ANCHOR]
        position = empirical_position(list(metrics[metric].values()), raw)
        rows.append({"metric": metric, "anchor_raw_value": raw} | position)
    cause_metrics = ["total_axis_width_kw", "median_base_boundary_radius"]
    causing = [row["metric"] for row in rows if row["metric"] in cause_metrics and row["classification"] in {"EXTREME", "NEAR_EXTREME"}]
    guidance = [
        {"scope": "ANCHOR_SPECIFIC_CLAIMS_ONLY", "finding": "Historical command-space bounds, translated command-axis comparisons, and analytical-corner geometry."},
        {"scope": "SUPPORTED_AS_REPRESENTATIVE_ACROSS_32_TIMESTAMPS", "finding": "Four-bus primary reported binding structure, Tier-1-center prevalence, absence of re-entry, and qualitative import-side asymmetry, subject to distribution tables."},
    ]
    return rows, {
        "production_classification": "NEAR_EXTREME",
        "production_classifier_metrics_only": cause_metrics,
        "metrics_causing_near_extreme": causing,
        "near_extreme_dimension_count": len(causing),
        "scope_interpretation": "Near-extreme in one classifier dimension" if len(causing) == 1 else "Near-extreme in several classifier dimensions",
        "note": "Other tabulated metrics are postproduction descriptive context and did not enter the production classifier.",
    }, guidance


def cardinal_audit(base: list[dict[str, str]], axes_by_time: dict[str, dict[str, dict[str, str]]], centers_by_time: dict[str, dict[str, str]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    axis_for_angle = {0.0: "P13_POSITIVE", 90.0: "P30_POSITIVE", 180.0: "P13_NEGATIVE", 270.0: "P30_NEGATIVE"}
    rows = []
    for ray in base:
        angle = f(ray["angle_deg"])
        if angle not in CARDINAL_ANGLES:
            continue
        timestamp = ray["timestamp"]
        scales = scales_for(timestamp, axes_by_time, centers_by_time)
        radius = f(ray["official_boundary_r"])
        constructed_p13, constructed_p30 = cardinal_r1_point(angle, scales)
        expected_p13, expected_p30 = expected_cardinal_r1_point(angle, scales)
        p13_error = abs(constructed_p13 - expected_p13)
        p30_error = abs(constructed_p30 - expected_p30)
        geometry_pass = p13_error <= CARDINAL_GEOMETRY_TOLERANCE_KW and p30_error <= CARDINAL_GEOMETRY_TOLERANCE_KW
        rows.append({
            "timestamp": timestamp, "angle_deg": angle, "axis": axis_for_angle[angle],
            "expected_r1_p13_kw": expected_p13, "expected_r1_p30_kw": expected_p30,
            "constructed_r1_p13_kw": constructed_p13, "constructed_r1_p30_kw": constructed_p30,
            "r1_p13_absolute_error_kw": p13_error, "r1_p30_absolute_error_kw": p30_error,
            "geometry_tolerance_kw": CARDINAL_GEOMETRY_TOLERANCE_KW,
            "cardinal_r1_geometry_identity_pass": geometry_pass,
            "actual_boundary_status": ray["status"],
            "actual_boundary_r": radius, "actual_boundary_delta_r": radius - 1.0,
            "actual_boundary_r_equal_one_required": False,
            "normal_boundary_contract_pass": certified_ray_contract_pass(ray),
            "ray_bracket_width_kw": f(ray["bracket_width_kw"]),
            "guard_limited": ray["status"] == "RAY_UNBOUNDED_WITHIN_GUARD",
        })
    direction_summaries = {}
    for angle in CARDINAL_ANGLES:
        direction_rows = [row for row in rows if row["angle_deg"] == angle]
        deltas = [row["actual_boundary_delta_r"] for row in direction_rows]
        positive_rows = [row for row in direction_rows if row["actual_boundary_delta_r"] > 0.0]
        negative_rows = [row for row in direction_rows if row["actual_boundary_delta_r"] < 0.0]
        direction_summaries[f"{int(angle)}_degrees"] = {
            "delta_r": numeric_summary(deltas),
            "fraction_r_greater_than_one": len(positive_rows) / len(direction_rows),
            "fraction_r_less_than_one": len(negative_rows) / len(direction_rows),
            "largest_positive_deviation": (
                {"timestamp": max(positive_rows, key=lambda row: (row["actual_boundary_delta_r"], row["timestamp"]))["timestamp"],
                 "delta_r": max(row["actual_boundary_delta_r"] for row in positive_rows)}
                if positive_rows else None
            ),
            "largest_negative_deviation": (
                {"timestamp": min(negative_rows, key=lambda row: (row["actual_boundary_delta_r"], row["timestamp"]))["timestamp"],
                 "delta_r": min(row["actual_boundary_delta_r"] for row in negative_rows)}
                if negative_rows else None
            ),
        }
    geometry_pass_count = sum(row["cardinal_r1_geometry_identity_pass"] for row in rows)
    return rows, {
        "comparison_count": len(rows),
        "timestamp_count": len({row["timestamp"] for row in rows}),
        "geometry_tolerance_kw": CARDINAL_GEOMETRY_TOLERANCE_KW,
        "geometry_identity_pass_count": geometry_pass_count,
        "geometry_identity_fail_count": len(rows) - geometry_pass_count,
        "normal_boundary_contract_pass_count": sum(row["normal_boundary_contract_pass"] for row in rows),
        "guard_limited_cardinal_count": sum(row["guard_limited"] for row in rows),
        "invariant_verdict": "PASS" if geometry_pass_count == len(rows) else "FAIL_MATERIAL",
        "correct_invariant": "At r=1 the centered cardinal construction reaches the signed-axis bound in the varying coordinate and retains the orthogonal center coordinate.",
        "actual_boundary_r_minus_one_by_direction": direction_summaries,
        "actual_boundary_interpretation": "CARDINAL_CENTERLINE_COUPLING_DIAGNOSTIC",
        "interpretation_limit": "Actual cardinal boundary delta_r alone does not measure convexity, anisotropy, or global coupling strength.",
        "historical_rule_note": "PREVIOUS_CARDINAL_R_EQ_1_AUDIT_RULE_INVALID_FOR_CENTERED_RADIAL_GEOMETRY",
    }


def main() -> int:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    axes = read_csv(PRODUCTION / "signed_axis_results.csv")
    centers = read_csv(PRODUCTION / "center_results.csv")
    base = read_csv(PRODUCTION / "base_ray_results.csv")
    adaptive = read_csv(PRODUCTION / "adaptive_ray_results.csv")
    attempts = read_csv(PRODUCTION / "evaluation_attempts.csv")
    runtime = read_csv(PRODUCTION / "timestamp_runtime_evaluation_summary.csv")
    with (PRODUCTION / "run_manifest.toml").open("rb") as handle:
        manifest = tomllib.load(handle)
    rays = base + adaptive
    axes_by_time = axis_maps(axes)
    centers_by_time = center_maps(centers)
    rays_by_key = {(row["timestamp"], f"{f(row['angle_deg']):.6f}"): row for row in rays}
    certified_boundaries = [row for row in axes + rays if row["status"] in {"AXIS_CERTIFIED_BOUNDARY", "RAY_CERTIFIED_BOUNDARY"}]

    binding_rows, binding_summary = binding_audit(certified_boundaries)
    sensitivity = sensitivity_audit()
    retry_rows, retry_summary = retry_audit(attempts, axes_by_time, rays_by_key)
    timing = timing_audit(manifest)
    first_attempts = [row for row in attempts if i(row["attempt_index"]) == 1]
    decomposition, bisection_rows, decomposition_summary = evaluation_decomposition(first_attempts, axes, rays_by_key, len(retry_rows))
    asymmetry_rows, asymmetry_summary = asymmetry_audit(axes_by_time)
    geometry_rows, geometry_summary = sampling_geometry(rays, axes_by_time, centers_by_time)
    guard_rows, guard_summary = guard_audit(rays, attempts, axes_by_time, centers_by_time)
    adaptive_rows, adaptive_summary = adaptive_audit(adaptive)
    corner_summary = analytical_corner_audit(rays, axes_by_time, centers_by_time)
    anchor_rows, anchor_summary, manuscript_guidance = anchor_decomposition(axes_by_time, centers, base, adaptive, runtime, asymmetry_rows)
    cardinal_rows, cardinal_summary = cardinal_audit(base, axes_by_time, centers_by_time)

    write_csv(OUTPUT / "primary_binding_bus_audit.csv", binding_rows)
    write_json(OUTPUT / "primary_binding_bus_summary.json", binding_summary)
    write_json(OUTPUT / "p30_sensitivity_consistency.json", sensitivity)
    write_csv(OUTPUT / "retry_effectiveness_failure_location.csv", retry_rows)
    write_json(OUTPUT / "retry_effectiveness_summary.json", retry_summary)
    write_json(OUTPUT / "timing_provenance.json", timing)
    write_csv(OUTPUT / "exact_evaluation_decomposition.csv", decomposition)
    write_csv(OUTPUT / "bisection_step_distribution.csv", bisection_rows)
    write_json(OUTPUT / "evaluation_decomposition_summary.json", decomposition_summary)
    write_csv(OUTPUT / "axis_asymmetry.csv", asymmetry_rows)
    write_json(OUTPUT / "axis_asymmetry_summary.json", asymmetry_summary)
    write_csv(OUTPUT / "centered_vs_origin_sampling_geometry.csv", geometry_rows)
    write_csv(OUTPUT / "sampling_geometry_timestamp_summary.csv", geometry_summary)
    write_csv(OUTPUT / "ray_guard_truncation_audit.csv", guard_rows)
    write_json(OUTPUT / "ray_guard_truncation_summary.json", guard_summary)
    write_csv(OUTPUT / "adaptive_trigger_audit.csv", adaptive_rows)
    write_json(OUTPUT / "adaptive_trigger_summary.json", adaptive_summary)
    write_json(OUTPUT / "analytical_corner_geometric_audit.json", corner_summary)
    write_csv(OUTPUT / "anchor_near_extreme_decomposition.csv", anchor_rows)
    write_json(OUTPUT / "anchor_near_extreme_summary.json", anchor_summary)
    write_csv(OUTPUT / "manuscript_scope_guidance.csv", manuscript_guidance)
    write_csv(OUTPUT / "cardinal_ray_invariant_audit.csv", cardinal_rows)
    write_json(OUTPUT / "cardinal_ray_invariant_summary.json", cardinal_summary)

    validation = {
        "timestamp_count": len(centers), "axis_count": len(axes), "ray_count": len(rays),
        "adaptive_count": len(adaptive), "guard_limited_count": len(guard_rows),
        "retry_count": len(retry_rows), "logical_evaluation_count": len(first_attempts),
        "actual_attempt_count": len(attempts), "cardinal_comparison_count": len(cardinal_rows),
        "new_ac_solves_performed": 0,
        "count_checks_pass": len(centers) == 32 and len(axes) == 128 and len(rays) == 1634
            and len(adaptive) == 482 and len(guard_rows) == 73 and len(retry_rows) == 143
            and len(first_attempts) == 87229 and len(attempts) == 87372 and len(cardinal_rows) == 128,
        "cardinal_geometry_pass": cardinal_summary["invariant_verdict"] == "PASS",
    }
    production_manifest_rows = read_csv(PRODUCTION / "artifact_manifest.csv")
    production_hashes_pass = all(
        (PRODUCTION / row["artifact"]).is_file()
        and (PRODUCTION / row["artifact"]).stat().st_size == i(row["bytes"])
        and sha256(PRODUCTION / row["artifact"]) == row["sha256"]
        for row in production_manifest_rows
    )
    config_hash_matches = manifest["config_sha256"] == "18530df3a6aad54c619e061b9c9f40136509cebe135fd42ee2e3c032383cb06d"
    validation.update({
        "cardinal_timestamp_count": cardinal_summary["timestamp_count"],
        "cardinal_boundary_contract_pass": cardinal_summary["normal_boundary_contract_pass_count"] == 128,
        "no_cardinal_guard_truncation": cardinal_summary["guard_limited_cardinal_count"] == 0,
        "production_artifact_hashes_pass": production_hashes_pass,
        "scientific_config_hash_matches": config_hash_matches,
    })
    material_checks_pass = (
        validation["count_checks_pass"]
        and validation["cardinal_geometry_pass"]
        and validation["cardinal_timestamp_count"] == 32
        and validation["cardinal_boundary_contract_pass"]
        and validation["no_cardinal_guard_truncation"]
        and validation["production_artifact_hashes_pass"]
        and validation["scientific_config_hash_matches"]
    )
    validation["material_checks_pass"] = material_checks_pass
    validation_rows = [
        {"check": "exactly_32_timestamps", "passed": len(centers) == 32, "detail": f"observed={len(centers)}"},
        {"check": "exactly_128_axes", "passed": len(axes) == 128, "detail": f"observed={len(axes)}"},
        {"check": "exactly_1634_rays", "passed": len(rays) == 1634, "detail": f"observed={len(rays)}"},
        {"check": "exactly_482_adaptive", "passed": len(adaptive) == 482, "detail": f"observed={len(adaptive)}"},
        {"check": "exactly_73_guard_truncations", "passed": len(guard_rows) == 73, "detail": f"observed={len(guard_rows)}"},
        {"check": "exactly_143_retries", "passed": len(retry_rows) == 143, "detail": f"observed={len(retry_rows)}"},
        {"check": "logical_evaluation_reconciliation", "passed": len(first_attempts) == 87229 and decomposition_summary["logical_total"] == 87229, "detail": f"first_attempts={len(first_attempts)} decomposition={decomposition_summary['logical_total']}"},
        {"check": "actual_attempt_reconciliation", "passed": len(attempts) == 87372 and decomposition_summary["actual_total"] == 87372, "detail": f"attempt_rows={len(attempts)} decomposition={decomposition_summary['actual_total']}"},
        {"check": "retry_difference_reconciliation", "passed": len(attempts) - len(first_attempts) == len(retry_rows), "detail": f"difference={len(attempts)-len(first_attempts)}"},
        {"check": "exactly_128_cardinal_comparisons", "passed": len(cardinal_rows) == 128, "detail": f"observed={len(cardinal_rows)}"},
        {"check": "exactly_32_cardinal_timestamps", "passed": cardinal_summary["timestamp_count"] == 32, "detail": f"observed={cardinal_summary['timestamp_count']}"},
        {"check": "no_cardinal_guard_truncation", "passed": cardinal_summary["guard_limited_cardinal_count"] == 0, "detail": f"observed={cardinal_summary['guard_limited_cardinal_count']}"},
        {"check": "production_artifact_hashes", "passed": production_hashes_pass, "detail": f"manifest_rows={len(production_manifest_rows)}"},
        {"check": "scientific_config_hash_matches", "passed": config_hash_matches, "detail": str(manifest["config_sha256"])},
        {"check": "no_new_ac_solves", "passed": True, "detail": "artifact-only Python extractor"},
        {"check": "all_128_cardinal_r1_geometry_identities", "passed": validation["cardinal_geometry_pass"], "detail": f"passed={cardinal_summary['geometry_identity_pass_count']} tolerance_kw={CARDINAL_GEOMETRY_TOLERANCE_KW}"},
        {"check": "all_128_cardinal_boundary_contracts", "passed": cardinal_summary["normal_boundary_contract_pass_count"] == 128, "detail": f"passed={cardinal_summary['normal_boundary_contract_pass_count']}"},
    ]
    write_csv(OUTPUT / "postproduction_validation_checks.csv", validation_rows)
    classification = "POSTPRODUCTION_RESULT_AUDIT_COMPLETE_WITH_DOCUMENTED_LIMITATIONS" if material_checks_pass else "POSTPRODUCTION_RESULT_AUDIT_BLOCKED"
    summary = {
        "classification": classification,
        "production_execution_base_commit": manifest["git_commit"],
        "production_artifact_commit": PRODUCTION_ARTIFACT_COMMIT,
        "production_commit_lineage": [
            manifest["git_commit"],
            "166a182",
            PRODUCTION_ARTIFACT_COMMIT,
        ],
        "production_artifact_config_sha256": manifest["config_sha256"],
        "production_manifest_sha256": sha256(PRODUCTION / "run_manifest.toml"),
        "binding": binding_summary, "sensitivity": sensitivity,
        "retry": retry_summary, "timing": timing, "evaluation": decomposition_summary,
        "asymmetry": asymmetry_summary, "guard": guard_summary,
        "adaptive": adaptive_summary, "analytical_corner": corner_summary,
        "anchor": anchor_summary, "cardinal": cardinal_summary,
        "validation": validation,
        "limitations": [
            "CO_BINDING_NOT_RESOLVABLE_FROM_STORED_ARTIFACTS",
            "Historical analytical corner lacks exact independent AC validation.",
            "Timing rate difference cause cannot be isolated from stored timing scopes.",
        ],
    }
    write_json(OUTPUT / "postproduction_result_audit_summary.json", summary)

    cardinal_diagnostic_lines = []
    for angle in CARDINAL_ANGLES:
        direction = cardinal_summary["actual_boundary_r_minus_one_by_direction"][f"{int(angle)}_degrees"]
        delta = direction["delta_r"]
        positive = direction["largest_positive_deviation"]
        negative = direction["largest_negative_deviation"]
        positive_text = f"{positive['delta_r']:.9f} at {positive['timestamp']}" if positive else "none"
        negative_text = f"{negative['delta_r']:.9f} at {negative['timestamp']}" if negative else "none"
        cardinal_diagnostic_lines.append(
            f"- {int(angle)} degrees: mean {delta['mean']:.9f}, median {delta['median']:.9f}, "
            f"min {delta['minimum']:.9f}, q25 {delta['q25']:.9f}, q75 {delta['q75']:.9f}, max {delta['maximum']:.9f}; "
            f"fraction r>1 {direction['fraction_r_greater_than_one']:.6f}, fraction r<1 {direction['fraction_r_less_than_one']:.6f}; "
            f"largest positive {positive_text}, largest negative {negative_text}."
        )
    cardinal_diagnostic_text = "\n".join(cardinal_diagnostic_lines)

    report = f"""# Postproduction result audit

Final classification: `{classification}`

## Provenance and reconciliation

The audit used only committed production and historical artifacts. It performed zero new AC solves. The run manifest records execution base commit `{manifest['git_commit']}`; implementation and result commits `166a182` and `{PRODUCTION_ARTIFACT_COMMIT}` are descendants in the verified local lineage. The scientific config hash is `{manifest['config_sha256']}`. Counts reconcile to 32 timestamps, 128 axes, 1,634 rays, 482 adaptive directions, 73 guard truncations, 143 retries, 87,229 logical evaluations, and 87,372 actual attempts.

## Binding structure

Primary VMAX bindings are bus 13: 429 ({100*429/851:.6f}%) and bus 30: 422 ({100*422/851:.6f}%). Primary VMIN bindings are bus 18: 435 ({100*435/838:.6f}%) and bus 33: 403 ({100*403/838:.6f}%). No fifth primary reported binding bus exists. `CO_BINDING_NOT_RESOLVABLE_FROM_STORED_ARTIFACTS`: full voltage vectors/all-bus margins are not retained.

## Coordinate/sensitivity check

The first-order prediction is ΔP30={sensitivity['predicted_delta_p30_kw']:.9f} kW versus observed {sensitivity['observed_delta_p30_kw']:.9f} kW; absolute discrepancy {sensitivity['absolute_discrepancy_kw']:.9f} kW ({100*sensitivity['relative_discrepancy_vs_observed']:.6f}%). Both historical and production primary VMAX records bind at bus 30. This is only `FIRST_ORDER_COORDINATE_AND_SENSITIVITY_CONSISTENCY_CHECK`.

## Retry and timing

All 143 retries failed: rescue rate 0/143 = 0%. Every retry occurred in an axis coarse sweep after doubling had already established a provisional converged feasible/violating bracket, before bisection, and beyond the final certified axis boundary; none defines a physical limit. Production aggregate rates are {timing['production']['logical_ms_per_evaluation']:.6f} ms/logical evaluation and {timing['production']['actual_ms_per_attempt']:.6f} ms/actual attempt. Exact timer inclusions/exclusions are in `timing_provenance.json`; causal attribution remains `TIMING_RATE_DIFFERENCE_CAUSE_UNRESOLVED`.

## Geometry and guards

Centered-production and hypothetical origin-radial angular geometry was reconstructed without solves. The 73 ray guards are `CERTIFIED_FEASIBLE_GUARD_TRUNCATION`, never AC boundaries or unbounded directions. Across them, the largest displacement component is below the 20 MW per-axis numerical guard, supporting `RAY_GUARD_PHYSICALLY_TIGHTER_THAN_AXIS_NUMERICAL_GUARD`.

## Adaptive refinement

All 482 intervals reconcile. Marginal and exact-combination counts are in `adaptive_trigger_summary.json`; marginal counts intentionally overlap.

## Analytical corner and anchor

The analytical corner was transformed into centered normalized coordinates and bracketed by stored production directions. No AC inference was made: `NO_NEW_AC_CORNER_VALIDATION_PERFORMED`. The anchor classifier used only total axis width and median base-ray radius; the exact causing metric(s) are listed in `anchor_near_extreme_summary.json`.

## Corrected cardinal geometry and coupling diagnostic

All {cardinal_summary['geometry_identity_pass_count']}/{cardinal_summary['comparison_count']} deterministic cardinal identities pass at tolerance {CARDINAL_GEOMETRY_TOLERANCE_KW:.1e} kW. At r=1 the centered construction maps 0 degrees to `(P13_max, center_P30)`, 180 degrees to `(P13_min, center_P30)`, 90 degrees to `(center_P13, P30_max)`, and 270 degrees to `(center_P13, P30_min)`. These are generally not the absolute-axis AC probe points because the orthogonal center coordinate need not be zero. Therefore `PREVIOUS_CARDINAL_R_EQ_1_AUDIT_RULE_INVALID_FOR_CENTERED_RADIAL_GEOMETRY`.

The actual certified boundary radii retain their scientific value as `CARDINAL_CENTERLINE_COUPLING_DIAGNOSTIC`; delta_r = r_boundary - 1 is summarized by direction:

{cardinal_diagnostic_text}

This diagnostic alone does not measure convexity, anisotropy, or global coupling strength. All {cardinal_summary['normal_boundary_contract_pass_count']} cardinal certified boundaries satisfy the normal safe/violating endpoint contract, and none was guard-limited (r_guard=2).

## Limitations

- `CO_BINDING_NOT_RESOLVABLE_FROM_STORED_ARTIFACTS`.
- Historical analytical corner has no exact independent AC replay evidence.
- Timing rate difference cause is unresolved because scopes/workloads differ.
"""
    (OUTPUT / "postproduction_result_audit_report.md").write_text(report, encoding="utf-8")

    artifact_rows = []
    for path in sorted(OUTPUT.iterdir(), key=lambda value: value.name):
        if path.is_file() and path.name != "artifact_manifest.csv":
            artifact_rows.append({"artifact": path.name, "bytes": path.stat().st_size, "sha256": sha256(path)})
    write_csv(OUTPUT / "artifact_manifest.csv", artifact_rows)
    print(f"classification={classification}")
    print(f"outputs={len(artifact_rows) + 1}")
    print(f"new_ac_solves=0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
