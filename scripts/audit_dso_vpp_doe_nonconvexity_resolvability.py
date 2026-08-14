#!/usr/bin/env python3
"""Deterministic, artifact-only audit of angular-polygon nonconvexity resolution."""

from __future__ import annotations

import argparse
import csv
import hashlib
import math
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence


SOURCE_BRANCH = "codex/dso-vpp-ac-map-pilot"
SOURCE_HEAD = "c18021d9b981f2629e54f60e8c2fc5f33b00c1a2"
PREREG = Path("results/dso_vpp_ac_map_pilot/doe_construction_policy_preregistration")
PRIOR_AUDIT = PREREG / "geometric_contraction_threshold_audit"
CANONICAL_OUTPUT = PREREG / "nonconvexity_resolvability_audit"
SCRIPT_PATH = Path("scripts/audit_dso_vpp_doe_nonconvexity_resolvability.py")

POLYGON_BOUNDARY_TOL_KW = 1.0e-8
KERNEL_HALFPLANE_TOL_KW = 1.0e-9
ORIENTATION_REL_TOL = 1.0e-12
DUPLICATE_ANGLE_TOL_DEG = 1.0e-9
DUPLICATE_POINT_TOL_KW = 1.0e-8
RAY_ANGLE_TOL_DEG = 1.0e-8
RAY_INTERSECTION_TOL = 1.0e-10
POSITIVE_DEFICIT_TOL_KW = 1.0e-8

CLASS_FAMILY = {
    "VMAX_BUS_13": "VMAX",
    "VMAX_BUS_30": "VMAX",
    "VMIN_BUS_18": "VMIN",
    "VMIN_BUS_33": "VMIN",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=CANONICAL_OUTPUT)
    return parser.parse_args()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
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
    if fields is None:
        fields = rows[0].keys() if rows else ()
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(fields), lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: csv_value(row.get(key)) for key in writer.fieldnames})


def write_text(path: Path, value: str) -> None:
    path.write_text(value, encoding="utf-8", newline="\n")


def f(value: str | float | int) -> float:
    return float(value)


def dot(a: tuple[float, float], b: tuple[float, float]) -> float:
    return a[0] * b[0] + a[1] * b[1]


def cross(a: tuple[float, float], b: tuple[float, float]) -> float:
    return a[0] * b[1] - a[1] * b[0]


def sub(a: tuple[float, float], b: tuple[float, float]) -> tuple[float, float]:
    return a[0] - b[0], a[1] - b[1]


def add(a: tuple[float, float], b: tuple[float, float]) -> tuple[float, float]:
    return a[0] + b[0], a[1] + b[1]


def mul(value: float, vector: tuple[float, float]) -> tuple[float, float]:
    return value * vector[0], value * vector[1]


def point(row: dict[str, str]) -> tuple[float, float]:
    return f(row["p13_abs_kw"]), f(row["p30_abs_kw"])


def endpoint_key(row: dict[str, str]) -> tuple[str, str, str, str]:
    return row["timestamp"], row["search_kind"], row["search_id"], row["level"]


def endpoint_id(row: dict[str, str]) -> str:
    return f"{row['search_kind']}:{row['search_id']}:{row['level']}"


def class_id(row: dict[str, str]) -> str:
    mechanism = row["binding_mechanism"].replace("BINDING_", "")
    value = f"{mechanism}_BUS_{row['binding_bus']}"
    if value not in CLASS_FAMILY:
        raise SystemExit(f"unexpected primary class {value}")
    return value


def angle_deg(vector: tuple[float, float]) -> float:
    return math.degrees(math.atan2(vector[1], vector[0])) % 360.0


def circular_distance(left: float, right: float) -> float:
    delta = abs(left - right) % 360.0
    return min(delta, 360.0 - delta)


def quantile(values: Sequence[float], probability: float) -> float:
    ordered = sorted(values)
    if not ordered:
        raise ValueError("empty distribution")
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def stats(values: Sequence[float]) -> dict[str, Any]:
    finite = [float(value) for value in values if value is not None and math.isfinite(float(value))]
    if not finite:
        return {"count": 0, "min": None, "q1": None, "median": None, "q3": None, "max": None, "mean": None}
    return {
        "count": len(finite),
        "min": min(finite),
        "q1": quantile(finite, 0.25),
        "median": quantile(finite, 0.5),
        "q3": quantile(finite, 0.75),
        "max": max(finite),
        "mean": sum(finite) / len(finite),
    }


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def verify_manifest(root: Path, manifest_path: Path) -> tuple[int, str]:
    rows = read_csv(root / manifest_path)
    failures: list[str] = []
    for row in rows:
        target = root / row["path"]
        if not target.is_file():
            failures.append(f"MISSING:{row['path']}")
            continue
        if target.stat().st_size != int(row["bytes"]):
            failures.append(f"BYTES:{row['path']}")
        if sha256(target) != row["sha256"]:
            failures.append(f"SHA256:{row['path']}")
    if failures:
        raise SystemExit("frozen manifest verification failed: " + ";".join(failures))
    return len(rows), sha256(root / manifest_path)


def signed_scales(axis_rows: list[dict[str, str]], center: tuple[float, float]) -> dict[str, float]:
    by_axis = {row["axis"]: row for row in axis_rows}
    required = {"P13_POSITIVE", "P13_NEGATIVE", "P30_POSITIVE", "P30_NEGATIVE"}
    if set(by_axis) != required:
        raise SystemExit("signed-axis scale inputs do not reconcile")
    result = {
        "s13_positive_kw": f(by_axis["P13_POSITIVE"]["safe_p13_abs_kw"]) - center[0],
        "s13_negative_kw": center[0] - f(by_axis["P13_NEGATIVE"]["safe_p13_abs_kw"]),
        "s30_positive_kw": f(by_axis["P30_POSITIVE"]["safe_p30_abs_kw"]) - center[1],
        "s30_negative_kw": center[1] - f(by_axis["P30_NEGATIVE"]["safe_p30_abs_kw"]),
    }
    if any(value <= 0 for value in result.values()):
        raise SystemExit("nonpositive production normalization scale")
    return result


def normalized_point(
    p: tuple[float, float], center: tuple[float, float], scales: dict[str, float]
) -> tuple[float, float, float, float]:
    dx, dy = p[0] - center[0], p[1] - center[1]
    sx = scales["s13_positive_kw"] if dx >= 0 else scales["s13_negative_kw"]
    sy = scales["s30_positive_kw"] if dy >= 0 else scales["s30_negative_kw"]
    x, y = dx / sx, dy / sy
    return x, y, math.hypot(x, y), angle_deg((x, y))


def ray_vector(theta_deg: float, scales: dict[str, float]) -> tuple[float, float]:
    theta = math.radians(theta_deg)
    cosine, sine = math.cos(theta), math.sin(theta)
    sx = scales["s13_positive_kw"] if cosine >= 0 else scales["s13_negative_kw"]
    sy = scales["s30_positive_kw"] if sine >= 0 else scales["s30_negative_kw"]
    return cosine * sx, sine * sy


def polygon_signed_area(vertices: Sequence[tuple[float, float]]) -> float:
    return 0.5 * sum(cross(vertices[index], vertices[(index + 1) % len(vertices)]) for index in range(len(vertices)))


def point_segment_distance(p: tuple[float, float], a: tuple[float, float], b: tuple[float, float]) -> float:
    edge = sub(b, a)
    length2 = dot(edge, edge)
    if length2 == 0:
        return math.dist(p, a)
    parameter = max(0.0, min(1.0, dot(sub(p, a), edge) / length2))
    projection = add(a, mul(parameter, edge))
    return math.dist(p, projection)


def point_line_distance(p: tuple[float, float], a: tuple[float, float], b: tuple[float, float]) -> float:
    edge = sub(b, a)
    length = math.hypot(*edge)
    return abs(cross(edge, sub(p, a))) / length if length else math.dist(p, a)


def boundary_distance(p: tuple[float, float], vertices: Sequence[tuple[float, float]]) -> float:
    return min(point_segment_distance(p, vertices[i], vertices[(i + 1) % len(vertices)]) for i in range(len(vertices)))


def point_in_polygon(p: tuple[float, float], vertices: Sequence[tuple[float, float]], tolerance_kw: float) -> str:
    if any(point_segment_distance(p, vertices[i], vertices[(i + 1) % len(vertices)]) <= tolerance_kw for i in range(len(vertices))):
        return "BOUNDARY"
    inside = False
    x, y = p
    for index, left in enumerate(vertices):
        right = vertices[(index + 1) % len(vertices)]
        if (left[1] > y) != (right[1] > y):
            crossing = left[0] + (y - left[1]) * (right[0] - left[0]) / (right[1] - left[1])
            if crossing > x:
                inside = not inside
    return "INSIDE" if inside else "OUTSIDE"


def convex_hull(points: Sequence[tuple[float, float]]) -> list[tuple[float, float]]:
    unique = sorted(set(points))
    if len(unique) <= 1:
        return unique

    def half(values: Sequence[tuple[float, float]]) -> list[tuple[float, float]]:
        result: list[tuple[float, float]] = []
        for p in values:
            while len(result) >= 2 and cross(sub(result[-1], result[-2]), sub(p, result[-1])) <= 0:
                result.pop()
            result.append(p)
        return result

    result = half(unique)[:-1] + half(list(reversed(unique)))[:-1]
    if polygon_signed_area(result) < 0:
        result.reverse()
    return result


def deduplicate_polygon(vertices: list[tuple[float, float]], tolerance: float = 1.0e-9) -> list[tuple[float, float]]:
    result: list[tuple[float, float]] = []
    for vertex in vertices:
        if not result or math.dist(vertex, result[-1]) > tolerance:
            result.append(vertex)
    if len(result) > 1 and math.dist(result[0], result[-1]) <= tolerance:
        result.pop()
    return result


def clip_halfplane(
    polygon: list[tuple[float, float]], signed_distance: Callable[[tuple[float, float]], float], tolerance: float
) -> list[tuple[float, float]]:
    if not polygon:
        return []
    result: list[tuple[float, float]] = []
    for index, current in enumerate(polygon):
        previous = polygon[index - 1]
        current_value = signed_distance(current)
        previous_value = signed_distance(previous)
        current_inside = current_value >= -tolerance
        previous_inside = previous_value >= -tolerance
        if current_inside != previous_inside:
            denominator = previous_value - current_value
            parameter = previous_value / denominator if denominator else 0.5
            result.append(add(previous, mul(parameter, sub(current, previous))))
        if current_inside:
            result.append(current)
    return deduplicate_polygon(result)


def halfplane_intersection(
    source_vertices: Sequence[tuple[float, float]], offset_kw: float = 0.0
) -> list[tuple[float, float]]:
    xs = [p[0] for p in source_vertices]
    ys = [p[1] for p in source_vertices]
    span = max(max(xs) - min(xs), max(ys) - min(ys), 1.0)
    margin = span + abs(offset_kw) + 1.0
    polygon = [
        (min(xs) - margin, min(ys) - margin),
        (max(xs) + margin, min(ys) - margin),
        (max(xs) + margin, max(ys) + margin),
        (min(xs) - margin, max(ys) + margin),
    ]
    for index, left in enumerate(source_vertices):
        right = source_vertices[(index + 1) % len(source_vertices)]
        edge = sub(right, left)
        length = math.hypot(*edge)
        if length <= POLYGON_BOUNDARY_TOL_KW:
            raise SystemExit("zero edge in halfplane intersection")
        polygon = clip_halfplane(
            polygon,
            lambda p, left=left, edge=edge, length=length: cross(edge, sub(p, left)) / length - offset_kw,
            KERNEL_HALFPLANE_TOL_KW,
        )
        if not polygon:
            break
    if len(polygon) >= 3 and polygon_signed_area(polygon) < 0:
        polygon.reverse()
    return polygon


def ray_polygon_intersection(
    center: tuple[float, float], direction: tuple[float, float], vertices: Sequence[tuple[float, float]]
) -> tuple[float | None, int, bool]:
    length2 = dot(direction, direction)
    candidates: list[float] = []
    collinear = False
    for index, a in enumerate(vertices):
        b = vertices[(index + 1) % len(vertices)]
        edge = sub(b, a)
        denominator = cross(direction, edge)
        relative = sub(a, center)
        scale = max(1.0, math.hypot(*direction) * math.hypot(*edge))
        if abs(denominator) <= RAY_INTERSECTION_TOL * scale:
            if abs(cross(relative, direction)) <= RAY_INTERSECTION_TOL * max(1.0, math.hypot(*relative) * math.hypot(*direction)):
                collinear = True
                for vertex in (a, b):
                    parameter = dot(sub(vertex, center), direction) / length2
                    if parameter >= -RAY_INTERSECTION_TOL:
                        candidates.append(max(0.0, parameter))
            continue
        ray_parameter = cross(relative, edge) / denominator
        edge_parameter = cross(relative, direction) / denominator
        if ray_parameter >= -RAY_INTERSECTION_TOL and -RAY_INTERSECTION_TOL <= edge_parameter <= 1.0 + RAY_INTERSECTION_TOL:
            candidates.append(max(0.0, ray_parameter))
    unique: list[float] = []
    for value in sorted(candidates):
        if not unique or abs(value - unique[-1]) > RAY_INTERSECTION_TOL * max(1.0, abs(value), abs(unique[-1])):
            unique.append(value)
    if not unique:
        return None, 0, collinear
    positive = [value for value in unique if value > RAY_INTERSECTION_TOL]
    return (max(positive) if positive else max(unique)), len(positive), collinear


def angular_groups(rows: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    ordered = sorted(rows, key=lambda row: (row["angle"], -row["radius"], row["endpoint_id"]))
    groups: list[list[dict[str, Any]]] = []
    for row in ordered:
        if groups and circular_distance(row["angle"], groups[-1][0]["angle"]) <= DUPLICATE_ANGLE_TOL_DEG:
            groups[-1].append(row)
        else:
            groups.append([row])
    if len(groups) > 1 and circular_distance(groups[0][0]["angle"], groups[-1][0]["angle"]) <= DUPLICATE_ANGLE_TOL_DEG:
        groups[0] = groups[-1] + groups[0]
        groups.pop()
    return groups


def distribution_rows(
    rows: list[dict[str, Any]], metrics: Sequence[tuple[str, str]], population: str
) -> list[dict[str, Any]]:
    scopes: list[tuple[str, Callable[[dict[str, Any]], str]]] = [
        ("GLOBAL", lambda row: "ALL"),
        ("TIMESTAMP", lambda row: row["timestamp"]),
        ("PRIMARY_CLASS", lambda row: row["primary_class"]),
        ("BINDING_FAMILY", lambda row: row["binding_family"]),
        ("SEARCH_KIND", lambda row: row["search_kind"]),
    ]
    result: list[dict[str, Any]] = []
    for scope, key_function in scopes:
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            grouped[key_function(row)].append(row)
        for key in sorted(grouped):
            for metric, field in metrics:
                values = [row[field] for row in grouped[key] if row.get(field) is not None]
                if not values:
                    continue
                result.append({
                    "population": population,
                    "scope": scope,
                    "group_key": key,
                    "timestamp_scope": key if scope == "TIMESTAMP" else "MULTIPLE_TIMESTAMPS",
                    "metric": metric,
                    **stats(values),
                    "quantile_method": "LINEAR_TYPE7",
                })
    return result


def format_stats_line(label: str, values: dict[str, Any], units: str = "") -> str:
    suffix = f" {units}" if units else ""
    return (
        f"- {label}: n={values['count']}; min {values['min']:.12g}{suffix}; Q1 {values['q1']:.12g}{suffix}; "
        f"median {values['median']:.12g}{suffix}; Q3 {values['q3']:.12g}{suffix}; "
        f"max {values['max']:.12g}{suffix}; mean {values['mean']:.12g}{suffix}."
    )


def format_median_max(values: dict[str, Any], units: str = "") -> str:
    if values["count"] == 0:
        return "n=0"
    suffix = f" {units}" if units else ""
    return f"n={values['count']}, median/max {values['median']:.12g}/{values['max']:.12g}{suffix}"


def build(root: Path, output: Path) -> None:
    prereg_count, prereg_manifest_sha = verify_manifest(root, PREREG / "artifact_manifest.csv")
    prior_count, prior_manifest_sha = verify_manifest(root, PRIOR_AUDIT / "artifact_manifest.csv")
    prod = root / "results/dso_vpp_ac_map_pilot/production_probe"
    output.mkdir(parents=True, exist_ok=True)

    center_rows = read_csv(prod / "center_results.csv")
    axis_rows = read_csv(prod / "signed_axis_results.csv")
    endpoint_rows = read_csv(prod / "boundary_endpoints.csv")
    centers = {row["timestamp"]: point(row) for row in center_rows}
    axes_by_time: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in axis_rows:
        axes_by_time[row["timestamp"]].append(row)
    scales_by_time = {timestamp: signed_scales(axes_by_time[timestamp], center) for timestamp, center in centers.items()}

    paired_sources: dict[tuple[str, str, str, str], dict[str, dict[str, str]]] = defaultdict(dict)
    for row in endpoint_rows:
        paired_sources[endpoint_key(row)][row["endpoint_side"]] = row
    if len(centers) != 32 or len(paired_sources) != 1689 or any(set(value) != {"SAFE", "VIOLATING"} for value in paired_sources.values()):
        raise SystemExit("frozen endpoint counts do not reconcile")

    pairs: list[dict[str, Any]] = []
    pairs_by_time: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for key in sorted(paired_sources):
        safe, outward = paired_sources[key]["SAFE"], paired_sources[key]["VIOLATING"]
        timestamp = safe["timestamp"]
        center, scales = centers[timestamp], scales_by_time[timestamp]
        pin, pout = point(safe), point(outward)
        nx_in, ny_in, radius_in, angle_in = normalized_point(pin, center, scales)
        nx_out, ny_out, radius_out, angle_out = normalized_point(pout, center, scales)
        same_ray = circular_distance(angle_in, angle_out) <= RAY_ANGLE_TOL_DEG and dot((nx_in, ny_in), (nx_out, ny_out)) > 0
        vector = ray_vector(angle_in, scales)
        radial_bracket = radius_out - radius_in if same_ray else None
        physical_radial_bracket = radial_bracket * math.hypot(*vector) if radial_bracket is not None else None
        primary = class_id(safe)
        pair = {
            "timestamp": timestamp,
            "endpoint_id": endpoint_id(safe),
            "search_kind": safe["search_kind"],
            "search_id": safe["search_id"],
            "level": safe["level"],
            "primary_class": primary,
            "binding_family": CLASS_FAMILY[primary],
            "binding_bus": safe["binding_bus"],
            "inward": pin,
            "outward": pout,
            "inward_radius": radius_in,
            "outward_radius": radius_out,
            "inward_angle": angle_in,
            "outward_angle": angle_out,
            "inward_normalized_x": nx_in,
            "inward_normalized_y": ny_in,
            "same_production_ray": same_ray,
            "physical_bracket_spacing_kw": math.dist(pin, pout),
            "signed_radial_bracket_spacing": radial_bracket,
            "physical_radial_bracket_spacing_kw": physical_radial_bracket,
        }
        pairs.append(pair)
        pairs_by_time[timestamp].append(pair)

    kernel_summary: list[dict[str, Any]] = []
    kernel_vertices: list[dict[str, Any]] = []
    concavity_rows: list[dict[str, Any]] = []
    inward_rows: list[dict[str, Any]] = []
    outward_rows: list[dict[str, Any]] = []
    structural_rows: list[dict[str, Any]] = []
    scale_rows: list[dict[str, Any]] = []
    erosion_rows: list[dict[str, Any]] = []

    for timestamp in sorted(centers):
        center, scales = centers[timestamp], scales_by_time[timestamp]
        timestamp_pairs = pairs_by_time[timestamp]
        prepared = [{
            "pair": pair,
            "point": pair["inward"],
            "angle": pair["inward_angle"],
            "radius": pair["inward_radius"],
            "endpoint_id": pair["endpoint_id"],
        } for pair in timestamp_pairs]
        groups = angular_groups(prepared)
        selected = [sorted(group, key=lambda row: (-row["radius"], row["endpoint_id"], row["point"]))[0] for group in groups]
        selected.sort(key=lambda row: (row["angle"], row["endpoint_id"]))
        vertices = [row["point"] for row in selected]
        if polygon_signed_area(vertices) < 0:
            selected.reverse()
            vertices.reverse()
        if point_in_polygon(center, vertices, POLYGON_BOUNDARY_TOL_KW) not in {"INSIDE", "BOUNDARY"}:
            raise SystemExit(f"frozen center-containment result failed for {timestamp}")

        kernel = halfplane_intersection(vertices)
        kernel_empty = len(kernel) < 3 or abs(polygon_signed_area(kernel)) <= POLYGON_BOUNDARY_TOL_KW**2
        kernel_area = 0.0 if kernel_empty else abs(polygon_signed_area(kernel))
        center_kernel_location = "EMPTY_KERNEL" if kernel_empty else point_in_polygon(center, kernel, POLYGON_BOUNDARY_TOL_KW)
        center_in_kernel = center_kernel_location in {"INSIDE", "BOUNDARY"}
        if kernel_empty:
            signed_kernel_distance = None
            nearest_kernel_distance = None
        else:
            nearest_kernel_distance = boundary_distance(center, kernel)
            signed_kernel_distance = nearest_kernel_distance if center_kernel_location == "INSIDE" else 0.0 if center_kernel_location == "BOUNDARY" else -nearest_kernel_distance
        edge_center_signed_distances = []
        for index, left in enumerate(vertices):
            edge = sub(vertices[(index + 1) % len(vertices)], left)
            edge_center_signed_distances.append(cross(edge, sub(center, left)) / math.hypot(*edge))
        center_satisfies_all_edge_halfplanes = min(edge_center_signed_distances) >= -KERNEL_HALFPLANE_TOL_KW
        every_boundary_segment_inside = center_in_kernel and center_satisfies_all_edge_halfplanes
        kernel_summary.append({
            "timestamp": timestamp,
            "polygon_vertex_count": len(vertices),
            "kernel_empty": kernel_empty,
            "kernel_vertex_count": 0 if kernel_empty else len(kernel),
            "kernel_area_kw2": kernel_area,
            "production_center_location_in_kernel": center_kernel_location,
            "production_center_in_polygon_kernel": center_in_kernel,
            "nearest_kernel_boundary_distance_kw": nearest_kernel_distance,
            "signed_distance_to_kernel_boundary_kw": signed_kernel_distance,
            "minimum_center_signed_polygon_edge_halfplane_distance_kw": min(edge_center_signed_distances),
            "center_satisfies_every_ccw_edge_left_halfplane": center_satisfies_all_edge_halfplanes,
            "every_radial_segment_center_to_every_polygon_boundary_point_inside": every_boundary_segment_inside,
            "visibility_verification_basis": "CENTER_IN_INTERSECTION_OF_ALL_CCW_POLYGON_EDGE_LEFT_HALFPLANES;POLYGON_KERNEL_THEOREM",
            "kernel_method": "DETERMINISTIC_SUTHERLAND_HODGMAN_INTERSECTION_OF_NORMALIZED_CCW_EDGE_HALFPLANES",
            "halfplane_tolerance_kw": KERNEL_HALFPLANE_TOL_KW,
            "polygon_boundary_tolerance_kw": POLYGON_BOUNDARY_TOL_KW,
            "center_p13_abs_kw": center[0],
            "center_p30_abs_kw": center[1],
            **scales,
            "coordinate_semantics": "ABSOLUTE_PHYSICAL_PCC_KERNEL;CENTERED_SIGN_NORMALIZED_PRODUCTION_RAY_ORDER",
            "units": "kW coordinates and distance; kW^2 area",
        })
        if not kernel_empty:
            for index, vertex in enumerate(kernel):
                kernel_vertices.append({
                    "timestamp": timestamp,
                    "kernel_vertex_index_ccw": index,
                    "p13_abs_kw": vertex[0],
                    "p30_abs_kw": vertex[1],
                    "center_p13_abs_kw": center[0],
                    "center_p30_abs_kw": center[1],
                    "coordinate_semantics": "ABSOLUTE_PHYSICAL_PCC",
                    "units": "kW",
                })

        polygon_diameter = max(math.dist(left, right) for left in vertices for right in vertices)
        for index, item in enumerate(selected):
            previous = vertices[index - 1]
            current = vertices[index]
            following = vertices[(index + 1) % len(vertices)]
            left_edge, right_edge = sub(current, previous), sub(following, current)
            orientation = cross(left_edge, right_edge)
            orientation_scale = max(1.0, math.hypot(*left_edge) * math.hypot(*right_edge))
            tolerance = ORIENTATION_REL_TOL * orientation_scale
            classification = "COLLINEAR" if abs(orientation) <= tolerance else "CONVEX" if orientation > 0 else "CONCAVE"
            depth_segment = point_segment_distance(current, previous, following) if classification == "CONCAVE" else None
            depth_line = point_line_distance(current, previous, following) if classification == "CONCAVE" else None
            pair = item["pair"]
            concavity_rows.append({
                "timestamp": timestamp,
                "vertex_index_ccw": index,
                "vertex_identifier": pair["endpoint_id"],
                "ray_angle_deg": item["angle"],
                "primary_class": pair["primary_class"],
                "binding_family": pair["binding_family"],
                "binding_bus": pair["binding_bus"],
                "search_kind": pair["search_kind"],
                "classification": classification,
                "orientation_cross_kw2": orientation,
                "orientation_tolerance_kw2": tolerance,
                "orientation_relative_tolerance": ORIENTATION_REL_TOL,
                "local_neighbor_chord_segment_depth_kw": depth_segment,
                "local_neighbor_chord_line_depth_kw": depth_line,
                "physical_bracket_spacing_kw": pair["physical_bracket_spacing_kw"],
                "depth_over_physical_bracket_ratio": depth_segment / pair["physical_bracket_spacing_kw"] if depth_segment is not None else None,
                "depth_over_polygon_diameter": depth_segment / polygon_diameter if depth_segment is not None else None,
                "p13_abs_kw": current[0],
                "p30_abs_kw": current[1],
                "previous_p13_abs_kw": previous[0],
                "previous_p30_abs_kw": previous[1],
                "next_p13_abs_kw": following[0],
                "next_p30_abs_kw": following[1],
                "coordinate_semantics": "ABSOLUTE_PHYSICAL_PCC;CCW_ORIENTATION_FROM_CENTERED_SIGN_NORMALIZED_RAY_ORDER",
                "units": "kW coordinates/depth/bracket; kW^2 cross product",
            })

        hull = convex_hull([item["point"] for item in prepared])
        hull_area = abs(polygon_signed_area(hull))
        polygon_area = abs(polygon_signed_area(vertices))
        inward_for_time: list[dict[str, Any]] = []
        outward_for_time: list[dict[str, Any]] = []
        for pair in timestamp_pairs:
            pin = pair["inward"]
            location = point_in_polygon(pin, hull, POLYGON_BOUNDARY_TOL_KW)
            perpendicular = 0.0 if location == "BOUNDARY" else boundary_distance(pin, hull)
            direction = ray_vector(pair["inward_angle"], scales)
            hull_radius, intersection_count, collinear = ray_polygon_intersection(center, direction, hull)
            if hull_radius is None:
                raise SystemExit(f"missing inward ray/hull intersection for {timestamp} {pair['endpoint_id']}")
            radial_deficit = max(0.0, hull_radius - pair["inward_radius"])
            physical_radial_deficit = radial_deficit * math.hypot(*direction)
            positive = perpendicular > POSITIVE_DEFICIT_TOL_KW or physical_radial_deficit > POSITIVE_DEFICIT_TOL_KW
            row = {
                "timestamp": timestamp,
                "endpoint_id": pair["endpoint_id"],
                "search_kind": pair["search_kind"],
                "search_id": pair["search_id"],
                "level": pair["level"],
                "primary_class": pair["primary_class"],
                "binding_family": pair["binding_family"],
                "binding_bus": pair["binding_bus"],
                "p13_abs_kw": pin[0],
                "p30_abs_kw": pin[1],
                "ray_angle_deg": pair["inward_angle"],
                "inward_normalized_radius": pair["inward_radius"],
                "hull_normalized_radius": hull_radius,
                "hull_location": location,
                "nonzero_hull_deficit": positive,
                "convex_hull_perpendicular_deficit_kw": perpendicular,
                "convex_hull_radial_deficit_normalized": radial_deficit,
                "convex_hull_radial_deficit_physical_kw": physical_radial_deficit,
                "physical_bracket_spacing_kw": pair["physical_bracket_spacing_kw"],
                "same_production_ray_pair": pair["same_production_ray"],
                "signed_radial_bracket_spacing": pair["signed_radial_bracket_spacing"],
                "physical_radial_bracket_spacing_kw": pair["physical_radial_bracket_spacing_kw"],
                "perpendicular_deficit_over_physical_bracket_ratio": perpendicular / pair["physical_bracket_spacing_kw"] if positive else None,
                "radial_deficit_over_radial_bracket_ratio": radial_deficit / pair["signed_radial_bracket_spacing"] if positive and pair["signed_radial_bracket_spacing"] and pair["signed_radial_bracket_spacing"] > 0 else None,
                "physical_radial_deficit_over_physical_radial_bracket_ratio": physical_radial_deficit / pair["physical_radial_bracket_spacing_kw"] if positive and pair["physical_radial_bracket_spacing_kw"] and pair["physical_radial_bracket_spacing_kw"] > 0 else None,
                "perpendicular_deficit_over_polygon_diameter": perpendicular / polygon_diameter,
                "physical_radial_deficit_over_polygon_diameter": physical_radial_deficit / polygon_diameter,
                "ray_hull_positive_intersection_count": intersection_count,
                "ray_hull_collinear_edge_encountered": collinear,
                "ray_hull_intersection_ambiguous": intersection_count != 1 and not collinear,
                "coordinate_semantics": "ABSOLUTE_PHYSICAL_PCC_HULL;CENTERED_SIGN_NORMALIZED_PRODUCTION_RAY",
                "units": "kW physical distances; dimensionless normalized radius and ratios",
            }
            inward_rows.append(row)
            inward_for_time.append(row)

            pout = pair["outward"]
            out_location = point_in_polygon(pout, hull, POLYGON_BOUNDARY_TOL_KW)
            if out_location == "INSIDE":
                out_angle = pair["outward_angle"]
                out_direction = ray_vector(out_angle, scales)
                out_radius_hull, out_intersections, out_collinear = ray_polygon_intersection(center, out_direction, hull)
                if out_radius_hull is None:
                    raise SystemExit(f"missing outward ray/hull intersection for {timestamp} {pair['endpoint_id']}")
                radial_penetration = max(0.0, out_radius_hull - pair["outward_radius"])
                physical_radial_penetration = radial_penetration * math.hypot(*out_direction)
                perpendicular_penetration = boundary_distance(pout, hull)
                out_row = {
                    "timestamp": timestamp,
                    "endpoint_id": pair["endpoint_id"],
                    "search_kind": pair["search_kind"],
                    "search_id": pair["search_id"],
                    "level": pair["level"],
                    "primary_class": pair["primary_class"],
                    "binding_family": pair["binding_family"],
                    "binding_bus": pair["binding_bus"],
                    "p13_abs_kw": pout[0],
                    "p30_abs_kw": pout[1],
                    "ray_angle_deg": out_angle,
                    "outward_normalized_radius": pair["outward_radius"],
                    "hull_normalized_radius": out_radius_hull,
                    "hull_location": out_location,
                    "convex_hull_perpendicular_penetration_kw": perpendicular_penetration,
                    "convex_hull_radial_penetration_normalized": radial_penetration,
                    "convex_hull_radial_penetration_physical_kw": physical_radial_penetration,
                    "physical_bracket_spacing_kw": pair["physical_bracket_spacing_kw"],
                    "same_production_ray_pair": pair["same_production_ray"],
                    "signed_radial_bracket_spacing": pair["signed_radial_bracket_spacing"],
                    "physical_radial_bracket_spacing_kw": pair["physical_radial_bracket_spacing_kw"],
                    "perpendicular_penetration_over_physical_bracket_ratio": perpendicular_penetration / pair["physical_bracket_spacing_kw"],
                    "radial_penetration_over_radial_bracket_ratio": radial_penetration / pair["signed_radial_bracket_spacing"] if pair["signed_radial_bracket_spacing"] and pair["signed_radial_bracket_spacing"] > 0 else None,
                    "physical_radial_penetration_over_physical_radial_bracket_ratio": physical_radial_penetration / pair["physical_radial_bracket_spacing_kw"] if pair["physical_radial_bracket_spacing_kw"] and pair["physical_radial_bracket_spacing_kw"] > 0 else None,
                    "perpendicular_penetration_over_polygon_diameter": perpendicular_penetration / polygon_diameter,
                    "physical_radial_penetration_over_polygon_diameter": physical_radial_penetration / polygon_diameter,
                    "ray_hull_positive_intersection_count": out_intersections,
                    "ray_hull_collinear_edge_encountered": out_collinear,
                    "ray_hull_intersection_ambiguous": out_intersections != 1 and not out_collinear,
                    "coordinate_semantics": "ABSOLUTE_PHYSICAL_PCC_HULL;CENTERED_SIGN_NORMALIZED_PRODUCTION_RAY",
                    "units": "kW physical distances; dimensionless normalized radius and ratios",
                }
                outward_rows.append(out_row)
                outward_for_time.append(out_row)

            polygon_direction_out = ray_vector(pair["outward_angle"], scales)
            polygon_radius_out, polygon_intersections, polygon_collinear = ray_polygon_intersection(center, polygon_direction_out, vertices)
            if polygon_radius_out is None:
                raise SystemExit(f"missing outward ray/polygon intersection for {timestamp} {pair['endpoint_id']}")
            outward_polygon_location = point_in_polygon(pout, vertices, POLYGON_BOUNDARY_TOL_KW)
            inward_is_selected_boundary = any(item["pair"] is pair for item in selected)
            automatic = (
                pair["same_production_ray"]
                and inward_is_selected_boundary
                and pair["outward_radius"] > pair["inward_radius"]
                and abs(polygon_radius_out - pair["inward_radius"]) <= 1.0e-8 * max(1.0, pair["inward_radius"])
            )
            structural_rows.append({
                "timestamp": timestamp,
                "endpoint_id": pair["endpoint_id"],
                "search_kind": pair["search_kind"],
                "search_id": pair["search_id"],
                "level": pair["level"],
                "primary_class": pair["primary_class"],
                "binding_family": pair["binding_family"],
                "binding_bus": pair["binding_bus"],
                "paired_same_production_ray": pair["same_production_ray"],
                "inward_is_selected_radial_polygon_vertex": inward_is_selected_boundary,
                "inward_normalized_radius": pair["inward_radius"],
                "outward_normalized_radius": pair["outward_radius"],
                "polygon_boundary_normalized_radius_on_outward_angle": polygon_radius_out,
                "outward_minus_polygon_boundary_normalized_radius": pair["outward_radius"] - polygon_radius_out,
                "outward_point_polygon_location": outward_polygon_location,
                "r_out_strictly_greater_than_r_in": pair["outward_radius"] > pair["inward_radius"],
                "exclusion_structurally_implied_by_same_ray_r_out_gt_selected_r_in": automatic,
                "classification": "EXPECTED_FROM_RADIAL_POLYGON_CONSTRUCTION_ON_SAMPLED_RAYS" if automatic else "DIRECT_GEOMETRIC_CHECK_NOT_SAME_RAY_STRUCTURAL_IMPLICATION",
                "ray_polygon_positive_intersection_count": polygon_intersections,
                "ray_polygon_collinear_edge_encountered": polygon_collinear,
                "ray_polygon_intersection_ambiguous": polygon_intersections != 1 and not polygon_collinear,
                "coordinate_semantics": "CENTERED_SIGN_NORMALIZED_PRODUCTION_RAY_WITH_ABSOLUTE_PHYSICAL_PCC_POLYGON",
                "units": "dimensionless normalized radius",
            })

        axis_by_name = {row["axis"]: row for row in axes_by_time[timestamp]}
        p13_span = f(axis_by_name["P13_POSITIVE"]["safe_p13_abs_kw"]) - f(axis_by_name["P13_NEGATIVE"]["safe_p13_abs_kw"])
        p30_span = f(axis_by_name["P30_POSITIVE"]["safe_p30_abs_kw"]) - f(axis_by_name["P30_NEGATIVE"]["safe_p30_abs_kw"])
        scale_rows.append({
            "timestamp": timestamp,
            "axis_span_p13_kw": p13_span,
            "axis_span_p30_kw": p30_span,
            "angular_polygon_diameter_kw": polygon_diameter,
            "angular_polygon_area_kw2": polygon_area,
            "convex_hull_area_kw2": hull_area,
            "convex_hull_area_over_angular_polygon_area": hull_area / polygon_area,
            "median_inward_physical_radius_kw": quantile([math.dist(pair["inward"], center) for pair in timestamp_pairs], 0.5),
            "median_inward_normalized_radius": quantile([pair["inward_radius"] for pair in timestamp_pairs], 0.5),
            "center_p13_abs_kw": center[0],
            "center_p30_abs_kw": center[1],
            **scales,
            "coordinate_semantics": "ABSOLUTE_PHYSICAL_PCC_WITH_PRODUCTION_CENTER_AND_SIGN_SPECIFIC_SCALES",
            "units": "kW spans/radii/diameter; kW^2 area",
        })

        if outward_for_time:
            delta_sup = max(row["convex_hull_perpendicular_penetration_kw"] for row in outward_for_time)
            eroded = halfplane_intersection(hull, delta_sup)
            eroded_area = abs(polygon_signed_area(eroded)) if len(eroded) >= 3 else 0.0
            inward_depths = []
            for pair in timestamp_pairs:
                depths = []
                for index, left in enumerate(hull):
                    edge = sub(hull[(index + 1) % len(hull)], left)
                    depths.append(cross(edge, sub(pair["inward"], left)) / math.hypot(*edge))
                inward_depths.append(min(depths))
            bracket_values = [pair["physical_bracket_spacing_kw"] for pair in timestamp_pairs]
            epsilon = 1.0e-9
            erosion_rows.append({
                "timestamp": timestamp,
                "outward_inside_hull_count": len(outward_for_time),
                "required_erosion_distance_sup_kw": delta_sup,
                "strict_exclusion_semantics": "ALL_STORED_OUTWARD_INSIDE_POINTS_EXCLUDED_FOR_DELTA_STRICTLY_GREATER_THAN_SUPREMUM;DEEPEST_POINT_ON_BOUNDARY_AT_EQUALITY",
                "outward_points_on_eroded_boundary_at_sup": sum(abs(row["convex_hull_perpendicular_penetration_kw"] - delta_sup) <= epsilon for row in outward_for_time),
                "inward_total": len(timestamp_pairs),
                "inward_retained_on_or_inside_at_sup": sum(value >= delta_sup - epsilon for value in inward_depths),
                "inward_retained_fraction_at_sup": sum(value >= delta_sup - epsilon for value in inward_depths) / len(timestamp_pairs),
                "original_hull_area_kw2": hull_area,
                "eroded_hull_area_at_sup_kw2": eroded_area,
                "area_retained_fraction_at_sup": eroded_area / hull_area,
                "median_physical_bracket_spacing_kw": quantile(bracket_values, 0.5),
                "max_physical_bracket_spacing_kw": max(bracket_values),
                "erosion_sup_over_median_bracket_ratio": delta_sup / quantile(bracket_values, 0.5),
                "erosion_sup_over_max_bracket_ratio": delta_sup / max(bracket_values),
                "diagnostic_role": "OPTIONAL_GEOMETRIC_DIAGNOSTIC_ONLY_NOT_POLICY",
                "erosion_method": "UNIFORM_INWARD_OFFSET_OF_EUCLIDEAN_UNIT_CCW_HULL_EDGE_HALFPLANES",
                "units": "kW distance; kW^2 area; dimensionless fractions/ratios",
            })

    concave = [row for row in concavity_rows if row["classification"] == "CONCAVE"]
    positive_inward = [row for row in inward_rows if row["nonzero_hull_deficit"]]
    concavity_summary = distribution_rows(concave, (
        ("LOCAL_NEIGHBOR_CHORD_SEGMENT_DEPTH_KW", "local_neighbor_chord_segment_depth_kw"),
        ("LOCAL_NEIGHBOR_CHORD_LINE_DEPTH_KW", "local_neighbor_chord_line_depth_kw"),
        ("LOCAL_DEPTH_OVER_PHYSICAL_BRACKET_RATIO", "depth_over_physical_bracket_ratio"),
        ("LOCAL_DEPTH_OVER_POLYGON_DIAMETER", "depth_over_polygon_diameter"),
    ), "GENUINELY_CONCAVE_VERTICES")
    inward_summary = distribution_rows(inward_rows, (
        ("CONVEX_HULL_PERPENDICULAR_DEFICIT_KW", "convex_hull_perpendicular_deficit_kw"),
        ("CONVEX_HULL_RADIAL_DEFICIT_NORMALIZED", "convex_hull_radial_deficit_normalized"),
        ("CONVEX_HULL_RADIAL_DEFICIT_PHYSICAL_KW", "convex_hull_radial_deficit_physical_kw"),
    ), "ALL_INWARD_POINTS")
    inward_summary.extend(distribution_rows(positive_inward, (
        ("CONVEX_HULL_PERPENDICULAR_DEFICIT_KW", "convex_hull_perpendicular_deficit_kw"),
        ("CONVEX_HULL_RADIAL_DEFICIT_NORMALIZED", "convex_hull_radial_deficit_normalized"),
        ("CONVEX_HULL_RADIAL_DEFICIT_PHYSICAL_KW", "convex_hull_radial_deficit_physical_kw"),
        ("PERPENDICULAR_DEFICIT_OVER_PHYSICAL_BRACKET_RATIO", "perpendicular_deficit_over_physical_bracket_ratio"),
        ("RADIAL_DEFICIT_OVER_RADIAL_BRACKET_RATIO", "radial_deficit_over_radial_bracket_ratio"),
        ("PERPENDICULAR_DEFICIT_OVER_POLYGON_DIAMETER", "perpendicular_deficit_over_polygon_diameter"),
    ), "INWARD_POINTS_WITH_NONZERO_HULL_DEFICIT"))
    outward_summary = distribution_rows(outward_rows, (
        ("CONVEX_HULL_PERPENDICULAR_PENETRATION_KW", "convex_hull_perpendicular_penetration_kw"),
        ("CONVEX_HULL_RADIAL_PENETRATION_NORMALIZED", "convex_hull_radial_penetration_normalized"),
        ("CONVEX_HULL_RADIAL_PENETRATION_PHYSICAL_KW", "convex_hull_radial_penetration_physical_kw"),
        ("PERPENDICULAR_PENETRATION_OVER_PHYSICAL_BRACKET_RATIO", "perpendicular_penetration_over_physical_bracket_ratio"),
        ("RADIAL_PENETRATION_OVER_RADIAL_BRACKET_RATIO", "radial_penetration_over_radial_bracket_ratio"),
        ("PERPENDICULAR_PENETRATION_OVER_POLYGON_DIAMETER", "perpendicular_penetration_over_polygon_diameter"),
    ), "OUTWARD_ENDPOINTS_STRICTLY_INSIDE_CONVEX_HULL")
    resolution_summary = distribution_rows(positive_inward, (
        ("INWARD_PERPENDICULAR_DEFICIT_OVER_PHYSICAL_BRACKET", "perpendicular_deficit_over_physical_bracket_ratio"),
        ("INWARD_RADIAL_DEFICIT_OVER_RADIAL_BRACKET", "radial_deficit_over_radial_bracket_ratio"),
    ), "INWARD_POINTS_WITH_NONZERO_HULL_DEFICIT")
    resolution_summary.extend(distribution_rows(outward_rows, (
        ("OUTWARD_PERPENDICULAR_PENETRATION_OVER_PHYSICAL_BRACKET", "perpendicular_penetration_over_physical_bracket_ratio"),
        ("OUTWARD_RADIAL_PENETRATION_OVER_RADIAL_BRACKET", "radial_penetration_over_radial_bracket_ratio"),
    ), "OUTWARD_ENDPOINTS_STRICTLY_INSIDE_CONVEX_HULL"))
    for collection in (concavity_summary, inward_summary, outward_summary, resolution_summary):
        collection.sort(key=lambda row: (row["population"], row["scope"], row["group_key"], row["metric"]))

    if len(outward_rows) != 730:
        raise SystemExit(f"frozen 730 outward-inside-hull count did not reconcile: {len(outward_rows)}")
    if any(row["ray_hull_intersection_ambiguous"] for row in inward_rows + outward_rows):
        raise SystemExit("ambiguous nondegenerate ray/hull intersection")
    if any(row["ray_polygon_intersection_ambiguous"] for row in structural_rows):
        raise SystemExit("ambiguous nondegenerate ray/polygon intersection")

    write_csv(output / "polygon_kernel_summary.csv", kernel_summary)
    write_csv(output / "polygon_kernel_vertices.csv", kernel_vertices)
    write_csv(output / "local_concavity_depth.csv", concavity_rows)
    write_csv(output / "local_concavity_depth_summary.csv", concavity_summary)
    write_csv(output / "convex_hull_deficit_inward_points.csv", inward_rows)
    write_csv(output / "convex_hull_deficit_summary.csv", inward_summary)
    write_csv(output / "convex_hull_outward_penetration.csv", outward_rows)
    write_csv(output / "convex_hull_outward_penetration_summary.csv", outward_summary)
    write_csv(output / "resolution_ratio_summary.csv", resolution_summary)
    write_csv(output / "radial_polygon_screen_structural_check.csv", structural_rows)
    write_csv(output / "physical_scale_context.csv", scale_rows)
    write_csv(output / "convex_hull_erosion_diagnostic.csv", erosion_rows)

    local_depth_stats = stats([row["local_neighbor_chord_segment_depth_kw"] for row in concave])
    local_ratio_stats = stats([row["depth_over_physical_bracket_ratio"] for row in concave])
    inward_perp_stats = stats([row["convex_hull_perpendicular_deficit_kw"] for row in positive_inward])
    inward_radial_stats = stats([row["convex_hull_radial_deficit_physical_kw"] for row in positive_inward])
    inward_perp_ratio_stats = stats([row["perpendicular_deficit_over_physical_bracket_ratio"] for row in positive_inward])
    inward_radial_ratio_stats = stats([row["radial_deficit_over_radial_bracket_ratio"] for row in positive_inward if row["radial_deficit_over_radial_bracket_ratio"] is not None])
    outward_perp_stats = stats([row["convex_hull_perpendicular_penetration_kw"] for row in outward_rows])
    outward_radial_stats = stats([row["convex_hull_radial_penetration_physical_kw"] for row in outward_rows])
    outward_perp_ratio_stats = stats([row["perpendicular_penetration_over_physical_bracket_ratio"] for row in outward_rows])
    outward_radial_ratio_stats = stats([row["radial_penetration_over_radial_bracket_ratio"] for row in outward_rows if row["radial_penetration_over_radial_bracket_ratio"] is not None])
    kernel_inside_count = sum(row["production_center_in_polygon_kernel"] for row in kernel_summary)
    automatic_count = sum(row["exclusion_structurally_implied_by_same_ray_r_out_gt_selected_r_in"] for row in structural_rows)
    same_ray_count = sum(row["paired_same_production_ray"] for row in structural_rows)
    location_counts = Counter(row["outward_point_polygon_location"] for row in structural_rows)
    vertex_counts = Counter(row["classification"] for row in concavity_rows)
    concave_by_time = Counter(row["timestamp"] for row in concave)
    family_depth = {family: stats([row["local_neighbor_chord_segment_depth_kw"] for row in concave if row["binding_family"] == family]) for family in sorted(CLASS_FAMILY.values())}
    family_pen = {family: stats([row["convex_hull_perpendicular_penetration_kw"] for row in outward_rows if row["binding_family"] == family]) for family in sorted(CLASS_FAMILY.values())}
    erosion_stats = stats([row["required_erosion_distance_sup_kw"] for row in erosion_rows])
    erosion_retention_stats = stats([row["inward_retained_fraction_at_sup"] for row in erosion_rows])
    erosion_area_stats = stats([row["area_retained_fraction_at_sup"] for row in erosion_rows])
    kernel_area_stats = stats([row["kernel_area_kw2"] for row in kernel_summary])
    kernel_distance_stats = stats([row["nearest_kernel_boundary_distance_kw"] for row in kernel_summary])
    p13_span_stats = stats([row["axis_span_p13_kw"] for row in scale_rows])
    p30_span_stats = stats([row["axis_span_p30_kw"] for row in scale_rows])
    diameter_stats = stats([row["angular_polygon_diameter_kw"] for row in scale_rows])
    inward_search = {
        kind: stats([row["perpendicular_deficit_over_physical_bracket_ratio"] for row in positive_inward if row["search_kind"] == kind])
        for kind in ("AXIS", "RAY")
    }
    outward_search = {
        kind: stats([row["perpendicular_penetration_over_physical_bracket_ratio"] for row in outward_rows if row["search_kind"] == kind])
        for kind in ("AXIS", "RAY")
    }
    inward_timestamp_medians = sorted(
        (timestamp, stats([row["perpendicular_deficit_over_physical_bracket_ratio"] for row in positive_inward if row["timestamp"] == timestamp])["median"])
        for timestamp in sorted(centers)
    )
    outward_timestamp_medians = sorted(
        (timestamp, stats([row["perpendicular_penetration_over_physical_bracket_ratio"] for row in outward_rows if row["timestamp"] == timestamp])["median"])
        for timestamp in sorted(centers)
    )
    inward_timestamp_low = min(inward_timestamp_medians, key=lambda item: (item[1], item[0]))
    inward_timestamp_high = max(inward_timestamp_medians, key=lambda item: (item[1], item[0]))
    outward_timestamp_low = min(outward_timestamp_medians, key=lambda item: (item[1], item[0]))
    outward_timestamp_high = max(outward_timestamp_medians, key=lambda item: (item[1], item[0]))

    report = f"""# Nonconvexity resolvability audit (artifact only)

## Safety, frozen inputs, and coordinate contract

- Starting branch: `{SOURCE_BRANCH}`
- Starting HEAD: `{SOURCE_HEAD}`
- Initial status: only `results/dso_vpp_ac_map_pilot/doe_construction_policy_preregistration/`, `scripts/prepare_dso_vpp_doe_construction_policy_preregistration.py`, and `scripts/audit_dso_vpp_doe_geometric_contraction_threshold.py` were untracked; there were no tracked modifications.
- The frozen preregistration manifest passed all {prereg_count} size/SHA-256 checks (manifest SHA-256 `{prereg_manifest_sha}`); the frozen geometric-contraction manifest passed all {prior_count} checks (manifest SHA-256 `{prior_manifest_sha}`).
- Geometry uses absolute physical PCC `(P13,P30)` in kW, `reference_pv_capacity_kw=0`, `Q_PCC=0`, and the timestamp-specific certified center plus sign-specific production scales. Angles are `atan2(normalized P30, normalized P13)` modulo 360 degrees. The historical `P13_command+777.7133428167988 kW` mapping is not applied.
- No AC solve, replay, probing, benchmark, HC/TVPP optimization, monotonicity analysis, mesh/alpha choice, or DOE-policy tuning is performed by this generator.

## A. Polygon kernel and star-shapedness

All {len(kernel_summary)} polygon kernels are nonempty. The certified production center is in the polygon kernel for {kernel_inside_count}/32 timestamps. The all-boundary visibility predicate is true for {sum(row['every_radial_segment_center_to_every_polygon_boundary_point_inside'] for row in kernel_summary)}/32 timestamps. Thus every angular polygon is star-shaped with respect to its production center. This is a geometric statement, not AC-feasibility proof for edges or angular interiors.

Kernel computation uses deterministic intersection of normalized left halfplanes of the CCW polygon edges at {KERNEL_HALFPLANE_TOL_KW:.3g} kW tolerance. Kernel vertices, areas, center locations, and signed/nearest boundary distances are reported in the kernel CSVs.

{format_stats_line('kernel area', kernel_area_stats, 'kW^2')}
{format_stats_line('production-center distance to nearest kernel boundary', kernel_distance_stats, 'kW')}

## Existing 0/1689 outward screen

The direct screen reconstructs {location_counts['INSIDE']} inside, {location_counts['BOUNDARY']} on boundary, and {location_counts['OUTSIDE']} outside. Same-production-ray pairing holds for {same_ray_count}/1689 pairs; the strict structural implication from a selected inward radial vertex and `r_out>r_in` is verified for {automatic_count}/1689 endpoints. Those rows are classified `EXPECTED_FROM_RADIAL_POLYGON_CONSTRUCTION_ON_SAMPLED_RAYS`.

The remaining {1689-automatic_count} rows are retained as direct geometric checks rather than mislabeled as same-ray implications; this includes signed-axis searches whose endpoints are not generally collinear with the certified center. Consequently, the radial subset of the prior screen is structurally expected and is not independent safety evidence. The unresolved risk remains `INTER_RAY_EDGE_AND_ANGULAR_INTERIOR_AC_FEASIBILITY`.

## B. Local concavity

Across {len(concavity_rows)} polygon vertices, the robust CCW orientation classification gives {vertex_counts['CONCAVE']} concave, {vertex_counts['CONVEX']} convex, and {vertex_counts['COLLINEAR']} numerically collinear vertices. The tolerance is `{ORIENTATION_REL_TOL:.3g}*max(1, ||incoming||*||outgoing||)` in kW^2. Every timestamp has at least one concave vertex; per-timestamp counts range from {min(concave_by_time.values())} to {max(concave_by_time.values())}.

{format_stats_line('local neighbor-chord segment depth', local_depth_stats, 'kW')}
{format_stats_line('local depth / paired physical bracket', local_ratio_stats)}
- VMAX local depth: {format_median_max(family_depth['VMAX'], 'kW')}; VMIN local depth: {format_median_max(family_depth['VMIN'], 'kW')}.

The local metric is diagnostic only; the global hull deficits below determine convexification severity.

## C. Convex-hull deficits of inward points

There are {len(positive_inward)}/{len(inward_rows)} inward points with a nonzero hull deficit above the {POSITIVE_DEFICIT_TOL_KW:.3g} kW reporting tolerance.

{format_stats_line('perpendicular hull deficit, positive-deficit points', inward_perp_stats, 'kW')}
{format_stats_line('physical production-ray hull deficit, positive-deficit points', inward_radial_stats, 'kW')}
{format_stats_line('perpendicular deficit / physical bracket', inward_perp_ratio_stats)}
{format_stats_line('radial deficit / signed radial bracket where same-ray denominator is valid', inward_radial_ratio_stats)}
- Axis positive-deficit ratio: {format_median_max(inward_search['AXIS'])}; production-ray positive-deficit ratio: {format_median_max(inward_search['RAY'])}.
- Per-timestamp median perpendicular-deficit/bracket ratio ranges from {inward_timestamp_low[1]:.12g} at `{inward_timestamp_low[0]}` to {inward_timestamp_high[1]:.12g} at `{inward_timestamp_high[0]}`.

No ambiguous nondegenerate ray/hull intersection occurred. The all-point, positive-deficit, timestamp, VMAX/VMIN, primary-class, and ray/axis distributions are in the summary CSV.

## D. Severity of convex-hull outward violations

Exactly {len(outward_rows)} stored outward converged-infeasible endpoints lie strictly inside the inward convex hull, reconciling the frozen comparator.

{format_stats_line('perpendicular penetration', outward_perp_stats, 'kW')}
{format_stats_line('physical production-ray penetration', outward_radial_stats, 'kW')}
{format_stats_line('perpendicular penetration / own physical bracket', outward_perp_ratio_stats)}
{format_stats_line('radial penetration / own signed radial bracket where valid', outward_radial_ratio_stats)}
- VMAX perpendicular penetration: {format_median_max(family_pen['VMAX'], 'kW')}; VMIN perpendicular penetration: {format_median_max(family_pen['VMIN'], 'kW')}.
- Axis violation ratio: {format_median_max(outward_search['AXIS'])}; production-ray violation ratio: {format_median_max(outward_search['RAY'])}.
- Per-timestamp median perpendicular-penetration/bracket ratio ranges from {outward_timestamp_low[1]:.12g} at `{outward_timestamp_low[0]}` to {outward_timestamp_high[1]:.12g} at `{outward_timestamp_high[0]}`.

Physical scale context is timestamp-specific in `physical_scale_context.csv`: signed-axis spans, angular-polygon diameter/area, convex-hull area, and median physical/normalized radii. Dimensionless diameter ratios are secondary; bracket ratios remain primary.

{format_stats_line('timestamp P13 axis span', p13_span_stats, 'kW')}
{format_stats_line('timestamp P30 axis span', p30_span_stats, 'kW')}
{format_stats_line('angular-polygon diameter', diameter_stats, 'kW')}

## Optional uniform convex-hull erosion diagnostic

For each timestamp with an inside outward endpoint, the supremum erosion distance is the maximum inward distance of such endpoints from a hull edge. Strictly greater erosion excludes every stored violation; equality leaves the deepest endpoint on the eroded boundary.

{format_stats_line('required erosion-distance supremum across timestamps', erosion_stats, 'kW')}
{format_stats_line('inward-point retained fraction at erosion supremum', erosion_retention_stats)}
{format_stats_line('hull-area retained fraction at erosion supremum', erosion_area_stats)}

This is a morphological diagnostic, not an adopted DOE policy.

## Interpretation boundary

The report supplies raw physical distances and bracket ratios without inventing a threshold for `COMPARABLE_TO_BOUNDARY_SEARCH_RESOLUTION` versus `RESOLVABLY_LARGER`. The distributions show how many bracket widths convexification adds and how deeply known infeasible endpoints penetrate; they do not choose convex versus piecewise-convex architecture. Kernel/star-shapedness does not resolve inter-ray AC feasibility.

## Outputs and reproducibility contract

`artifact_manifest.csv` records deterministic sizes and SHA-256 hashes for every generated file other than itself plus the generator. The generator accepts `--output`; two clean-location byte comparisons are performed externally during handoff. The frozen 14-entry preregistration and 19-entry geometric-audit manifests are verified before every build and are never rewritten.
"""
    write_text(output / "nonconvexity_resolvability_report.md", report)

    generated = sorted(path for path in output.iterdir() if path.is_file() and path.name != "artifact_manifest.csv")
    manifest_rows = [{
        "path": (CANONICAL_OUTPUT / path.name).as_posix(),
        "bytes": path.stat().st_size,
        "sha256": sha256(path),
    } for path in generated]
    script = root / SCRIPT_PATH
    manifest_rows.append({"path": SCRIPT_PATH.as_posix(), "bytes": script.stat().st_size, "sha256": sha256(script)})
    manifest_rows.sort(key=lambda row: row["path"])
    write_csv(output / "artifact_manifest.csv", manifest_rows)


def main() -> None:
    args = parse_args()
    root = Path(__file__).resolve().parents[1]
    output = args.output if args.output.is_absolute() else root / args.output
    build(root, output)


if __name__ == "__main__":
    main()
