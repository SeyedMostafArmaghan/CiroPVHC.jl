#!/usr/bin/env python3
"""Artifact-only geometric audit of the preregistered DSO/VPP DOE candidate.

This program reads stored CSV artifacts only.  It performs no AC evaluation,
replay, production probing, optimization, benchmark, or policy tuning.  Output
is deterministic: no wall-clock time, temporary path, or platform newline is
written to an artifact.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable, Sequence


SOURCE_BRANCH = "codex/dso-vpp-ac-map-pilot"
SOURCE_HEAD = "c18021d9b981f2629e54f60e8c2fc5f33b00c1a2"
PREREG = Path("results/dso_vpp_ac_map_pilot/doe_construction_policy_preregistration")
CANONICAL_OUTPUT = PREREG / "geometric_contraction_threshold_audit"
SCRIPT_PATH = Path("scripts/audit_dso_vpp_doe_geometric_contraction_threshold.py")

ALPHA1_MEMBERSHIP_TOL_KW = 1.0e-8
GAUGE_COMPARISON_TOL = 1.0e-12
POLYGON_BOUNDARY_TOL_KW = 1.0e-8
DUPLICATE_POINT_TOL_KW = 1.0e-8
DUPLICATE_ANGLE_TOL_DEG = 1.0e-9
IDENTITY_TOL_KW = 1.0e-9

CLASS_ORDER = ("VMAX_BUS_13", "VMAX_BUS_30", "VMIN_BUS_18", "VMIN_BUS_33")
CLASS_KEY = {
    ("BINDING_VMAX", "13"): "VMAX_BUS_13",
    ("BINDING_VMAX", "30"): "VMAX_BUS_30",
    ("BINDING_VMIN", "18"): "VMIN_BUS_18",
    ("BINDING_VMIN", "33"): "VMIN_BUS_33",
}
CLASS_FAMILY = {
    "VMAX_BUS_13": "TOPOLOGY_FAMILY_VMAX13_VMIN18",
    "VMIN_BUS_18": "TOPOLOGY_FAMILY_VMAX13_VMIN18",
    "VMAX_BUS_30": "TOPOLOGY_FAMILY_VMAX30_VMIN33",
    "VMIN_BUS_33": "TOPOLOGY_FAMILY_VMAX30_VMIN33",
}


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
        return format(value, ".15g")
    return value


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


def write_text(path: Path, value: str) -> None:
    path.write_text(value.rstrip() + "\n", encoding="utf-8", newline="\n")


def f(value: str | int | float) -> float:
    return float(value)


def dot(a: tuple[float, float], p: tuple[float, float]) -> float:
    return a[0] * p[0] + a[1] * p[1]


def cross(a: tuple[float, float], b: tuple[float, float]) -> float:
    return a[0] * b[1] - a[1] * b[0]


def sub(a: tuple[float, float], b: tuple[float, float]) -> tuple[float, float]:
    return a[0] - b[0], a[1] - b[1]


def point(row: dict[str, str]) -> tuple[float, float]:
    return f(row["p13_abs_kw"]), f(row["p30_abs_kw"])


def endpoint_key(row: dict[str, str]) -> tuple[str, str, str, str]:
    return row["timestamp"], row["search_kind"], row["search_id"], row["level"]


def endpoint_id(row: dict[str, str]) -> str:
    return "|".join(endpoint_key(row))


def class_id(row: dict[str, str]) -> str:
    try:
        return CLASS_KEY[(row["binding_mechanism"], row["binding_bus"])]
    except KeyError as exc:
        raise SystemExit(f"unexpected primary class {exc.args[0]}") from exc


def angle_deg(vector: tuple[float, float]) -> float:
    return math.degrees(math.atan2(vector[1], vector[0])) % 360.0


def circular_distance(left: float, right: float) -> float:
    return abs((left - right + 180.0) % 360.0 - 180.0)


def quantile(values: Sequence[float], probability: float) -> float:
    ordered = sorted(values)
    if not ordered:
        raise ValueError("quantile of empty collection")
    position = (len(ordered) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def stats(values: Sequence[float]) -> dict[str, Any]:
    selected = [value for value in values if value is not None and math.isfinite(value)]
    if not selected:
        return {"count": 0, "min": None, "q1": None, "median": None, "q3": None, "max": None, "mean": None}
    return {
        "count": len(selected),
        "min": min(selected),
        "q1": quantile(selected, 0.25),
        "median": quantile(selected, 0.5),
        "q3": quantile(selected, 0.75),
        "max": max(selected),
        "mean": sum(selected) / len(selected),
    }


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def signed_scales(axis_rows: list[dict[str, str]], center: tuple[float, float]) -> dict[str, float]:
    by_axis = {row["axis"]: row for row in axis_rows}
    required = {"P13_POSITIVE", "P13_NEGATIVE", "P30_POSITIVE", "P30_NEGATIVE"}
    if set(by_axis) != required:
        raise SystemExit("signed-axis scale inputs do not reconcile")
    values = {
        "s13_positive_kw": f(by_axis["P13_POSITIVE"]["safe_p13_abs_kw"]) - center[0],
        "s13_negative_kw": center[0] - f(by_axis["P13_NEGATIVE"]["safe_p13_abs_kw"]),
        "s30_positive_kw": f(by_axis["P30_POSITIVE"]["safe_p30_abs_kw"]) - center[1],
        "s30_negative_kw": center[1] - f(by_axis["P30_NEGATIVE"]["safe_p30_abs_kw"]),
    }
    if any(value <= 0 for value in values.values()):
        raise SystemExit("nonpositive production-ray normalization scale")
    return values


def normalized_point(
    p: tuple[float, float], center: tuple[float, float], scales: dict[str, float]
) -> tuple[float, float, float, float]:
    dx, dy = p[0] - center[0], p[1] - center[1]
    sx = scales["s13_positive_kw"] if dx >= 0 else scales["s13_negative_kw"]
    sy = scales["s30_positive_kw"] if dy >= 0 else scales["s30_negative_kw"]
    x, y = dx / sx, dy / sy
    return x, y, math.hypot(x, y), angle_deg((x, y))


def geometry_context(
    p: tuple[float, float], center: tuple[float, float], scales: dict[str, float]
) -> dict[str, Any]:
    nx, ny, radius, theta = normalized_point(p, center, scales)
    return {
        "coordinate_semantics": "ABSOLUTE_PHYSICAL_P_PCC_P13_P30",
        "units": "kW",
        "p13_abs_kw": p[0],
        "p30_abs_kw": p[1],
        "center_p13_abs_kw": center[0],
        "center_p30_abs_kw": center[1],
        "centered_p13_kw": p[0] - center[0],
        "centered_p30_kw": p[1] - center[1],
        **scales,
        "normalized_x": nx,
        "normalized_y": ny,
        "normalized_radius": radius,
        "normalized_ray_angle_deg": theta,
        "ray_angle_convention": "ATAN2_NORMALIZED_P30_P13_MOD_360_CCW_FROM_POSITIVE_P13",
        "reactive_and_reference_contract": "Q_PCC=0;reference_pv_capacity_kw=0",
    }


def polygon_signed_area(vertices: Sequence[tuple[float, float]]) -> float:
    return 0.5 * sum(cross(vertices[index], vertices[(index + 1) % len(vertices)]) for index in range(len(vertices)))


def point_segment_distance(p: tuple[float, float], a: tuple[float, float], b: tuple[float, float]) -> float:
    ab = sub(b, a)
    length2 = dot(ab, ab)
    if length2 == 0:
        return math.dist(p, a)
    t = max(0.0, min(1.0, dot(sub(p, a), ab) / length2))
    projection = (a[0] + t * ab[0], a[1] + t * ab[1])
    return math.dist(p, projection)


def point_in_polygon(
    p: tuple[float, float], vertices: Sequence[tuple[float, float]], tolerance_kw: float
) -> str:
    if any(point_segment_distance(p, vertices[i], vertices[(i + 1) % len(vertices)]) <= tolerance_kw for i in range(len(vertices))):
        return "BOUNDARY"
    inside = False
    x, y = p
    for i, left in enumerate(vertices):
        right = vertices[(i + 1) % len(vertices)]
        if (left[1] > y) != (right[1] > y):
            crossing_x = left[0] + (y - left[1]) * (right[0] - left[0]) / (right[1] - left[1])
            if crossing_x > x:
                inside = not inside
    return "INSIDE" if inside else "OUTSIDE"


def segments_intersect(
    a: tuple[float, float], b: tuple[float, float], c: tuple[float, float], d: tuple[float, float]
) -> bool:
    # Nonadjacent polygon edges only; tolerance is applied as physical point-to-segment distance.
    ab, cd = sub(b, a), sub(d, c)
    denominator = cross(ab, cd)
    if abs(denominator) > 1.0e-14:
        ac = sub(c, a)
        t, u = cross(ac, cd) / denominator, cross(ac, ab) / denominator
        return -1.0e-12 <= t <= 1.0 + 1.0e-12 and -1.0e-12 <= u <= 1.0 + 1.0e-12
    return (
        point_segment_distance(a, c, d) <= POLYGON_BOUNDARY_TOL_KW
        or point_segment_distance(b, c, d) <= POLYGON_BOUNDARY_TOL_KW
        or point_segment_distance(c, a, b) <= POLYGON_BOUNDARY_TOL_KW
        or point_segment_distance(d, a, b) <= POLYGON_BOUNDARY_TOL_KW
    )


def polygon_self_intersection_count(vertices: Sequence[tuple[float, float]]) -> int:
    total = 0
    count = len(vertices)
    for i in range(count):
        for j in range(i + 1, count):
            if j == i or j == (i + 1) % count or i == (j + 1) % count:
                continue
            if segments_intersect(vertices[i], vertices[(i + 1) % count], vertices[j], vertices[(j + 1) % count]):
                total += 1
    return total


def polygon_is_convex(vertices: Sequence[tuple[float, float]]) -> bool:
    signs: set[int] = set()
    for index in range(len(vertices)):
        left = sub(vertices[(index + 1) % len(vertices)], vertices[index])
        right = sub(vertices[(index + 2) % len(vertices)], vertices[(index + 1) % len(vertices)])
        value = cross(left, right)
        scale = max(1.0, math.hypot(*left) * math.hypot(*right))
        if abs(value) <= 1.0e-12 * scale:
            continue
        signs.add(1 if value > 0 else -1)
    return len(signs) <= 1


def candidate_polygon(constraints: list[dict[str, Any]]) -> list[tuple[float, float]]:
    vertices: list[tuple[float, float]] = []
    for index, left in enumerate(constraints):
        for right in constraints[index + 1 :]:
            determinant = left["a13"] * right["a30"] - left["a30"] * right["a13"]
            if abs(determinant) <= 1.0e-14:
                continue
            p = (
                (left["b"] * right["a30"] - left["a30"] * right["b"]) / determinant,
                (left["a13"] * right["b"] - left["b"] * right["a13"]) / determinant,
            )
            if max(dot((item["a13"], item["a30"]), p) - item["b"] for item in constraints) <= ALPHA1_MEMBERSHIP_TOL_KW:
                if not any(math.dist(p, existing) <= 1.0e-7 for existing in vertices):
                    vertices.append(p)
    if len(vertices) < 3:
        raise SystemExit("candidate halfspaces did not form a bounded polygon")
    centroid = (sum(p[0] for p in vertices) / len(vertices), sum(p[1] for p in vertices) / len(vertices))
    vertices.sort(key=lambda p: (angle_deg(sub(p, centroid)), p[0], p[1]))
    if polygon_signed_area(vertices) < 0:
        vertices.reverse()
    return vertices


def convex_hull(points: Sequence[tuple[float, float]]) -> list[tuple[float, float]]:
    unique = sorted(set(points))
    if len(unique) <= 1:
        return unique

    def build(values: Sequence[tuple[float, float]]) -> list[tuple[float, float]]:
        result: list[tuple[float, float]] = []
        for p in values:
            while len(result) >= 2 and cross(sub(result[-1], result[-2]), sub(p, result[-1])) <= 0:
                result.pop()
            result.append(p)
        return result

    return build(unique)[:-1] + build(list(reversed(unique)))[:-1]


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


def angular_coverage(angles: Sequence[float]) -> tuple[float, float, int]:
    unique: list[float] = []
    for value in sorted(angles):
        if not unique or circular_distance(value, unique[-1]) > DUPLICATE_ANGLE_TOL_DEG:
            unique.append(value)
    if len(unique) > 1 and circular_distance(unique[0], unique[-1]) <= DUPLICATE_ANGLE_TOL_DEG:
        unique.pop()
    if not unique:
        return 0.0, 360.0, 0
    if len(unique) == 1:
        return 0.0, 360.0, 1
    gaps = [((unique[(i + 1) % len(unique)] - unique[i]) % 360.0) for i in range(len(unique))]
    largest = max(gaps)
    return 360.0 - largest, largest, len(unique)


def distribution_rows(
    rows: list[dict[str, Any]], value_fields: Sequence[tuple[str, str]]
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    scopes = [
        ("GLOBAL", lambda row: "ALL"),
        ("TIMESTAMP", lambda row: row["timestamp"]),
        ("PRIMARY_CLASS", lambda row: row["primary_class"]),
        ("POINT_TOPOLOGY_FAMILY", lambda row: row["point_topology_family"]),
    ]
    for side in ("INWARD", "OUTWARD"):
        side_rows = [row for row in rows if row["endpoint_side"] == side]
        for scope, key_function in scopes:
            grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
            for row in side_rows:
                grouped[key_function(row)].append(row)
            for group_key in sorted(grouped):
                for metric_name, field in value_fields:
                    result.append({
                        "timestamp_scope": group_key if scope == "TIMESTAMP" else "MULTIPLE_TIMESTAMPS",
                        "scope": scope,
                        "group_key": group_key,
                        "endpoint_side": side,
                        "metric": metric_name,
                        **stats([row[field] for row in grouped[group_key]]),
                        "quantile_method": "LINEAR_TYPE7",
                    })
    return result


def pair_summary_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    scopes = [
        ("GLOBAL", lambda row: "ALL"),
        ("TIMESTAMP", lambda row: row["timestamp"]),
        ("BINDING_MECHANISM", lambda row: row["binding_mechanism"]),
        ("PRIMARY_CLASS", lambda row: row["primary_class"]),
        ("SEARCH_KIND", lambda row: row["search_kind"]),
    ]
    metrics = (
        ("DELTA_RHO_OUT_MINUS_IN", "delta_rho_out_minus_in"),
        ("PHYSICAL_PAIR_SPACING_KW", "physical_pair_spacing_kw"),
        ("SIGNED_PRODUCTION_RAY_SPACING", "signed_production_ray_spacing"),
    )
    for scope, key_function in scopes:
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            grouped[key_function(row)].append(row)
        for key in sorted(grouped):
            selected = grouped[key]
            for metric_name, field in metrics:
                values = [row[field] for row in selected if row[field] is not None]
                result.append({
                    "timestamp_scope": key if scope == "TIMESTAMP" else "MULTIPLE_TIMESTAMPS",
                    "scope": scope,
                    "group_key": key,
                    "metric": metric_name,
                    **stats(values),
                    "expected_ordering_violation_count": sum(row["expected_ordering_violated"] for row in selected),
                    "quantile_method": "LINEAR_TYPE7",
                })
    return result


def build(root: Path, output: Path) -> None:
    prereg = root / PREREG
    prod = root / "results/dso_vpp_ac_map_pilot/production_probe"
    output.mkdir(parents=True, exist_ok=True)

    center_rows = read_csv(prod / "center_results.csv")
    axis_rows = read_csv(prod / "signed_axis_results.csv")
    endpoint_rows = read_csv(prod / "boundary_endpoints.csv")
    facet_rows = read_csv(prereg / "candidate_facets.csv")
    guard_rows = read_csv(prereg / "guard_caps.csv")
    prior_screen = read_csv(prereg / "infeasible_endpoint_exclusion_screen.csv")

    centers = {row["timestamp"]: (f(row["p13_abs_kw"]), f(row["p30_abs_kw"])) for row in center_rows}
    axes_by_time: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in axis_rows:
        axes_by_time[row["timestamp"]].append(row)
    scales_by_time = {timestamp: signed_scales(axes_by_time[timestamp], center) for timestamp, center in centers.items()}

    paired: dict[tuple[str, str, str, str], dict[str, dict[str, str]]] = defaultdict(dict)
    for row in endpoint_rows:
        paired[endpoint_key(row)][row["endpoint_side"]] = row
    if len(centers) != 32 or len(paired) != 1689 or any(set(sides) != {"SAFE", "VIOLATING"} for sides in paired.values()):
        raise SystemExit("frozen endpoint counts do not reconcile")

    constraints_by_time: dict[str, list[dict[str, Any]]] = defaultdict(list)
    normal_semantics: list[dict[str, Any]] = []
    for row in facet_rows:
        normal = (f(row["a13_unit"]), f(row["a30_unit"]))
        raw = (f(row["raw_topology_a13"]), f(row["raw_topology_a30"]))
        constraint = {
            "timestamp": row["timestamp"],
            "constraint_id": row["class_id"],
            "constraint_type": row["constraint_type"],
            "constraint_category": "PHYSICAL_CANDIDATE_FACET",
            "constraint_family": CLASS_FAMILY[row["class_id"]],
            "a13": normal[0],
            "a30": normal[1],
            "b": f(row["b_kw"]),
        }
        constraints_by_time[row["timestamp"]].append(constraint)
        normal_semantics.append({
            "timestamp": row["timestamp"],
            "constraint_id": row["class_id"],
            "constraint_category": constraint["constraint_category"],
            "topology_normal_family": constraint["constraint_family"],
            "raw_a13": raw[0],
            "raw_a30": raw[1],
            "raw_normal_l2_norm": math.hypot(*raw),
            "stored_a13": normal[0],
            "stored_a30": normal[1],
            "stored_normal_l2_norm": math.hypot(*normal),
            "raw_slack_definition": "b-a^T_P; positive inside, zero boundary, negative outside",
            "raw_slack_units": "kW because a is dimensionless and P,b use kW",
            "signed_perpendicular_distance_definition": "(b-a^T_P)/norm2(a); positive inside",
            "signed_perpendicular_distance_units": "kW",
            "prior_inside_margin_semantics": "minimum raw slack over stored Euclidean-unit candidate normals; therefore numerically equals nearest signed perpendicular distance",
        })
    for row in guard_rows:
        normal = (f(row["a13_unit"]), f(row["a30_unit"]))
        constraint = {
            "timestamp": row["timestamp"],
            "constraint_id": row["constraint_id"],
            "constraint_type": row["constraint_type"],
            "constraint_category": "ARTIFICIAL_GUARD_CAP",
            "constraint_family": "ARTIFICIAL_GUARD_CAP",
            "a13": normal[0],
            "a30": normal[1],
            "b": f(row["b_kw"]),
        }
        constraints_by_time[row["timestamp"]].append(constraint)
        normal_semantics.append({
            "timestamp": row["timestamp"],
            "constraint_id": row["constraint_id"],
            "constraint_category": constraint["constraint_category"],
            "topology_normal_family": "ARTIFICIAL_GUARD_CAP",
            "raw_a13": None,
            "raw_a30": None,
            "raw_normal_l2_norm": None,
            "stored_a13": normal[0],
            "stored_a30": normal[1],
            "stored_normal_l2_norm": math.hypot(*normal),
            "raw_slack_definition": "b-a^T_P; positive inside, zero boundary, negative outside",
            "raw_slack_units": "kW because a is dimensionless and P,b use kW",
            "signed_perpendicular_distance_definition": "(b-a^T_P)/norm2(a); positive inside",
            "signed_perpendicular_distance_units": "kW",
            "prior_inside_margin_semantics": "minimum raw slack over stored Euclidean-unit candidate normals; therefore numerically equals nearest signed perpendicular distance",
        })
    for timestamp in constraints_by_time:
        constraints_by_time[timestamp].sort(key=lambda row: row["constraint_id"])

    all_constraints = [item for rows in constraints_by_time.values() for item in rows]
    if len(facet_rows) != 128 or len(guard_rows) != 73 or len(all_constraints) != 201:
        raise SystemExit("frozen constraint counts do not reconcile")
    maximum_unit_norm_error = max(abs(math.hypot(item["a13"], item["a30"]) - 1.0) for item in all_constraints)

    center_depths: list[float] = []
    for timestamp, constraints in constraints_by_time.items():
        center = centers[timestamp]
        for item in constraints:
            item["D"] = item["b"] - dot((item["a13"], item["a30"]), center)
            center_depths.append(item["D"])
            if item["D"] <= 0:
                raise SystemExit(f"nonpositive D for {timestamp} {item['constraint_id']}")

    distance_rows: list[dict[str, Any]] = []
    gauge_rows: list[dict[str, Any]] = []
    gauge_lookup: dict[tuple[tuple[str, str, str, str], str], dict[str, Any]] = {}
    max_gauge_identity_error = 0.0
    equivalence_mismatch_count = 0

    for key in sorted(paired):
        for stored_side, side in (("SAFE", "INWARD"), ("VIOLATING", "OUTWARD")):
            source = paired[key][stored_side]
            timestamp = source["timestamp"]
            p = point(source)
            center = centers[timestamp]
            scales = scales_by_time[timestamp]
            primary = class_id(source)
            context = geometry_context(p, center, scales)
            computed: list[dict[str, Any]] = []
            for constraint in constraints_by_time[timestamp]:
                normal = (constraint["a13"], constraint["a30"])
                norm = math.hypot(*normal)
                slack = constraint["b"] - dot(normal, p)
                perpendicular = slack / norm
                ratio = (dot(normal, p) - dot(normal, center)) / constraint["D"]
                computed.append({"constraint": constraint, "slack": slack, "perpendicular": perpendicular, "ratio": ratio})
            restrictive = min(computed, key=lambda row: (row["perpendicular"], row["constraint"]["constraint_id"]))
            gauge_item = max(computed, key=lambda row: (row["ratio"], row["constraint"]["constraint_id"]))
            rho = gauge_item["ratio"]
            candidate_member = all(row["slack"] >= -ALPHA1_MEMBERSHIP_TOL_KW for row in computed)
            for item in computed:
                constraint = item["constraint"]
                distance_rows.append({
                    "timestamp": timestamp,
                    "endpoint_id": endpoint_id(source),
                    "search_kind": source["search_kind"],
                    "search_id": source["search_id"],
                    "level": source["level"],
                    "endpoint_side": side,
                    "primary_class": primary,
                    "point_topology_family": CLASS_FAMILY[primary],
                    "binding_mechanism": source["binding_mechanism"],
                    "binding_bus": source["binding_bus"],
                    **context,
                    "constraint_id": constraint["constraint_id"],
                    "constraint_category": constraint["constraint_category"],
                    "constraint_family": constraint["constraint_family"],
                    "a13": constraint["a13"],
                    "a30": constraint["a30"],
                    "b_kw": constraint["b"],
                    "normal_l2_norm": math.hypot(constraint["a13"], constraint["a30"]),
                    "raw_halfspace_slack_kw": item["slack"],
                    "signed_perpendicular_distance_kw": item["perpendicular"],
                    "sign_convention": "POSITIVE_INSIDE_ZERO_BOUNDARY_NEGATIVE_OUTSIDE",
                    "candidate_member_at_alpha1": candidate_member,
                    "alpha1_membership_tolerance_kw": ALPHA1_MEMBERSHIP_TOL_KW,
                    "is_most_restrictive_by_perpendicular_distance": constraint["constraint_id"] == restrictive["constraint"]["constraint_id"],
                    "is_gauge_attaining_constraint": constraint["constraint_id"] == gauge_item["constraint"]["constraint_id"],
                })
            gauge_row = {
                "timestamp": timestamp,
                "endpoint_id": endpoint_id(source),
                "search_kind": source["search_kind"],
                "search_id": source["search_id"],
                "level": source["level"],
                "endpoint_side": side,
                "primary_class": primary,
                "point_topology_family": CLASS_FAMILY[primary],
                "binding_mechanism": source["binding_mechanism"],
                "binding_bus": source["binding_bus"],
                **context,
                "rho": rho,
                "gauge_constraint_id": gauge_item["constraint"]["constraint_id"],
                "gauge_constraint_category": gauge_item["constraint"]["constraint_category"],
                "gauge_constraint_family": gauge_item["constraint"]["constraint_family"],
                "gauge_constraint_D_kw": gauge_item["constraint"]["D"],
                "gauge_constraint_alpha1_raw_slack_kw": gauge_item["slack"],
                "gauge_constraint_alpha1_perpendicular_distance_kw": gauge_item["perpendicular"],
                "most_restrictive_constraint_id": restrictive["constraint"]["constraint_id"],
                "most_restrictive_constraint_category": restrictive["constraint"]["constraint_category"],
                "minimum_raw_halfspace_slack_kw": restrictive["slack"],
                "minimum_signed_perpendicular_distance_kw": restrictive["perpendicular"],
                "candidate_member_at_alpha1": candidate_member,
                "alpha1_membership_tolerance_kw": ALPHA1_MEMBERSHIP_TOL_KW,
                "gauge_definition": "max_j((a_j^T P-a_j^T c_t)/(b_j-a_j^T c_t))",
            }
            gauge_rows.append(gauge_row)
            gauge_lookup[(key, side)] = gauge_row

            for alpha in (0.25, 0.5, 0.75, 1.0):
                transformed_slacks = []
                for item in computed:
                    transformed_slack = item["constraint"]["D"] * (alpha - item["ratio"])
                    direct_b = dot((item["constraint"]["a13"], item["constraint"]["a30"]), center) + alpha * item["constraint"]["D"]
                    direct_slack = direct_b - dot((item["constraint"]["a13"], item["constraint"]["a30"]), p)
                    max_gauge_identity_error = max(max_gauge_identity_error, abs(transformed_slack - direct_slack))
                    transformed_slacks.append(direct_slack)
                member_from_halfspaces = all(value >= -IDENTITY_TOL_KW for value in transformed_slacks)
                member_from_gauge = rho <= alpha + GAUGE_COMPARISON_TOL
                equivalence_mismatch_count += member_from_halfspaces != member_from_gauge

    prior_by_key = {
        (row["timestamp"], row["search_kind"], row["search_id"], row["level"]): row for row in prior_screen
    }
    prior_margin_max_error = 0.0
    for key in paired:
        gauge_row = gauge_lookup[(key, "OUTWARD")]
        prior_margin_max_error = max(
            prior_margin_max_error,
            abs(f(prior_by_key[key]["minimum_inside_slack_kw"]) - gauge_row["minimum_raw_halfspace_slack_kw"]),
        )
    prior_timestamp_largest_inside_margins = []
    for timestamp in sorted(centers):
        positive = [
            f(row["minimum_inside_slack_kw"])
            for row in prior_screen
            if row["timestamp"] == timestamp and f(row["minimum_inside_slack_kw"]) > 0
        ]
        prior_timestamp_largest_inside_margins.append(max(positive))

    threshold_rows: list[dict[str, Any]] = []
    retention_rows: list[dict[str, Any]] = []
    limiting_rows: list[dict[str, Any]] = []
    architecture_rows: list[dict[str, Any]] = []
    area_rows: list[dict[str, Any]] = []

    gauges_by_time_side: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in gauge_rows:
        gauges_by_time_side[(row["timestamp"], row["endpoint_side"])].append(row)

    for timestamp in sorted(centers):
        outward = gauges_by_time_side[(timestamp, "OUTWARD")]
        inward = gauges_by_time_side[(timestamp, "INWARD")]
        alpha_sup = min(row["rho"] for row in outward)
        limiting = sorted(
            [row for row in outward if abs(row["rho"] - alpha_sup) <= GAUGE_COMPARISON_TOL],
            key=lambda row: (row["endpoint_id"], row["gauge_constraint_id"]),
        )
        chosen = limiting[0]
        retained_sup = [row for row in inward if row["rho"] <= alpha_sup + GAUGE_COMPARISON_TOL]
        retained_strict = [row for row in inward if row["rho"] < alpha_sup]
        retained_angles = [row["normalized_ray_angle_deg"] for row in retained_strict]
        coverage, largest_gap, unique_angle_count = angular_coverage(retained_angles)
        retained_classes = sorted({row["primary_class"] for row in retained_strict})
        retained_axes = [row for row in retained_strict if row["search_kind"] == "AXIS"]

        threshold_rows.append({
            "timestamp": timestamp,
            "alpha_outward_exclusion_sup": alpha_sup,
            "outward_endpoint_count": len(outward),
            "limiting_outward_endpoint_count_at_gauge_tolerance": len(limiting),
            "gauge_comparison_tolerance": GAUGE_COMPARISON_TOL,
            "strict_exclusion_interpretation": "ALL_STORED_OUTWARD_EXCLUDED_FOR_EXACT_ALPHA_STRICTLY_BELOW_SUPREMUM;EQUALITY_PLACES_LIMITER_ON_BOUNDARY",
            "limiting_endpoint_id": chosen["endpoint_id"],
            "limiting_primary_class": chosen["primary_class"],
            "limiting_constraint_id": chosen["gauge_constraint_id"],
            "limiting_constraint_category": chosen["gauge_constraint_category"],
            "limiting_p13_abs_kw": chosen["p13_abs_kw"],
            "limiting_p30_abs_kw": chosen["p30_abs_kw"],
            "center_p13_abs_kw": chosen["center_p13_abs_kw"],
            "center_p30_abs_kw": chosen["center_p30_abs_kw"],
            "centered_p13_kw": chosen["centered_p13_kw"],
            "centered_p30_kw": chosen["centered_p30_kw"],
            "s13_positive_kw": chosen["s13_positive_kw"],
            "s13_negative_kw": chosen["s13_negative_kw"],
            "s30_positive_kw": chosen["s30_positive_kw"],
            "s30_negative_kw": chosen["s30_negative_kw"],
            "normalized_x": chosen["normalized_x"],
            "normalized_y": chosen["normalized_y"],
            "normalized_ray_angle_deg": chosen["normalized_ray_angle_deg"],
            "limiting_alpha1_raw_slack_kw": chosen["gauge_constraint_alpha1_raw_slack_kw"],
            "limiting_alpha1_perpendicular_distance_kw": chosen["gauge_constraint_alpha1_perpendicular_distance_kw"],
            "coordinate_semantics": chosen["coordinate_semantics"],
            "units": "kW for physical coordinates/slack/distance; dimensionless alpha and normalized coordinates",
            "ray_angle_convention": chosen["ray_angle_convention"],
        })
        retention_rows.append({
            "timestamp": timestamp,
            "coordinate_semantics": "ABSOLUTE_PHYSICAL_P_PCC_ENDPOINTS_WITH_CENTERED_SIGN_NORMALIZED_GAUGE",
            "units": "kW for physical coordinates/scales; dimensionless fractions and alpha",
            "center_p13_abs_kw": centers[timestamp][0],
            "center_p30_abs_kw": centers[timestamp][1],
            **scales_by_time[timestamp],
            "alpha_outward_exclusion_sup": alpha_sup,
            "N_in_total": len(inward),
            "N_in_retained_at_sup": len(retained_sup),
            "fraction_in_retained_at_sup": len(retained_sup) / len(inward),
            "comparison_tolerance_at_sup": GAUGE_COMPARISON_TOL,
            "N_in_strictly_below_sup": len(retained_strict),
            "fraction_in_strictly_below_sup": len(retained_strict) / len(inward),
            "strict_comparison_has_no_subtracted_epsilon": True,
        })
        limiting_rows.append({
            "timestamp": timestamp,
            "classification": "PHYSICAL_CANDIDATE_FACET_LIMITED" if chosen["gauge_constraint_category"] == "PHYSICAL_CANDIDATE_FACET" else "GUARD_CAP_LIMITED",
            "alpha_outward_exclusion_sup": alpha_sup,
            "limiting_endpoint_id": chosen["endpoint_id"],
            "search_kind": chosen["search_kind"],
            "search_id": chosen["search_id"],
            "level": chosen["level"],
            "endpoint_primary_class": chosen["primary_class"],
            "constraint_id": chosen["gauge_constraint_id"],
            "constraint_category": chosen["gauge_constraint_category"],
            "constraint_family": chosen["gauge_constraint_family"],
            "same_primary_class_as_limiting_constraint": chosen["primary_class"] == chosen["gauge_constraint_id"],
            "p13_abs_kw": chosen["p13_abs_kw"],
            "p30_abs_kw": chosen["p30_abs_kw"],
            "center_p13_abs_kw": chosen["center_p13_abs_kw"],
            "center_p30_abs_kw": chosen["center_p30_abs_kw"],
            "centered_p13_kw": chosen["centered_p13_kw"],
            "centered_p30_kw": chosen["centered_p30_kw"],
            "normalized_x": chosen["normalized_x"],
            "normalized_y": chosen["normalized_y"],
            "normalized_ray_angle_deg": chosen["normalized_ray_angle_deg"],
            "s13_positive_kw": chosen["s13_positive_kw"],
            "s13_negative_kw": chosen["s13_negative_kw"],
            "s30_positive_kw": chosen["s30_positive_kw"],
            "s30_negative_kw": chosen["s30_negative_kw"],
            "alpha1_raw_slack_kw": chosen["gauge_constraint_alpha1_raw_slack_kw"],
            "alpha1_perpendicular_distance_kw": chosen["gauge_constraint_alpha1_perpendicular_distance_kw"],
            "coordinate_semantics": chosen["coordinate_semantics"],
            "units": chosen["units"],
            "ray_angle_convention": chosen["ray_angle_convention"],
        })
        architecture_rows.append({
            "timestamp": timestamp,
            "coordinate_semantics": "ABSOLUTE_PHYSICAL_P_PCC_WITH_CENTERED_SIGN_NORMALIZED_PRODUCTION_RAY_DIAGNOSTICS",
            "units": "kW for center/scales; degrees for angular diagnostics; dimensionless fractions",
            "center_p13_abs_kw": centers[timestamp][0],
            "center_p30_abs_kw": centers[timestamp][1],
            **scales_by_time[timestamp],
            "alpha_outward_exclusion_sup": alpha_sup,
            "inward_retained_fraction_at_sup": len(retained_sup) / len(inward),
            "inward_strictly_below_fraction": len(retained_strict) / len(inward),
            "candidate_area_retention_factor_alpha_squared": alpha_sup * alpha_sup,
            "primary_classes_with_retained_inward_point": len(retained_classes),
            "retained_primary_classes": ";".join(retained_classes),
            "retained_unique_production_ray_angle_count": unique_angle_count,
            "retained_angular_coverage_deg": coverage,
            "largest_retained_angular_gap_deg": largest_gap,
            "signed_axis_inward_total": sum(row["search_kind"] == "AXIS" for row in inward),
            "signed_axis_inward_retained_strict_count": len(retained_axes),
            "any_signed_axis_inward_survives": bool(retained_axes),
            "all_signed_axis_inward_survive": len(retained_axes) == sum(row["search_kind"] == "AXIS" for row in inward),
            "retention_basis": "STRICTLY_BELOW_OUTWARD_EXCLUSION_SUPREMUM_WITHOUT_EPSILON",
            "ray_angle_convention": "ATAN2_NORMALIZED_P30_P13_MOD_360_CCW_FROM_POSITIVE_P13",
        })

        candidate = candidate_polygon(constraints_by_time[timestamp])
        base_area = abs(polygon_signed_area(candidate))
        alpha_errors = []
        for alpha in (0.25, 0.5, 0.75, alpha_sup):
            transformed = [
                (centers[timestamp][0] + alpha * (p[0] - centers[timestamp][0]), centers[timestamp][1] + alpha * (p[1] - centers[timestamp][1]))
                for p in candidate
            ]
            measured = abs(polygon_signed_area(transformed))
            expected = alpha * alpha * base_area
            alpha_errors.append((abs(measured - expected), abs(measured - expected) / expected if expected else 0.0))
        area_rows.append({
            "timestamp": timestamp,
            "coordinate_semantics": "ABSOLUTE_PHYSICAL_P_PCC_HOMOTHETY_ABOUT_CERTIFIED_PRODUCTION_CENTER",
            "units": "kW center coordinates; kW^2 area; dimensionless alpha and retention",
            "center_p13_abs_kw": centers[timestamp][0],
            "center_p30_abs_kw": centers[timestamp][1],
            **scales_by_time[timestamp],
            "alpha_outward_exclusion_sup": alpha_sup,
            "alpha_squared_geometric_area_retention": alpha_sup * alpha_sup,
            "alpha1_guard_capped_candidate_area_kw2": base_area,
            "area_at_sup_by_exact_scaling_kw2": alpha_sup * alpha_sup * base_area,
            "verification_alpha_values": "0.25;0.5;0.75;alpha_outward_exclusion_sup",
            "maximum_absolute_alpha_squared_identity_error_kw2": max(value[0] for value in alpha_errors),
            "maximum_relative_alpha_squared_identity_error": max(value[1] for value in alpha_errors),
            "identity": "AREA(c+alpha(K-c))=alpha^2*AREA(K)",
            "interpretation": "GEOMETRIC_CONSEQUENCE_NOT_ACCEPTED_FINAL_AREA_RETENTION_FACTOR",
        })

        # Threshold-specific equivalence check, supplementing fixed-alpha checks above.
        for row in inward + outward:
            p = (row["p13_abs_kw"], row["p30_abs_kw"])
            direct = []
            for constraint in constraints_by_time[timestamp]:
                contracted_b = dot((constraint["a13"], constraint["a30"]), centers[timestamp]) + alpha_sup * constraint["D"]
                direct.append(contracted_b - dot((constraint["a13"], constraint["a30"]), p))
            equivalence_mismatch_count += (all(value >= -IDENTITY_TOL_KW for value in direct) != (row["rho"] <= alpha_sup + GAUGE_COMPARISON_TOL))

    pair_rows: list[dict[str, Any]] = []
    for key in sorted(paired):
        inward = gauge_lookup[(key, "INWARD")]
        outward = gauge_lookup[(key, "OUTWARD")]
        safe_source, violating_source = paired[key]["SAFE"], paired[key]["VIOLATING"]
        delta = outward["rho"] - inward["rho"]
        signed_radial = None
        signed_radial_semantics = "NOT_APPLICABLE_TO_SIGNED_AXIS_SEARCH"
        if safe_source["search_kind"] == "RAY":
            signed_radial = f(violating_source["radius"]) - f(safe_source["radius"])
            signed_radial_semantics = "OUTWARD_MINUS_INWARD_NORMALIZED_PRODUCTION_RAY_RADIUS"
        pair_rows.append({
            "timestamp": key[0],
            "endpoint_id": endpoint_id(safe_source),
            "search_kind": safe_source["search_kind"],
            "search_id": safe_source["search_id"],
            "level": safe_source["level"],
            "binding_mechanism": safe_source["binding_mechanism"],
            "primary_class": class_id(safe_source),
            "point_topology_family": CLASS_FAMILY[class_id(safe_source)],
            "rho_in": inward["rho"],
            "rho_out": outward["rho"],
            "delta_rho_out_minus_in": delta,
            "expected_ordering_violated": delta < -GAUGE_COMPARISON_TOL,
            "ordering_tolerance": GAUGE_COMPARISON_TOL,
            "physical_pair_spacing_kw": math.dist(point(safe_source), point(violating_source)),
            "signed_production_ray_spacing": signed_radial,
            "signed_production_ray_spacing_semantics": signed_radial_semantics,
            "inward_p13_abs_kw": inward["p13_abs_kw"],
            "inward_p30_abs_kw": inward["p30_abs_kw"],
            "outward_p13_abs_kw": outward["p13_abs_kw"],
            "outward_p30_abs_kw": outward["p30_abs_kw"],
            "center_p13_abs_kw": inward["center_p13_abs_kw"],
            "center_p30_abs_kw": inward["center_p30_abs_kw"],
            "s13_positive_kw": inward["s13_positive_kw"],
            "s13_negative_kw": inward["s13_negative_kw"],
            "s30_positive_kw": inward["s30_positive_kw"],
            "s30_negative_kw": inward["s30_negative_kw"],
            "inward_normalized_angle_deg": inward["normalized_ray_angle_deg"],
            "outward_normalized_angle_deg": outward["normalized_ray_angle_deg"],
            "coordinate_semantics": inward["coordinate_semantics"],
            "units": "kW for physical spacing and coordinates; dimensionless for rho and ray radius",
            "ray_angle_convention": inward["ray_angle_convention"],
        })

    angular_summary: list[dict[str, Any]] = []
    angular_screen: list[dict[str, Any]] = []
    hull_rows: list[dict[str, Any]] = []
    area_by_time = {row["timestamp"]: row for row in area_rows}
    for timestamp in sorted(centers):
        inward = gauges_by_time_side[(timestamp, "INWARD")]
        outward = gauges_by_time_side[(timestamp, "OUTWARD")]
        prepared = [
            {
                "point": (row["p13_abs_kw"], row["p30_abs_kw"]),
                "angle": row["normalized_ray_angle_deg"],
                "radius": row["normalized_radius"],
                "endpoint_id": row["endpoint_id"],
            }
            for row in inward
        ]
        groups = angular_groups(prepared)
        selected_rows = [sorted(group, key=lambda row: (-row["radius"], row["endpoint_id"], row["point"]))[0] for group in groups]
        selected_rows.sort(key=lambda row: (row["angle"], row["endpoint_id"]))
        vertices = [row["point"] for row in selected_rows]
        duplicate_angle_groups = sum(len(group) > 1 for group in groups)
        duplicate_angle_rows = sum(len(group) - 1 for group in groups)
        duplicate_point_pairs = sum(
            math.dist(prepared[i]["point"], prepared[j]["point"]) <= DUPLICATE_POINT_TOL_KW
            for i in range(len(prepared)) for j in range(i + 1, len(prepared))
        )
        zero_edges = sum(math.dist(vertices[i], vertices[(i + 1) % len(vertices)]) <= POLYGON_BOUNDARY_TOL_KW for i in range(len(vertices)))
        signed_area = polygon_signed_area(vertices)
        orientation = "COUNTERCLOCKWISE" if signed_area > 0 else "CLOCKWISE" if signed_area < 0 else "DEGENERATE"
        intersections = polygon_self_intersection_count(vertices)
        simple = intersections == 0 and zero_edges == 0 and abs(signed_area) > 0
        convex = polygon_is_convex(vertices) if simple else False
        center_location = point_in_polygon(centers[timestamp], vertices, POLYGON_BOUNDARY_TOL_KW) if simple else "NOT_TESTED_NON_SIMPLE"
        input_locations = [point_in_polygon(item["point"], vertices, POLYGON_BOUNDARY_TOL_KW) for item in prepared] if simple else []
        input_counts = Counter(input_locations)
        out_locations = [point_in_polygon((row["p13_abs_kw"], row["p30_abs_kw"]), vertices, POLYGON_BOUNDARY_TOL_KW) for row in outward] if simple else []
        out_counts = Counter(out_locations)
        angular_area = abs(signed_area) if simple else None
        construction = "SUCCESS_SIMPLE_ANGULAR_INWARD_POLYGON" if simple else "FAILED_NON_SIMPLE_OR_DEGENERATE"
        angular_summary.append({
            "timestamp": timestamp,
            "comparator": "ANGULAR_INWARD_POLYGON_CANDIDATE_DIAGNOSTIC",
            "input_inward_physical_boundary_row_count": len(prepared),
            "guard_truncation_input_count": 0,
            "duplicate_point_pair_count_at_tolerance": duplicate_point_pairs,
            "duplicate_point_tolerance_kw": DUPLICATE_POINT_TOL_KW,
            "duplicate_angle_group_count": duplicate_angle_groups,
            "duplicate_angle_nonselected_row_count": duplicate_angle_rows,
            "duplicate_angle_tolerance_deg": DUPLICATE_ANGLE_TOL_DEG,
            "duplicate_angle_rule": "SELECT_MAXIMUM_NORMALIZED_RADIUS_THEN_ENDPOINT_ID;RETAIN_NONSELECTED_INPUTS_FOR_CONTAINMENT_CHECK",
            "polygon_vertex_count": len(vertices),
            "zero_length_edge_count": zero_edges,
            "self_intersection_count": intersections,
            "orientation": orientation,
            "is_simple": simple,
            "is_convex": convex,
            "production_center_location": center_location,
            "contains_production_center": center_location in {"INSIDE", "BOUNDARY"},
            "input_inward_inside_count": input_counts["INSIDE"],
            "input_inward_boundary_count": input_counts["BOUNDARY"],
            "input_inward_outside_count": input_counts["OUTSIDE"],
            "all_input_inward_on_or_inside": input_counts["OUTSIDE"] == 0 if simple else False,
            "polygon_area_kw2": angular_area,
            "construction_status": construction,
            "coordinate_semantics": "VERTICES_ARE_ABSOLUTE_PHYSICAL_PCC;ORDER_USES_CENTERED_SIGN_NORMALIZED_PRODUCTION_RAY_ANGLE",
            "units": "kW coordinates; kW^2 area; degrees angle",
            "center_p13_abs_kw": centers[timestamp][0],
            "center_p30_abs_kw": centers[timestamp][1],
            **scales_by_time[timestamp],
            "ray_angle_convention": "ATAN2_NORMALIZED_P30_P13_MOD_360_CCW_FROM_POSITIVE_P13",
        })
        angular_screen.append({
            "timestamp": timestamp,
            "comparator": "ANGULAR_INWARD_POLYGON_CANDIDATE_DIAGNOSTIC",
            "construction_status": construction,
            "N_out_total": len(outward),
            "N_out_inside": out_counts["INSIDE"],
            "N_out_boundary": out_counts["BOUNDARY"],
            "N_out_outside": out_counts["OUTSIDE"],
            "geometric_tolerance_kw": POLYGON_BOUNDARY_TOL_KW,
            "all_input_inward_on_or_inside": input_counts["OUTSIDE"] == 0 if simple else False,
            "coordinate_semantics": "ABSOLUTE_PHYSICAL_P_PCC_SCREEN_AGAINST_ANGULAR_POLYGON",
            "units": "kW",
            "center_p13_abs_kw": centers[timestamp][0],
            "center_p30_abs_kw": centers[timestamp][1],
            **scales_by_time[timestamp],
            "ray_angle_convention": "ATAN2_NORMALIZED_P30_P13_MOD_360_CCW_FROM_POSITIVE_P13",
        })

        hull = convex_hull([item["point"] for item in prepared])
        hull_area = abs(polygon_signed_area(hull))
        hull_locations = [point_in_polygon((row["p13_abs_kw"], row["p30_abs_kw"]), hull, POLYGON_BOUNDARY_TOL_KW) for row in outward]
        hull_counts = Counter(hull_locations)
        hull_vertex_input_count = sum(any(math.dist(item["point"], vertex) <= DUPLICATE_POINT_TOL_KW for vertex in hull) for item in prepared)
        hull_rows.append({
            "timestamp": timestamp,
            "comparator": "INWARD_POINT_CONVEX_HULL_DIAGNOSTIC",
            "inward_input_count": len(prepared),
            "unique_inward_coordinate_count": len(set(item["point"] for item in prepared)),
            "hull_vertex_count": len(hull),
            "input_rows_at_hull_vertices": hull_vertex_input_count,
            "fraction_inward_points_that_are_hull_vertices": hull_vertex_input_count / len(prepared),
            "N_out_total": len(outward),
            "N_out_inside": hull_counts["INSIDE"],
            "N_out_boundary": hull_counts["BOUNDARY"],
            "N_out_outside": hull_counts["OUTSIDE"],
            "geometric_tolerance_kw": POLYGON_BOUNDARY_TOL_KW,
            "hull_area_kw2": hull_area,
            "alpha1_candidate_area_kw2": area_by_time[timestamp]["alpha1_guard_capped_candidate_area_kw2"],
            "angular_inward_polygon_area_kw2": angular_area,
            "area_ratio_to_alpha1_candidate": hull_area / area_by_time[timestamp]["alpha1_guard_capped_candidate_area_kw2"],
            "area_ratio_to_angular_inward_polygon": hull_area / angular_area if angular_area else None,
            "coordinate_semantics": "ABSOLUTE_PHYSICAL_P_PCC_CONVEX_HULL_OF_CERTIFIED_INWARD_PHYSICAL_BOUNDARY_POINTS",
            "units": "kW coordinates; kW^2 area",
            "center_p13_abs_kw": centers[timestamp][0],
            "center_p30_abs_kw": centers[timestamp][1],
            **scales_by_time[timestamp],
            "ray_angle_convention": "ATAN2_NORMALIZED_P30_P13_MOD_360_CCW_FROM_POSITIVE_P13",
            "role": "DIAGNOSTIC_ONLY_NOT_DOE_POLICY",
        })

    distance_summary = distribution_rows(
        distance_rows,
        (
            ("ALL_CONSTRAINT_RAW_HALFSPACE_SLACK_KW", "raw_halfspace_slack_kw"),
            ("ALL_CONSTRAINT_SIGNED_PERPENDICULAR_DISTANCE_KW", "signed_perpendicular_distance_kw"),
        ),
    )
    # Add distributions of the nearest/restrictive constraint from one row per point.
    distance_summary.extend(distribution_rows(
        gauge_rows,
        (
            ("MOST_RESTRICTIVE_RAW_HALFSPACE_SLACK_KW", "minimum_raw_halfspace_slack_kw"),
            ("MOST_RESTRICTIVE_SIGNED_PERPENDICULAR_DISTANCE_KW", "minimum_signed_perpendicular_distance_kw"),
        ),
    ))
    distance_summary.sort(key=lambda row: (row["scope"], row["group_key"], row["endpoint_side"], row["metric"]))
    gauge_summary = distribution_rows(gauge_rows, (("HOMOTHETIC_GAUGE_RHO", "rho"),))
    gauge_summary.sort(key=lambda row: (row["scope"], row["group_key"], row["endpoint_side"]))
    pair_summaries = pair_summary_rows(pair_rows)

    architecture_summary: list[dict[str, Any]] = []
    for metric, field, units in (
        ("INWARD_RETAINED_FRACTION_AT_SUP", "inward_retained_fraction_at_sup", "dimensionless"),
        ("INWARD_STRICTLY_BELOW_FRACTION", "inward_strictly_below_fraction", "dimensionless"),
        ("CANDIDATE_AREA_RETENTION_ALPHA_SQUARED", "candidate_area_retention_factor_alpha_squared", "dimensionless"),
        ("PRIMARY_CLASSES_WITH_RETAINED_POINT", "primary_classes_with_retained_inward_point", "count"),
        ("RETAINED_UNIQUE_RAY_ANGLE_COUNT", "retained_unique_production_ray_angle_count", "count"),
        ("RETAINED_ANGULAR_COVERAGE_DEG", "retained_angular_coverage_deg", "degrees"),
        ("LARGEST_RETAINED_ANGULAR_GAP_DEG", "largest_retained_angular_gap_deg", "degrees"),
        ("SIGNED_AXIS_RETAINED_STRICT_COUNT", "signed_axis_inward_retained_strict_count", "count"),
    ):
        architecture_summary.append({
            "timestamp_scope": "ALL_32_TIMESTAMPS",
            "metric": metric,
            "units": units,
            **stats([row[field] for row in architecture_rows]),
            "quantile_method": "LINEAR_TYPE7",
            "coordinate_semantics": "TIMESTAMP_AGGREGATE_OF_ABSOLUTE_PCC_AND_CENTERED_SIGN_NORMALIZED_PRODUCTION_RAY_DIAGNOSTICS",
        })

    verification_rows = [{
        "candidate_constraint_count": len(all_constraints),
        "minimum_center_depth_D_kw": min(center_depths),
        "maximum_center_depth_D_kw": max(center_depths),
        "all_center_depths_strictly_positive": all(value > 0 for value in center_depths),
        "maximum_stored_normal_norm_error_from_one": maximum_unit_norm_error,
        "maximum_direct_vs_D_times_alpha_minus_ratio_identity_error_kw": max_gauge_identity_error,
        "membership_equivalence_comparison_tolerance_kw": IDENTITY_TOL_KW,
        "gauge_comparison_tolerance": GAUGE_COMPARISON_TOL,
        "membership_equivalence_mismatch_count": equivalence_mismatch_count,
        "membership_equivalence_checks": len(gauge_rows) * 5,
        "alphas_checked": "0.25;0.5;0.75;1.0;timestamp_alpha_outward_exclusion_sup",
        "maximum_reconstructed_prior_inside_margin_error_kw": prior_margin_max_error,
        "gauge_equivalence_statement": "P_IN_K_ALPHA_IFF_RHO_LE_ALPHA_WITH_REPORTED_COMPARISON_TOLERANCES",
    }]

    write_csv(output / "halfspace_normal_and_margin_semantics.csv", normal_semantics)
    write_csv(output / "inward_outward_distance_distribution.csv", distance_rows)
    write_csv(output / "inward_outward_distance_distribution_summary.csv", distance_summary)
    write_csv(output / "homothetic_gauge_all_points.csv", gauge_rows)
    write_csv(output / "homothetic_gauge_distribution_summary.csv", gauge_summary)
    write_csv(output / "homothetic_gauge_verification.csv", verification_rows)
    write_csv(output / "alpha_outward_exclusion_threshold_by_timestamp.csv", threshold_rows)
    write_csv(output / "inward_retention_at_outward_threshold.csv", retention_rows)
    write_csv(output / "paired_inward_outward_gauge_separation.csv", pair_rows)
    write_csv(output / "paired_inward_outward_gauge_separation_summary.csv", pair_summaries)
    write_csv(output / "area_retention_by_timestamp.csv", area_rows)
    write_csv(output / "limiting_constraint_summary.csv", limiting_rows)
    write_csv(output / "architecture_viability_diagnostics.csv", architecture_rows)
    write_csv(output / "architecture_viability_diagnostics_summary.csv", architecture_summary)
    write_csv(output / "angular_inward_polygon_summary.csv", angular_summary)
    write_csv(output / "angular_inward_polygon_outward_screen.csv", angular_screen)
    write_csv(output / "inward_convex_hull_diagnostic.csv", hull_rows)

    alpha_stats = stats([row["alpha_outward_exclusion_sup"] for row in threshold_rows])
    area_stats = stats([row["alpha_squared_geometric_area_retention"] for row in area_rows])
    retained_sup_stats = stats([row["fraction_in_retained_at_sup"] for row in retention_rows])
    retained_strict_stats = stats([row["fraction_in_strictly_below_sup"] for row in retention_rows])
    coverage_stats = stats([row["retained_angular_coverage_deg"] for row in architecture_rows])
    gap_stats = stats([row["largest_retained_angular_gap_deg"] for row in architecture_rows])
    class_count_stats = stats([row["primary_classes_with_retained_inward_point"] for row in architecture_rows])
    axis_count_stats = stats([row["signed_axis_inward_retained_strict_count"] for row in architecture_rows])
    rho_in_stats = stats([row["rho"] for row in gauge_rows if row["endpoint_side"] == "INWARD"])
    rho_out_stats = stats([row["rho"] for row in gauge_rows if row["endpoint_side"] == "OUTWARD"])
    delta_stats = stats([row["delta_rho_out_minus_in"] for row in pair_rows])
    spacing_stats = stats([row["physical_pair_spacing_kw"] for row in pair_rows])
    limit_counts = Counter(row["classification"] for row in limiting_rows)
    class_match_count = sum(row["same_primary_class_as_limiting_constraint"] for row in limiting_rows)
    pair_order_violations = sum(row["expected_ordering_violated"] for row in pair_rows)
    total_inward = sum(row["N_in_total"] for row in retention_rows)
    total_sup = sum(row["N_in_retained_at_sup"] for row in retention_rows)
    total_strict = sum(row["N_in_strictly_below_sup"] for row in retention_rows)
    angular_out = Counter()
    for row in angular_screen:
        angular_out["inside"] += row["N_out_inside"]
        angular_out["boundary"] += row["N_out_boundary"]
        angular_out["outside"] += row["N_out_outside"]
    hull_out = Counter()
    for row in hull_rows:
        hull_out["inside"] += row["N_out_inside"]
        hull_out["boundary"] += row["N_out_boundary"]
        hull_out["outside"] += row["N_out_outside"]

    def stat_line(label: str, values: dict[str, Any], percent: bool = False) -> str:
        scale = 100.0 if percent else 1.0
        suffix = "%" if percent else ""
        return f"- {label}: min {values['min']*scale:.12g}{suffix}; Q1 {values['q1']*scale:.12g}{suffix}; median {values['median']*scale:.12g}{suffix}; Q3 {values['q3']*scale:.12g}{suffix}; max {values['max']*scale:.12g}{suffix}."

    alpha_table = "\n".join(
        f"| {row['timestamp']} | {row['alpha_outward_exclusion_sup']:.12g} | {row['alpha_outward_exclusion_sup']**2:.12g} | {next(item for item in retention_rows if item['timestamp'] == row['timestamp'])['N_in_strictly_below_sup']}/{next(item for item in retention_rows if item['timestamp'] == row['timestamp'])['N_in_total']} | {row['limiting_constraint_category']} |"
        for row in threshold_rows
    )
    report = f"""# Geometric contraction threshold audit (artifact only)

## Safety and scope

- Starting branch: `{SOURCE_BRANCH}`
- Starting HEAD: `{SOURCE_HEAD}`
- Initial status: only the frozen untracked preregistration directory and its generator were present.
- This separate audit reads frozen artifacts and changes no topology normal, offset, guard cap, DOE policy, or historical production result.
- No AC solve, replay, production probe, HC/TVPP optimization, substantive mesh, runtime benchmark, alpha-policy selection, monotonicity rerun, or deferred 1,561-boundary slope study was performed.
- Production DOE geometry is stored directly in absolute physical PCC coordinates with `reference_pv_capacity_kw=0` and `Q_PCC=0`. The resolved historical Phase-B relation remains `P_PCC_13_abs=P_command_13+777.7133428167988 kW`; it is not applied to production DOE rows.

## Margin semantics and normals

The previously reported "inside margin" is exactly `min_j(b_j-a_j^T P)` over the full alpha=1 candidate. It is raw halfspace slack: positive inside, zero on the boundary, negative outside. Here `a_j` was stored after positive Euclidean unit normalization, so the raw slack (kW) is numerically equal to the signed perpendicular distance `(b_j-a_j^T P)/||a_j||_2` (kW). That equivalence would not hold for arbitrarily scaled normals. The prior timestamp-summary range {min(prior_timestamp_largest_inside_margins):.12g} to {max(prior_timestamp_largest_inside_margins):.12g} kW is therefore both raw unit-normal slack and signed perpendicular distance in this specific representation, not an invariant distance under arbitrary normal scaling.

The raw topology norm for VMAX/13 and VMIN/18 is `{math.hypot(f(facet_rows[0]['raw_topology_a13']), f(facet_rows[0]['raw_topology_a30'])):.15g}`; the raw norm for VMAX/30 and VMIN/33 is `{math.hypot(f(facet_rows[1]['raw_topology_a13']), f(facet_rows[1]['raw_topology_a30'])):.15g}`. Every stored physical/guard candidate normal has norm 1 within maximum error `{maximum_unit_norm_error:.3g}`. The prior margins were reconstructed with maximum error `{prior_margin_max_error:.3g}` kW. Full point-constraint values and grouped distributions are in the distance CSVs.

## Homothetic gauge and outward threshold

For every actual physical facet and guard cap, `D_jt=b_jt-a_jt^T c_t` was checked: all {len(center_depths)} values are positive, ranging from {min(center_depths):.12g} to {max(center_depths):.12g} kW. The audit uses exactly `rho_t(P)=max_j[(a_jt^T P-a_jt^T c_t)/D_jt]`. Direct contracted-halfspace membership and `rho<=alpha` were compared for all 3,378 endpoints at alpha 0.25, 0.5, 0.75, 1, and the timestamp threshold: {equivalence_mismatch_count} mismatches at {IDENTITY_TOL_KW:.3g} kW halfspace and {GAUGE_COMPARISON_TOL:.3g} gauge comparison tolerances; maximum algebraic identity error was {max_gauge_identity_error:.3g} kW.

`alpha_outward_exclusion_sup,t=min rho_t(P_out)`. Exact alpha strictly below it excludes every stored outward point; equality leaves at least one limiter on the boundary and is not relabeled as a final alpha.

{stat_line('alpha outward-exclusion supremum', alpha_stats)}
{stat_line('alpha-squared area consequence', area_stats, True)}

| timestamp | alpha supremum | alpha^2 | inward strictly below / total | limiter type |
|---|---:|---:|---:|---|
{alpha_table}

Limiter counts: {limit_counts['PHYSICAL_CANDIDATE_FACET_LIMITED']} physical-candidate-facet-limited and {limit_counts['GUARD_CAP_LIMITED']} guard-cap-limited. The limiter constraint matches the outward endpoint's primary class in {class_match_count}/32 timestamps; mismatches are retained as observations.

## Certified inward evidence retained

At the supremum with comparison tolerance, {total_sup}/{total_inward} inward points ({100*total_sup/total_inward:.12g}%) are retained. Under the strict `< alpha_sup` interpretation before any epsilon, {total_strict}/{total_inward} ({100*total_strict/total_inward:.12g}%) are retained.

{stat_line('per-timestamp retained fraction at supremum', retained_sup_stats, True)}
{stat_line('per-timestamp fraction strictly below supremum', retained_strict_stats, True)}

Gauge distributions show the paired clouds directly:

{stat_line('inward rho', rho_in_stats)}
{stat_line('outward rho', rho_out_stats)}
{stat_line('paired delta rho = rho_out-rho_in', delta_stats)}
{stat_line('physical inward/outward bracket spacing (kW)', spacing_stats)}

There are {pair_order_violations} pairwise gauge-ordering violations at tolerance {GAUGE_COMPARISON_TOL:.3g}; none were sign-corrected. Full global/timestamp/VMAX-VMIN/class/ray-axis summaries are provided.

The two-dimensional area consequence is exactly `alpha_sup^2`; this is not an accepted operational factor. Independent polygon calculations at four deterministic alpha values have maximum relative identity error {max(row['maximum_relative_alpha_squared_identity_error'] for row in area_rows):.3g}.

## Neutral architecture diagnostics

The retained class count, exact normalized angular coverage, largest gap, and signed-axis survival are reported per timestamp in `architecture_viability_diagnostics.csv`; no viability threshold or post-hoc category is introduced.

{stat_line('retained angular coverage (degrees)', coverage_stats)}
{stat_line('largest retained angular gap (degrees)', gap_stats)}
{stat_line('primary classes represented among retained points', class_count_stats)}
{stat_line('signed-axis inward endpoints retained strictly', axis_count_stats)}

## Angular inward polygon and convex hull comparators

All 32 angular constructions are simple: {sum(row['is_simple'] for row in angular_summary)}/32; all contain the production center: {sum(row['contains_production_center'] for row in angular_summary)}/32; convex: {sum(row['is_convex'] for row in angular_summary)}/32. Duplicate-angle groups are handled deterministically by selecting maximum normalized radius, then endpoint ID, while all nonselected inward rows remain in the containment check. All-input inward containment passes in {sum(row['all_input_inward_on_or_inside'] for row in angular_summary)}/32 timestamps.

Against the angular polygons, stored outward endpoints are: {angular_out['inside']} inside, {angular_out['boundary']} on boundary, and {angular_out['outside']} outside at {POLYGON_BOUNDARY_TOL_KW:.3g} kW. This result is measured, not inferred from paired directions.

The optional artifact-only convex hull comparator was also produced. Stored outward endpoints are: {hull_out['inside']} inside, {hull_out['boundary']} on boundary, and {hull_out['outside']} outside. Hull vertex fractions and areas relative to the alpha=1 candidate and angular polygon are reported per timestamp. It remains diagnostic only.

## Outputs and reproducibility contract

`artifact_manifest.csv` lists every generated audit artifact other than itself plus this generator, with deterministic byte size and SHA-256. The generator accepts `--output` so clean-location reconstructions can be compared byte-for-byte without embedding temporary paths. The external two-pass reconstruction result is reported with the task handoff.

## Quantitative consequence

Global homothetic contraction to the stored-outward exclusion supremum retains {100*total_sup/total_inward:.12g}% of measured certified-feasible inward boundary points using the supremum comparison tolerance, and {100*total_strict/total_inward:.12g}% under strict comparison before any epsilon. Per timestamp, the strict retained fraction ranges from {100*retained_strict_stats['min']:.12g}% to {100*retained_strict_stats['max']:.12g}% (median {100*retained_strict_stats['median']:.12g}%), while the geometric candidate-area consequence ranges from {100*area_stats['min']:.12g}% to {100*area_stats['max']:.12g}% (median {100*area_stats['median']:.12g}%). These percentages state the evidence loss without assigning an unpreregistered viability label.
"""
    write_text(output / "geometric_contraction_audit_report.md", report)

    generated = sorted(path for path in output.iterdir() if path.is_file() and path.name != "artifact_manifest.csv")
    manifest_rows = [
        {"path": (CANONICAL_OUTPUT / path.name).as_posix(), "bytes": path.stat().st_size, "sha256": sha256(path)}
        for path in generated
    ]
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
