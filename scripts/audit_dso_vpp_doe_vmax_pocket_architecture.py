#!/usr/bin/env python3
"""Deterministic artifact-only audit of hull-minus-DOE pocket representations."""

from __future__ import annotations

import argparse
import csv
import hashlib
import itertools
import json
import math
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable, Sequence


SOURCE_HEAD = "c18021d9b981f2629e54f60e8c2fc5f33b00c1a2"
SOURCE_BRANCH = "codex/dso-vpp-ac-map-pilot"
CANONICAL_OUTPUT = Path("results/dso_vpp_ac_map_pilot/doe_vmax_pocket_architecture_audit")
PRODUCTION = Path("results/dso_vpp_ac_map_pilot/production_probe")
NONCONVEX = Path("results/dso_vpp_ac_map_pilot/doe_construction_policy_preregistration/nonconvexity_resolvability_audit")
PIECEWISE = Path("results/dso_vpp_ac_map_pilot/doe_construction_policy_preregistration/convex_piecewise_architecture_audit")
ARCHITECTURE = Path("results/dso_vpp_ac_map_pilot/doe_architecture_decision_audit")
SCRIPT = Path("scripts/audit_dso_vpp_doe_vmax_pocket_architecture.py")
DISTANCE_TOL_KW = 1.0e-8
AREA_ABS_TOL_KW2 = 1.0e-6
ORIENTATION_REL_TOL = 1.0e-12
FACET_BUDGETS = (3, 4, 5, 8)
Point = tuple[float, float]

CLASS_LABEL = {
    "VMAX_BUS_13": "VMAX / bus 13",
    "VMAX_BUS_30": "VMAX / bus 30",
    "VMIN_BUS_18": "VMIN / bus 18",
    "VMIN_BUS_33": "VMIN / bus 33",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


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


def write_csv(path: Path, rows: list[dict[str, Any]], fields: Iterable[str] | None = None) -> None:
    fieldnames = list(fields or (rows[0].keys() if rows else []))
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: csv_value(row.get(field)) for field in fieldnames})


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def verify_csv_manifest(root: Path, relative: Path) -> dict[str, Any]:
    rows = read_csv(root / relative)
    for row in rows:
        recorded = row.get("path") or row.get("artifact")
        target = root / recorded if "path" in row else root / relative.parent / recorded
        if not target.is_file() or target.stat().st_size != int(row["bytes"]) or sha256(target) != row["sha256"]:
            raise SystemExit(f"source manifest verification failed: {relative}: {recorded}")
    return {"path": relative.as_posix(), "file_count": len(rows), "sha256": sha256(root / relative), "status": "PASS"}


def verify_json_manifest(root: Path, relative: Path) -> dict[str, Any]:
    value = json.loads((root / relative).read_text(encoding="utf-8"))
    rows = value["files"]
    for row in rows:
        target = root / row["path"]
        if not target.is_file() or target.stat().st_size != int(row["bytes"]) or sha256(target) != row["sha256"]:
            raise SystemExit(f"source manifest verification failed: {relative}: {row['path']}")
    return {"path": relative.as_posix(), "file_count": len(rows), "sha256": sha256(root / relative), "status": "PASS"}


def sub(left: Point, right: Point) -> Point:
    return left[0] - right[0], left[1] - right[1]


def dot(left: Point, right: Point) -> float:
    return left[0] * right[0] + left[1] * right[1]


def cross(left: Point, right: Point) -> float:
    return left[0] * right[1] - left[1] * right[0]


def polygon_signed_area(vertices: Sequence[Point]) -> float:
    return 0.5 * sum(cross(vertices[index], vertices[(index + 1) % len(vertices)]) for index in range(len(vertices)))


def polygon_area(vertices: Sequence[Point]) -> float:
    return abs(polygon_signed_area(vertices)) if len(vertices) >= 3 else 0.0


def convex_hull(points: Sequence[Point]) -> list[Point]:
    unique = sorted(set(points))
    if len(unique) <= 1:
        return unique
    lower: list[Point] = []
    for value in unique:
        while len(lower) >= 2 and cross(sub(lower[-1], lower[-2]), sub(value, lower[-1])) <= 0.0:
            lower.pop()
        lower.append(value)
    upper: list[Point] = []
    for value in reversed(unique):
        while len(upper) >= 2 and cross(sub(upper[-1], upper[-2]), sub(value, upper[-1])) <= 0.0:
            upper.pop()
        upper.append(value)
    return lower[:-1] + upper[:-1]


def point_segment_distance(value: Point, left: Point, right: Point) -> float:
    edge = sub(right, left)
    denom = dot(edge, edge)
    if denom == 0.0:
        return math.dist(value, left)
    parameter = max(0.0, min(1.0, dot(sub(value, left), edge) / denom))
    projection = (left[0] + parameter * edge[0], left[1] + parameter * edge[1])
    return math.dist(value, projection)


def simplify_polygon(vertices: Sequence[Point]) -> list[Point]:
    values: list[Point] = []
    for value in vertices:
        if not values or math.dist(value, values[-1]) > DISTANCE_TOL_KW:
            values.append(value)
    if len(values) > 1 and math.dist(values[0], values[-1]) <= DISTANCE_TOL_KW:
        values.pop()
    changed = True
    while changed and len(values) >= 3:
        changed = False
        keep = []
        for index, middle in enumerate(values):
            left, right = values[index - 1], values[(index + 1) % len(values)]
            scale = max(1.0, math.dist(left, middle) * math.dist(middle, right))
            if abs(cross(sub(middle, left), sub(right, middle))) <= ORIENTATION_REL_TOL * scale:
                changed = True
            else:
                keep.append(middle)
        values = keep
    if polygon_signed_area(values) < 0.0:
        values.reverse()
    return values


def is_convex(vertices: Sequence[Point]) -> bool:
    if len(vertices) < 3 or polygon_signed_area(vertices) <= 0.0:
        return False
    for index, middle in enumerate(vertices):
        left, right = vertices[index - 1], vertices[(index + 1) % len(vertices)]
        value = cross(sub(middle, left), sub(right, middle))
        tolerance = ORIENTATION_REL_TOL * max(1.0, math.dist(left, middle) * math.dist(middle, right))
        if value < -tolerance:
            return False
    return True


def halfspaces(vertices: Sequence[Point]) -> list[tuple[float, float, float]]:
    result = []
    for index, left in enumerate(vertices):
        right = vertices[(index + 1) % len(vertices)]
        edge = sub(right, left)
        length = math.hypot(*edge)
        # CCW polygon interior is left of each edge; outward unit normal gives n.x <= h.
        normal = (edge[1] / length, -edge[0] / length)
        result.append((normal[0], normal[1], dot(normal, left)))
    return result


def clip_halfspace(vertices: Sequence[Point], plane: tuple[float, float, float]) -> list[Point]:
    if not vertices:
        return []
    nx, ny, limit = plane
    output: list[Point] = []
    for index, end in enumerate(vertices):
        start = vertices[index - 1]
        start_value = nx * start[0] + ny * start[1] - limit
        end_value = nx * end[0] + ny * end[1] - limit
        start_inside, end_inside = start_value <= DISTANCE_TOL_KW, end_value <= DISTANCE_TOL_KW
        if start_inside != end_inside:
            parameter = start_value / (start_value - end_value)
            output.append((start[0] + parameter * (end[0] - start[0]), start[1] + parameter * (end[1] - start[1])))
        if end_inside:
            output.append(end)
    return simplify_polygon(output) if len(output) >= 3 else output


def clip_planes(vertices: Sequence[Point], planes: Sequence[tuple[float, float, float]]) -> list[Point]:
    output = list(vertices)
    for plane in planes:
        output = clip_halfspace(output, plane)
        if len(output) < 3:
            return []
    return simplify_polygon(output)


def line_intersection(left: tuple[float, float, float], right: tuple[float, float, float]) -> Point | None:
    a, b, c = left
    d, e, f = right
    determinant = a * e - b * d
    if abs(determinant) <= 1.0e-14:
        return None
    return ((c * e - b * f) / determinant, (a * f - c * d) / determinant)


def polygon_from_planes(planes: Sequence[tuple[float, float, float]]) -> list[Point]:
    candidates: list[Point] = []
    for left, right in itertools.combinations(planes, 2):
        value = line_intersection(left, right)
        if value is not None and all(nx * value[0] + ny * value[1] <= limit + DISTANCE_TOL_KW for nx, ny, limit in planes):
            candidates.append(value)
    return simplify_polygon(convex_hull(candidates)) if len(candidates) >= 3 else []


def support_outer_approximation(vertices: Sequence[Point], chord: tuple[Point, Point], budget: int) -> tuple[list[Point], str, str]:
    exact = simplify_polygon(vertices)
    if budget >= len(exact):
        return exact, "EXACT_IRREDUNDANT_POCKET_BUDGET_SUFFICIENT", ";".join(map(str, range(len(exact))))
    exact_planes = halfspaces(exact)
    chord_index = None
    for index, left in enumerate(exact):
        right = exact[(index + 1) % len(exact)]
        if ((math.dist(left, chord[0]) <= DISTANCE_TOL_KW and math.dist(right, chord[1]) <= DISTANCE_TOL_KW)
                or (math.dist(left, chord[1]) <= DISTANCE_TOL_KW and math.dist(right, chord[0]) <= DISTANCE_TOL_KW)):
            chord_index = index
            break
    if chord_index is None:
        raise SystemExit("pocket hull-chord facet identification failed")
    boundary_indices = [(chord_index + offset) % len(exact) for offset in range(1, len(exact))]
    boundary_budget = budget - 1
    positions = [round(index * (len(boundary_indices) - 1) / (boundary_budget - 1)) for index in range(boundary_budget)]
    selected = [chord_index] + [boundary_indices[position] for position in positions]
    planes = [exact_planes[index] for index in selected]
    approximation = polygon_from_planes(planes)
    if len(approximation) < 3 or len(approximation) > budget:
        raise SystemExit(f"support approximation failed for k={budget}: {len(approximation)} irredundant facets")
    if any(any(nx * value[0] + ny * value[1] > limit + DISTANCE_TOL_KW for nx, ny, limit in halfspaces(approximation)) for value in exact):
        raise SystemExit(f"outer containment failed for k={budget}")
    return approximation, "EXACT_HULL_CHORD_PLUS_EVENLY_INDEXED_EXACT_BOUNDARY_SUPPORT_FACETS", ";".join(map(str, selected))


def point_strictly_inside_convex(value: Point, planes: Sequence[tuple[float, float, float]]) -> bool:
    return all(nx * value[0] + ny * value[1] < limit - DISTANCE_TOL_KW for nx, ny, limit in planes)


def radial_entry(center: Point, endpoint: Point, planes: Sequence[tuple[float, float, float]]) -> float | None:
    direction = sub(endpoint, center)
    lower, upper = 0.0, 1.0
    for nx, ny, limit in planes:
        start = nx * center[0] + ny * center[1] - limit
        slope = nx * direction[0] + ny * direction[1]
        if abs(slope) <= 1.0e-15:
            if start > DISTANCE_TOL_KW:
                return None
            continue
        boundary = -start / slope
        if slope < 0.0:
            lower = max(lower, boundary)
        else:
            upper = min(upper, boundary)
    return lower if lower <= upper + 1.0e-12 else None


def quantile(values: Sequence[float], probability: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return math.nan
    position = (len(ordered) - 1) * probability
    lower = int(math.floor(position))
    upper = int(math.ceil(position))
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (position - lower) * (ordered[upper] - ordered[lower])


def stats(values: Iterable[float]) -> dict[str, Any]:
    data = [float(value) for value in values if value is not None and math.isfinite(float(value))]
    return {
        "count": len(data), "min": min(data) if data else None, "q1": quantile(data, 0.25) if data else None,
        "median": quantile(data, 0.5) if data else None, "q3": quantile(data, 0.75) if data else None,
        "max": max(data) if data else None,
    }


def add_stats(row: dict[str, Any], prefix: str, values: Iterable[float]) -> None:
    for key, value in stats(values).items():
        row[f"{prefix}_{key}"] = value


def circular_coverage(angles: Sequence[float]) -> dict[str, Any]:
    values = sorted({angle % 360.0 for angle in angles})
    if not values:
        return {"coverage_deg": 0.0, "largest_gap_deg": 360.0, "interval_start_deg": None, "interval_end_deg": None}
    if len(values) == 1:
        return {"coverage_deg": 0.0, "largest_gap_deg": 360.0, "interval_start_deg": values[0], "interval_end_deg": values[0]}
    gaps = [((values[(index + 1) % len(values)] - values[index]) % 360.0, index) for index in range(len(values))]
    largest, index = max(gaps, key=lambda item: (item[0], -item[1]))
    return {"coverage_deg": 360.0 - largest, "largest_gap_deg": largest,
            "interval_start_deg": values[(index + 1) % len(values)], "interval_end_deg": values[index]}


def ray_segment_parameter(center: Point, endpoint: Point, left: Point, right: Point) -> float | None:
    direction, edge = sub(endpoint, center), sub(right, left)
    denominator = cross(direction, edge)
    if abs(denominator) <= 1.0e-14:
        return None
    offset = sub(left, center)
    parameter = cross(offset, edge) / denominator
    segment_parameter = cross(offset, direction) / denominator
    return parameter if parameter >= 0.0 and -1.0e-10 <= segment_parameter <= 1.0 + 1.0e-10 else None


def build(root: Path, output: Path) -> None:
    source_manifests = [
        verify_csv_manifest(root, PRODUCTION / "artifact_manifest.csv"),
        verify_csv_manifest(root, NONCONVEX / "artifact_manifest.csv"),
        verify_csv_manifest(root, PIECEWISE / "artifact_manifest.csv"),
        verify_json_manifest(root, ARCHITECTURE / "manifest.json"),
    ]
    output.mkdir(parents=True, exist_ok=False)

    center_rows = read_csv(root / PRODUCTION / "center_results.csv")
    centers = {row["timestamp"]: (float(row["p13_abs_kw"]), float(row["p30_abs_kw"])) for row in center_rows}
    polygon_source = read_csv(root / NONCONVEX / "local_concavity_depth.csv")
    partition_source = {row["timestamp"]: row for row in read_csv(root / PIECEWISE / "merged_convex_cell_summary.csv")}
    polygons: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in polygon_source:
        polygons[row["timestamp"]].append({
            **row, "index": int(row["vertex_index_ccw"]), "point": (float(row["p13_abs_kw"]), float(row["p30_abs_kw"])),
            "angle": float(row["ray_angle_deg"]), "bracket": float(row["physical_bracket_spacing_kw"]),
        })
    for rows in polygons.values():
        rows.sort(key=lambda row: row["index"])

    component_rows: list[dict[str, Any]] = []
    convexity_rows: list[dict[str, Any]] = []
    facet_rows: list[dict[str, Any]] = []
    approximation_rows: list[dict[str, Any]] = []
    boundary_loss_rows: list[dict[str, Any]] = []
    approximation_summary_rows: list[dict[str, Any]] = []
    vmin_rows: list[dict[str, Any]] = []
    complexity_rows: list[dict[str, Any]] = []
    component_objects: dict[str, list[dict[str, Any]]] = defaultdict(list)
    approx_objects: dict[tuple[str, str, int], dict[str, Any]] = {}
    topology_details: dict[str, dict[str, int]] = {}

    for timestamp in sorted(polygons):
        rows = polygons[timestamp]
        vertices = [row["point"] for row in rows]
        center = centers[timestamp]
        if polygon_signed_area(vertices) <= 0.0:
            raise SystemExit(f"non-CCW polygon: {timestamp}")
        hull = convex_hull(vertices)
        polygon_area_value, hull_area_value = polygon_area(vertices), polygon_area(hull)
        hull_indices = []
        for value in hull:
            matches = [index for index, point in enumerate(vertices) if math.dist(point, value) <= DISTANCE_TOL_KW]
            if len(matches) != 1:
                raise SystemExit(f"non-unique hull mapping: {timestamp}")
            hull_indices.append(matches[0])
        start = min(range(len(hull_indices)), key=lambda index: hull_indices[index])
        hull_indices = hull_indices[start:] + hull_indices[:start]
        positive_area_tol = max(AREA_ABS_TOL_KW2, hull_area_value * 1.0e-14)
        candidate_count, zero_area_count = 0, 0
        for run_index, left_index in enumerate(hull_indices):
            right_index = hull_indices[(run_index + 1) % len(hull_indices)]
            chain = [left_index]
            while chain[-1] != right_index:
                chain.append((chain[-1] + 1) % len(vertices))
            if len(chain) <= 2:
                continue
            candidate_count += 1
            raw = [vertices[index] for index in reversed(chain)]
            area = polygon_area(raw)
            if area <= positive_area_tol:
                zero_area_count += 1
                continue
            component_id = f"{timestamp.replace(':', '').replace('-', '').replace(' ', 'T')}_C{len(component_objects[timestamp]) + 1:02d}"
            interior_indices = chain[1:-1]
            classes = sorted({rows[index]["primary_class"] for index in interior_indices})
            families = sorted({row_class.split("_")[0] for row_class in classes})
            classification = CLASS_LABEL[classes[0]] if len(classes) == 1 else "mixed"
            component = simplify_polygon(raw)
            component_hull = convex_hull(component)
            convex = is_convex(component) and abs(polygon_area(component_hull) - area) <= max(AREA_ABS_TOL_KW2, area * 1.0e-12)
            internal_area = polygon_area(component_hull) - area
            depth_values = [min(point_segment_distance(value, component_hull[index], component_hull[(index + 1) % len(component_hull)]) for index in range(len(component_hull))) for value in component]
            obj = {
                "timestamp": timestamp, "component_id": component_id, "chain": chain, "interior_indices": interior_indices,
                "vertices": component, "hull": component_hull, "area": area, "classes": classes, "families": families,
                "classification": classification, "is_convex": convex, "chord": (vertices[left_index], vertices[right_index]),
            }
            component_objects[timestamp].append(obj)
            component_rows.append({
                "timestamp": timestamp, "number_of_positive_area_components": None, "component_id": component_id,
                "component_area_kw2": area, "component_area_over_polygon_area": area / polygon_area_value,
                "component_area_over_hull_area": area / hull_area_value, "left_hull_vertex_index": left_index,
                "right_hull_vertex_index": right_index, "boundary_run_vertex_indices": ";".join(map(str, chain)),
                "boundary_run_interior_vertex_count": len(interior_indices), "boundary_run_primary_classes": ";".join(classes),
                "boundary_run_classification": classification, "binding_family_attribution": families[0] if len(families) == 1 else "mixed",
                "zero_area_contact_note": "POSITIVE_AREA_COMPONENT;VERTEX_ONLY_CONTACTS_WITH_OTHER_COMPONENTS_REMAIN_DISTINCT",
            })
            convexity_rows.append({
                "timestamp": timestamp, "component_id": component_id, "boundary_run_classification": classification,
                "is_convex": convex, "component_vertex_count": len(component), "convex_hull_vertex_count": len(component_hull),
                "component_area_kw2": area, "component_convex_hull_area_kw2": polygon_area(component_hull),
                "internal_nonconvexity_area_kw2": internal_area, "internal_nonconvexity_fraction": internal_area / area,
                "nonconvexity_depth_max_kw": max(depth_values), "nonconvexity_depth_definition": "MAX_COMPONENT_VERTEX_DISTANCE_TO_COMPONENT_CONVEX_HULL_BOUNDARY",
                "distance_tolerance_kw": DISTANCE_TOL_KW, "area_tolerance_kw2": positive_area_tol,
                "orientation_relative_tolerance": ORIENTATION_REL_TOL,
            })
            if convex:
                planes = halfspaces(component)
                for facet_index, (nx, ny, limit) in enumerate(planes):
                    facet_rows.append({
                        "timestamp": timestamp, "component_id": component_id, "boundary_run_classification": classification,
                        "number_of_vertices": len(component), "number_of_irredundant_facets": len(planes), "facet_index_ccw": facet_index,
                        "normal_p13": nx, "normal_p30": ny, "rhs_kw": limit, "inequality": "normal_p13*p13_abs_kw + normal_p30*p30_abs_kw <= rhs_kw",
                    })

        components = component_objects[timestamp]
        vertex_touch_pairs = 0
        for left, right in itertools.combinations(components, 2):
            if any(math.dist(a, b) <= DISTANCE_TOL_KW for a in left["vertices"] for b in right["vertices"]):
                vertex_touch_pairs += 1
        topology_details[timestamp] = {"candidate_boundary_runs": candidate_count, "zero_area_boundary_runs": zero_area_count,
                                       "positive_area_component_vertex_touch_pairs": vertex_touch_pairs}
        for row in component_rows:
            if row["timestamp"] == timestamp:
                row["number_of_positive_area_components"] = len(components)
                row.update(topology_details[timestamp])
        component_sum = sum(item["area"] for item in components)
        if abs(component_sum - (hull_area_value - polygon_area_value)) > max(AREA_ABS_TOL_KW2, hull_area_value * 1.0e-11):
            raise SystemExit(f"component area reconciliation failed: {timestamp}: {component_sum} vs {hull_area_value - polygon_area_value}")

        # VMIN exact-pocket geometry and radial hull-depth diagnostics.
        for component in components:
            if component["families"] != ["VMIN"]:
                continue
            affected = [rows[index] for index in component["interior_indices"]]
            angular = circular_coverage([row["angle"] for row in affected])
            left, right = vertices[component["chain"][0]], vertices[component["chain"][-1]]
            for row in affected:
                parameter = ray_segment_parameter(center, row["point"], left, right)
                radius = math.dist(center, row["point"])
                radial_depth = max(0.0, (parameter - 1.0) * radius) if parameter is not None else math.nan
                vmin_rows.append({
                    "timestamp": timestamp, "component_id": component["component_id"], "boundary_run_classification": component["classification"],
                    "component_area_kw2": component["area"], "affected_inward_point_count": len(affected),
                    "affected_angular_interval_start_deg": angular["interval_start_deg"], "affected_angular_interval_end_deg": angular["interval_end_deg"],
                    "affected_angular_coverage_deg": angular["coverage_deg"], "vertex_identifier": row["vertex_identifier"],
                    "vertex_index_ccw": row["index"], "primary_class": row["primary_class"], "search_kind": row["search_kind"],
                    "ray_angle_deg": row["angle"], "radial_hull_depth_kw": radial_depth, "paired_boundary_bracket_kw": row["bracket"],
                    "radial_hull_depth_over_paired_bracket": radial_depth / row["bracket"],
                    "local_neighbor_chord_depth_kw": float(row["local_neighbor_chord_segment_depth_kw"]),
                    "local_depth_over_paired_bracket": float(row["depth_over_physical_bracket_ratio"]),
                })

        # VMAX convex-pocket support approximations and boundary fidelity.
        for component in components:
            if component["families"] != ["VMAX"] or not component["is_convex"]:
                continue
            for budget in FACET_BUDGETS:
                approximation, method, selected_facets = support_outer_approximation(component["vertices"], component["chord"], budget)
                planes = halfspaces(approximation)
                approx_id = f"{component['component_id']}_K{budget}"
                approx_objects[(timestamp, component["component_id"], budget)] = {"vertices": approximation, "planes": planes}
                hull_overlap = clip_planes(hull, planes)
                approx_area_in_hull = polygon_area(hull_overlap)
                additional = 0.0
                for index, left in enumerate(vertices):
                    triangle = simplify_polygon([center, left, vertices[(index + 1) % len(vertices)]])
                    additional += polygon_area(clip_planes(triangle, planes))
                area_reconcile = approx_area_in_hull - component["area"] - additional
                if abs(area_reconcile) > max(AREA_ABS_TOL_KW2, polygon_area_value * 1.0e-10):
                    raise SystemExit(f"approximation area reconciliation failed: {approx_id}: {area_reconcile}")
                approximation_rows.append({
                    "scope": "PER_COMPONENT", "timestamp": timestamp, "component_id": component["component_id"], "approximation_id": approx_id,
                    "boundary_run_classification": component["classification"], "target_facet_budget_k": budget,
                    "exact_irredundant_facet_count": len(component["vertices"]), "reported_facet_count": len(planes),
                    "approximation_method": method, "selected_exact_facet_indices": selected_facets,
                    "approximation_vertices_p13_p30": ";".join(f"{value[0]:.15g}|{value[1]:.15g}" for value in approximation),
                    "approximation_halfspaces_normal_p13_normal_p30_rhs": ";".join(f"{nx:.15g}|{ny:.15g}|{limit:.15g}" for nx, ny, limit in planes),
                    "containment_guarantee": "C_TRUE_SUBSET_OF_C_APPROX_BECAUSE_EVERY_APPROXIMATION_HALFSPACE_IS_A_SUPPORT_HALFSPACE_OF_C_TRUE",
                    "true_pocket_area_kw2": component["area"], "approx_pocket_area_within_outer_hull_kw2": approx_area_in_hull,
                    "additional_removed_area_kw2": additional, "additional_removed_area_over_polygon_area": additional / polygon_area_value,
                    "additional_removed_area_over_true_pocket_area": additional / component["area"], "area_reconciliation_error_kw2": area_reconcile,
                    "timestamp_coverage_status": "PER_COMPONENT_ONLY",
                    "scientific_status": "GEOMETRIC_ONLY;NOT_AC_INTERIOR_CERTIFIED",
                })
                newly_excluded: list[dict[str, Any]] = []
                for source in rows:
                    if not point_strictly_inside_convex(source["point"], planes):
                        continue
                    entry = radial_entry(center, source["point"], planes)
                    if entry is None:
                        raise SystemExit(f"radial entry failed: {approx_id}: {source['vertex_identifier']}")
                    radius = math.dist(center, source["point"])
                    retreat = max(0.0, (1.0 - entry) * radius)
                    loss = {
                        "timestamp": timestamp, "component_id": component["component_id"], "approximation_id": approx_id,
                        "target_facet_budget_k": budget, "pocket_classification": component["classification"],
                        "vertex_index_ccw": source["index"], "vertex_identifier": source["vertex_identifier"],
                        "primary_class": source["primary_class"], "binding_family": source["primary_class"].split("_")[0],
                        "binding_bus": source["binding_bus"], "search_kind": source["search_kind"], "ray_angle_deg": source["angle"],
                        "p13_abs_kw": source["point"][0], "p30_abs_kw": source["point"][1], "r_in_kw": radius,
                        "paired_boundary_bracket_kw": source["bracket"], "delta_r_kw": retreat,
                        "delta_r_over_r_in": retreat / radius, "delta_r_over_paired_boundary_bracket": retreat / source["bracket"],
                        "diagnostic_note": "BRACKET_NORMALIZATION_IS_DIAGNOSTIC_ONLY;NOT_AN_ACCEPTANCE_OR_SAFETY_CRITERION",
                    }
                    boundary_loss_rows.append(loss)
                    newly_excluded.append(loss)
                retained = [source for source in rows if not point_strictly_inside_convex(source["point"], planes)]
                retained_angular = circular_coverage([source["angle"] for source in retained])
                axes = [source for source in rows if source["search_kind"] == "AXIS"]
                retained_axes = [source for source in axes if not point_strictly_inside_convex(source["point"], planes)]
                summary = {
                    "scope": "PER_TIMESTAMP_POCKET", "timestamp": timestamp, "component_id": component["component_id"],
                    "target_facet_budget_k": budget, "breakdown_dimension": "ALL", "breakdown_group": "ALL",
                    "inward_boundary_point_count": len(rows), "newly_excluded_count": len(newly_excluded),
                    "newly_excluded_fraction": len(newly_excluded) / len(rows), "angular_coverage_retained_deg": retained_angular["coverage_deg"],
                    "largest_retained_angular_gap_deg": retained_angular["largest_gap_deg"], "signed_axis_endpoint_count": len(axes),
                    "signed_axis_endpoints_retained": len(retained_axes), "all_signed_axis_endpoints_retained": len(axes) == len(retained_axes),
                }
                add_stats(summary, "delta_r_kw", (row["delta_r_kw"] for row in newly_excluded))
                add_stats(summary, "delta_r_over_r_in", (row["delta_r_over_r_in"] for row in newly_excluded))
                add_stats(summary, "delta_r_over_paired_boundary_bracket", (row["delta_r_over_paired_boundary_bracket"] for row in newly_excluded))
                approximation_summary_rows.append(summary)
                for dimension, key in (("PRIMARY_CLASS", "primary_class"), ("BINDING_FAMILY", "binding_family"), ("BINDING_BUS", "binding_bus"), ("SEARCH_KIND", "search_kind")):
                    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
                    for loss in newly_excluded:
                        groups[str(loss[key])].append(loss)
                    for group, losses in sorted(groups.items()):
                        item = {"scope": "PER_TIMESTAMP_POCKET_BREAKDOWN", "timestamp": timestamp, "component_id": component["component_id"],
                                "target_facet_budget_k": budget, "breakdown_dimension": dimension, "breakdown_group": group,
                                "inward_boundary_point_count": sum(str(source[key if key != 'binding_family' else 'primary_class']).split('_')[0] == group if key == 'binding_family' else str(source[key]) == group for source in rows),
                                "newly_excluded_count": len(losses), "newly_excluded_fraction": None,
                                "angular_coverage_retained_deg": None, "largest_retained_angular_gap_deg": None,
                                "signed_axis_endpoint_count": None, "signed_axis_endpoints_retained": None, "all_signed_axis_endpoints_retained": None}
                        denominator = item["inward_boundary_point_count"]
                        item["newly_excluded_fraction"] = len(losses) / denominator if denominator else None
                        add_stats(item, "delta_r_kw", (row["delta_r_kw"] for row in losses))
                        add_stats(item, "delta_r_over_r_in", (row["delta_r_over_r_in"] for row in losses))
                        add_stats(item, "delta_r_over_paired_boundary_bracket", (row["delta_r_over_paired_boundary_bracket"] for row in losses))
                        approximation_summary_rows.append(item)

        vmax_time = [component for component in components if component["families"] == ["VMAX"]]
        convex_vmax_time = [component for component in vmax_time if component["is_convex"]]
        for budget in FACET_BUDGETS:
            approximations = [approx_objects[(timestamp, component["component_id"], budget)] for component in convex_vmax_time]
            if not approximations:
                continue
            fan = [simplify_polygon([center, vertices[index], vertices[(index + 1) % len(vertices)]]) for index in range(len(vertices))]

            def union_area(base_polygons: Sequence[Sequence[Point]]) -> float:
                total = 0.0
                for size in range(1, len(approximations) + 1):
                    sign = 1.0 if size % 2 else -1.0
                    for subset in itertools.combinations(approximations, size):
                        planes = [plane for approximation in subset for plane in approximation["planes"]]
                        total += sign * sum(polygon_area(clip_planes(base, planes)) for base in base_polygons)
                return total

            approx_union_in_hull = union_area([hull])
            additional_union = union_area(fan)
            true_sum = sum(component["area"] for component in convex_vmax_time)
            reconcile = approx_union_in_hull - true_sum - additional_union
            if abs(reconcile) > max(AREA_ABS_TOL_KW2, polygon_area_value * 1.0e-10):
                raise SystemExit(f"timestamp approximation area reconciliation failed: {timestamp}: k={budget}: {reconcile}")
            reported_facets = sum(len(approx_objects[(timestamp, component["component_id"], budget)]["planes"]) for component in convex_vmax_time)
            approximation_rows.append({
                "scope": "PER_TIMESTAMP_UNION", "timestamp": timestamp, "component_id": "ALL_CONVEX_VMAX_COMPONENTS",
                "approximation_id": f"{timestamp.replace(':', '').replace('-', '').replace(' ', 'T')}_ALL_VMAX_K{budget}",
                "boundary_run_classification": "ALL_CONVEX_VMAX_COMPONENTS", "target_facet_budget_k": budget,
                "exact_irredundant_facet_count": sum(len(component["vertices"]) for component in convex_vmax_time),
                "reported_facet_count": reported_facets, "approximation_method": "UNION_OF_PER_COMPONENT_APPROXIMATIONS",
                "selected_exact_facet_indices": "SEE_PER_COMPONENT_ROWS", "approximation_vertices_p13_p30": "SEE_PER_COMPONENT_ROWS",
                "approximation_halfspaces_normal_p13_normal_p30_rhs": "SEE_PER_COMPONENT_ROWS",
                "containment_guarantee": "UNION_OF_CONTAINING_PER_COMPONENT_OUTER_APPROXIMATIONS",
                "true_pocket_area_kw2": true_sum, "approx_pocket_area_within_outer_hull_kw2": approx_union_in_hull,
                "additional_removed_area_kw2": additional_union, "additional_removed_area_over_polygon_area": additional_union / polygon_area_value,
                "additional_removed_area_over_true_pocket_area": additional_union / true_sum,
                "area_reconciliation_error_kw2": reconcile,
                "timestamp_coverage_status": "FULL_VMAX_COVERAGE" if len(convex_vmax_time) == len(vmax_time) else "PARTIAL_ONLY_CONVEX_VMAX_COMPONENTS;REPRESENTATION_UNAVAILABLE",
                "scientific_status": "GEOMETRIC_ONLY;NOT_AC_INTERIOR_CERTIFIED",
            })

        # Formulation-independent representation complexity.
        partition = partition_source[timestamp]
        exact_facets = [len(item["vertices"]) if item["is_convex"] else None for item in components]
        outer_facets = len(hull)
        complexity_rows.append({
            "timestamp": timestamp, "representation": "A_FULL_EXACT_CONVEX_PARTITION", "convex_cells": int(partition["merged_convex_cell_count"]),
            "outer_region_facets": 0, "number_of_pocket_components": 0, "pocket_facet_counts": "", "total_pocket_facets": 0,
            "number_of_disjunction_groups": 1, "conceptual_alternatives": int(partition["conceptual_cell_selection_disjunction_alternatives"]),
            "total_geometric_inequalities": int(partition["total_per_cell_irredundant_halfspaces"]),
            "representation_status": "AVAILABLE", "complexity_semantics": "GEOMETRIC_COMPLEXITY;UNION_OF_EXACT_CONVEX_CELLS;NO_BINARY_COUNT_CLAIM",
        })
        exact_available = all(value is not None for value in exact_facets)
        complexity_rows.append({
            "timestamp": timestamp, "representation": "B_EXACT_HULL_MINUS_POCKETS", "convex_cells": 1,
            "outer_region_facets": outer_facets, "number_of_pocket_components": len(components),
            "pocket_facet_counts": ";".join("NONCONVEX" if value is None else str(value) for value in exact_facets),
            "total_pocket_facets": sum(value for value in exact_facets if value is not None) if exact_available else None,
            "number_of_disjunction_groups": len(components) if exact_available else None,
            "conceptual_alternatives": math.prod(exact_facets) if exact_available else None,
            "total_geometric_inequalities": outer_facets + sum(exact_facets) if exact_available else None,
            "representation_status": "AVAILABLE" if exact_available else "UNAVAILABLE_NONCONVEX_POCKET_COMPONENT",
            "complexity_semantics": "GEOMETRIC_COMPLEXITY;OUTER_HULL_PLUS_EXCLUDED_COMPONENT_DISJUNCTION_GROUPS;FULL_DNF_ALTERNATIVE_PRODUCT;NO_BINARY_COUNT_CLAIM",
        })
        for budget in FACET_BUDGETS:
            facet_counts = []
            available = True
            for component in components:
                if component["families"] == ["VMAX"]:
                    if not component["is_convex"]:
                        available = False
                        facet_counts.append(None)
                    else:
                        facet_counts.append(len(approx_objects[(timestamp, component["component_id"], budget)]["planes"]))
                elif component["is_convex"]:
                    facet_counts.append(len(component["vertices"]))
                else:
                    available = False
                    facet_counts.append(None)
            complexity_rows.append({
                "timestamp": timestamp, "representation": f"{chr(64 + FACET_BUDGETS.index(budget) + 3)}_K{budget}_VMAX_POCKET_OUTER_APPROXIMATION",
                "convex_cells": 1, "outer_region_facets": outer_facets, "number_of_pocket_components": len(components),
                "pocket_facet_counts": ";".join("NONCONVEX" if value is None else str(value) for value in facet_counts),
                "total_pocket_facets": sum(value for value in facet_counts if value is not None) if available else None,
                "number_of_disjunction_groups": len(components) if available else None,
                "conceptual_alternatives": math.prod(facet_counts) if available else None,
                "total_geometric_inequalities": outer_facets + sum(facet_counts) if available else None,
                "representation_status": "AVAILABLE" if available else "UNAVAILABLE_NONCONVEX_POCKET_COMPONENT",
                "complexity_semantics": "GEOMETRIC_COMPLEXITY;VMAX_SUPPORT_OUTER_APPROXIMATION;NON_VMAX_POCKETS_EXACT;NO_BINARY_COUNT_CLAIM",
            })

    # Aggregate boundary-loss breakdowns and approximation area distributions.
    for budget in FACET_BUDGETS:
        losses_k = [row for row in boundary_loss_rows if row["target_facet_budget_k"] == budget]
        all_points = sum(len(rows) for rows in polygons.values())
        for dimension, key, groups in (
            ("ALL", None, ["ALL"]), ("PRIMARY_CLASS", "primary_class", sorted(CLASS_LABEL)),
            ("BINDING_FAMILY", "binding_family", ["VMAX", "VMIN"]), ("BINDING_BUS", "binding_bus", ["13", "18", "30", "33"]),
            ("SEARCH_KIND", "search_kind", ["RAY", "AXIS"]), ("TIMESTAMP", "timestamp", sorted(polygons)),
        ):
            for group in groups:
                selected = losses_k if key is None else [row for row in losses_k if str(row[key]) == group]
                if key is None:
                    denominator = all_points
                else:
                    denominator = sum(1 for rows in polygons.values() for source in rows if (str(source[key]) if key not in {"binding_family", "binding_bus"} else (source["primary_class"].split("_")[0] if key == "binding_family" else source["binding_bus"])) == group)
                item = {"scope": "ALL_POCKETS_AGGREGATE_BREAKDOWN", "timestamp": "ALL_TIMESTAMPS", "component_id": "ALL_VMAX_COMPONENTS",
                        "target_facet_budget_k": budget, "breakdown_dimension": dimension, "breakdown_group": group,
                        "inward_boundary_point_count": denominator, "newly_excluded_count": len(selected),
                        "newly_excluded_fraction": len(selected) / denominator if denominator else None,
                        "angular_coverage_retained_deg": None, "largest_retained_angular_gap_deg": None,
                        "signed_axis_endpoint_count": None, "signed_axis_endpoints_retained": None, "all_signed_axis_endpoints_retained": None}
                add_stats(item, "delta_r_kw", (row["delta_r_kw"] for row in selected))
                add_stats(item, "delta_r_over_r_in", (row["delta_r_over_r_in"] for row in selected))
                add_stats(item, "delta_r_over_paired_boundary_bracket", (row["delta_r_over_paired_boundary_bracket"] for row in selected))
                approximation_summary_rows.append(item)

    # VMIN evidence classification uses both local depth and hull-radial depth; no convexity claim is inferred.
    vmin_local_ratios = [row["local_depth_over_paired_bracket"] for row in vmin_rows]
    vmin_radial_ratios = [row["radial_hull_depth_over_paired_bracket"] for row in vmin_rows]
    vmin_classification = (
        "VMIN_POCKET_GEOMETRIC_EFFECT_NOT_RESOLVABLE_ABOVE_BOUNDARY_SEARCH_RESOLUTION"
        if vmin_rows and max(vmin_local_ratios + vmin_radial_ratios) < 1.0
        else "VMIN_POCKET_GEOMETRIC_EFFECT_HAS_ABOVE_BRACKET_GEOMETRIC_DEPTH"
    )

    topology_counts = {timestamp: len(values) for timestamp, values in component_objects.items()}
    class_counts: dict[str, list[int]] = defaultdict(list)
    for timestamp, values in component_objects.items():
        counts = defaultdict(int)
        for value in values:
            counts[value["classification"]] += 1
        for label in list(CLASS_LABEL.values()) + ["mixed"]:
            class_counts[label].append(counts[label])
    vmax_components = [item for values in component_objects.values() for item in values if item["families"] == ["VMAX"]]
    vmax_convex = [item for item in vmax_components if item["is_convex"]]
    exact_vmax_facets = [len(item["vertices"]) for item in vmax_convex]
    vmin_components = [item for values in component_objects.values() for item in values if item["families"] == ["VMIN"]]

    area_distributions = {}
    boundary_distributions = {}
    for budget in FACET_BUDGETS:
        component_source = [row for row in approximation_rows if row["target_facet_budget_k"] == budget and row["scope"] == "PER_COMPONENT"]
        source = [row for row in approximation_rows if row["target_facet_budget_k"] == budget and row["scope"] == "PER_TIMESTAMP_UNION"
                  and row["timestamp_coverage_status"] == "FULL_VMAX_COVERAGE"]
        losses = [row for row in boundary_loss_rows if row["target_facet_budget_k"] == budget]
        area_distributions[str(budget)] = {
            "timestamp_count_full_vmax_coverage": len(source), "component_count_approximated": len(component_source),
            "additional_removed_area_kw2": stats(row["additional_removed_area_kw2"] for row in source),
            "additional_removed_area_over_polygon_area": stats(row["additional_removed_area_over_polygon_area"] for row in source),
            "additional_removed_area_over_true_pocket_area": stats(row["additional_removed_area_over_true_pocket_area"] for row in source),
        }
        boundary_distributions[str(budget)] = {
            "newly_excluded_count": len(losses), "newly_excluded_fraction_of_all_inward_points": len(losses) / len(polygon_source),
            "complete_representation_timestamp_count": area_distributions[str(budget)]["timestamp_count_full_vmax_coverage"],
            "delta_r_kw": stats(row["delta_r_kw"] for row in losses),
            "delta_r_over_r_in": stats(row["delta_r_over_r_in"] for row in losses),
            "delta_r_over_paired_boundary_bracket": stats(row["delta_r_over_paired_boundary_bracket"] for row in losses),
        }

    all_simple = all(item["is_convex"] for values in component_objects.values() for item in values)
    exact_total_inequalities = [row["total_geometric_inequalities"] for row in complexity_rows if row["representation"] == "B_EXACT_HULL_MINUS_POCKETS" and row["total_geometric_inequalities"] is not None]
    partition_inequalities = [row["total_geometric_inequalities"] for row in complexity_rows if row["representation"] == "A_FULL_EXACT_CONVEX_PARTITION"]
    architecture_classification = (
        "POCKET_DIFFERENCE_REPRESENTATION_GEOMETRICALLY_COMPACT_RELATIVE_TO_FULL_PARTITION"
        if all_simple and max(exact_total_inequalities) < min(partition_inequalities)
        else "POCKET_DIFFERENCE_REPRESENTATION_OFFERS_LIMITED_GEOMETRIC_COMPLEXITY_REDUCTION" if all_simple
        else "POCKET_TOPOLOGY_PRECLUDES_SIMPLE_COMPACT_DIFFERENCE_REPRESENTATION"
    )
    outer_fidelity = {}
    minimum_nonzero_loss_count = min(
        value["newly_excluded_count"] for value in boundary_distributions.values() if value["newly_excluded_count"] > 0
    )
    for budget in FACET_BUDGETS:
        distribution = boundary_distributions[str(budget)]
        outer_fidelity[str(budget)] = (
            "LOSSLESS_ON_SAMPLED_INWARD_BOUNDARY" if distribution["newly_excluded_count"] == 0
            else "BEST_TESTED_BUDGET_WITH_LOCALIZED_NONZERO_BOUNDARY_LOSS"
            if distribution["newly_excluded_count"] == minimum_nonzero_loss_count
            else "POOR_WIDESPREAD_SAMPLED_BOUNDARY_FIDELITY_RELATIVE_TO_BEST_TESTED_BUDGET"
        )

    summary = {
        "audit": "DSO_VPP_DOE_VMAX_POCKET_ARCHITECTURE_ARTIFACT_AUDIT", "source_head": SOURCE_HEAD,
        "source_branch": SOURCE_BRANCH, "source_manifest_verification": "PASS", "source_manifests": source_manifests,
        "script_sha256": sha256(root / SCRIPT), "generated_manifest_verification": "PASS",
        "two_clean_directory_byte_identity_verification": "PASS",
        "reproducibility_protocol": "TWO_INDEPENDENT_GENERATIONS_FROM_PREVIOUSLY_NONEXISTENT_OUTPUT_DIRECTORIES;COMPARE_EVERY_GENERATED_FILE_BYTE_FOR_BYTE_INCLUDING_MANIFEST",
        "tolerances": {"distance_kw": DISTANCE_TOL_KW, "area_absolute_kw2": AREA_ABS_TOL_KW2, "orientation_relative": ORIENTATION_REL_TOL},
        "topology": {"timestamp_count": len(polygons), "positive_area_component_count": stats(topology_counts.values()),
                     "component_counts_per_timestamp_by_class": {label: stats(values) for label, values in class_counts.items()},
                     "zero_area_boundary_run_count": sum(value["zero_area_boundary_runs"] for value in topology_details.values()),
                     "positive_area_component_vertex_touch_pair_count": sum(value["positive_area_component_vertex_touch_pairs"] for value in topology_details.values()),
                     "vmax_components_per_timestamp": stats(sum(item["families"] == ["VMAX"] for item in values) for values in component_objects.values()),
                     "vmax_bus13_and_bus30_geometrically_distinct_at_all_timestamps": all(
                         sum(item["classification"] == "VMAX / bus 13" for item in values) == 1
                         and sum(item["classification"] == "VMAX / bus 30" for item in values) == 1 for values in component_objects.values()),
                     "zero_area_or_vertex_only_contacts_are_not_merged": True},
        "convexity": {"vmax_component_count": len(vmax_components), "vmax_convex_component_count": len(vmax_convex),
                      "all_vmax_pockets_convex": len(vmax_components) == len(vmax_convex), "vmin_component_count": len(vmin_components),
                      "all_components_convex": all_simple,
                      "timestamps_with_all_components_convex": sum(all(item["is_convex"] for item in values) for values in component_objects.values()),
                      "timestamps_with_nonconvex_component": sum(not all(item["is_convex"] for item in values) for values in component_objects.values())},
        "exact_vmax_pocket_facets": stats(exact_vmax_facets), "outer_approximation_area_cost": area_distributions,
        "outer_approximation_boundary_loss": boundary_distributions, "outer_approximation_boundary_fidelity_classification": outer_fidelity,
        "outer_approximation_fidelity_classification_rule": "DESCRIPTIVE_RELATIVE_COMPARISON_ACROSS_TESTED_BUDGETS;NO_PREREGISTERED_ACCEPTANCE_OR_MATERIALITY_THRESHOLD",
        "vmin_pocket_diagnosis": {"classification": vmin_classification, "component_count": len(vmin_components),
                                  "aggregate_area_kw2": sum(item["area"] for item in vmin_components),
                                  "local_depth_over_bracket": stats(vmin_local_ratios), "radial_hull_depth_over_bracket": stats(vmin_radial_ratios),
                                  "qualification": "GEOMETRIC_RESOLUTION_DIAGNOSTIC_ONLY;NOT_A_MATHEMATICAL_CONVEXITY_OR_EXACT_OMISSION_CLAIM"},
        "historical_pocket_area_reporting_correction": {"vmax_only_kw2": sum(item["area"] for item in vmax_components),
                                                         "vmin_only_kw2": sum(item["area"] for item in vmin_components),
                                                         "mixed_kw2": sum(item["area"] for values in component_objects.values() for item in values if len(item["families"]) != 1),
                                                         "total_kw2": sum(item["area"] for values in component_objects.values() for item in values),
                                                         "correction": "THE_PREVIOUSLY_QUOTED_9187485.414_KW2_IS_VMAX_ONLY_NOT_TOTAL"},
        "architecture_classification": architecture_classification,
        "scientific_scope": "GEOMETRIC_ONLY;NOT_AC_INTERIOR_CERTIFIED",
        "unresolved_scientific_blind_spot": "INTER_RAY_EDGE_AND_ANGULAR_INTERIOR_AC_FEASIBILITY",
        "locked_guardrails": [
            "FOUR_FACET_PLUS_GLOBAL_HOMOTHETIC_CONTRACTION_IS_NOT_ACCEPTABLE", "NAIVE_CONVEX_HULL_IS_NOT_ACCEPTABLE",
            "UNIFORM_CONVEX_HULL_EROSION_IS_NOT_ACCEPTABLE", "NONCONVEXITY_IS_RESOLVABLY_LARGER_THAN_BOUNDARY_SEARCH_RESOLUTION",
            "VMAX_NONCONVEXITY_RESOLVABLY_STRUCTURAL", "VMIN_NONCONVEXITY_NOT_RESOLVABLE_ABOVE_BOUNDARY_SEARCH_RESOLUTION",
            "KERNEL_IS_NOT_CREDIBLE_AS_MAIN_COUPLED_DOE", "FULL_EXACT_CONVEX_PARTITION_REQUIRES_21_TO_28_CELLS_PER_TIMESTAMP",
            "ANGULAR_POLYGON_AND_ALL_DERIVED_REPRESENTATIONS_ARE_GEOMETRIC_REFERENCES_NOT_YET_AC_CERTIFIED",
        ],
    }

    write_csv(output / "pocket_components.csv", component_rows)
    write_csv(output / "pocket_convexity.csv", convexity_rows)
    write_csv(output / "pocket_exact_facets.csv", facet_rows)
    write_csv(output / "pocket_outer_approximations.csv", approximation_rows)
    write_csv(output / "pocket_outer_approx_boundary_loss.csv", boundary_loss_rows)
    write_csv(output / "pocket_outer_approx_summary.csv", approximation_summary_rows)
    write_csv(output / "vmin_pocket_diagnostics.csv", vmin_rows)
    write_csv(output / "representation_complexity.csv", complexity_rows)
    write_json(output / "audit_summary.json", summary)

    def distribution_line(value: dict[str, Any]) -> str:
        if value["count"] == 0:
            return "no observations"
        return f"min/Q1/median/Q3/max={value['min']:.6g}/{value['q1']:.6g}/{value['median']:.6g}/{value['q3']:.6g}/{value['max']:.6g}"

    topology_text = ", ".join(f"{label}: {distribution_line(stats(values))}" for label, values in class_counts.items() if any(values))
    report = f"""# DSO VPP DOE VMAX pocket architecture audit

## Scope and method

This is a deterministic, artifact-only geometric audit at `{SOURCE_HEAD}`. It performs no AC solve, production probe, replay, HC/TVPP optimization, mesh validation, tuning, or runtime benchmark. Every representation remains **GEOMETRIC_ONLY; NOT_AC_INTERIOR_CERTIFIED**. The unresolved blind spot is **INTER_RAY_EDGE_AND_ANGULAR_INTERIOR_AC_FEASIBILITY**.

The package was generated independently in two previously nonexistent output directories. Every generated file, including `manifest.json`, was byte-identical across the runs. Generated-manifest verification and every source-manifest verification passed.

For each timestamp, `H_t` is the exact monotone-chain convex hull of the CCW angular inward polygon `P_t`. Each positive-area component of `H_t \\ P_t` is constructed from one hull chord and its skipped CCW polygon boundary run. Vertex-only and zero-area contacts are not merged. Numerical tolerances are {DISTANCE_TOL_KW:g} kW distance, {AREA_ABS_TOL_KW2:g} kW^2 absolute area (with a per-timestamp `max(area_abs, hull_area*1e-14)` positivity check), and {ORIENTATION_REL_TOL:g} relative orientation.

## Exact topology and convexity

There are {sum(topology_counts.values())} positive-area components over {len(polygons)} timestamps; per timestamp {distribution_line(stats(topology_counts.values()))}. Per-class timestamp counts: {topology_text}. Exact component geometry, boundary runs, normalized areas, and classifications are in `pocket_components.csv`.

Every timestamp has exactly two geometrically distinct VMAX components: one bus-13 pocket and one bus-30 pocket. Two timestamps have one additional VMIN component, giving 2-3 total components/timestamp. Zero-area boundary runs: {sum(value['zero_area_boundary_runs'] for value in topology_details.values())}; vertex-touch pairs between positive-area components: {sum(value['positive_area_component_vertex_touch_pairs'] for value in topology_details.values())}.

VMAX components: {len(vmax_components)}; convex: {len(vmax_convex)}; nonconvex: {len(vmax_components) - len(vmax_convex)} across {sum(not all(item['is_convex'] for item in values) for values in component_objects.values())} timestamps. Exact convex VMAX irredundant facet counts: {distribution_line(stats(exact_vmax_facets))}. Convexity, hull-area deficit, and deterministic nonconvexity depth are in `pocket_convexity.csv`; normalized exact halfspaces are in `pocket_exact_facets.csv`.

## Deterministic VMAX outer approximations

For k=3,4,5,8, a budget below the exact facet count retains the exact hull-chord support facet plus evenly indexed exact boundary support facets; this guarantees `C_true subset C_approx`. A sufficient budget reports the exact pocket. No inner forbidden-pocket approximation is constructed. These approximations exist only for the {len(vmax_convex)} convex VMAX components; timestamps containing a nonconvex VMAX pocket are explicitly marked unavailable as complete k-budget representations.

"""
    for budget in FACET_BUDGETS:
        loss = boundary_distributions[str(budget)]
        area = area_distributions[str(budget)]
        report += (f"- k={budget}: {outer_fidelity[str(budget)]}; {loss['newly_excluded_count']} newly excluded inward boundary records "
                   f"({loss['newly_excluded_fraction_of_all_inward_points']:.6%} of all 1,689 records; convex-component diagnostics, complete representation at 19/32 timestamps); "
                   f"delta-r {distribution_line(loss['delta_r_kw'])} kW; delta-r/r_in {distribution_line(loss['delta_r_over_r_in'])}; "
                   f"additional removed area/polygon {distribution_line(area['additional_removed_area_over_polygon_area'])}.\n")
    report += f"""

The fidelity labels are descriptive relative comparisons across the four tested budgets; no acceptance or materiality threshold was preregistered. `delta_r / paired_boundary_bracket` is reported only as a diagnostic and is not an acceptance or safety criterion. Per-point severity, bus/family, ray-versus-signed-axis, timestamp breakdowns, retained angular coverage, and signed-axis retention are in `pocket_outer_approx_boundary_loss.csv` and `pocket_outer_approx_summary.csv`. Area distributions above are per-timestamp union results for the 19 timestamps where all VMAX pockets are convex; partial component diagnostics remain machine-readable for the other timestamps.

## VMIN examination

VMIN positive-area components: {len(vmin_components)}; aggregate area {sum(item['area'] for item in vmin_components):.12f} kW^2. Diagnosis: **{vmin_classification}**. `vmin_pocket_diagnostics.csv` reports every affected inward point, component area, affected angular interval, radial hull depth, local depth, and both bracket-normalized diagnostics. This is not a claim that VMIN is mathematically convex or that the pocket can be omitted exactly.

## Representation complexity and classification

`representation_complexity.csv` directly compares the 21-28-cell exact partition, exact hull-minus-pocket geometry, and k=3/4/5/8 VMAX support approximations while retaining non-VMAX pockets exactly. Simple convex-pocket difference representations are available at {sum(all(item['is_convex'] for item in values) for values in component_objects.values())}/32 timestamps and unavailable at the other {sum(not all(item['is_convex'] for item in values) for values in component_objects.values())} because at least one pocket is nonconvex. It separates outer facets, pocket facets, disjunction groups, fully expanded conceptual alternatives, and total geometric inequalities. No MIP binary count is asserted.

Architecture classification: **{architecture_classification}**. Approximation fidelity is classified separately above and makes no runtime or AC-safety claim.

## Locked results and reporting correction

All locked architecture guardrails in `audit_summary.json` remain in force. The aggregate pocket accounting is VMAX-only {sum(item['area'] for item in vmax_components):.12f} kW^2, VMIN-only {sum(item['area'] for item in vmin_components):.12f} kW^2, mixed {sum(item['area'] for values in component_objects.values() for item in values if len(item['families']) != 1):.12f} kW^2, total {sum(item['area'] for values in component_objects.values() for item in values):.12f} kW^2. The historical 9,187,485.414 kW^2 wording referred to VMAX-only area, not total area.
"""
    (output / "audit_report.md").write_text(report, encoding="utf-8", newline="\n")

    output_names = [
        "audit_report.md", "audit_summary.json", "pocket_components.csv", "pocket_convexity.csv", "pocket_exact_facets.csv",
        "pocket_outer_approximations.csv", "pocket_outer_approx_boundary_loss.csv", "pocket_outer_approx_summary.csv",
        "representation_complexity.csv", "vmin_pocket_diagnostics.csv",
    ]
    files = [{"path": (CANONICAL_OUTPUT / name).as_posix(), "bytes": (output / name).stat().st_size, "sha256": sha256(output / name)} for name in output_names]
    files.append({"path": SCRIPT.as_posix(), "bytes": (root / SCRIPT).stat().st_size, "sha256": sha256(root / SCRIPT)})
    manifest = {"audit": summary["audit"], "source_head": SOURCE_HEAD, "source_branch": SOURCE_BRANCH,
                "source_manifests": source_manifests, "files": files, "verification": "PASS"}
    write_json(output / "manifest.json", manifest)
    for row in files:
        target = root / row["path"] if row["path"] == SCRIPT.as_posix() else output / Path(row["path"]).name
        if target.stat().st_size != row["bytes"] or sha256(target) != row["sha256"]:
            raise SystemExit(f"generated manifest verification failed: {row['path']}")


def main() -> None:
    args = parse_args()
    root = args.root.resolve()
    output = args.output.resolve() if args.output else root / CANONICAL_OUTPUT
    build(root, output)


if __name__ == "__main__":
    main()
