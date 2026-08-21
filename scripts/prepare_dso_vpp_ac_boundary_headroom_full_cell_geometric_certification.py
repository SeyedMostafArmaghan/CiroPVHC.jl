from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import subprocess
from collections import Counter, defaultdict
from pathlib import Path


AUDIT_BASE_COMMIT = "32fc5697fdeb5a2a2fb0395d09e56db7c47250e2"
PREREGISTRATION_COMMIT = "fc15fbf7bf93ca89c2ab4a45145f937abbc70f63"
GEOMETRY_SOURCE_COMMIT = "ba88f54f52f7bcd03df2466ce69dff2b9b1c538b"
SOURCE_BRANCH = "codex/dso-vpp-ac-map-pilot"
SCHEMA_VERSION = 1
METHOD = "IMMUTABLE_COMMITTED_INPUTS_ZERO_AC_FULL_CELL_LINE_CERTIFICATION"

COORD_TOL_KW = 1.0e-8
GEOMETRY_TOL_KW = 1.0e-7
DIRECTION_TOL = 1.0e-12
SLOPE_TOL = 1.0e-12
CAP_TIE_TOL_KW = 1.0e-8
CAP_GUARD_KW = GEOMETRY_TOL_KW
GRID_RESOLUTION_KW = 0.25

ROOT = Path(__file__).resolve().parents[1]
GENERATOR_PATH = (
    "scripts/prepare_dso_vpp_ac_boundary_headroom_full_cell_geometric_certification.py"
)
PREREGISTRATION_DIR = (
    "results/dso_vpp_ac_map_pilot/doe_ac_boundary_headroom_repair_preregistration"
)
CELL_DIR = (
    "results/dso_vpp_ac_map_pilot/doe_construction_policy_preregistration/"
    "convex_piecewise_architecture_audit"
)
POLYGON_DIR = (
    "results/dso_vpp_ac_map_pilot/doe_ac_interior_validation_preregistration"
)
OUTDIR = ROOT / (
    "results/dso_vpp_ac_map_pilot/"
    "doe_ac_boundary_headroom_full_cell_geometric_certification_v1"
)

MEMBERSHIP_PATH = f"{PREREGISTRATION_DIR}/calibration_fraction_inventory.csv"
POLICY_PATH = f"{PREREGISTRATION_DIR}/edge_repair_policy.csv"
REPAIR_CONFIG_PATH = f"{PREREGISTRATION_DIR}/repair_config.json"
PREREGISTRATION_MANIFEST_PATH = f"{PREREGISTRATION_DIR}/manifest.json"
PREREGISTRATION_SOURCE_MANIFEST_PATH = f"{PREREGISTRATION_DIR}/source_manifest.json"
CELL_PATH = f"{CELL_DIR}/merged_convex_cells.csv"
CELL_MANIFEST_PATH = f"{CELL_DIR}/artifact_manifest.csv"
POLYGON_PATH = f"{POLYGON_DIR}/validation_polygon_edges.csv"

SOURCE_ARTIFACTS = [
    (PREREGISTRATION_COMMIT, MEMBERSHIP_PATH, "locked probe memberships and source coordinates"),
    (PREREGISTRATION_COMMIT, POLICY_PATH, "registered owner cells and immutable inward directions"),
    (PREREGISTRATION_COMMIT, REPAIR_CONFIG_PATH, "locked predecessor repair configuration"),
    (PREREGISTRATION_COMMIT, PREREGISTRATION_MANIFEST_PATH, "predecessor output integrity manifest"),
    (PREREGISTRATION_COMMIT, PREREGISTRATION_SOURCE_MANIFEST_PATH, "predecessor immutable source manifest"),
    (GEOMETRY_SOURCE_COMMIT, CELL_PATH, "committed CCW convex owner-cell vertices"),
    (GEOMETRY_SOURCE_COMMIT, CELL_MANIFEST_PATH, "committed cell artifact integrity manifest"),
    (GEOMETRY_SOURCE_COMMIT, POLYGON_PATH, "registered polygon facet endpoints"),
]

CLASSIFICATIONS = [
    "INPUT_PROVENANCE_MISMATCH",
    "CELL_GEOMETRY_INVALID",
    "REGISTERED_FACET_OWNERSHIP_MISMATCH",
    "SOURCE_POINT_OUTSIDE_OWNER_CELL",
    "FULL_CELL_TOLERANCE_AMBIGUITY",
    "NO_POSITIVE_FULL_CELL_MOVEMENT",
    "FULL_CELL_CAP_BELOW_GRID",
    "GEOMETRICALLY_CERTIFIED",
]

CONTENT_NAMES = {
    "full_cell_probe_limits.csv",
    "full_cell_limit_checks.csv",
    "full_cell_repair_config.json",
    "source_manifest.json",
    "summary_report.md",
}
EXPECTED_NAMES = CONTENT_NAMES | {"hashes.sha256", "manifest.json"}


def git(*args: str) -> bytes:
    return subprocess.check_output(["git", *args], cwd=ROOT)


def git_bytes(commit: str, path: str) -> bytes:
    return git("show", f"{commit}:{path}")


def read_csv_bytes(data: bytes) -> list[dict[str, str]]:
    return list(csv.DictReader(io.StringIO(data.decode("utf-8-sig"))))


def read_csv_git(commit: str, path: str) -> list[dict[str, str]]:
    return read_csv_bytes(git_bytes(commit, path))


def read_json_git(commit: str, path: str):
    return json.loads(git_bytes(commit, path).decode("utf-8-sig"))


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def truth(value: str) -> bool:
    return value.strip().lower() == "true"


def finite(value: float) -> bool:
    return math.isfinite(value)


def fmt(value) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, float):
        if math.isnan(value):
            return "NaN"
        if math.isinf(value):
            return "Infinity" if value > 0 else "-Infinity"
        return format(value, ".15g")
    return str(value)


def write_text(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8", newline="\n")


def write_csv(path: Path, fields: list[str], rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: fmt(row.get(field)) for field in fields})


def polygon_area(vertices: list[tuple[float, float]]) -> float:
    return 0.5 * sum(
        a[0] * b[1] - b[0] * a[1]
        for a, b in zip(vertices, vertices[1:] + vertices[:1])
    )


def componentwise_close(
    a: tuple[float, float], b: tuple[float, float], tol: float = COORD_TOL_KW
) -> bool:
    return max(abs(a[0] - b[0]), abs(a[1] - b[1])) <= tol


def point_segment_distance(
    point: tuple[float, float], a: tuple[float, float], b: tuple[float, float]
) -> float:
    dx = b[0] - a[0]
    dy = b[1] - a[1]
    length_sq = dx * dx + dy * dy
    if length_sq == 0.0:
        return math.hypot(point[0] - a[0], point[1] - a[1])
    t = ((point[0] - a[0]) * dx + (point[1] - a[1]) * dy) / length_sq
    t = min(1.0, max(0.0, t))
    closest = (a[0] + t * dx, a[1] + t * dy)
    return math.hypot(point[0] - closest[0], point[1] - closest[1])


def polygon_membership(
    vertices: list[tuple[float, float]],
    point: tuple[float, float],
    tol: float = GEOMETRY_TOL_KW,
) -> dict:
    """Independent even/odd polygon test with a Euclidean boundary test."""
    minimum_boundary_distance = min(
        point_segment_distance(point, a, b)
        for a, b in zip(vertices, vertices[1:] + vertices[:1])
    )
    if minimum_boundary_distance <= tol:
        return {
            "inside": True,
            "location": "BOUNDARY",
            "minimum_boundary_distance_kw": minimum_boundary_distance,
        }
    x, y = point
    crossings = 0
    for a, b in zip(vertices, vertices[1:] + vertices[:1]):
        if (a[1] > y) == (b[1] > y):
            continue
        intersection_x = a[0] + (y - a[1]) * (b[0] - a[0]) / (b[1] - a[1])
        if intersection_x > x:
            crossings += 1
    inside = crossings % 2 == 1
    return {
        "inside": inside,
        "location": "INTERIOR" if inside else "OUTSIDE",
        "minimum_boundary_distance_kw": minimum_boundary_distance,
    }


def build_facets(vertices: list[tuple[float, float]]) -> list[dict]:
    facets = []
    for index, (a, b) in enumerate(zip(vertices, vertices[1:] + vertices[:1])):
        dx = b[0] - a[0]
        dy = b[1] - a[1]
        length = math.hypot(dx, dy)
        facets.append({
            "index": index,
            "a": a,
            "b": b,
            "length": length,
            "normal": (-dy / length, dx / length) if length > 0.0 else (math.nan, math.nan),
        })
    return facets


def cell_geometry_valid(vertices: list[tuple[float, float]], declared_convex: bool) -> tuple[bool, str]:
    if len(vertices) < 3:
        return False, "FEWER_THAN_THREE_VERTICES"
    if not all(finite(value) for point in vertices for value in point):
        return False, "NONFINITE_VERTEX"
    facets = build_facets(vertices)
    if any(facet["length"] <= GEOMETRY_TOL_KW for facet in facets):
        return False, "DEGENERATE_FACET"
    area = polygon_area(vertices)
    if area <= GEOMETRY_TOL_KW * GEOMETRY_TOL_KW:
        return False, "NONPOSITIVE_OR_DEGENERATE_CCW_AREA"
    signs = []
    for index in range(len(vertices)):
        a = vertices[index]
        b = vertices[(index + 1) % len(vertices)]
        c = vertices[(index + 2) % len(vertices)]
        signs.append((b[0] - a[0]) * (c[1] - b[1]) - (b[1] - a[1]) * (c[0] - b[0]))
    if any(value < -GEOMETRY_TOL_KW for value in signs):
        return False, "NONCONVEX_VERTEX_TURN"
    if not declared_convex:
        return False, "COMMITTED_CONVEX_FLAG_FALSE"
    return True, "VALID_CCW_CONVEX_CELL"


def halfspace_values(
    facets: list[dict], point: tuple[float, float], direction: tuple[float, float]
) -> list[dict]:
    values = []
    for facet in facets:
        nx, ny = facet["normal"]
        s = nx * (point[0] - facet["a"][0]) + ny * (point[1] - facet["a"][1])
        q = nx * direction[0] + ny * direction[1]
        limit = -s / q if q < -SLOPE_TOL else None
        values.append({**facet, "s": s, "q": q, "limit": limit})
    return values


def analytical_membership(values: list[dict], tol: float = GEOMETRY_TOL_KW) -> dict:
    slacks = [value["s"] for value in values]
    minimum = min(slacks)
    return {
        "inside": minimum >= -tol,
        "strict_nonnegative": minimum >= 0.0,
        "minimum_signed_slack_kw": minimum,
    }


def snap_down(value: float, resolution: float = GRID_RESOLUTION_KW) -> float:
    if not finite(value) or value <= 0.0:
        return 0.0
    return math.floor(value / resolution) * resolution


def match_registered_facet(
    facets: list[dict], endpoint_a: tuple[float, float], endpoint_b: tuple[float, float]
) -> list[int]:
    matches = []
    for facet in facets:
        same = componentwise_close(facet["a"], endpoint_a) and componentwise_close(facet["b"], endpoint_b)
        reverse = componentwise_close(facet["a"], endpoint_b) and componentwise_close(facet["b"], endpoint_a)
        if same or reverse:
            matches.append(facet["index"])
    return matches


def classification_for(
    *,
    provenance_ok: bool,
    geometry_ok: bool,
    ownership_ok: bool,
    source_outside: bool,
    tolerance_ambiguous: bool,
    raw_cap: float | None,
    guarded_cap: float | None,
    grid_cap: float,
    accepted_membership_ok: bool,
) -> tuple[str, str]:
    if not provenance_ok:
        return "INPUT_PROVENANCE_MISMATCH", "cross-artifact source or registered-direction consistency failed"
    if not geometry_ok:
        return "CELL_GEOMETRY_INVALID", "owner cell is not a finite nondegenerate committed CCW convex polygon"
    if not ownership_ok:
        return "REGISTERED_FACET_OWNERSHIP_MISMATCH", "registered polygon facet does not match exactly one owner-cell facet"
    if source_outside:
        return "SOURCE_POINT_OUTSIDE_OWNER_CELL", "source fails analytical or independent polygon membership"
    if tolerance_ambiguous or not accepted_membership_ok:
        return "FULL_CELL_TOLERANCE_AMBIGUITY", "membership methods disagree or a result lies only in the numerical ambiguity band"
    if raw_cap is None or guarded_cap is None or raw_cap <= GEOMETRY_TOL_KW or guarded_cap <= 0.0:
        return "NO_POSITIVE_FULL_CELL_MOVEMENT", "no positive guarded line interval exists in the owner cell"
    if grid_cap < GRID_RESOLUTION_KW:
        return "FULL_CELL_CAP_BELOW_GRID", "positive guarded interval is smaller than one locked grid step"
    return "GEOMETRICALLY_CERTIFIED", "source and downward-snapped endpoint pass both independent membership checks"


def source_manifest_verification() -> tuple[bool, list[str]]:
    errors = []
    prereg_manifest = read_json_git(PREREGISTRATION_COMMIT, PREREGISTRATION_MANIFEST_PATH)
    prereg_by_name = {item["path"]: item for item in prereg_manifest["files"]}
    for name, path in [
        ("calibration_fraction_inventory.csv", MEMBERSHIP_PATH),
        ("edge_repair_policy.csv", POLICY_PATH),
        ("repair_config.json", REPAIR_CONFIG_PATH),
        ("source_manifest.json", PREREGISTRATION_SOURCE_MANIFEST_PATH),
    ]:
        data = git_bytes(PREREGISTRATION_COMMIT, path)
        expected = prereg_by_name.get(name)
        if expected is None or len(data) != expected["bytes"] or sha256(data) != expected["sha256"]:
            errors.append(f"PREREGISTRATION_MANIFEST_MISMATCH:{name}")

    cell_manifest = read_csv_git(GEOMETRY_SOURCE_COMMIT, CELL_MANIFEST_PATH)
    cell_expected = {row["path"]: row for row in cell_manifest}.get(CELL_PATH)
    cell_data = git_bytes(GEOMETRY_SOURCE_COMMIT, CELL_PATH)
    if (
        cell_expected is None
        or len(cell_data) != int(cell_expected["bytes"])
        or sha256(cell_data) != cell_expected["sha256"]
    ):
        errors.append("CELL_MANIFEST_MISMATCH:merged_convex_cells.csv")

    prereg_sources = read_json_git(PREREGISTRATION_COMMIT, PREREGISTRATION_SOURCE_MANIFEST_PATH)
    polygon_expected = {item["path"]: item for item in prereg_sources["files"]}.get(POLYGON_PATH)
    polygon_data = git_bytes(GEOMETRY_SOURCE_COMMIT, POLYGON_PATH)
    if (
        prereg_sources.get("source_commit") != GEOMETRY_SOURCE_COMMIT
        or polygon_expected is None
        or len(polygon_data) != polygon_expected["bytes"]
        or sha256(polygon_data) != polygon_expected["sha256"]
    ):
        errors.append("SOURCE_MANIFEST_MISMATCH:validation_polygon_edges.csv")
    return not errors, errors


def build_source_manifest() -> dict:
    files = []
    for commit, path, role in SOURCE_ARTIFACTS:
        data = git_bytes(commit, path)
        item = {
            "bytes": len(data),
            "path": path,
            "role": role,
            "sha256": sha256(data),
            "source_commit": commit,
        }
        if path.endswith(".csv"):
            item["row_count"] = len(read_csv_bytes(data))
        files.append(item)
    ok, errors = source_manifest_verification()
    return {
        "files": files,
        "read_semantics": "DIRECT_IMMUTABLE_GIT_OBJECT_BYTES_NOT_WORKING_TREE",
        "verification": "PASS" if ok else "FAIL",
        "verification_errors": errors,
    }


def load_inputs() -> dict:
    memberships = read_csv_git(PREREGISTRATION_COMMIT, MEMBERSHIP_PATH)
    policies = read_csv_git(PREREGISTRATION_COMMIT, POLICY_PATH)
    polygon_rows = read_csv_git(GEOMETRY_SOURCE_COMMIT, POLYGON_PATH)
    cell_rows = read_csv_git(GEOMETRY_SOURCE_COMMIT, CELL_PATH)

    policies_by_key: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    for row in policies:
        policies_by_key[(row["timestamp"], row["edge_id"])].append(row)
    polygons_by_key: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    for row in polygon_rows:
        polygons_by_key[(row["timestamp"], row["source_polygon_edge_id"])].append(row)

    grouped_cells: dict[tuple[str, int], list[dict[str, str]]] = defaultdict(list)
    for row in cell_rows:
        grouped_cells[(row["timestamp"], int(row["cell_index"]))].append(row)
    cells = {}
    for key, rows in grouped_cells.items():
        ordered = sorted(rows, key=lambda row: int(row["cell_vertex_index_ccw"]))
        cells[key] = {
            "vertices": [(float(row["p13_abs_kw"]), float(row["p30_abs_kw"])) for row in ordered],
            "declared_convex": all(truth(row["cell_convex"]) for row in ordered),
        }
    return {
        "memberships": memberships,
        "policies_by_key": policies_by_key,
        "polygons_by_key": polygons_by_key,
        "cells": cells,
    }


def certify_memberships() -> dict:
    branch = git("branch", "--show-current").decode().strip()
    ancestor_ok = subprocess.run(
        ["git", "merge-base", "--is-ancestor", AUDIT_BASE_COMMIT, "HEAD"],
        cwd=ROOT,
        check=False,
    ).returncode == 0
    if branch != SOURCE_BRANCH or not ancestor_ok:
        raise RuntimeError(
            f"source lock failed: branch={branch}, audit_base_is_ancestor={ancestor_ok}"
        )

    source_manifest = build_source_manifest()
    global_provenance_ok = source_manifest["verification"] == "PASS"
    inputs = load_inputs()
    memberships = sorted(
        inputs["memberships"], key=lambda row: (row["timestamp"], row["calibration_membership_id"])
    )
    if len(memberships) != 24004:
        global_provenance_ok = False

    result_rows = []
    check_rows = []
    seen_membership_ids = set()
    for member in memberships:
        membership_id = member["calibration_membership_id"]
        key = (member["timestamp"], member["edge_id"])
        provenance_errors = []
        if membership_id in seen_membership_ids:
            provenance_errors.append("DUPLICATE_MEMBERSHIP_ID")
        seen_membership_ids.add(membership_id)

        policy_matches = inputs["policies_by_key"].get(key, [])
        polygon_matches = inputs["polygons_by_key"].get(key, [])
        if len(policy_matches) != 1:
            provenance_errors.append(f"POLICY_MATCH_COUNT_{len(policy_matches)}")
        if len(polygon_matches) != 1:
            provenance_errors.append(f"POLYGON_FACET_MATCH_COUNT_{len(polygon_matches)}")

        policy = policy_matches[0] if len(policy_matches) == 1 else None
        polygon = polygon_matches[0] if len(polygon_matches) == 1 else None
        x0 = (
            float(member["p13_abs_kw_at_source_geometry"]),
            float(member["p30_abs_kw_at_source_geometry"]),
        )
        t = float(member["t"])
        direction = (
            float(policy["inward_normal_p13"]) if policy else math.nan,
            float(policy["inward_normal_p30"]) if policy else math.nan,
        )
        owner_cell_id = int(policy["owner_cell_id"]) if policy else -1
        cell = inputs["cells"].get((member["timestamp"], owner_cell_id))
        if cell is None:
            geometry_ok, geometry_detail = False, "OWNER_CELL_NOT_FOUND"
            vertices = []
            facets = []
        else:
            vertices = cell["vertices"]
            geometry_ok, geometry_detail = cell_geometry_valid(vertices, cell["declared_convex"])
            facets = build_facets(vertices) if len(vertices) >= 2 else []

        endpoint_a = (math.nan, math.nan)
        endpoint_b = (math.nan, math.nan)
        source_reconstruction_error = math.inf
        facet_matches = []
        registered_facet_index = None
        if polygon is not None:
            endpoint_a = (
                float(polygon["endpoint_a_p13_abs_kw"]),
                float(polygon["endpoint_a_p30_abs_kw"]),
            )
            endpoint_b = (
                float(polygon["endpoint_b_p13_abs_kw"]),
                float(polygon["endpoint_b_p30_abs_kw"]),
            )
            reconstructed = (
                endpoint_a[0] + t * (endpoint_b[0] - endpoint_a[0]),
                endpoint_a[1] + t * (endpoint_b[1] - endpoint_a[1]),
            )
            source_reconstruction_error = max(
                abs(x0[0] - reconstructed[0]), abs(x0[1] - reconstructed[1])
            )
            if not finite(t) or t < -COORD_TOL_KW or t > 1.0 + COORD_TOL_KW:
                provenance_errors.append("MEMBERSHIP_FRACTION_OUT_OF_RANGE")
            if source_reconstruction_error > COORD_TOL_KW:
                provenance_errors.append("SOURCE_COORDINATE_RECONSTRUCTION_MISMATCH")
            if facets:
                facet_matches = match_registered_facet(facets, endpoint_a, endpoint_b)
                if len(facet_matches) == 1:
                    registered_facet_index = facet_matches[0]

        direction_norm = math.hypot(*direction)
        if not all(finite(value) for value in (*x0, *direction)):
            provenance_errors.append("NONFINITE_SOURCE_OR_DIRECTION")
        if not finite(direction_norm) or abs(direction_norm - 1.0) > DIRECTION_TOL:
            provenance_errors.append("REGISTERED_DIRECTION_NOT_UNIT")

        values = halfspace_values(facets, x0, direction) if geometry_ok else []
        if registered_facet_index is not None and values:
            registered_q = values[registered_facet_index]["q"]
            if registered_q <= SLOPE_TOL:
                provenance_errors.append("REGISTERED_DIRECTION_NOT_INWARD_FOR_REGISTERED_FACET")
            facet_vector = (
                endpoint_b[0] - endpoint_a[0], endpoint_b[1] - endpoint_a[1]
            )
            facet_length = math.hypot(*facet_vector)
            perpendicular_residual = abs(
                facet_vector[0] * direction[0] + facet_vector[1] * direction[1]
            ) / facet_length
            if perpendicular_residual > DIRECTION_TOL:
                provenance_errors.append("REGISTERED_DIRECTION_NOT_FACET_NORMAL")

        provenance_ok = global_provenance_ok and not provenance_errors
        ownership_ok = len(facet_matches) == 1
        registered_facet_id = (
            f"C{owner_cell_id}:F{registered_facet_index:02d}"
            if registered_facet_index is not None
            else ""
        )

        source_halfspace = analytical_membership(values) if values else {
            "inside": False,
            "strict_nonnegative": False,
            "minimum_signed_slack_kw": math.nan,
        }
        source_polygon = polygon_membership(vertices, x0) if geometry_ok else {
            "inside": False,
            "location": "INVALID_CELL",
            "minimum_boundary_distance_kw": math.nan,
        }
        source_outside = geometry_ok and (
            not source_halfspace["inside"] or not source_polygon["inside"]
        )
        tolerance_ambiguous = geometry_ok and (
            source_halfspace["inside"] != source_polygon["inside"]
            or (
                -GEOMETRY_TOL_KW
                <= source_halfspace["minimum_signed_slack_kw"]
                < -COORD_TOL_KW
            )
        )

        finite_limits = [value for value in values if value["limit"] is not None]
        raw_cap = min((value["limit"] for value in finite_limits), default=None)
        guarded_cap = max(0.0, raw_cap - CAP_GUARD_KW) if raw_cap is not None else None
        grid_cap = snap_down(guarded_cap) if guarded_cap is not None else 0.0
        limiting = (
            [value for value in finite_limits if abs(value["limit"] - raw_cap) <= CAP_TIE_TOL_KW]
            if raw_cap is not None
            else []
        )
        limiting_ids = [f"C{owner_cell_id}:F{value['index']:02d}" for value in limiting]
        limiting_facet_id = limiting_ids[0] if limiting_ids else ""

        def point_at(distance: float | None) -> tuple[float, float] | None:
            if distance is None:
                return None
            return (x0[0] + distance * direction[0], x0[1] + distance * direction[1])

        raw_point = point_at(raw_cap)
        guarded_point = point_at(guarded_cap)
        grid_point = point_at(grid_cap)

        def validate_point(point: tuple[float, float] | None) -> tuple[dict, dict]:
            if point is None or not geometry_ok:
                return (
                    {"inside": False, "strict_nonnegative": False, "minimum_signed_slack_kw": math.nan},
                    {"inside": False, "location": "NOT_APPLICABLE", "minimum_boundary_distance_kw": math.nan},
                )
            point_values = halfspace_values(facets, point, direction)
            return analytical_membership(point_values), polygon_membership(vertices, point)

        raw_halfspace, raw_polygon = validate_point(raw_point)
        guarded_halfspace, guarded_polygon = validate_point(guarded_point)
        grid_halfspace, grid_polygon = validate_point(grid_point)
        accepted_membership_ok = (
            grid_halfspace["inside"]
            and grid_polygon["inside"]
            and grid_halfspace["inside"] == grid_polygon["inside"]
        )
        if geometry_ok and raw_cap is not None and raw_cap > GEOMETRY_TOL_KW:
            tolerance_ambiguous = tolerance_ambiguous or not (
                guarded_halfspace["inside"] and guarded_polygon["inside"]
            )

        classification, classification_detail = classification_for(
            provenance_ok=provenance_ok,
            geometry_ok=geometry_ok,
            ownership_ok=ownership_ok,
            source_outside=source_outside,
            tolerance_ambiguous=tolerance_ambiguous,
            raw_cap=raw_cap,
            guarded_cap=guarded_cap,
            grid_cap=grid_cap,
            accepted_membership_ok=accepted_membership_ok,
        )
        result_rows.append({
            "timestamp": member["timestamp"],
            "membership_id": membership_id,
            "registered_edge_id": member["edge_id"],
            "owner_cell_id": owner_cell_id if owner_cell_id >= 0 else "",
            "source_p13_abs_kw": x0[0],
            "source_p30_abs_kw": x0[1],
            "direction_p13": direction[0],
            "direction_p30": direction[1],
            "direction_norm": direction_norm,
            "registered_facet_id": registered_facet_id,
            "limiting_facet_id": limiting_facet_id,
            "co_limiting_facet_ids": ";".join(limiting_ids),
            "raw_cap_kw": raw_cap,
            "guarded_cap_kw": guarded_cap,
            "grid_cap_kw": grid_cap,
            "grid_endpoint_p13_abs_kw": grid_point[0] if grid_point else None,
            "grid_endpoint_p30_abs_kw": grid_point[1] if grid_point else None,
            "classification": classification,
            "classification_detail": classification_detail,
            "minimum_signed_slack_kw": source_halfspace["minimum_signed_slack_kw"],
            "source_halfspace_membership": "INSIDE" if source_halfspace["inside"] else "OUTSIDE",
            "source_polygon_membership": source_polygon["location"],
            "grid_halfspace_membership": "INSIDE" if grid_halfspace["inside"] else "OUTSIDE",
            "grid_polygon_membership": grid_polygon["location"],
            "source_reconstruction_error_kw": source_reconstruction_error,
            "provenance_errors": ";".join(provenance_errors),
            "geometry_detail": geometry_detail,
            "direction_immutable": True,
            "ac_evaluated": False,
        })

        for value in values:
            facet_id = f"C{owner_cell_id}:F{value['index']:02d}"
            grid_slack = (
                value["s"] + grid_cap * value["q"] if grid_point is not None else None
            )
            guarded_slack = (
                value["s"] + guarded_cap * value["q"] if guarded_cap is not None else None
            )
            raw_slack = value["s"] + raw_cap * value["q"] if raw_cap is not None else None
            check_rows.append({
                "timestamp": member["timestamp"],
                "membership_id": membership_id,
                "owner_cell_id": owner_cell_id,
                "registered_edge_id": member["edge_id"],
                "registered_facet_id": registered_facet_id,
                "facet_id": facet_id,
                "facet_index_ccw": value["index"],
                "facet_a_p13_abs_kw": value["a"][0],
                "facet_a_p30_abs_kw": value["a"][1],
                "facet_b_p13_abs_kw": value["b"][0],
                "facet_b_p30_abs_kw": value["b"][1],
                "source_signed_slack_s_j_kw": value["s"],
                "direction_projection_q_j": value["q"],
                "finite_facet_limit_kw": value["limit"],
                "is_registered_facet": value["index"] == registered_facet_index,
                "is_limiting_facet": facet_id in limiting_ids,
                "raw_cap_signed_slack_kw": raw_slack,
                "guarded_cap_signed_slack_kw": guarded_slack,
                "grid_cap_signed_slack_kw": grid_slack,
                "source_analytical_membership": "INSIDE" if source_halfspace["inside"] else "OUTSIDE",
                "source_polygon_membership": source_polygon["location"],
                "raw_analytical_membership": "INSIDE" if raw_halfspace["inside"] else "OUTSIDE",
                "raw_polygon_membership": raw_polygon["location"],
                "guarded_analytical_membership": "INSIDE" if guarded_halfspace["inside"] else "OUTSIDE",
                "guarded_polygon_membership": guarded_polygon["location"],
                "grid_analytical_membership": "INSIDE" if grid_halfspace["inside"] else "OUTSIDE",
                "grid_polygon_membership": grid_polygon["location"],
                "geometry_tolerance_kw": GEOMETRY_TOL_KW,
            })

    if len(result_rows) != 24004 or len({row["membership_id"] for row in result_rows}) != 24004:
        raise RuntimeError("probe result completeness failure")
    if any(row["classification"] not in CLASSIFICATIONS for row in result_rows):
        raise RuntimeError("unknown classification generated")
    if any(
        row["classification"] == "GEOMETRICALLY_CERTIFIED"
        and (
            row["source_halfspace_membership"] != "INSIDE"
            or row["source_polygon_membership"] == "OUTSIDE"
            or row["grid_halfspace_membership"] != "INSIDE"
            or row["grid_polygon_membership"] == "OUTSIDE"
        )
        for row in result_rows
    ):
        raise RuntimeError("outside-cell coordinate was accepted as geometrically certified")
    return {
        "result_rows": result_rows,
        "check_rows": check_rows,
        "source_manifest": source_manifest,
    }


def build_config() -> dict:
    return {
        "artifact": "DSO_VPP_AC_BOUNDARY_HEADROOM_FULL_CELL_GEOMETRIC_CERTIFICATION",
        "schema_version": SCHEMA_VERSION,
        "method": METHOD,
        "source_lock": {
            "required_branch": SOURCE_BRANCH,
            "audit_base_must_be_ancestor_of_head": AUDIT_BASE_COMMIT,
            "fixed_preregistration_commit": PREREGISTRATION_COMMIT,
            "fixed_geometry_commit": GEOMETRY_SOURCE_COMMIT,
            "read_semantics": "git show <fixed-commit>:<path>",
        },
        "line_parameterization": "x(d)=x0+d*u",
        "halfspace_parameterization": "g_j(x(d))=s_j+d*q_j;inside_when_g_j>=0",
        "finite_limit_rule": "compute_-s_j/q_j_only_when_q_j<-slope_tolerance",
        "raw_cap_rule": "minimum_finite_facet_limit",
        "guarded_cap_rule": "max(0,raw_cap_kw-cap_guard_kw)",
        "grid_cap_rule": "floor(guarded_cap_kw/grid_resolution_kw)*grid_resolution_kw",
        "tolerances": {
            "coordinate_consistency_kw_componentwise": COORD_TOL_KW,
            "geometry_membership_kw": GEOMETRY_TOL_KW,
            "direction_unit_and_perpendicular": DIRECTION_TOL,
            "direction_projection": SLOPE_TOL,
            "co_limiting_cap_kw": CAP_TIE_TOL_KW,
            "cap_guard_kw": CAP_GUARD_KW,
            "grid_resolution_kw": GRID_RESOLUTION_KW,
        },
        "classification_precedence": CLASSIFICATIONS,
        "independent_membership_methods": [
            "NORMALIZED_CCW_FACET_HALFSPACES",
            "EVEN_ODD_POLYGON_RAY_CROSSING_WITH_EUCLIDEAN_BOUNDARY_TEST",
        ],
        "direction_policy": {
            "source": "registered edge_repair_policy inward_normal_p13/inward_normal_p30",
            "rotation_allowed": False,
            "optimization_allowed": False,
            "alternative_facet_normal_selection_allowed": False,
            "length_restriction_only": True,
        },
        "scope_guards": {
            "ac_power_flow_allowed": False,
            "optimization_allowed": False,
            "doe_construction_allowed": False,
            "candidate_geometry_freeze_allowed": False,
            "committed_partition_modification_allowed": False,
        },
    }


def generate(outdir: Path) -> int:
    data = certify_memberships()
    outdir.mkdir(parents=True, exist_ok=True)
    unexpected = sorted(path.name for path in outdir.iterdir() if path.name not in EXPECTED_NAMES)
    if unexpected:
        raise RuntimeError(f"unexpected files in output directory: {unexpected}")

    result_fields = [
        "timestamp", "membership_id", "registered_edge_id", "owner_cell_id",
        "source_p13_abs_kw", "source_p30_abs_kw", "direction_p13", "direction_p30",
        "direction_norm", "registered_facet_id", "limiting_facet_id",
        "co_limiting_facet_ids", "raw_cap_kw", "guarded_cap_kw", "grid_cap_kw",
        "grid_endpoint_p13_abs_kw", "grid_endpoint_p30_abs_kw", "classification",
        "classification_detail", "minimum_signed_slack_kw", "source_halfspace_membership",
        "source_polygon_membership", "grid_halfspace_membership", "grid_polygon_membership",
        "source_reconstruction_error_kw", "provenance_errors", "geometry_detail",
        "direction_immutable", "ac_evaluated",
    ]
    check_fields = [
        "timestamp", "membership_id", "owner_cell_id", "registered_edge_id",
        "registered_facet_id", "facet_id", "facet_index_ccw", "facet_a_p13_abs_kw",
        "facet_a_p30_abs_kw", "facet_b_p13_abs_kw", "facet_b_p30_abs_kw",
        "source_signed_slack_s_j_kw", "direction_projection_q_j", "finite_facet_limit_kw",
        "is_registered_facet", "is_limiting_facet", "raw_cap_signed_slack_kw",
        "guarded_cap_signed_slack_kw", "grid_cap_signed_slack_kw",
        "source_analytical_membership", "source_polygon_membership",
        "raw_analytical_membership", "raw_polygon_membership",
        "guarded_analytical_membership", "guarded_polygon_membership",
        "grid_analytical_membership", "grid_polygon_membership", "geometry_tolerance_kw",
    ]
    write_csv(outdir / "full_cell_probe_limits.csv", result_fields, data["result_rows"])
    write_csv(outdir / "full_cell_limit_checks.csv", check_fields, data["check_rows"])
    write_text(
        outdir / "full_cell_repair_config.json",
        json.dumps(build_config(), indent=2, sort_keys=True) + "\n",
    )
    write_text(
        outdir / "source_manifest.json",
        json.dumps(data["source_manifest"], indent=2, sort_keys=True) + "\n",
    )

    counts = Counter(row["classification"] for row in data["result_rows"])
    classification_counts = {name: counts.get(name, 0) for name in CLASSIFICATIONS}
    certified = classification_counts["GEOMETRICALLY_CERTIFIED"]
    report = [
        "# Full-cell geometric certification v1",
        "",
        "## Scope and result",
        "",
        f"This is a deterministic `{METHOD}` artifact over all `{len(data['result_rows'])}` locked probe memberships.",
        "It reads only immutable committed geometry/provenance objects. It performs no AC power flow, optimization, DOE construction, cell-partition modification, direction change, or candidate-geometry freeze.",
        "",
        f"Geometrically certified memberships: `{certified}`. Every certification restricts only movement length along the registered inward direction.",
        "",
        "## Classification counts",
        "",
    ]
    report.extend(f"- `{name}`: `{classification_counts[name]}`" for name in CLASSIFICATIONS)
    report.extend([
        "",
        "## Method",
        "",
        "For every owner-cell facet, the generator records `s_j`, `q_j`, and the finite limit `-s_j/q_j` only when `q_j < 0`. The raw cap is the minimum finite limit, the guarded cap subtracts the fixed 1e-7 kW geometry guard, and the accepted grid cap is snapped downward to 0.25 kW.",
        "",
        "Source and snapped endpoint membership are checked independently by normalized CCW halfspaces and an even/odd polygon ray-crossing test with a Euclidean boundary calculation. No coordinate outside its owner cell under either check can receive `GEOMETRICALLY_CERTIFIED`.",
        "",
        "## Provenance and determinism",
        "",
        f"Registered memberships/policies are read from `{PREREGISTRATION_COMMIT}`. Owner cells and polygon facets are read from `{GEOMETRY_SOURCE_COMMIT}`. `source_manifest.json` records exact byte sizes and SHA-256 hashes.",
        "",
        "`hashes.sha256` and `manifest.json` cover the generated payloads. Byte identity must be checked by two clean-location generations; it demonstrates determinism, not AC feasibility.",
        "",
        "## Claim boundary",
        "",
        "`GEOMETRICALLY_CERTIFIED` means only that the registered line segment from `x0` through the downward-snapped cap stays in the immutable owner cell under both geometric checks. It is not an AC, headroom, feasibility, repair, or freeze decision.",
        "",
    ])
    write_text(outdir / "summary_report.md", "\n".join(report))

    hash_lines = [
        f"{sha256((outdir / name).read_bytes())}  {name}" for name in sorted(CONTENT_NAMES)
    ]
    write_text(outdir / "hashes.sha256", "\n".join(hash_lines) + "\n")
    manifest_files = []
    for name in sorted(EXPECTED_NAMES - {"manifest.json"}):
        payload = (outdir / name).read_bytes()
        item = {"path": name, "bytes": len(payload), "sha256": sha256(payload)}
        if name.endswith(".csv"):
            item["row_count"] = len(read_csv_bytes(payload))
        manifest_files.append(item)
    manifest = {
        "artifact": "DSO_VPP_AC_BOUNDARY_HEADROOM_FULL_CELL_GEOMETRIC_CERTIFICATION",
        "schema_version": SCHEMA_VERSION,
        "source_branch": SOURCE_BRANCH,
        "audit_base_commit": AUDIT_BASE_COMMIT,
        "preregistration_commit": PREREGISTRATION_COMMIT,
        "geometry_source_commit": GEOMETRY_SOURCE_COMMIT,
        "method": METHOD,
        "generator": {"path": GENERATOR_PATH, "sha256": sha256((ROOT / GENERATOR_PATH).read_bytes())},
        "counts": {
            "probe_memberships": len(data["result_rows"]),
            "facet_check_rows": len(data["check_rows"]),
            "classifications": classification_counts,
        },
        "files": manifest_files,
    }
    write_text(outdir / "manifest.json", json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    print(f"wrote {outdir}")
    print(json.dumps(manifest["counts"], sort_keys=True))
    return 0


def parse_hashes(data: bytes) -> dict[str, str]:
    result = {}
    for line in data.decode("utf-8").splitlines():
        digest, name = line.split("  ", 1)
        result[name] = digest
    return result


def verify_disk(outdir: Path = OUTDIR) -> int:
    manifest = json.loads((outdir / "manifest.json").read_text(encoding="utf-8"))
    expected_names = {item["path"] for item in manifest["files"]} | {"manifest.json"}
    actual_names = {path.name for path in outdir.iterdir() if path.is_file()}
    mismatches = []
    if actual_names != expected_names:
        mismatches.append("UNEXPECTED_OR_MISSING_FILES")
    for item in manifest["files"]:
        data = (outdir / item["path"]).read_bytes()
        if len(data) != item["bytes"] or sha256(data) != item["sha256"]:
            mismatches.append(item["path"])
    recorded_hashes = parse_hashes((outdir / "hashes.sha256").read_bytes())
    for name, digest in recorded_hashes.items():
        if sha256((outdir / name).read_bytes()) != digest:
            mismatches.append(f"HASHES:{name}")
    generator = manifest["generator"]
    if generator["path"] != GENERATOR_PATH or sha256((ROOT / GENERATOR_PATH).read_bytes()) != generator["sha256"]:
        mismatches.append("GENERATOR_SHA256")
    source_manifest = json.loads((outdir / "source_manifest.json").read_text(encoding="utf-8"))
    for item in source_manifest["files"]:
        data = git_bytes(item["source_commit"], item["path"])
        if len(data) != item["bytes"] or sha256(data) != item["sha256"]:
            mismatches.append(f"SOURCE:{item['path']}")
    if source_manifest["verification"] != "PASS":
        mismatches.append("SOURCE_MANIFEST_VERIFICATION")
    print(f"disk verification: {'PASS' if not mismatches else 'FAIL'}")
    if mismatches:
        print("mismatches=" + ";".join(mismatches))
    return 1 if mismatches else 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=OUTDIR)
    parser.add_argument("--verify-disk", action="store_true")
    args = parser.parse_args()
    if args.verify_disk:
        return verify_disk(args.output_dir.resolve())
    return generate(args.output_dir.resolve())


if __name__ == "__main__":
    raise SystemExit(main())
