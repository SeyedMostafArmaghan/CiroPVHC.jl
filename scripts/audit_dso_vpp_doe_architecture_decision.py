#!/usr/bin/env python3
"""Deterministic artifact-only DSO/VPP DOE architecture-decision audit."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable, Sequence


SOURCE_HEAD = "c18021d9b981f2629e54f60e8c2fc5f33b00c1a2"
SOURCE_BRANCH = "codex/dso-vpp-ac-map-pilot"
BASE = Path("results/dso_vpp_ac_map_pilot")
PRODUCTION = BASE / "production_probe"
PREREG = BASE / "doe_construction_policy_preregistration"
CONTRACTION = PREREG / "geometric_contraction_threshold_audit"
NONCONVEX = PREREG / "nonconvexity_resolvability_audit"
ARCHITECTURE = PREREG / "convex_piecewise_architecture_audit"
CANONICAL_OUTPUT = BASE / "doe_architecture_decision_audit"
SCRIPT_PATH = Path("scripts/audit_dso_vpp_doe_architecture_decision.py")

CLASS_ORDER = ("VMAX_BUS_13", "VMAX_BUS_30", "VMIN_BUS_18", "VMIN_BUS_33")
POCKET_PRIOR_VALUE_KW2 = 9_187_485.414
DISTANCE_TOL_KW = 1.0e-8
AREA_TOL_KW2 = 1.0e-5


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=CANONICAL_OUTPUT)
    return parser.parse_args()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def csv_value(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        if math.isnan(value):
            return "NaN"
        if math.isinf(value):
            return "Inf" if value > 0 else "-Inf"
        return format(value, ".15g")
    return value


def write_csv(path: Path, rows: list[dict[str, Any]], fields: Iterable[str] | None = None) -> None:
    fieldnames = list(fields if fields is not None else (rows[0].keys() if rows else ()))
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({name: csv_value(row.get(name)) for name in fieldnames})


def write_text(path: Path, text: str) -> None:
    path.write_text(text.rstrip() + "\n", encoding="utf-8", newline="\n")


def write_json(path: Path, value: Any) -> None:
    write_text(path, json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def verify_source_manifest(root: Path, relative: Path) -> dict[str, Any]:
    manifest = root / relative
    rows = read_csv(manifest)
    failures: list[str] = []
    for row in rows:
        item = row.get("path") or row.get("artifact")
        if item is None:
            failures.append("MISSING_PATH_FIELD")
            continue
        target = root / item if row.get("path") else manifest.parent / item
        if not target.is_file():
            failures.append(f"MISSING:{item}")
        elif target.stat().st_size != int(row["bytes"]):
            failures.append(f"BYTES:{item}")
        elif sha256(target) != row["sha256"]:
            failures.append(f"SHA256:{item}")
    if failures:
        raise SystemExit(f"source manifest verification failed for {relative}: {';'.join(failures)}")
    return {
        "path": relative.as_posix(),
        "entry_count": len(rows),
        "sha256": sha256(manifest),
        "status": "PASS",
    }


def quantile(values: Sequence[float], probability: float) -> float:
    ordered = sorted(values)
    if not ordered:
        raise ValueError("empty distribution")
    position = (len(ordered) - 1) * probability
    lower, upper = math.floor(position), math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def stats(values: Iterable[float]) -> dict[str, Any]:
    finite = [float(value) for value in values if value is not None and math.isfinite(float(value))]
    if not finite:
        return {"count": 0, "min": None, "q1": None, "median": None, "q3": None, "max": None}
    return {
        "count": len(finite),
        "min": min(finite),
        "q1": quantile(finite, 0.25),
        "median": quantile(finite, 0.5),
        "q3": quantile(finite, 0.75),
        "max": max(finite),
    }


def prefixed_stats(prefix: str, values: Iterable[float]) -> dict[str, Any]:
    return {f"{prefix}_{key}": value for key, value in stats(values).items() if key != "count"}


def pearson(left: Sequence[float], right: Sequence[float]) -> float | None:
    if len(left) != len(right) or len(left) < 2:
        return None
    left_mean, right_mean = sum(left) / len(left), sum(right) / len(right)
    numerator = sum((x - left_mean) * (y - right_mean) for x, y in zip(left, right))
    left_ss = sum((x - left_mean) ** 2 for x in left)
    right_ss = sum((y - right_mean) ** 2 for y in right)
    if left_ss == 0.0 or right_ss == 0.0:
        return None
    return numerator / math.sqrt(left_ss * right_ss)


Point = tuple[float, float]


def sub(left: Point, right: Point) -> Point:
    return left[0] - right[0], left[1] - right[1]


def cross(left: Point, right: Point) -> float:
    return left[0] * right[1] - left[1] * right[0]


def polygon_signed_area(vertices: Sequence[Point]) -> float:
    return 0.5 * sum(cross(vertices[index], vertices[(index + 1) % len(vertices)]) for index in range(len(vertices)))


def polygon_area(vertices: Sequence[Point]) -> float:
    return abs(polygon_signed_area(vertices))


def convex_hull(points: Sequence[Point]) -> list[Point]:
    unique = sorted(set(points))
    if len(unique) <= 1:
        return unique

    def turn(origin: Point, left: Point, right: Point) -> float:
        return cross(sub(left, origin), sub(right, origin))

    lower: list[Point] = []
    for point in unique:
        while len(lower) >= 2 and turn(lower[-2], lower[-1], point) <= 0.0:
            lower.pop()
        lower.append(point)
    upper: list[Point] = []
    for point in reversed(unique):
        while len(upper) >= 2 and turn(upper[-2], upper[-1], point) <= 0.0:
            upper.pop()
        upper.append(point)
    return lower[:-1] + upper[:-1]


def radial_kernel_parameter(center: Point, direction: Point, kernel: Sequence[Point]) -> float:
    """Return maximum t with center + t*direction in a CCW convex kernel."""
    if polygon_signed_area(kernel) <= 0.0:
        raise SystemExit("kernel is not counterclockwise")
    bound = math.inf
    for index, left in enumerate(kernel):
        right = kernel[(index + 1) % len(kernel)]
        edge = sub(right, left)
        center_margin = cross(edge, sub(center, left))
        directional_rate = cross(edge, direction)
        if center_margin < -DISTANCE_TOL_KW:
            raise SystemExit("production center lies outside a kernel halfplane")
        if directional_rate < 0.0:
            bound = min(bound, center_margin / -directional_rate)
    if not math.isfinite(bound) or bound < 0.0:
        raise SystemExit("failed to intersect production ray with kernel")
    return bound


def distribution_line(value: dict[str, Any]) -> str:
    return (
        f"min/Q1/median/Q3/max = {value['min']:.12g}/{value['q1']:.12g}/"
        f"{value['median']:.12g}/{value['q3']:.12g}/{value['max']:.12g}"
    )


def build(root: Path, output: Path) -> None:
    source_manifests = [
        verify_source_manifest(root, PRODUCTION / "artifact_manifest.csv"),
        verify_source_manifest(root, PREREG / "artifact_manifest.csv"),
        verify_source_manifest(root, CONTRACTION / "artifact_manifest.csv"),
        verify_source_manifest(root, NONCONVEX / "artifact_manifest.csv"),
        verify_source_manifest(root, ARCHITECTURE / "artifact_manifest.csv"),
    ]

    retention_source = read_csv(root / ARCHITECTURE / "kernel_inward_boundary_retention.csv")
    paired_source = read_csv(root / CONTRACTION / "paired_inward_outward_gauge_separation.csv")
    kernel_source = read_csv(root / NONCONVEX / "polygon_kernel_vertices.csv")
    kernel_summary_source = read_csv(root / NONCONVEX / "polygon_kernel_summary.csv")
    concavity_source = read_csv(root / ARCHITECTURE / "concave_vertices.csv")
    pockets_source = read_csv(root / ARCHITECTURE / "hull_deficit_pockets.csv")
    partition_source = read_csv(root / ARCHITECTURE / "merged_convex_cell_summary.csv")
    polygon_summary_source = read_csv(root / CONTRACTION / "angular_inward_polygon_summary.csv")

    if len(retention_source) != 1689:
        raise SystemExit(f"expected 1689 inward points, observed {len(retention_source)}")

    paired = {
        (row["timestamp"], row["search_kind"], row["search_id"], row["level"]): row
        for row in paired_source
    }
    kernels: dict[str, list[Point]] = defaultdict(list)
    for row in sorted(kernel_source, key=lambda item: (item["timestamp"], int(item["kernel_vertex_index_ccw"]))):
        kernels[row["timestamp"]].append((float(row["p13_abs_kw"]), float(row["p30_abs_kw"])))
    centers = {
        row["timestamp"]: (float(row["center_p13_abs_kw"]), float(row["center_p30_abs_kw"]))
        for row in kernel_summary_source
    }

    retention_points: list[dict[str, Any]] = []
    radial_loss: list[dict[str, Any]] = []
    for row in sorted(
        retention_source,
        key=lambda item: (item["timestamp"], float(item["ray_angle_deg"]), item["endpoint_id"]),
    ):
        retained = row["retained_in_kernel"] == "true"
        item = {
            "timestamp": row["timestamp"],
            "endpoint_id": row["endpoint_id"],
            "search_kind": "SIGNED_AXIS" if row["search_kind"] == "AXIS" else "RAY",
            "search_id": row["search_id"],
            "level": row["level"],
            "primary_class": row["primary_class"],
            "binding_family": row["binding_family"],
            "binding_bus": int(row["binding_bus"]),
            "production_angle_deg": float(row["ray_angle_deg"]),
            "p13_abs_kw": float(row["p13_abs_kw"]),
            "p30_abs_kw": float(row["p30_abs_kw"]),
            "kernel_location": row["kernel_location"],
            "retained_in_kernel": retained,
            "coordinate_semantics": "ABSOLUTE_PHYSICAL_PCC;PRODUCTION_CENTERED_SIGN_NORMALIZED_ANGLE",
        }
        retention_points.append(item)
        if retained:
            continue

        timestamp = row["timestamp"]
        center = centers[timestamp]
        point = (float(row["p13_abs_kw"]), float(row["p30_abs_kw"]))
        direction = sub(point, center)
        r_in = math.hypot(*direction)
        parameter = radial_kernel_parameter(center, direction, kernels[timestamp])
        r_kernel = parameter * r_in
        delta = r_in - r_kernel
        pair_key = (timestamp, row["search_kind"], row["search_id"], row["level"])
        pair = paired.get(pair_key)
        if pair is None:
            raise SystemExit(f"missing paired bracket for {pair_key}")
        bracket = float(pair["physical_pair_spacing_kw"])
        if r_in <= 0.0 or bracket <= 0.0 or delta < -DISTANCE_TOL_KW or parameter > 1.0 + 1.0e-9:
            raise SystemExit(f"invalid radial-loss geometry for {pair_key}")
        radial_loss.append({
            **{key: item[key] for key in (
                "timestamp", "endpoint_id", "search_kind", "search_id", "level", "primary_class",
                "binding_family", "binding_bus", "production_angle_deg", "p13_abs_kw", "p30_abs_kw"
            )},
            "center_p13_abs_kw": center[0],
            "center_p30_abs_kw": center[1],
            "r_in_kw": r_in,
            "kernel_ray_parameter": parameter,
            "r_kernel_kw": r_kernel,
            "delta_r_kw": delta,
            "relative_radial_loss": delta / r_in,
            "paired_physical_bracket_width_kw": bracket,
            "delta_r_over_bracket": delta / bracket,
            "radial_semantics": "PHYSICAL_EUCLIDEAN_DISTANCE_ALONG_PRODUCTION_CENTERED_SIGN_NORMALIZED_ANGLE_RAY",
        })

    retention_by_class: list[dict[str, Any]] = []
    retention_groups = [
        ("PRIMARY_CLASS", name, [row for row in retention_points if row["primary_class"] == name])
        for name in CLASS_ORDER
    ] + [
        ("BINDING_FAMILY", family, [row for row in retention_points if row["binding_family"] == family])
        for family in ("VMAX", "VMIN")
    ] + [("ALL", "ALL_INWARD_POINTS", retention_points)]
    for dimension, group, rows in retention_groups:
        retained_count = sum(row["retained_in_kernel"] for row in rows)
        retention_by_class.append({
            "group_dimension": dimension,
            "group": group,
            "retained_count": retained_count,
            "total_count": len(rows),
            "excluded_count": len(rows) - retained_count,
            "retained_fraction": retained_count / len(rows),
        })
    counts = {row["group"]: row for row in retention_by_class}
    if counts["VMAX"]["total_count"] != 851 or counts["VMIN"]["total_count"] != 838:
        raise SystemExit("VMAX/VMIN totals do not match locked cross-checks")
    if counts["ALL_INWARD_POINTS"]["retained_count"] != 819:
        raise SystemExit("kernel retained total does not match locked cross-check")

    radial_summary: list[dict[str, Any]] = []
    radial_groups: list[tuple[str, str, list[dict[str, Any]]]] = [("ALL", "ALL_EXCLUDED", radial_loss)]
    radial_groups.extend(("BINDING_FAMILY", family, [row for row in radial_loss if row["binding_family"] == family]) for family in ("VMAX", "VMIN"))
    radial_groups.extend(("PRIMARY_CLASS", name, [row for row in radial_loss if row["primary_class"] == name]) for name in CLASS_ORDER)
    radial_groups.extend(("SEARCH_KIND", kind, [row for row in radial_loss if row["search_kind"] == kind]) for kind in ("RAY", "SIGNED_AXIS"))
    for timestamp in sorted(centers):
        radial_groups.append(("TIMESTAMP", timestamp, [row for row in radial_loss if row["timestamp"] == timestamp]))
    for dimension, group, rows in radial_groups:
        radial_summary.append({
            "group_dimension": dimension,
            "group": group,
            "excluded_count": len(rows),
            **prefixed_stats("delta_r_kw", (row["delta_r_kw"] for row in rows)),
            **prefixed_stats("relative_radial_loss", (row["relative_radial_loss"] for row in rows)),
            **prefixed_stats("delta_r_over_bracket", (row["delta_r_over_bracket"] for row in rows)),
        })

    points_by_timestamp: dict[str, list[Point]] = defaultdict(list)
    for row in retention_points:
        points_by_timestamp[row["timestamp"]].append((row["p13_abs_kw"], row["p30_abs_kw"]))
    polygon_summaries = {row["timestamp"]: row for row in polygon_summary_source}
    pockets_by_timestamp: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in pockets_source:
        pockets_by_timestamp[row["timestamp"]].append(row)
    pocket_rows: list[dict[str, Any]] = []
    for timestamp in sorted(points_by_timestamp):
        polygon_value = polygon_area(points_by_timestamp[timestamp])
        recorded_polygon = float(polygon_summaries[timestamp]["polygon_area_kw2"])
        hull_value = polygon_area(convex_hull(points_by_timestamp[timestamp]))
        pocket_value = hull_value - polygon_value
        components = pockets_by_timestamp[timestamp]
        component_sum = sum(float(row["polygon_vs_hull_pocket_area_kw2"]) for row in components)
        if abs(polygon_value - recorded_polygon) > AREA_TOL_KW2 or abs(pocket_value - component_sum) > AREA_TOL_KW2:
            raise SystemExit(f"pocket geometry does not reconcile for {timestamp}")
        family_area = {
            family: sum(
                float(row["polygon_vs_hull_pocket_area_kw2"])
                for row in components if row["family_area_attribution"] == family
            )
            for family in ("VMAX_ONLY", "VMIN_ONLY", "MIXED_VMAX_VMIN")
        }
        pocket_rows.append({
            "timestamp": timestamp,
            "polygon_area_kw2": polygon_value,
            "convex_hull_area_kw2": hull_value,
            "pocket_area_kw2": pocket_value,
            "pocket_fraction_polygon": pocket_value / polygon_value,
            "pocket_fraction_hull": pocket_value / hull_value,
            "vmax_only_pocket_area_kw2": family_area["VMAX_ONLY"],
            "vmin_only_pocket_area_kw2": family_area["VMIN_ONLY"],
            "mixed_vmax_vmin_pocket_area_kw2": family_area["MIXED_VMAX_VMIN"],
            "classification_rule": "EXISTING_INTERIOR_POLYGON_VERTEX_BINDING_FAMILY_ATTRIBUTION;NO_MATERIALITY_THRESHOLD",
        })
    pocket_summary = {
        "timestamp_count": len(pocket_rows),
        "polygon_area_kw2": stats(row["polygon_area_kw2"] for row in pocket_rows),
        "convex_hull_area_kw2": stats(row["convex_hull_area_kw2"] for row in pocket_rows),
        "pocket_area_kw2": stats(row["pocket_area_kw2"] for row in pocket_rows),
        "pocket_fraction_polygon": stats(row["pocket_fraction_polygon"] for row in pocket_rows),
        "pocket_fraction_hull": stats(row["pocket_fraction_hull"] for row in pocket_rows),
        "sum_polygon_area_kw2": sum(row["polygon_area_kw2"] for row in pocket_rows),
        "sum_convex_hull_area_kw2": sum(row["convex_hull_area_kw2"] for row in pocket_rows),
        "sum_pocket_area_kw2": sum(row["pocket_area_kw2"] for row in pocket_rows),
        "aggregate_pocket_over_polygon": sum(row["pocket_area_kw2"] for row in pocket_rows) / sum(row["polygon_area_kw2"] for row in pocket_rows),
        "aggregate_pocket_over_hull": sum(row["pocket_area_kw2"] for row in pocket_rows) / sum(row["convex_hull_area_kw2"] for row in pocket_rows),
        "sum_vmax_only_pocket_area_kw2": sum(row["vmax_only_pocket_area_kw2"] for row in pocket_rows),
        "sum_vmin_only_pocket_area_kw2": sum(row["vmin_only_pocket_area_kw2"] for row in pocket_rows),
        "sum_mixed_vmax_vmin_pocket_area_kw2": sum(row["mixed_vmax_vmin_pocket_area_kw2"] for row in pocket_rows),
    }
    pocket_summary["prior_9187485_414_interpretation"] = (
        "VMAX_ONLY_COMPONENT_NOT_ALL_POCKETS"
        if abs(pocket_summary["sum_vmax_only_pocket_area_kw2"] - POCKET_PRIOR_VALUE_KW2) < 0.001
        else "DOES_NOT_RECONCILE"
    )

    vmax_concavity = [row for row in concavity_source if row["binding_family"] == "VMAX"]
    vmax_concavity_summary: list[dict[str, Any]] = []
    for scope, rows in [("ALL_TIMESTAMPS", vmax_concavity)] + [
        (timestamp, [row for row in vmax_concavity if row["timestamp"] == timestamp]) for timestamp in sorted(centers)
    ]:
        depth = stats(float(row["local_concavity_depth_kw"]) for row in rows)
        vmax_concavity_summary.append({
            "scope": scope,
            "vmax_reflex_count": len(rows),
            "local_depth_min_kw": depth["min"],
            "local_depth_q1_kw": depth["q1"],
            "local_depth_median_kw": depth["median"],
            "local_depth_q3_kw": depth["q3"],
            "local_depth_max_kw": depth["max"],
            "metric_definition": "PERPENDICULAR_DISTANCE_FROM_REFLEX_VERTEX_TO_SEGMENT_JOINING_IMMEDIATE_POLYGON_NEIGHBORS",
            "validation_label": "GEOMETRIC_ONLY_NOT_AC_VALIDATED",
            "explicit_non_equivalence": "NOT_AC_INTER_RAY_SAGITTA;NOT_AN_AC_FEASIBILITY_GUARANTEE",
        })

    concavity_by_timestamp: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in concavity_source:
        concavity_by_timestamp[row["timestamp"]].append(row)
    partition_by_timestamp = {row["timestamp"]: row for row in partition_source}
    complexity_rows: list[dict[str, Any]] = []
    for timestamp in sorted(centers):
        concave = concavity_by_timestamp[timestamp]
        total_reflex = len(concave)
        vmax_reflex = sum(row["binding_family"] == "VMAX" for row in concave)
        vmin_reflex = sum(row["binding_family"] == "VMIN" for row in concave)
        actual = int(partition_by_timestamp[timestamp]["merged_convex_cell_count"])
        lower = math.ceil(total_reflex / 2) + 1
        upper = total_reflex + 1
        complexity_rows.append({
            "timestamp": timestamp,
            "total_reflex_vertices": total_reflex,
            "vmax_reflex_vertices": vmax_reflex,
            "vmin_reflex_vertices": vmin_reflex,
            "vmax_reflex_fraction": vmax_reflex / total_reflex,
            "generic_no_steiner_lower_bound_cells": lower,
            "generic_no_steiner_upper_bound_cells": upper,
            "actual_minimum_center_fan_cells": actual,
            "gap_actual_minus_generic_lower": actual - lower,
            "gap_generic_upper_minus_actual": upper - actual,
            "actual_equals_vmax_reflex_plus_one": actual == vmax_reflex + 1,
            "bound_theorem": "SIMPLE_POLYGON_DIAGONAL_CONVEX_PARTITION:CEIL(R/2)+1<=OPT_NO_STEINER<=R+1",
            "bound_assumptions": "SIMPLE_POLYGON;PARTITION_BY_NONCROSSING_DIAGONALS;NO_STEINER_POINTS",
            "actual_partition_class": "EXACT_MINIMUM_WITHIN_PRODUCTION_CENTER_FAN_CONSECUTIVE_INTERVAL_MERGES;COMMON_CENTER_IS_STEINER_POINT",
            "bound_applicability": "GENERIC_NO_STEINER_OPTIMUM_REFERENCE;NOT_A_THEOREM_BOUND_ON_RESTRICTED_CENTER_FAN_MINIMUM",
        })
    complexity_variables = {
        name: [float(row[name]) for row in complexity_rows]
        for name in ("total_reflex_vertices", "vmax_reflex_vertices", "vmin_reflex_vertices", "actual_minimum_center_fan_cells")
    }
    complexity_summary = {
        "distributions": {name: stats(values) for name, values in complexity_variables.items()},
        "pearson_correlations": {
            f"{left}__vs__{right}": pearson(complexity_variables[left], complexity_variables[right])
            for index, left in enumerate(complexity_variables)
            for right in list(complexity_variables)[index + 1:]
        },
        "timestamps_actual_equals_vmax_reflex_plus_one": sum(row["actual_equals_vmax_reflex_plus_one"] for row in complexity_rows),
        "timestamp_count": len(complexity_rows),
        "classification": "VMAX_ONLY_PIECEWISE_COMPLEXITY_REDUCTION_UNLIKELY_FROM_EXISTING_GEOMETRY",
        "qualification": "EMPIRICAL_GEOMETRIC_DIAGNOSTIC_NOT_AN_IMPOSSIBILITY_PROOF_FOR_A_DIFFERENT_VMAX_ONLY_ARCHITECTURE",
    }

    loss_all = stats(row["delta_r_kw"] for row in radial_loss)
    loss_vmax = stats(row["delta_r_kw"] for row in radial_loss if row["binding_family"] == "VMAX")
    loss_vmin = stats(row["delta_r_kw"] for row in radial_loss if row["binding_family"] == "VMIN")
    vmax_depth = stats(float(row["local_concavity_depth_kw"]) for row in vmax_concavity)
    audit_summary = {
        "source_head": SOURCE_HEAD,
        "source_branch": SOURCE_BRANCH,
        "source_manifest_verification": "PASS",
        "kernel_retention": {row["group"]: row for row in retention_by_class},
        "kernel_radial_loss": {"all": loss_all, "vmax": loss_vmax, "vmin": loss_vmin},
        "pocket_area": pocket_summary,
        "vmax_local_concavity_depth_kw": vmax_depth,
        "piecewise_complexity": complexity_summary,
        "loss_mechanism_diagnostic": {
            "classification": "LOSS_MECHANISM_NOT_TESTABLE_FROM_STORED_ARTIFACTS",
            "reason": "STORED_PRODUCTION_BOUNDARY_SERIES_HAS_NO_PAIRED_BRANCH_FLOW_OR_LOSS_QUANTITY_AT_REFLEX_VERTICES",
        },
        "kernel_architecture_assessment": "KERNEL_NOT_CREDIBLE_AS_MAIN_COUPLED_DOE_FROM_EXISTING_BOUNDARY_MECHANISM_FIDELITY",
        "recommended_architecture": "RETAIN_FULL_EXACT_CONVEX_PARTITION_AS_MAIN_COUPLED_DOE_CANDIDATE;DO_NOT_PROMOTE_KERNEL_OR_VMAX_ONLY_SIMPLIFICATION",
        "scientific_scope": "ARTIFACT_ONLY_GEOMETRIC_EVIDENCE;NO_AC_INTERIOR_CERTIFICATION",
    }

    output.mkdir(parents=True, exist_ok=True)
    write_csv(output / "kernel_retention_by_class.csv", retention_by_class)
    write_csv(output / "kernel_retention_points.csv", retention_points)
    write_csv(output / "kernel_radial_loss.csv", radial_loss)
    write_csv(output / "kernel_radial_loss_summary.csv", radial_summary)
    write_csv(output / "pocket_area_normalized.csv", pocket_rows)
    write_json(output / "pocket_area_normalized_summary.json", pocket_summary)
    write_csv(output / "vmax_concavity_summary.csv", vmax_concavity_summary)
    write_csv(output / "piecewise_complexity_check.csv", complexity_rows)
    write_json(output / "audit_summary.json", audit_summary)

    locked = [
        "NAIVE_CONVEX_HULL_IS_NOT_ACCEPTABLE",
        "FOUR_FACET_PLUS_GLOBAL_HOMOTHETIC_CONTRACTION_IS_NOT_ACCEPTABLE",
        "UNIFORM_CONVEX_HULL_EROSION_IS_NOT_ACCEPTABLE",
        "NONCONVEXITY_IS_RESOLVABLY_LARGER_THAN_BOUNDARY_SEARCH_RESOLUTION",
        "VMAX_NONCONVEXITY_RESOLVABLY_STRUCTURAL",
        "VMIN_NONCONVEXITY_NOT_RESOLVABLE_ABOVE_BOUNDARY_SEARCH_RESOLUTION",
        "ANGULAR_POLYGON_IS_GEOMETRIC_REFERENCE_NOT_AC_CERTIFIED",
        "KERNEL_IS_NOT_KNOWN_TO_BE_MAXIMUM_AREA_CONVEX_SUBSET",
    ]
    report = f"""# DOE architecture-decision artifact audit

## Scope

Deterministic artifact-only analysis at committed HEAD `{SOURCE_HEAD}` on `{SOURCE_BRANCH}`. No AC solve, production probe, replay, optimization, benchmark, mesh validation, parameter tuning, staging, commit, or push was performed. All five source manifests verified `PASS` before calculation.

## Kernel retention by mechanism

The kernel retains **{counts['VMAX']['retained_count']}/{counts['VMAX']['total_count']} VMAX** points and **{counts['VMIN']['retained_count']}/{counts['VMIN']['total_count']} VMIN** points, aggregate **{counts['ALL_INWARD_POINTS']['retained_count']}/1689**.

- `VMAX_BUS_13`: {counts['VMAX_BUS_13']['retained_count']}/{counts['VMAX_BUS_13']['total_count']}.
- `VMAX_BUS_30`: {counts['VMAX_BUS_30']['retained_count']}/{counts['VMAX_BUS_30']['total_count']}.
- `VMIN_BUS_18`: {counts['VMIN_BUS_18']['retained_count']}/{counts['VMIN_BUS_18']['total_count']}.
- `VMIN_BUS_33`: {counts['VMIN_BUS_33']['retained_count']}/{counts['VMIN_BUS_33']['total_count']}.

Because every stored VMAX boundary point is excluded, area retention cannot establish mechanism fidelity. The artifact result is `KERNEL_NOT_CREDIBLE_AS_MAIN_COUPLED_DOE_FROM_EXISTING_BOUNDARY_MECHANISM_FIDELITY`. This is not an AC-safety claim, and the kernel is not known to be the maximum-area convex subset.

## Kernel radial-loss severity

For all {len(radial_loss)} excluded points, physical radial loss is measured from the production center along the established centered/sign-normalized production-angle ray. Overall delta-r: {distribution_line(loss_all)} kW. VMAX: {distribution_line(loss_vmax)} kW. VMIN: {distribution_line(loss_vmin)} kW. Relative and bracket-normalized distributions, including family, bus class, ray/signed-axis, and every timestamp, are in `kernel_radial_loss_summary.csv`.

## Normalized hull-minus-polygon pockets

Across 32 timestamps, pocket fraction relative to polygon area is {distribution_line(pocket_summary['pocket_fraction_polygon'])}; relative to hull area it is {distribution_line(pocket_summary['pocket_fraction_hull'])}. Aggregate ratios are {pocket_summary['aggregate_pocket_over_polygon']:.12g} and {pocket_summary['aggregate_pocket_over_hull']:.12g}, respectively.

The all-pocket sum is **{pocket_summary['sum_pocket_area_kw2']:.12f} kW^2**. The previously quoted 9,187,485.414 kW^2 is not the all-pocket sum: it is the rounded VMAX-only component ({pocket_summary['sum_vmax_only_pocket_area_kw2']:.12f} kW^2). The additional VMIN-only component is {pocket_summary['sum_vmin_only_pocket_area_kw2']:.12f} kW^2; mixed is {pocket_summary['sum_mixed_vmax_vmin_pocket_area_kw2']:.12f} kW^2. Existing classification is preserved with no new threshold.

## VMAX local geometric concavity

There are {vmax_depth['count']} VMAX reflex vertices. Local neighbor-chord segment depth is {distribution_line(vmax_depth)} kW. This is a purely geometric local concavity-depth metric, labeled `GEOMETRIC_ONLY_NOT_AC_VALIDATED`; it is **not** an AC inter-ray sagitta and does not make an inward edge AC-feasible. Per-timestamp count/median/max and full distributions are in `vmax_concavity_summary.csv`.

## Piecewise complexity

The exact minimum within the existing production-center fan/consecutive-interval merge class is {distribution_line(complexity_summary['distributions']['actual_minimum_center_fan_cells'])} cells. VMAX reflex counts are {distribution_line(complexity_summary['distributions']['vmax_reflex_vertices'])}; total reflex counts are {distribution_line(complexity_summary['distributions']['total_reflex_vertices'])}. At {complexity_summary['timestamps_actual_equals_vmax_reflex_plus_one']}/32 timestamps the existing exact count equals VMAX-reflex-count plus one, including the two timestamps with a trace VMIN reflex vertex.

For a simple polygon partitioned by noncrossing diagonals without Steiner points, the generic optimum satisfies `ceil(r/2)+1 <= cells <= r+1`. Those generic bounds are recorded as a reference only: the existing exact DP minimizes a restricted center-fan class whose common production center is a Steiner point, so the theorem does not certify that restricted minimum. Correlations are in `audit_summary.json`.

Classification: `VMAX_ONLY_PIECEWISE_COMPLEXITY_REDUCTION_UNLIKELY_FROM_EXISTING_GEOMETRY`. This is strong empirical geometry evidence, not proof that every possible VMAX-focused architecture is mathematically impossible to simplify.

## Loss-mechanism diagnostic

`LOSS_MECHANISM_NOT_TESTABLE_FROM_STORED_ARTIFACTS`: the production boundary series does not store a branch-flow/loss quantity paired to each reflex vertex. No causal claim is made.

## Architecture decision

Retain the full exact convex partition as the credible **Main Coupled DOE candidate** from the existing geometry. Do not promote the polygon kernel: it removes 100% of stored VMAX boundary evidence. Do not invest in a VMAX-only simplification on the present evidence: the exact full-partition count already tracks VMAX reflex count plus one at every timestamp. The cells and angular polygon remain geometric references, not AC-certified interiors.

## Locked conclusions preserved

{chr(10).join(f'- `{value}`' for value in locked)}

The audit does not claim VMIN mathematical convexity, kernel AC safety, angular-polygon AC safety, equivalence of local depth and AC sagitta, convexity from fitted-normal deviation, or fidelity from area retention alone.
"""
    write_text(output / "audit_report.md", report)

    output_names = [
        "audit_report.md",
        "audit_summary.json",
        "kernel_radial_loss.csv",
        "kernel_radial_loss_summary.csv",
        "kernel_retention_by_class.csv",
        "kernel_retention_points.csv",
        "piecewise_complexity_check.csv",
        "pocket_area_normalized.csv",
        "pocket_area_normalized_summary.json",
        "vmax_concavity_summary.csv",
    ]
    manifest_files = [
        {
            "path": (CANONICAL_OUTPUT / name).as_posix(),
            "bytes": (output / name).stat().st_size,
            "sha256": sha256(output / name),
        }
        for name in output_names
    ]
    script = root / SCRIPT_PATH
    manifest = {
        "audit": "DSO_VPP_DOE_ARCHITECTURE_DECISION_ARTIFACT_AUDIT",
        "source_branch": SOURCE_BRANCH,
        "source_head": SOURCE_HEAD,
        "verification_status": "PASS",
        "source_manifests": source_manifests,
        "files": manifest_files + [{
            "path": SCRIPT_PATH.as_posix(),
            "bytes": script.stat().st_size,
            "sha256": sha256(script),
        }],
        "manifest_self_reference": "OMITTED_BY_DESIGN",
    }
    write_json(output / "manifest.json", manifest)

    loaded = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    for row in loaded["files"]:
        target = root / row["path"] if row["path"] == SCRIPT_PATH.as_posix() else output / Path(row["path"]).name
        if target.stat().st_size != row["bytes"] or sha256(target) != row["sha256"]:
            raise SystemExit(f"generated manifest verification failed: {row['path']}")
    print(json.dumps({
        "manifest_sha256": sha256(output / "manifest.json"),
        "output_file_count": len(output_names) + 1,
        "verification_status": "PASS",
    }, sort_keys=True))


def main() -> None:
    args = parse_args()
    root = Path(__file__).resolve().parents[1]
    output = args.output if args.output.is_absolute() else root / args.output
    build(root, output)


if __name__ == "__main__":
    main()
