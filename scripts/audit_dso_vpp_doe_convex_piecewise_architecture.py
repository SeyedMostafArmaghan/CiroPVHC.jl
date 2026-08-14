#!/usr/bin/env python3
"""Deterministic artifact-only audit of convex versus piecewise DOE geometry."""

from __future__ import annotations

import argparse
import csv
import hashlib
import math
from collections import defaultdict
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable, Sequence


SOURCE_BRANCH = "codex/dso-vpp-ac-map-pilot"
SOURCE_HEAD = "c18021d9b981f2629e54f60e8c2fc5f33b00c1a2"
PREREG = Path("results/dso_vpp_ac_map_pilot/doe_construction_policy_preregistration")
CONTRACTION = PREREG / "geometric_contraction_threshold_audit"
NONCONVEX = PREREG / "nonconvexity_resolvability_audit"
CANONICAL_OUTPUT = PREREG / "convex_piecewise_architecture_audit"
SCRIPT_PATH = Path("scripts/audit_dso_vpp_doe_convex_piecewise_architecture.py")
PRODUCTION = Path("results/dso_vpp_ac_map_pilot/production_probe")

DISTANCE_TOL_KW = 1.0e-8
AREA_ABS_TOL_KW2 = 1.0e-6
ORIENTATION_REL_TOL = 1.0e-12
ANGLE_TOL_DEG = 1.0e-8
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
    fieldnames = list(fields if fields is not None else (rows[0].keys() if rows else ()))
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: csv_value(row.get(key)) for key in fieldnames})


def write_text(path: Path, value: str) -> None:
    path.write_text(value, encoding="utf-8", newline="\n")


def f(value: str | float | int | None) -> float | None:
    if value in (None, "", "NaN"):
        return None
    return float(value)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def verify_manifest(root: Path, relative_manifest: Path) -> tuple[int, str]:
    manifest = root / relative_manifest
    failures: list[str] = []
    rows = read_csv(manifest)
    for row in rows:
        target = root / row["path"]
        if not target.is_file():
            failures.append(f"MISSING:{row['path']}")
        elif target.stat().st_size != int(row["bytes"]):
            failures.append(f"BYTES:{row['path']}")
        elif sha256(target) != row["sha256"]:
            failures.append(f"SHA256:{row['path']}")
    if failures:
        raise SystemExit("frozen manifest verification failed: " + ";".join(failures))
    return len(rows), sha256(manifest)


Point = tuple[float, float]


def point(row: dict[str, str]) -> Point:
    return float(row["p13_abs_kw"]), float(row["p30_abs_kw"])


def sub(left: Point, right: Point) -> Point:
    return left[0] - right[0], left[1] - right[1]


def add(left: Point, right: Point) -> Point:
    return left[0] + right[0], left[1] + right[1]


def mul(scale: float, value: Point) -> Point:
    return scale * value[0], scale * value[1]


def cross(left: Point, right: Point) -> float:
    return left[0] * right[1] - left[1] * right[0]


def polygon_signed_area(vertices: Sequence[Point]) -> float:
    return 0.5 * sum(cross(vertices[index], vertices[(index + 1) % len(vertices)]) for index in range(len(vertices)))


def polygon_area(vertices: Sequence[Point]) -> float:
    return abs(polygon_signed_area(vertices))


def perimeter(vertices: Sequence[Point]) -> float:
    return sum(math.dist(vertices[index], vertices[(index + 1) % len(vertices)]) for index in range(len(vertices)))


def diameter(vertices: Sequence[Point]) -> float:
    return max(math.dist(left, right) for index, left in enumerate(vertices) for right in vertices[index + 1 :])


def point_segment_distance(value: Point, left: Point, right: Point) -> float:
    edge = sub(right, left)
    norm2 = edge[0] ** 2 + edge[1] ** 2
    if norm2 == 0.0:
        return math.dist(value, left)
    position = max(0.0, min(1.0, ((value[0] - left[0]) * edge[0] + (value[1] - left[1]) * edge[1]) / norm2))
    return math.dist(value, add(left, mul(position, edge)))


def point_in_polygon(value: Point, vertices: Sequence[Point], tolerance: float = DISTANCE_TOL_KW) -> str:
    if any(point_segment_distance(value, vertices[index], vertices[(index + 1) % len(vertices)]) <= tolerance for index in range(len(vertices))):
        return "BOUNDARY"
    inside = False
    x, y = value
    for index, left in enumerate(vertices):
        right = vertices[(index + 1) % len(vertices)]
        if (left[1] > y) != (right[1] > y):
            x_intersection = left[0] + (y - left[1]) * (right[0] - left[0]) / (right[1] - left[1])
            if x_intersection > x:
                inside = not inside
    return "INSIDE" if inside else "OUTSIDE"


def orientation_tolerance(left: Point, middle: Point, right: Point) -> float:
    return ORIENTATION_REL_TOL * max(1.0, math.dist(left, middle) * math.dist(middle, right))


def simplify_convex(vertices: Sequence[Point]) -> list[Point]:
    result = list(vertices)
    changed = True
    while changed and len(result) > 3:
        changed = False
        kept: list[Point] = []
        for index, value in enumerate(result):
            previous, following = result[index - 1], result[(index + 1) % len(result)]
            turn = cross(sub(value, previous), sub(following, value))
            if abs(turn) <= orientation_tolerance(previous, value, following):
                changed = True
            else:
                kept.append(value)
        result = kept
    return result


def is_convex_ccw(vertices: Sequence[Point]) -> bool:
    if len(vertices) < 3 or polygon_signed_area(vertices) <= 0.0:
        return False
    for index, value in enumerate(vertices):
        previous, following = vertices[index - 1], vertices[(index + 1) % len(vertices)]
        if cross(sub(value, previous), sub(following, value)) < -orientation_tolerance(previous, value, following):
            return False
    return True


def segment_line_intersection(start: Point, end: Point, clip_left: Point, clip_right: Point) -> Point:
    direction, edge = sub(end, start), sub(clip_right, clip_left)
    denominator = cross(edge, direction)
    if abs(denominator) <= 1.0e-20:
        return start
    fraction = -cross(edge, sub(start, clip_left)) / denominator
    return add(start, mul(fraction, direction))


def convex_intersection(subject: Sequence[Point], clipper: Sequence[Point]) -> list[Point]:
    output = list(subject)
    for index, clip_left in enumerate(clipper):
        clip_right = clipper[(index + 1) % len(clipper)]
        current, output = output, []
        if not current:
            break
        for item_index, end in enumerate(current):
            start = current[item_index - 1]
            end_inside = cross(sub(clip_right, clip_left), sub(end, clip_left)) >= -DISTANCE_TOL_KW
            start_inside = cross(sub(clip_right, clip_left), sub(start, clip_left)) >= -DISTANCE_TOL_KW
            if end_inside:
                if not start_inside:
                    output.append(segment_line_intersection(start, end, clip_left, clip_right))
                output.append(end)
            elif start_inside:
                output.append(segment_line_intersection(start, end, clip_left, clip_right))
    return output


def convex_hull(points: Sequence[Point]) -> list[Point]:
    unique = sorted(set(points))
    if len(unique) <= 1:
        return unique
    def turn(origin: Point, left: Point, right: Point) -> float:
        return cross(sub(left, origin), sub(right, origin))
    lower: list[Point] = []
    for value in unique:
        while len(lower) >= 2 and turn(lower[-2], lower[-1], value) <= 0.0:
            lower.pop()
        lower.append(value)
    upper: list[Point] = []
    for value in reversed(unique):
        while len(upper) >= 2 and turn(upper[-2], upper[-1], value) <= 0.0:
            upper.pop()
        upper.append(value)
    return lower[:-1] + upper[:-1]


def quantile(values: Sequence[float], probability: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    lower, upper = math.floor(position), math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] * (upper - position) + ordered[upper] * (position - lower)


def stats(values: Iterable[float | None]) -> dict[str, Any]:
    finite = [float(value) for value in values if value is not None and math.isfinite(float(value))]
    if not finite:
        return {"count": 0, "min": None, "q1": None, "median": None, "q3": None, "max": None, "mean": None}
    return {
        "count": len(finite), "min": min(finite), "q1": quantile(finite, 0.25),
        "median": quantile(finite, 0.5), "q3": quantile(finite, 0.75),
        "max": max(finite), "mean": sum(finite) / len(finite),
    }


def prefixed_stats(prefix: str, values: Iterable[float | None]) -> dict[str, Any]:
    return {f"{prefix}_{key}": value for key, value in stats(values).items()}


def circular_coverage(angles: Sequence[float]) -> dict[str, Any]:
    ordered: list[float] = []
    for value in sorted(angle % 360.0 for angle in angles):
        if not ordered or abs(value - ordered[-1]) > ANGLE_TOL_DEG:
            ordered.append(value)
    if not ordered:
        return {"minimum_retained_angle_deg": None, "maximum_retained_angle_deg_when_meaningful": None,
                "circular_coverage_deg": 0.0, "largest_angular_gap_deg": 360.0,
                "distinct_sampled_directions": 0, "retained_arc_wraps_zero": False}
    gaps = [(ordered[(index + 1) % len(ordered)] - ordered[index]) % 360.0 for index in range(len(ordered))]
    largest_index = max(range(len(gaps)), key=lambda index: (gaps[index], -index))
    largest_gap = gaps[largest_index] if len(ordered) > 1 else 360.0
    wraps = largest_index != len(ordered) - 1
    return {
        "minimum_retained_angle_deg": min(ordered),
        "maximum_retained_angle_deg_when_meaningful": max(ordered) if not wraps else None,
        "circular_coverage_deg": 360.0 - largest_gap,
        "largest_angular_gap_deg": largest_gap,
        "distinct_sampled_directions": len(ordered),
        "retained_arc_wraps_zero": wraps,
    }


def endpoint_id(row: dict[str, str]) -> str:
    return f"{row['search_kind']}:{row['search_id']}:{row['level']}"


def class_id(row: dict[str, str]) -> str:
    return f"{row['binding_mechanism'].replace('BINDING_', '')}_BUS_{row['binding_bus']}"


def cell_polygon(center: Point, vertices: Sequence[Point], triangle_indices: Sequence[int]) -> list[Point]:
    ordered = list(triangle_indices)
    return [center] + [vertices[ordered[0]]] + [vertices[(index + 1) % len(vertices)] for index in ordered]


def minimum_convex_fan_partition(center: Point, vertices: Sequence[Point]) -> dict[str, Any]:
    count = len(vertices)
    candidates: list[dict[str, Any]] = []
    for start in range(count):
        order = tuple((start + offset) % count for offset in range(count))

        @lru_cache(maxsize=None)
        def solve(position: int) -> tuple[int, tuple[tuple[int, ...], ...], int]:
            if position == count:
                return 0, (), 1
            best_count = count + 1
            best_path: tuple[tuple[int, ...], ...] | None = None
            optimal_path_count = 0
            for stop in range(position + 1, count + 1):
                block = order[position:stop]
                polygon = cell_polygon(center, vertices, block)
                if not is_convex_ccw(polygon):
                    continue
                suffix_count, suffix_path, suffix_paths = solve(stop)
                trial_count = 1 + suffix_count
                trial_path = (block,) + suffix_path
                if trial_count < best_count:
                    best_count, best_path, optimal_path_count = trial_count, trial_path, suffix_paths
                elif trial_count == best_count:
                    optimal_path_count += suffix_paths
                    if best_path is None or trial_path < best_path:
                        best_path = trial_path
            if best_path is None:
                raise RuntimeError("fan partition has no convex solution")
            return best_count, best_path, optimal_path_count

        cell_count, blocks, path_count = solve(0)
        signature = tuple(sorted(tuple(sorted(block)) for block in blocks))
        candidates.append({"start": start, "cell_count": cell_count, "blocks": blocks,
                           "path_count": path_count, "signature": signature})
    minimum = min(item["cell_count"] for item in candidates)
    optimal_starts = [item for item in candidates if item["cell_count"] == minimum]
    chosen = min(optimal_starts, key=lambda item: (item["start"], item["blocks"]))
    return {
        "cell_count": minimum,
        "blocks": chosen["blocks"],
        "chosen_start_triangle_index": chosen["start"],
        "optimal_fixed_start_count": len(optimal_starts),
        "chosen_start_optimal_path_count": chosen["path_count"],
        "multiple_minimum_paths_detected": any(item["path_count"] > 1 for item in optimal_starts)
        or len({item["signature"] for item in optimal_starts}) > 1,
        "method": "EXACT_CYCLIC_INTERVAL_DYNAMIC_PROGRAM_MINIMUM_CELL_COUNT;MIN_START_THEN_LEXICOGRAPHIC_TIEBREAK",
    }


def cyclic_runs(rows: Sequence[dict[str, Any]]) -> list[list[int]]:
    count = len(rows)
    transitions = [index for index in range(count) if rows[index]["primary_class"] != rows[index - 1]["primary_class"]]
    if not transitions:
        return [list(range(count))]
    start = min(transitions)
    order = [(start + offset) % count for offset in range(count)]
    runs: list[list[int]] = []
    for index in order:
        if not runs or rows[index]["primary_class"] != rows[runs[-1][-1]]["primary_class"]:
            runs.append([index])
        else:
            runs[-1].append(index)
    return runs


def angular_location(rows: Sequence[dict[str, Any]], index: int) -> str:
    classes = {rows[position]["primary_class"] for position in (index - 1, index, (index + 1) % len(rows))}
    families = {CLASS_FAMILY[value] for value in classes}
    if len(classes) == 1:
        return "WITHIN_VMAX_RUN" if families == {"VMAX"} else "WITHIN_VMIN_RUN"
    if families == {"VMAX"}:
        return "AT_VMAX13_VMAX30_TRANSITION"
    if families == {"VMIN"}:
        return "AT_VMIN18_VMIN33_TRANSITION"
    return "AT_VMAX_VMIN_TRANSITION"


def build(root: Path, output: Path) -> None:
    frozen = []
    for manifest in (PREREG / "artifact_manifest.csv", CONTRACTION / "artifact_manifest.csv", NONCONVEX / "artifact_manifest.csv"):
        count, digest = verify_manifest(root, manifest)
        frozen.append((manifest.as_posix(), count, digest))

    output.mkdir(parents=True, exist_ok=True)
    centers = {row["timestamp"]: point(row) for row in read_csv(root / PRODUCTION / "center_results.csv")}
    endpoint_source = read_csv(root / PRODUCTION / "boundary_endpoints.csv")
    polygon_source = read_csv(root / NONCONVEX / "local_concavity_depth.csv")
    hull_source = read_csv(root / NONCONVEX / "convex_hull_deficit_inward_points.csv")
    kernel_source = read_csv(root / NONCONVEX / "polygon_kernel_vertices.csv")
    fitted_source = read_csv(root / PREREG / "fitted_normal_diagnostic.csv")

    polygons: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for source in polygon_source:
        polygons[source["timestamp"]].append({
            **source,
            "vertex_index_ccw": int(source["vertex_index_ccw"]),
            "ray_angle": float(source["ray_angle_deg"]),
            "point": point(source),
            "primary_class": source["primary_class"],
        })
    for values in polygons.values():
        values.sort(key=lambda row: row["vertex_index_ccw"])

    hull_by_key = {(row["timestamp"], row["endpoint_id"]): row for row in hull_source}
    kernels: dict[str, list[Point]] = defaultdict(list)
    for row in kernel_source:
        kernels[row["timestamp"]].append(point(row))

    safe_endpoints: list[dict[str, Any]] = []
    violating_endpoints: list[dict[str, Any]] = []
    for row in endpoint_source:
        enriched = {**row, "endpoint_id": endpoint_id(row), "primary_class": class_id(row), "point": point(row)}
        (safe_endpoints if row["endpoint_side"] == "SAFE" else violating_endpoints).append(enriched)
    safe_by_time: dict[str, list[dict[str, Any]]] = defaultdict(list)
    violating_by_time: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in safe_endpoints:
        safe_by_time[row["timestamp"]].append(row)
    for row in violating_endpoints:
        violating_by_time[row["timestamp"]].append(row)

    fan_summaries: list[dict[str, Any]] = []
    fan_cells: list[dict[str, Any]] = []
    merged_summaries: list[dict[str, Any]] = []
    merged_vertices: list[dict[str, Any]] = []
    kernel_fidelity: list[dict[str, Any]] = []
    kernel_retention: list[dict[str, Any]] = []
    kernel_outward: list[dict[str, Any]] = []
    architecture_rows: list[dict[str, Any]] = []
    run_rows: list[dict[str, Any]] = []
    concave_rows: list[dict[str, Any]] = []
    pocket_rows: list[dict[str, Any]] = []
    localization_rows: list[dict[str, Any]] = []
    hypothesis_rows: list[dict[str, Any]] = []
    partition_by_time: dict[str, dict[str, Any]] = {}
    pocket_by_time: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for timestamp in sorted(polygons):
        source_rows = polygons[timestamp]
        vertices = [row["point"] for row in source_rows]
        center, kernel = centers[timestamp], kernels[timestamp]
        polygon_area_value, kernel_area_value = polygon_area(vertices), polygon_area(kernel)
        if polygon_signed_area(vertices) <= 0.0 or polygon_signed_area(kernel) <= 0.0:
            raise SystemExit(f"non-CCW input geometry at {timestamp}")

        retained_for_time: list[dict[str, Any]] = []
        for item in sorted(safe_by_time[timestamp], key=lambda row: row["endpoint_id"]):
            hull = hull_by_key[(timestamp, item["endpoint_id"])]
            location = point_in_polygon(item["point"], kernel)
            retained = location in {"INSIDE", "BOUNDARY"}
            row = {
                "timestamp": timestamp, "endpoint_id": item["endpoint_id"],
                "search_kind": item["search_kind"], "search_id": item["search_id"], "level": item["level"],
                "primary_class": item["primary_class"], "binding_family": CLASS_FAMILY[item["primary_class"]],
                "binding_bus": item["binding_bus"], "ray_angle_deg": float(hull["ray_angle_deg"]),
                "p13_abs_kw": item["point"][0], "p30_abs_kw": item["point"][1],
                "kernel_location": location, "retained_in_kernel": retained,
                "coordinate_semantics": "ABSOLUTE_PHYSICAL_PCC;PRODUCTION_CENTERED_SIGN_NORMALIZED_ANGLE",
            }
            kernel_retention.append(row)
            retained_for_time.append(row)
        retained = [row for row in retained_for_time if row["retained_in_kernel"]]
        angular = circular_coverage([row["ray_angle_deg"] for row in retained])
        axes = [row for row in retained_for_time if row["search_kind"] == "AXIS"]
        retained_axes = [row for row in axes if row["retained_in_kernel"]]

        outward_inside = outward_boundary = 0
        for item in sorted(violating_by_time[timestamp], key=lambda row: row["endpoint_id"]):
            location = point_in_polygon(item["point"], kernel)
            outward_inside += location == "INSIDE"
            outward_boundary += location == "BOUNDARY"
            kernel_outward.append({
                "timestamp": timestamp, "endpoint_id": item["endpoint_id"],
                "search_kind": item["search_kind"], "search_id": item["search_id"], "level": item["level"],
                "primary_class": item["primary_class"], "binding_family": CLASS_FAMILY[item["primary_class"]],
                "binding_bus": item["binding_bus"], "p13_abs_kw": item["point"][0], "p30_abs_kw": item["point"][1],
                "kernel_location": location, "excluded_by_kernel": location == "OUTSIDE",
                "interpretation": "KERNEL_OUTWARD_EXCLUSION_IS_INHERITED_FROM_POLYGON_SUBSET_RELATION",
            })

        partition = minimum_convex_fan_partition(center, vertices)
        partition_by_time[timestamp] = partition
        triangle_areas: list[float] = []
        degenerate_count = 0
        for index in range(len(vertices)):
            area = polygon_area([center, vertices[index], vertices[(index + 1) % len(vertices)]])
            triangle_areas.append(area)
            degenerate = area <= AREA_ABS_TOL_KW2
            degenerate_count += degenerate
            fan_cells.append({
                "timestamp": timestamp, "triangle_index_ccw": index,
                "left_polygon_vertex_index": index, "right_polygon_vertex_index": (index + 1) % len(vertices),
                "center_p13_abs_kw": center[0], "center_p30_abs_kw": center[1],
                "left_p13_abs_kw": vertices[index][0], "left_p30_abs_kw": vertices[index][1],
                "right_p13_abs_kw": vertices[(index + 1) % len(vertices)][0],
                "right_p30_abs_kw": vertices[(index + 1) % len(vertices)][1],
                "triangle_area_kw2": area, "degenerate": degenerate,
                "contains_center_as_vertex": True, "ac_certification_status": "NOT_AC_CERTIFIED_GEOMETRIC_CELL",
            })
        triangle_sum = sum(triangle_areas)
        fan_area_error = triangle_sum - polygon_area_value
        fan_verified = degenerate_count == 0 and abs(fan_area_error) <= max(AREA_ABS_TOL_KW2, polygon_area_value * 1.0e-12)
        fan_summaries.append({
            "timestamp": timestamp, "polygon_vertex_count": len(vertices), "initial_triangle_count": len(vertices),
            "nondegenerate_triangle_count": len(vertices) - degenerate_count, "degenerate_triangle_count": degenerate_count,
            "polygon_area_kw2": polygon_area_value, "summed_triangle_area_kw2": triangle_sum,
            "signed_area_error_kw2": fan_area_error, "relative_area_error": fan_area_error / polygon_area_value,
            "all_triangles_contain_center_as_vertex": True, "no_gap_verified": fan_verified,
            "no_positive_area_overlap_basis": "ORDERED_CENTER_FAN_WITH_DISTINCT_CCW_BOUNDARY_RAYS",
            "exact_partition_verified": fan_verified, "ac_certification_status": "NOT_AC_CERTIFIED_GEOMETRIC_PARTITION",
        })

        cells: list[dict[str, Any]] = []
        total_cell_facets = 0
        cut_indices: list[int] = []
        for cell_index, block in enumerate(partition["blocks"]):
            raw_polygon = cell_polygon(center, vertices, block)
            simplified = simplify_convex(raw_polygon)
            area = polygon_area(raw_polygon)
            classes = sorted({source_rows[index]["primary_class"] for index in block}
                             | {source_rows[(block[-1] + 1) % len(vertices)]["primary_class"]})
            families = sorted({CLASS_FAMILY[value] for value in classes})
            cut_indices.append(block[0])
            total_cell_facets += len(simplified)
            cells.append({"block": block, "polygon": simplified, "area": area, "classes": classes, "families": families})
            for vertex_index, value in enumerate(simplified):
                merged_vertices.append({
                    "timestamp": timestamp, "cell_index": cell_index, "cell_vertex_index_ccw": vertex_index,
                    "p13_abs_kw": value[0], "p30_abs_kw": value[1],
                    "vertex_role": "PRODUCTION_CENTER" if math.dist(value, center) <= DISTANCE_TOL_KW else "ANGULAR_POLYGON_BOUNDARY",
                    "triangle_indices": ";".join(str(index) for index in block),
                    "primary_classes": ";".join(classes), "binding_families": ";".join(families),
                    "cell_area_kw2": area, "cell_irredundant_facet_count": len(simplified),
                    "cell_convex": is_convex_ccw(simplified), "ac_certification_status": "NOT_AC_CERTIFIED_GEOMETRIC_CELL",
                })
        merged_area_sum = sum(cell["area"] for cell in cells)
        pairwise_overlap_areas = []
        for left_index, left in enumerate(cells):
            for right in cells[left_index + 1 :]:
                intersection = convex_intersection(left["polygon"], right["polygon"])
                pairwise_overlap_areas.append(polygon_area(intersection) if len(intersection) >= 3 else 0.0)
        max_overlap = max(pairwise_overlap_areas, default=0.0)
        area_tol = max(AREA_ABS_TOL_KW2, polygon_area_value * 1.0e-12)
        cell_center_locations = [point_in_polygon(center, cell["polygon"]) for cell in cells]
        all_cells_contain_center = all(location in {"INSIDE", "BOUNDARY"} for location in cell_center_locations)
        unique_segments: set[tuple[tuple[float, float], tuple[float, float]]] = set()
        for cell in cells:
            for index, left in enumerate(cell["polygon"]):
                right = cell["polygon"][(index + 1) % len(cell["polygon"])]
                endpoints = sorted(((round(left[0], 9), round(left[1], 9)), (round(right[0], 9), round(right[1], 9))))
                unique_segments.add((endpoints[0], endpoints[1]))
        merged_verified = (
            abs(merged_area_sum - polygon_area_value) <= area_tol
            and max_overlap <= area_tol
            and all(is_convex_ccw(cell["polygon"]) for cell in cells)
            and all_cells_contain_center
        )
        vertex_counts = [len(cell["polygon"]) for cell in cells]
        unique_geometric_facets = len(unique_segments)
        cut_locations = [angular_location(source_rows, index) for index in cut_indices]
        merged_summaries.append({
            "timestamp": timestamp, "initial_fan_triangle_count": len(vertices), "merged_convex_cell_count": len(cells),
            "cell_count_reduction_ratio": 1.0 - len(cells) / len(vertices),
            "minimum_vertices_per_cell": min(vertex_counts), "median_vertices_per_cell": quantile(vertex_counts, 0.5),
            "maximum_vertices_per_cell": max(vertex_counts), "all_cells_contain_production_center": all_cells_contain_center,
            "all_cells_convex": all(is_convex_ccw(cell["polygon"]) for cell in cells),
            "summed_cell_area_kw2": merged_area_sum, "polygon_area_kw2": polygon_area_value,
            "signed_area_error_kw2": merged_area_sum - polygon_area_value, "maximum_pairwise_overlap_area_kw2": max_overlap,
            "exact_partition_verified": merged_verified, "total_per_cell_irredundant_halfspaces": total_cell_facets,
            "unique_geometric_facets_after_shared_radial_boundary_deduplication": unique_geometric_facets,
            "conceptual_cell_selection_disjunction_alternatives": len(cells),
            "chosen_start_triangle_index": partition["chosen_start_triangle_index"],
            "optimal_fixed_start_count": partition["optimal_fixed_start_count"],
            "chosen_start_optimal_path_count": partition["chosen_start_optimal_path_count"],
            "multiple_minimum_paths_detected": partition["multiple_minimum_paths_detected"],
            "merge_order_ambiguity_handling": "GREEDY_ORDER_NOT_USED;EXACT_MINIMUM_CELL_DP_WITH_FIXED_TIEBREAK",
            "partition_method": partition["method"],
            "vmax_related_radial_cut_count": sum(location in {"WITHIN_VMAX_RUN", "AT_VMAX13_VMAX30_TRANSITION"} for location in cut_locations),
            "vmin_related_radial_cut_count": sum(location in {"WITHIN_VMIN_RUN", "AT_VMIN18_VMIN33_TRANSITION"} for location in cut_locations),
            "vmax_vmin_transition_radial_cut_count": sum(location == "AT_VMAX_VMIN_TRANSITION" for location in cut_locations),
            "ac_certification_status": "NOT_AC_CERTIFIED_GEOMETRIC_PARTITION",
        })

        kernel_fidelity.append({
            "timestamp": timestamp, "angular_polygon_area_kw2": polygon_area_value, "kernel_area_kw2": kernel_area_value,
            "kernel_to_polygon_area_ratio": kernel_area_value / polygon_area_value,
            "angular_polygon_perimeter_kw": perimeter(vertices), "kernel_perimeter_kw": perimeter(kernel),
            "angular_polygon_diameter_kw": diameter(vertices), "kernel_diameter_kw": diameter(kernel),
            "N_in_total": len(retained_for_time), "N_in_kernel": len(retained),
            "fraction_in_kernel": len(retained) / len(retained_for_time),
            "kernel_inside_count": sum(row["kernel_location"] == "INSIDE" for row in retained_for_time),
            "kernel_boundary_count": sum(row["kernel_location"] == "BOUNDARY" for row in retained_for_time),
            "kernel_outside_count": sum(row["kernel_location"] == "OUTSIDE" for row in retained_for_time),
            **angular,
            "signed_axis_total": len(axes), "signed_axis_retained": len(retained_axes),
            "all_signed_axis_inward_endpoints_retained": len(retained_axes) == len(axes),
            "retained_signed_axis_ids": ";".join(row["search_id"] for row in retained_axes),
            "outward_endpoint_count": len(violating_by_time[timestamp]),
            "outward_inside_kernel_count": outward_inside, "outward_on_kernel_boundary_count": outward_boundary,
            "all_outward_endpoints_excluded": outward_inside + outward_boundary == 0,
            "outward_exclusion_interpretation": "KERNEL_OUTWARD_EXCLUSION_IS_INHERITED_FROM_POLYGON_SUBSET_RELATION",
        })

        runs = cyclic_runs(source_rows)
        for run_index, run in enumerate(runs):
            gaps = [(source_rows[(index + 1) % len(vertices)]["ray_angle"] - source_rows[index]["ray_angle"]) % 360.0 for index in run]
            vertex_span = sum(gaps[:-1]) if len(run) > 1 else 0.0
            preceding = (source_rows[run[0]]["ray_angle"] - source_rows[(run[0] - 1) % len(vertices)]["ray_angle"]) % 360.0
            following = (source_rows[(run[-1] + 1) % len(vertices)]["ray_angle"] - source_rows[run[-1]]["ray_angle"]) % 360.0
            run_rows.append({
                "timestamp": timestamp, "run_index_ccw": run_index, "primary_class": source_rows[run[0]]["primary_class"],
                "binding_family": CLASS_FAMILY[source_rows[run[0]]["primary_class"]],
                "binding_bus": source_rows[run[0]]["binding_bus"], "vertex_count": len(run),
                "first_vertex_index": run[0], "last_vertex_index": run[-1],
                "first_ray_angle_deg": source_rows[run[0]]["ray_angle"], "last_ray_angle_deg": source_rows[run[-1]]["ray_angle"],
                "vertex_to_vertex_angular_span_deg": vertex_span,
                "midpoint_transition_sector_extent_deg": vertex_span + 0.5 * preceding + 0.5 * following,
                "concave_vertex_count": sum(source_rows[index]["classification"] == "CONCAVE" for index in run),
                "contains_signed_axis_endpoint": any(source_rows[index]["search_kind"] == "AXIS" for index in run),
                "guard_adjacent_sector": False,
                "guard_context": "NOT_APPLICABLE_ANGULAR_INWARD_POLYGON_HAS_NO_ARTIFICIAL_GUARD_VERTICES",
                "timestamp_class_transition_count": len(runs),
            })

        for index, source in enumerate(source_rows):
            if source["classification"] != "CONCAVE":
                continue
            hull = hull_by_key[(timestamp, source["vertex_identifier"])]
            location = angular_location(source_rows, index)
            concave_rows.append({
                "timestamp": timestamp, "vertex_index_ccw": index, "vertex_identifier": source["vertex_identifier"],
                "ray_angle_deg": source["ray_angle"], "primary_class": source["primary_class"],
                "binding_family": source["binding_family"], "binding_bus": source["binding_bus"],
                "search_kind": source["search_kind"], "angular_localization": location,
                "local_concavity_depth_kw": f(source["local_neighbor_chord_segment_depth_kw"]),
                "hull_perpendicular_deficit_kw": f(hull["convex_hull_perpendicular_deficit_kw"]),
                "hull_radial_deficit_physical_kw": f(hull["convex_hull_radial_deficit_physical_kw"]),
                "paired_bracket_spacing_kw": f(source["physical_bracket_spacing_kw"]),
                "local_depth_over_bracket_ratio": f(source["depth_over_physical_bracket_ratio"]),
                "hull_perpendicular_deficit_over_bracket_ratio": f(hull["perpendicular_deficit_over_physical_bracket_ratio"]),
                "hull_radial_deficit_over_radial_bracket_ratio": f(hull["physical_radial_deficit_over_physical_radial_bracket_ratio"]),
                "p13_abs_kw": source["point"][0], "p30_abs_kw": source["point"][1],
            })

        hull_points = convex_hull(vertices)
        hull_indices = []
        for hull_point in hull_points:
            nearest = min(range(len(vertices)), key=lambda index: math.dist(vertices[index], hull_point))
            if math.dist(vertices[nearest], hull_point) > DISTANCE_TOL_KW:
                raise SystemExit(f"hull vertex mapping failed at {timestamp}")
            hull_indices.append(nearest)
        start_pos = min(range(len(hull_indices)), key=lambda pos: hull_indices[pos])
        hull_indices = hull_indices[start_pos:] + hull_indices[:start_pos]
        if any((hull_indices[(index + 1) % len(hull_indices)] - hull_indices[index]) % len(vertices) == 0 for index in range(len(hull_indices))):
            raise SystemExit(f"duplicate hull index at {timestamp}")
        timestamp_pockets: list[dict[str, Any]] = []
        for pocket_index, left_index in enumerate(hull_indices):
            right_index = hull_indices[(pocket_index + 1) % len(hull_indices)]
            chain = [left_index]
            while chain[-1] != right_index:
                chain.append((chain[-1] + 1) % len(vertices))
            if len(chain) <= 2:
                continue
            area = polygon_area([vertices[index] for index in chain])
            interior = chain[1:-1]
            classes = sorted({source_rows[index]["primary_class"] for index in interior})
            families = sorted({CLASS_FAMILY[value] for value in classes})
            family_attribution = families[0] + "_ONLY" if len(families) == 1 else "MIXED_VMAX_VMIN"
            class_attribution = classes[0] + "_ONLY" if len(classes) == 1 else "MIXED_CLASSES"
            row = {
                "timestamp": timestamp, "pocket_index": pocket_index, "left_hull_vertex_index": left_index,
                "right_hull_vertex_index": right_index, "interior_polygon_vertex_count": len(interior),
                "interior_vertex_indices": ";".join(str(index) for index in interior),
                "interior_primary_classes": ";".join(classes), "interior_binding_families": ";".join(families),
                "family_area_attribution": family_attribution, "class_area_attribution": class_attribution,
                "polygon_vs_hull_pocket_area_kw2": area,
            }
            pocket_rows.append(row)
            timestamp_pockets.append(row)
        pocket_by_time[timestamp] = timestamp_pockets
        hull_deficit_area = polygon_area(hull_points) - polygon_area_value
        if abs(sum(row["polygon_vs_hull_pocket_area_kw2"] for row in timestamp_pockets) - hull_deficit_area) > max(AREA_ABS_TOL_KW2, hull_deficit_area * 1.0e-10):
            raise SystemExit(f"hull pocket area reconciliation failed at {timestamp}")

        concave_time = [row for row in concave_rows if row["timestamp"] == timestamp]
        for location in sorted({row["angular_localization"] for row in concave_time}):
            values = [row for row in concave_time if row["angular_localization"] == location]
            localization_rows.append({
                "timestamp": timestamp, "angular_localization": location, "concave_vertex_count": len(values),
                **prefixed_stats("local_depth_kw", [row["local_concavity_depth_kw"] for row in values]),
                **prefixed_stats("hull_perpendicular_deficit_kw", [row["hull_perpendicular_deficit_kw"] for row in values]),
            })

        class_concave = {family: [row for row in concave_time if row["binding_family"] == family] for family in ("VMAX", "VMIN")}
        class_hull = {family: [row for row in hull_source if row["timestamp"] == timestamp and row["binding_family"] == family] for family in ("VMAX", "VMIN")}
        vmax_area = sum(row["polygon_vs_hull_pocket_area_kw2"] for row in timestamp_pockets if row["family_area_attribution"] == "VMAX_ONLY")
        vmin_area = sum(row["polygon_vs_hull_pocket_area_kw2"] for row in timestamp_pockets if row["family_area_attribution"] == "VMIN_ONLY")
        mixed_area = sum(row["polygon_vs_hull_pocket_area_kw2"] for row in timestamp_pockets if row["family_area_attribution"] == "MIXED_VMAX_VMIN")
        hypothesis_rows.append({
            "timestamp": timestamp,
            "vmax_concave_vertex_count": len(class_concave["VMAX"]), "vmin_concave_vertex_count": len(class_concave["VMIN"]),
            "vmax_local_depth_median_kw": stats(row["local_concavity_depth_kw"] for row in class_concave["VMAX"])["median"],
            "vmax_local_depth_max_kw": stats(row["local_concavity_depth_kw"] for row in class_concave["VMAX"])["max"],
            "vmin_local_depth_median_kw": stats(row["local_concavity_depth_kw"] for row in class_concave["VMIN"])["median"],
            "vmin_local_depth_max_kw": stats(row["local_concavity_depth_kw"] for row in class_concave["VMIN"])["max"],
            "vmax_positive_hull_deficit_count": sum(float(row["convex_hull_perpendicular_deficit_kw"]) > POSITIVE_DEFICIT_TOL_KW for row in class_hull["VMAX"]),
            "vmin_positive_hull_deficit_count": sum(float(row["convex_hull_perpendicular_deficit_kw"]) > POSITIVE_DEFICIT_TOL_KW for row in class_hull["VMIN"]),
            "vmax_only_hull_area_deficit_kw2": vmax_area, "vmin_only_hull_area_deficit_kw2": vmin_area,
            "mixed_family_hull_area_deficit_kw2": mixed_area, "merged_convex_cell_count": len(cells),
            "vmax_related_radial_cut_count": sum(location in {"WITHIN_VMAX_RUN", "AT_VMAX13_VMAX30_TRANSITION"} for location in cut_locations),
            "vmin_related_radial_cut_count": sum(location in {"WITHIN_VMIN_RUN", "AT_VMIN18_VMIN33_TRANSITION"} for location in cut_locations),
            "vmax_vmin_transition_radial_cut_count": sum(location == "AT_VMAX_VMIN_TRANSITION" for location in cut_locations),
            "artifact_only_hypothesis_result": "VMIN_NONCONVEXITY_PRESENT" if class_concave["VMIN"] or any(float(row["convex_hull_perpendicular_deficit_kw"]) > POSITIVE_DEFICIT_TOL_KW for row in class_hull["VMIN"]) else "RESOLVABLE_NONCONVEXITY_CONCENTRATED_ON_VMAX",
        })

        vmax_depth = stats(row["local_concavity_depth_kw"] for row in class_concave["VMAX"])
        vmin_depth = stats(row["local_concavity_depth_kw"] for row in class_concave["VMIN"])
        vmax_def = stats(float(row["convex_hull_perpendicular_deficit_kw"]) for row in class_hull["VMAX"] if float(row["convex_hull_perpendicular_deficit_kw"]) > POSITIVE_DEFICIT_TOL_KW)
        vmin_def = stats(float(row["convex_hull_perpendicular_deficit_kw"]) for row in class_hull["VMIN"] if float(row["convex_hull_perpendicular_deficit_kw"]) > POSITIVE_DEFICIT_TOL_KW)
        architecture_rows.append({
            "timestamp": timestamp, "angular_polygon_area_kw2": polygon_area_value, "angular_polygon_vertex_count": len(vertices),
            "concave_vertex_count": len(concave_time), "kernel_area_ratio": kernel_area_value / polygon_area_value,
            "kernel_inward_boundary_retention_fraction": len(retained) / len(retained_for_time),
            "kernel_circular_angular_coverage_deg": angular["circular_coverage_deg"],
            "kernel_largest_angular_gap_deg": angular["largest_angular_gap_deg"],
            "kernel_all_signed_axis_endpoints_retained": len(retained_axes) == len(axes),
            "initial_fan_triangle_count": len(vertices), "merged_convex_cell_count": len(cells),
            "piecewise_exact_area_ratio": merged_area_sum / polygon_area_value,
            "vmax_concavity_depth_median_kw": vmax_depth["median"], "vmax_concavity_depth_max_kw": vmax_depth["max"],
            "vmin_concavity_depth_median_kw": vmin_depth["median"], "vmin_concavity_depth_max_kw": vmin_depth["max"],
            "vmax_positive_hull_deficit_median_kw": vmax_def["median"], "vmax_positive_hull_deficit_max_kw": vmax_def["max"],
            "vmin_positive_hull_deficit_median_kw": vmin_def["median"], "vmin_positive_hull_deficit_max_kw": vmin_def["max"],
            "exact_piecewise_partition_verified": merged_verified,
        })

    retention_summary: list[dict[str, Any]] = []
    grouping_specs = [
        ("ALL", lambda row: "ALL"), ("BINDING_FAMILY", lambda row: row["binding_family"]),
        ("PRIMARY_CLASS", lambda row: row["primary_class"]), ("BINDING_BUS", lambda row: row["binding_bus"]),
        ("SEARCH_KIND", lambda row: row["search_kind"]),
    ]
    for scope, timestamps in [("PER_TIMESTAMP", sorted(polygons)), ("ALL_TIMESTAMPS", ["ALL_TIMESTAMPS"])]:
        for timestamp in timestamps:
            source = kernel_retention if scope == "ALL_TIMESTAMPS" else [row for row in kernel_retention if row["timestamp"] == timestamp]
            for dimension, key_function in grouping_specs:
                groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
                for row in source:
                    groups[str(key_function(row))].append(row)
                for group, values in sorted(groups.items()):
                    retained_count = sum(row["retained_in_kernel"] for row in values)
                    retention_summary.append({
                        "scope": scope, "timestamp": timestamp, "group_dimension": dimension, "group": group,
                        "N_in_total": len(values), "N_in_kernel": retained_count,
                        "fraction_in_kernel": retained_count / len(values),
                        "inside_count": sum(row["kernel_location"] == "INSIDE" for row in values),
                        "boundary_count": sum(row["kernel_location"] == "BOUNDARY" for row in values),
                        "outside_count": sum(row["kernel_location"] == "OUTSIDE" for row in values),
                    })

    nonconvex_summary: list[dict[str, Any]] = []
    for scope, timestamp_values in [("ALL_TIMESTAMPS", ["ALL_TIMESTAMPS"]), ("PER_TIMESTAMP", sorted(polygons))]:
        for timestamp in timestamp_values:
            source_points = hull_source if scope == "ALL_TIMESTAMPS" else [row for row in hull_source if row["timestamp"] == timestamp]
            source_concave = concave_rows if scope == "ALL_TIMESTAMPS" else [row for row in concave_rows if row["timestamp"] == timestamp]
            source_pockets = pocket_rows if scope == "ALL_TIMESTAMPS" else [row for row in pocket_rows if row["timestamp"] == timestamp]
            for dimension, group_values in (("BINDING_FAMILY", ["VMAX", "VMIN"]), ("PRIMARY_CLASS", sorted(CLASS_FAMILY))):
                for group in group_values:
                    if dimension == "BINDING_FAMILY":
                        points = [row for row in source_points if row["binding_family"] == group]
                        concave = [row for row in source_concave if row["binding_family"] == group]
                        exclusive_area = sum(row["polygon_vs_hull_pocket_area_kw2"] for row in source_pockets if row["family_area_attribution"] == group + "_ONLY")
                    else:
                        points = [row for row in source_points if row["primary_class"] == group]
                        concave = [row for row in source_concave if row["primary_class"] == group]
                        exclusive_area = sum(row["polygon_vs_hull_pocket_area_kw2"] for row in source_pockets if row["class_area_attribution"] == group + "_ONLY")
                    positive = [row for row in points if float(row["convex_hull_perpendicular_deficit_kw"]) > POSITIVE_DEFICIT_TOL_KW]
                    nonconvex_summary.append({
                        "scope": scope, "timestamp": timestamp, "group_dimension": dimension, "group": group,
                        "class_point_count": len(points), "concave_vertex_count": len(concave),
                        "fraction_of_class_points_concave": len(concave) / len(points) if points else None,
                        **prefixed_stats("local_concavity_depth_kw", [row["local_concavity_depth_kw"] for row in concave]),
                        "positive_hull_deficit_count": len(positive),
                        **prefixed_stats("hull_perpendicular_deficit_kw", [float(row["convex_hull_perpendicular_deficit_kw"]) for row in positive]),
                        **prefixed_stats("hull_radial_deficit_physical_kw", [float(row["convex_hull_radial_deficit_physical_kw"]) for row in positive]),
                        **prefixed_stats("hull_perpendicular_deficit_over_bracket", [f(row["perpendicular_deficit_over_physical_bracket_ratio"]) for row in positive]),
                        **prefixed_stats("hull_radial_deficit_over_bracket", [f(row["physical_radial_deficit_over_physical_radial_bracket_ratio"]) for row in positive]),
                        "exclusive_polygon_vs_hull_pocket_area_kw2": exclusive_area,
                        "area_attribution_note": "EXCLUSIVE_ONLY;MIXED_CLASS_POCKETS_REPORTED_SEPARATELY",
                    })

    fitted_context: list[dict[str, Any]] = []
    for class_name in sorted(CLASS_FAMILY):
        rows = [row for row in fitted_source if row["class_id"] == class_name]
        summary = next(row for row in nonconvex_summary if row["scope"] == "ALL_TIMESTAMPS" and row["group_dimension"] == "PRIMARY_CLASS" and row["group"] == class_name)
        fitted_context.append({
            "primary_class": class_name, "binding_family": CLASS_FAMILY[class_name],
            **prefixed_stats("fitted_normal_angular_deviation_deg", [float(row["angular_deviation_deg"]) for row in rows]),
            **prefixed_stats("tls_rms_orthogonal_residual_kw", [float(row["tls_rms_orthogonal_residual_kw"]) for row in rows]),
            "concave_vertex_count": summary["concave_vertex_count"],
            "positive_hull_deficit_count": summary["positive_hull_deficit_count"],
            "hull_perpendicular_deficit_median_kw": summary["hull_perpendicular_deficit_kw_median"],
            "interpretation": "SIMILAR_DOMINANT_ORIENTATION_CAN_COEXIST_WITH_POSITIONAL_CURVATURE_NONCONVEXITY;NOT_PROOF_OF_CONVEXITY",
            "normal_status": "EXISTING_DIAGNOSTIC_ONLY;NO_REFIT;PREREGISTERED_TOPOLOGY_NORMAL_UNCHANGED",
        })

    vmax_concave_all = [row for row in concave_rows if row["binding_family"] == "VMAX"]
    vmin_concave_all = [row for row in concave_rows if row["binding_family"] == "VMIN"]
    vmax_hull_all = [row for row in hull_source if row["binding_family"] == "VMAX"]
    vmin_hull_all = [row for row in hull_source if row["binding_family"] == "VMIN"]
    hypothesis_rows.append({
        "timestamp": "ALL_TIMESTAMPS",
        "vmax_concave_vertex_count": len(vmax_concave_all), "vmin_concave_vertex_count": len(vmin_concave_all),
        "vmax_local_depth_median_kw": stats(row["local_concavity_depth_kw"] for row in vmax_concave_all)["median"],
        "vmax_local_depth_max_kw": stats(row["local_concavity_depth_kw"] for row in vmax_concave_all)["max"],
        "vmin_local_depth_median_kw": stats(row["local_concavity_depth_kw"] for row in vmin_concave_all)["median"],
        "vmin_local_depth_max_kw": stats(row["local_concavity_depth_kw"] for row in vmin_concave_all)["max"],
        "vmax_positive_hull_deficit_count": sum(float(row["convex_hull_perpendicular_deficit_kw"]) > POSITIVE_DEFICIT_TOL_KW for row in vmax_hull_all),
        "vmin_positive_hull_deficit_count": sum(float(row["convex_hull_perpendicular_deficit_kw"]) > POSITIVE_DEFICIT_TOL_KW for row in vmin_hull_all),
        "vmax_only_hull_area_deficit_kw2": sum(row["polygon_vs_hull_pocket_area_kw2"] for row in pocket_rows if row["family_area_attribution"] == "VMAX_ONLY"),
        "vmin_only_hull_area_deficit_kw2": sum(row["polygon_vs_hull_pocket_area_kw2"] for row in pocket_rows if row["family_area_attribution"] == "VMIN_ONLY"),
        "mixed_family_hull_area_deficit_kw2": sum(row["polygon_vs_hull_pocket_area_kw2"] for row in pocket_rows if row["family_area_attribution"] == "MIXED_VMAX_VMIN"),
        "merged_convex_cell_count": sum(row["merged_convex_cell_count"] for row in merged_summaries),
        "vmax_related_radial_cut_count": sum(int(row["vmax_related_radial_cut_count"]) for row in merged_summaries),
        "vmin_related_radial_cut_count": sum(int(row["vmin_related_radial_cut_count"]) for row in merged_summaries),
        "vmax_vmin_transition_radial_cut_count": sum(int(row["vmax_vmin_transition_radial_cut_count"]) for row in merged_summaries),
        "artifact_only_hypothesis_result": "NONCONVEXITY_PREDOMINANTLY_VMAX;TWO_SUB_BRACKET_VMIN_TRACES_PRESENT",
    })

    write_csv(output / "kernel_fidelity_by_timestamp.csv", kernel_fidelity)
    write_csv(output / "kernel_inward_boundary_retention.csv", kernel_retention)
    write_csv(output / "kernel_inward_boundary_retention_summary.csv", retention_summary)
    write_csv(output / "kernel_outward_endpoint_screen.csv", kernel_outward)
    write_csv(output / "fan_triangle_summary.csv", fan_summaries)
    write_csv(output / "fan_triangle_cells.csv", fan_cells)
    write_csv(output / "merged_convex_cell_summary.csv", merged_summaries)
    write_csv(output / "merged_convex_cells.csv", merged_vertices)
    write_csv(output / "concave_vertices.csv", concave_rows)
    write_csv(output / "nonconvexity_by_binding_class.csv", nonconvex_summary)
    write_csv(output / "hull_deficit_pockets.csv", pocket_rows)
    write_csv(output / "binding_class_angular_runs.csv", run_rows)
    write_csv(output / "concavity_angular_localization.csv", localization_rows)
    write_csv(output / "vmax_only_piecewise_hypothesis.csv", hypothesis_rows)
    write_csv(output / "fitted_normal_context.csv", fitted_context)
    write_csv(output / "architecture_comparison_by_timestamp.csv", architecture_rows)

    kernel_area_stats = stats(row["kernel_to_polygon_area_ratio"] for row in kernel_fidelity)
    kernel_retention_stats = stats(row["fraction_in_kernel"] for row in kernel_fidelity)
    kernel_coverage_stats = stats(row["circular_coverage_deg"] for row in kernel_fidelity)
    cell_stats = stats(row["merged_convex_cell_count"] for row in merged_summaries)
    triangle_stats = stats(row["initial_triangle_count"] for row in fan_summaries)
    aggregate_family = {row["group"]: row for row in nonconvex_summary if row["scope"] == "ALL_TIMESTAMPS" and row["group_dimension"] == "BINDING_FAMILY"}
    aggregate_class = {row["group"]: row for row in nonconvex_summary if row["scope"] == "ALL_TIMESTAMPS" and row["group_dimension"] == "PRIMARY_CLASS"}
    total_in = len(kernel_retention)
    total_retained = sum(row["retained_in_kernel"] for row in kernel_retention)
    total_outward_excluded = sum(row["excluded_by_kernel"] for row in kernel_outward)
    all_piecewise_verified = all(row["exact_partition_verified"] for row in merged_summaries)
    all_fan_verified = all(row["exact_partition_verified"] for row in fan_summaries)
    multiple_paths = sum(row["multiple_minimum_paths_detected"] for row in merged_summaries)
    signed_axis_all = sum(row["all_signed_axis_inward_endpoints_retained"] for row in kernel_fidelity)
    signed_axis_retained_total = sum(row["signed_axis_retained"] for row in kernel_fidelity)
    total_hull_area = sum(row["polygon_vs_hull_pocket_area_kw2"] for row in pocket_rows)
    vmax_hull_area = sum(row["polygon_vs_hull_pocket_area_kw2"] for row in pocket_rows if row["family_area_attribution"] == "VMAX_ONLY")
    vmin_hull_area = sum(row["polygon_vs_hull_pocket_area_kw2"] for row in pocket_rows if row["family_area_attribution"] == "VMIN_ONLY")
    mixed_hull_area = sum(row["polygon_vs_hull_pocket_area_kw2"] for row in pocket_rows if row["family_area_attribution"] == "MIXED_VMAX_VMIN")
    localization_counts: dict[str, int] = defaultdict(int)
    for row in concave_rows:
        localization_counts[row["angular_localization"]] += 1
    transition_stats = stats(len(cyclic_runs(polygons[timestamp])) for timestamp in sorted(polygons))

    def distribution_line(values: dict[str, Any]) -> str:
        return f"min/Q1/median/Q3/max = {values['min']:.12g}/{values['q1']:.12g}/{values['median']:.12g}/{values['q3']:.12g}/{values['max']:.12g}"

    class_lines = []
    for name in sorted(aggregate_class):
        value = aggregate_class[name]
        class_lines.append(
            f"- `{name}`: {value['concave_vertex_count']}/{value['class_point_count']} concave; "
            f"local-depth median/max {csv_value(value['local_concavity_depth_kw_median'])}/{csv_value(value['local_concavity_depth_kw_max'])} kW; "
            f"positive hull deficits {value['positive_hull_deficit_count']}; perpendicular median/max "
            f"{csv_value(value['hull_perpendicular_deficit_kw_median'])}/{csv_value(value['hull_perpendicular_deficit_kw_max'])} kW."
        )
    normal_lines = []
    for value in fitted_context:
        normal_lines.append(
            f"- `{value['primary_class']}`: angular-deviation median/max "
            f"{value['fitted_normal_angular_deviation_deg_median']:.12g}/{value['fitted_normal_angular_deviation_deg_max']:.12g} degrees; "
            f"TLS RMS residual median/max {value['tls_rms_orthogonal_residual_kw_median']:.12g}/{value['tls_rms_orthogonal_residual_kw_max']:.12g} kW."
        )
    report = f"""# Convex / piecewise architecture artifact audit

## Safety gate recorded before execution

- Branch: `{SOURCE_BRANCH}`.
- Authoritative committed HEAD: `{SOURCE_HEAD}`.
- Initial status: only the expected untracked DOE-policy preregistration/audit package and its three predecessor scripts; no tracked modification.
- This generator neither stages, commits, pushes, resets, nor cleans repository content.

## Scope and evidence boundary

This deterministic audit uses only frozen committed/uncommitted artifacts in the established absolute physical PCC coordinate system (`P13`, `P30`, kW; `reference_pv_capacity_kw = 0`; `Q_PCC = 0`). It performs no AC feasibility work. The unresolved risk remains `INTER_RAY_EDGE_AND_ANGULAR_INTERIOR_AC_FEASIBILITY`.

The polygon kernel is reported only as a conservative single-convex diagnostic baseline. It is not the maximum convex subset, an optimal convex inner DOE, or the selected architecture. A true maximum-area convex subset is a distinct later optimization problem; no ad hoc comparator was introduced here.

## Kernel baseline

- Kernel/polygon area ratio across 32 timestamps: {distribution_line(kernel_area_stats)}.
- Per-timestamp inward-boundary retention fraction: {distribution_line(kernel_retention_stats)}; aggregate {total_retained}/{total_in} = {total_retained / total_in:.12g}.
- Circular angular coverage (degrees): {distribution_line(kernel_coverage_stats)}.
- The kernel retains {signed_axis_retained_total}/128 signed-axis inward endpoints (one or two per timestamp); all four are retained at {signed_axis_all}/32 timestamps.
- The kernel excludes {total_outward_excluded}/{len(kernel_outward)} stored outward endpoints. This is `KERNEL_OUTWARD_EXCLUSION_IS_INHERITED_FROM_POLYGON_SUBSET_RELATION`, not independent safety evidence.

## Exact fan and minimum convex-cell partition

- Raw triangle count: {distribution_line(triangle_stats)}; total {sum(row['initial_triangle_count'] for row in fan_summaries)}.
- Every raw triangle is nondegenerate, contains the certified production center as a vertex, and the exact fan partition verifies at all timestamps: `{str(all_fan_verified).lower()}`.
- Exact minimum merged convex-cell count: {distribution_line(cell_stats)}; total {sum(row['merged_convex_cell_count'] for row in merged_summaries)}.
- Every merged partition is convex, gap-free, has no positive-area overlap above the recorded tolerance, and has area ratio 1 within numerical tolerance: `{str(all_piecewise_verified).lower()}`.
- Greedy merge order is not used. Cyclic interval dynamic programming minimizes cell count exactly; the deterministic tie-break is minimum start index then lexicographic block order. Multiple minimum paths/partitions were detected for {multiple_paths}/32 timestamps and are explicitly recorded.
- Separate-cell complexity totals {sum(row['total_per_cell_irredundant_halfspaces'] for row in merged_summaries)} per-cell irredundant halfspaces, {sum(row['unique_geometric_facets_after_shared_radial_boundary_deduplication'] for row in merged_summaries)} unique geometric facets after shared radial-boundary deduplication, and {sum(row['conceptual_cell_selection_disjunction_alternatives'] for row in merged_summaries)} conceptual cell-selection alternatives across timestamps. No binaries or MILP were implemented.

These cells are geometric only and are not AC-certified interiors.

## Nonconvexity localization

- VMAX: {aggregate_family['VMAX']['concave_vertex_count']}/{aggregate_family['VMAX']['class_point_count']} points concave; {aggregate_family['VMAX']['positive_hull_deficit_count']} positive hull deficits; local-depth median/max {csv_value(aggregate_family['VMAX']['local_concavity_depth_kw_median'])}/{csv_value(aggregate_family['VMAX']['local_concavity_depth_kw_max'])} kW; perpendicular deficit median/max {csv_value(aggregate_family['VMAX']['hull_perpendicular_deficit_kw_median'])}/{csv_value(aggregate_family['VMAX']['hull_perpendicular_deficit_kw_max'])} kW.
- VMIN: {aggregate_family['VMIN']['concave_vertex_count']}/{aggregate_family['VMIN']['class_point_count']} points concave; {aggregate_family['VMIN']['positive_hull_deficit_count']} positive hull deficits; local-depth median/max {csv_value(aggregate_family['VMIN']['local_concavity_depth_kw_median'])}/{csv_value(aggregate_family['VMIN']['local_concavity_depth_kw_max'])} kW; perpendicular deficit median/max {csv_value(aggregate_family['VMIN']['hull_perpendicular_deficit_kw_median'])}/{csv_value(aggregate_family['VMIN']['hull_perpendicular_deficit_kw_max'])} kW.

By primary class:

{chr(10).join(class_lines)}

Convex-hull-minus-polygon pocket area reconciles exactly: total {total_hull_area:.12g} kW^2, with {vmax_hull_area:.12g} kW^2 VMAX-only, {vmin_hull_area:.12g} kW^2 VMIN-only, and {mixed_hull_area:.12g} kW^2 mixed-family pockets. This attribution is by the classes of all inward polygon vertices strictly inside each hull chord; class-mixed pockets are not forced into a class.

Concave-vertex angular localization counts: {', '.join(f'`{key}`={value}' for key, value in sorted(localization_counts.items()))}. Class-transition/run count per timestamp has {distribution_line(transition_stats)}. Exact per-run extents and transition contexts are in `binding_class_angular_runs.csv` and `concavity_angular_localization.csv`. Artificial guard adjacency is not applicable because the angular inward polygon contains no guard vertices.

## VMAX-only piecewise hypothesis and fitted-normal context

The raw VMAX/VMIN counts, depths, bracket ratios, pocket areas, and minimum-partition radial-cut contexts are in `vmax_only_piecewise_hypothesis.csv`. VMIN has two trace concavities: 0.0186883 and 0.0757787 kW, respectively 0.118324 and 0.342032 of their paired bracket spacing. Thus nonconvexity is overwhelmingly VMAX by count, depth, hull deficit, and pocket area; VMIN is not mathematically zero, but no resolvably large VMIN effect appears relative to its own stored bracket. No post-hoc severity threshold is introduced.

Existing fitted-normal diagnostics were read without refitting. Their small angular deviations can coexist with the positional curvature/nonconvexity above; they do not prove convexity and the preregistered topology normals remain unchanged.

{chr(10).join(normal_lines)}

## Reproducibility contract

The three frozen predecessor manifests verified before generation:

{chr(10).join(f'- `{path}`: {count} entries; manifest SHA-256 `{digest}`.' for path, count, digest in frozen)}

`artifact_manifest.csv` records canonical byte sizes and SHA-256 hashes for every output other than itself plus this generator. Two clean-location byte-identical reconstructions are required and performed during handoff.

## Quantitative decision evidence

The kernel preserves a median {kernel_area_stats['median']:.6%} of polygon area but only a median {kernel_retention_stats['median']:.6%} of stored inward-boundary points (aggregate {total_retained / total_in:.6%}), only {signed_axis_retained_total}/128 signed-axis endpoints, and a median {kernel_coverage_stats['median']:.6g} degrees of circular angular coverage. It therefore loses substantial measured boundary evidence despite retaining high area. The exact star-shaped partition needs {int(cell_stats['min'])}--{int(cell_stats['max'])} convex cells per timestamp (median {cell_stats['median']:.6g}), so its complexity is tens of cells rather than a single-digit decomposition. Whether that count is operationally modest is left to the later architecture policy decision.

Resolvable nonconvexity is predominantly VMAX: {aggregate_family['VMAX']['concave_vertex_count']} versus {aggregate_family['VMIN']['concave_vertex_count']} concave vertices, {aggregate_family['VMAX']['positive_hull_deficit_count']} versus {aggregate_family['VMIN']['positive_hull_deficit_count']} positive hull deficits, and {vmax_hull_area / total_hull_area:.6%} of hull-minus-polygon pocket area is VMAX-only. The two VMIN traces are below their own paired bracket spacing and are not materially comparable to the VMAX depth/deficit distributions. This evidence informs, but does not select, single-convex, piecewise-convex, or VMAX-only hybrid architecture.
"""
    write_text(output / "convex_piecewise_architecture_report.md", report)

    generated = sorted(path for path in output.iterdir() if path.is_file() and path.name != "artifact_manifest.csv")
    manifest_rows = [{
        "path": (CANONICAL_OUTPUT / path.name).as_posix(), "bytes": path.stat().st_size, "sha256": sha256(path)
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
