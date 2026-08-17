from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import statistics
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path


SOURCE_COMMIT = "5538146bc22386abe52601a2ab0129064335f855"
SOURCE_BRANCH = "codex/dso-vpp-ac-map-pilot"
COORD_TOL_KW = 1e-8
OUTDIR = Path(
    "results/dso_vpp_ac_map_pilot/"
    "doe_ac_repairability_interpolation_audit"
)

PATHS = {
    "edges": "results/dso_vpp_ac_map_pilot/doe_ac_interior_validation_preregistration/validation_polygon_edges.csv",
    "provenance": "results/dso_vpp_ac_map_pilot/doe_ac_interior_validation_preregistration/validation_point_provenance.csv",
    "points": "results/dso_vpp_ac_map_pilot/doe_ac_interior_validation/validation_point_results.csv",
    "cells": "results/dso_vpp_ac_map_pilot/doe_construction_policy_preregistration/convex_piecewise_architecture_audit/merged_convex_cells.csv",
    "triangles": "results/dso_vpp_ac_map_pilot/doe_construction_policy_preregistration/convex_piecewise_architecture_audit/fan_triangle_cells.csv",
    "production_endpoints": "results/dso_vpp_ac_map_pilot/production_probe/boundary_endpoints.csv",
    "production_attempts": "results/dso_vpp_ac_map_pilot/production_probe/evaluation_attempts.csv",
    "validation_attempts": "results/dso_vpp_ac_map_pilot/doe_ac_interior_validation/validation_attempts.csv",
    "validation_runtime": "results/dso_vpp_ac_map_pilot/doe_ac_interior_validation/validation_runtime_summary.json",
    "validation_integrity": "results/dso_vpp_ac_map_pilot/doe_ac_interior_validation/validation_integrity_checks.csv",
    "validation_category": "results/dso_vpp_ac_map_pilot/doe_ac_interior_validation/validation_category_summary.csv",
    "validation_guard": "results/dso_vpp_ac_map_pilot/doe_ac_interior_validation/validation_guard_summary.csv",
    "interpretation_summary": "results/dso_vpp_ac_map_pilot/doe_ac_interior_validation_interpretation_audit/interpretation_audit_summary.json",
    "topology": "results/dso_vpp_ac_map_pilot/doe_preconstruction_artifact_refinement/sensitivity_topology_reconstruction.csv",
    "timer_inventory": "results/dso_vpp_ac_map_pilot/doe_ac_runtime_benchmark/timer_scope_inventory.csv",
    "runtime_reconciliation": "results/dso_vpp_ac_map_pilot/doe_ac_runtime_benchmark/runtime_reconciliation_summary.json",
    "validation_script": "scripts/run_dso_vpp_ac_interior_validation.jl",
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


def truth(value: str) -> bool:
    return value.lower() == "true"


def finite(x: float) -> bool:
    return math.isfinite(x)


def fmt(x) -> str:
    if isinstance(x, float):
        if math.isnan(x):
            return "NaN"
        if math.isinf(x):
            return "Inf" if x > 0 else "-Inf"
        return format(x, ".15g")
    return str(x)


def quantile(values: list[float], p: float) -> float:
    xs = sorted(x for x in values if finite(x))
    if not xs:
        return math.nan
    z = (len(xs) - 1) * p
    lo, hi = math.floor(z), math.ceil(z)
    if lo == hi:
        return xs[lo]
    return xs[lo] * (hi - z) + xs[hi] * (z - lo)


def stats(values: list[float]) -> dict[str, float | int]:
    xs = [x for x in values if finite(x)]
    if not xs:
        return {"count": 0, "min": math.nan, "q1": math.nan,
                "median": math.nan, "q3": math.nan, "max": math.nan,
                "mean": math.nan}
    return {
        "count": len(xs), "min": min(xs), "q1": quantile(xs, 0.25),
        "median": statistics.median(xs), "q3": quantile(xs, 0.75),
        "max": max(xs), "mean": statistics.fmean(xs),
    }


def pearson(xs: list[float], ys: list[float]) -> float:
    pairs = [(x, y) for x, y in zip(xs, ys) if finite(x) and finite(y)]
    if len(pairs) < 3:
        return math.nan
    ax = statistics.fmean(x for x, _ in pairs)
    ay = statistics.fmean(y for _, y in pairs)
    sxx = sum((x - ax) ** 2 for x, _ in pairs)
    syy = sum((y - ay) ** 2 for _, y in pairs)
    if sxx == 0 or syy == 0:
        return math.nan
    return sum((x - ax) * (y - ay) for x, y in pairs) / math.sqrt(sxx * syy)


def ranks(values: list[float]) -> list[float]:
    order = sorted(range(len(values)), key=lambda i: (values[i], i))
    out = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i + 1
        while j < len(order) and values[order[j]] == values[order[i]]:
            j += 1
        rank = (i + 1 + j) / 2
        for k in order[i:j]:
            out[k] = rank
        i = j
    return out


def spearman(xs: list[float], ys: list[float]) -> float:
    pairs = [(x, y) for x, y in zip(xs, ys) if finite(x) and finite(y)]
    if len(pairs) < 3:
        return math.nan
    return pearson(ranks([x for x, _ in pairs]), ranks([y for _, y in pairs]))


def regression(xs: list[float], ys: list[float]) -> tuple[float, float, float]:
    pairs = [(x, y) for x, y in zip(xs, ys) if finite(x) and finite(y)]
    if len(pairs) < 3:
        return math.nan, math.nan, math.nan
    mx = statistics.fmean(x for x, _ in pairs)
    my = statistics.fmean(y for _, y in pairs)
    sxx = sum((x - mx) ** 2 for x, _ in pairs)
    if sxx == 0:
        return math.nan, math.nan, math.nan
    slope = sum((x - mx) * (y - my) for x, y in pairs) / sxx
    intercept = my - slope * mx
    sst = sum((y - my) ** 2 for _, y in pairs)
    sse = sum((y - (intercept + slope * x)) ** 2 for x, y in pairs)
    r2 = 1 - sse / sst if sst else math.nan
    return slope, intercept, r2


def cross(a: tuple[float, float], b: tuple[float, float]) -> float:
    return a[0] * b[1] - a[1] * b[0]


def sub(a: tuple[float, float], b: tuple[float, float]) -> tuple[float, float]:
    return a[0] - b[0], a[1] - b[1]


def dot(a: tuple[float, float], b: tuple[float, float]) -> float:
    return a[0] * b[0] + a[1] * b[1]


def norm(a: tuple[float, float]) -> float:
    return math.hypot(a[0], a[1])


def coord_close(a: tuple[float, float], b: tuple[float, float],
                tol: float = COORD_TOL_KW) -> bool:
    """Locked coordinate contract: tolerance applies to each kW coordinate."""
    return abs(a[0] - b[0]) <= tol and abs(a[1] - b[1]) <= tol


def projection_fraction_distance(
    p: tuple[float, float], a: tuple[float, float], b: tuple[float, float]
) -> tuple[float, float]:
    v = sub(b, a)
    vv = dot(v, v)
    if vv == 0:
        return math.nan, math.inf
    t = dot(sub(p, a), v) / vv
    q = (a[0] + t * v[0], a[1] + t * v[1])
    return t, norm(sub(p, q))


def unique_fractions(values: list[float], tol: float = 1e-12) -> list[float]:
    out: list[float] = []
    for x in sorted(min(1.0, max(0.0, v)) for v in values):
        if not out or abs(x - out[-1]) > tol:
            out.append(x)
    return out


def gaps(fractions: list[float]) -> list[float]:
    xs = unique_fractions([0.0, 1.0, *fractions])
    return [b - a for a, b in zip(xs, xs[1:])]


def margin(row: dict[str, str], channel: str) -> float:
    if channel == "VMAX_MARGIN":
        return 1.05 - f(row, "vmax_pu")
    if channel == "VMIN_MARGIN":
        return f(row, "vmin_pu") - 0.90
    raise ValueError(channel)


def channels_for_class(boundary_class: str) -> list[str]:
    if boundary_class.startswith("VMAX"):
        return ["VMAX_MARGIN"]
    if boundary_class.startswith("VMIN"):
        return ["VMIN_MARGIN"]
    if boundary_class == "CLASS_TRANSITION":
        return ["VMAX_MARGIN", "VMIN_MARGIN"]
    return ["VMAX_MARGIN", "VMIN_MARGIN"]


def write_csv(path: Path, fields: list[str], rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({k: fmt(row.get(k, "")) for k in fields})


def write_text(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8", newline="\n")


def json_safe(value):
    """Convert non-finite floats to JSON null for strict machine readability."""
    if isinstance(value, float) and not finite(value):
        return None
    if isinstance(value, dict):
        return {k: json_safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [json_safe(v) for v in value]
    return value


def verify_index() -> int:
    manifest_path = OUTDIR.as_posix() + "/manifest.json"
    manifest = json.loads(git("show", f":{manifest_path}").decode("utf-8"))
    errors = []
    for item in manifest["files"]:
        path = OUTDIR.as_posix() + "/" + item["path"]
        data = git("show", f":{path}")
        observed = hashlib.sha256(data).hexdigest()
        if observed != item["sha256"] or len(data) != item["bytes"]:
            errors.append(path)
    print(f"staged manifest payloads: {len(manifest['files'])}")
    print(f"staged manifest mismatches: {len(errors)}")
    return 1 if errors else 0


def main() -> int:
    branch = git("branch", "--show-current").decode().strip()
    head = git("rev-parse", "HEAD").decode().strip()
    if branch != SOURCE_BRANCH or head != SOURCE_COMMIT:
        raise RuntimeError(f"source state mismatch: branch={branch}, head={head}")

    edges = read_csv_git(PATHS["edges"])
    provenance = read_csv_git(PATHS["provenance"])
    points = read_csv_git(PATHS["points"])
    cells = read_csv_git(PATHS["cells"])
    triangles = read_csv_git(PATHS["triangles"])
    production_endpoints = read_csv_git(PATHS["production_endpoints"])
    production_attempts = read_csv_git(PATHS["production_attempts"])
    validation_attempts = read_csv_git(PATHS["validation_attempts"])
    runtime = read_json_git(PATHS["validation_runtime"])
    interpretation = read_json_git(PATHS["interpretation_summary"])
    topology = read_csv_git(PATHS["topology"])
    timer_inventory = read_csv_git(PATHS["timer_inventory"])
    runtime_reconciliation = read_json_git(PATHS["runtime_reconciliation"])

    checks: list[dict[str, str]] = []

    def check(check_id: str, condition: bool, detail: str,
              severity: str = "BLOCKER") -> None:
        checks.append({
            "check_id": check_id,
            "status": "PASS" if condition else severity,
            "detail": detail,
        })

    check("SOURCE_BRANCH", branch == SOURCE_BRANCH, branch, "FAIL")
    check("SOURCE_HEAD", head == SOURCE_COMMIT, head, "FAIL")
    check("OUTER_EDGE_COUNT", len(edges) == 1689, str(len(edges)))
    check("VALIDATION_POINT_COUNT", len(points) == 65494, str(len(points)))

    edge_by_key: dict[tuple[str, str], dict] = {}
    edges_by_ts: dict[str, list[dict]] = defaultdict(list)
    for row in edges:
        key = (row["timestamp"], row["source_polygon_edge_id"])
        edge_by_key[key] = row
        edges_by_ts[row["timestamp"]].append(row)
    for ts in edges_by_ts:
        edges_by_ts[ts].sort(key=lambda r: int(r["source_polygon_edge_id"][1:]))

    cell_vertices: dict[tuple[str, str], list[tuple[float, float]]] = defaultdict(list)
    cell_rows: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for row in cells:
        cell_rows[(row["timestamp"], row["cell_index"])].append(row)
    for key, rows in cell_rows.items():
        rows.sort(key=lambda r: int(r["cell_vertex_index_ccw"]))
        cell_vertices[key] = [(f(r, "p13_abs_kw"), f(r, "p30_abs_kw")) for r in rows]

    centers: dict[str, tuple[float, float]] = {}
    for row in triangles:
        centers.setdefault(row["timestamp"], (f(row, "center_p13_abs_kw"), f(row, "center_p30_abs_kw")))

    polygon_orientation: dict[str, float] = {}
    vertex_status: dict[tuple[str, str], str] = {}
    vertex_turn: dict[tuple[str, str], float] = {}
    vertex_coord: dict[tuple[str, str], tuple[float, float]] = {}
    edge_geometry: dict[tuple[str, str], dict] = {}

    for ts, erows in edges_by_ts.items():
        vertices = [(f(r, "endpoint_a_p13_abs_kw"), f(r, "endpoint_a_p30_abs_kw")) for r in erows]
        area2 = sum(cross(vertices[i], vertices[(i + 1) % len(vertices)]) for i in range(len(vertices)))
        orient = 1.0 if area2 > 0 else -1.0
        polygon_orientation[ts] = orient
        for i, row in enumerate(erows):
            prev = vertices[(i - 1) % len(vertices)]
            cur = vertices[i]
            nxt = vertices[(i + 1) % len(vertices)]
            vin = sub(cur, prev)
            vout = sub(nxt, cur)
            signed_cross = orient * cross(vin, vout)
            scale = max(norm(vin) * norm(vout), 1.0)
            status = "CONVEX" if signed_cross > 1e-12 * scale else "REFLEX" if signed_cross < -1e-12 * scale else "COLLINEAR"
            turn = math.degrees(math.atan2(orient * cross(vin, vout), dot(vin, vout)))
            vkey = (ts, row["endpoint_a_id"])
            vertex_status[vkey] = status
            vertex_turn[vkey] = turn
            vertex_coord[vkey] = cur

    angular_prov_by_edge: dict[tuple[str, str], list[dict]] = defaultdict(list)
    angular_coords_by_ts: dict[str, list[tuple[float, float, str]]] = defaultdict(list)
    max_t_mismatch = 0.0
    for row in provenance:
        if row["source_kind"] != "ANGULAR_BOUNDARY":
            continue
        key = (row["timestamp"], row["source_polygon_edge_id"])
        angular_prov_by_edge[key].append(row)
        angular_coords_by_ts[row["timestamp"]].append((f(row, "p13_abs_kw"), f(row, "p30_abs_kw"), row["validation_point_id"]))
        e = edge_by_key[key]
        a = (f(e, "endpoint_a_p13_abs_kw"), f(e, "endpoint_a_p30_abs_kw"))
        b = (f(e, "endpoint_b_p13_abs_kw"), f(e, "endpoint_b_p30_abs_kw"))
        t, distance = projection_fraction_distance((f(row, "p13_abs_kw"), f(row, "p30_abs_kw")), a, b)
        max_t_mismatch = max(max_t_mismatch, abs(t - f(row, "edge_interpolation_fraction")), distance)
    check("ANGULAR_T_MAPPING", max_t_mismatch <= COORD_TOL_KW,
          f"maximum_fraction_or_distance_mismatch={fmt(max_t_mismatch)}")

    official_safe_by_ts: dict[str, list[dict]] = defaultdict(list)
    for row in production_endpoints:
        if row["endpoint_side"] == "SAFE" and truth(row["official_boundary"]):
            official_safe_by_ts[row["timestamp"]].append(row)
    production_attempts_by_ts: dict[str, list[dict]] = defaultdict(list)
    for row in production_attempts:
        production_attempts_by_ts[row["timestamp"]].append(row)

    def nearest_row(rows: list[dict], p: tuple[float, float], tol=COORD_TOL_KW):
        matches = []
        for row in rows:
            q = (f(row, "p13_abs_kw"), f(row, "p30_abs_kw"))
            d = norm(sub(q, p))
            if coord_close(q, p, tol):
                matches.append((d, row.get("search_kind", ""), row.get("search_id", ""), row))
        return min(matches, default=None, key=lambda x: (x[0], x[1], x[2]))

    point_by_id = {r["validation_point_id"]: r for r in points}
    both_points = [r for r in points if r["source_category"] == "BOTH"]
    both_by_ts: dict[str, list[dict]] = defaultdict(list)
    for row in both_points:
        both_by_ts[row["timestamp"]].append(row)

    angular_hit_vertices: set[tuple[str, str]] = set()
    both_vertex_keys: set[tuple[str, str]] = set()
    vertex_rows: list[dict] = []
    both_nonvertices = 0
    endpoint_match_failures = 0

    for vkey in sorted(vertex_coord):
        ts, vertex_id = vkey
        p = vertex_coord[vkey]
        angular_hits = [x for x in angular_coords_by_ts[ts] if coord_close((x[0], x[1]), p)]
        both_hits = [r for r in both_by_ts[ts] if coord_close((f(r, "p13_abs_kw"), f(r, "p30_abs_kw")), p)]
        if angular_hits:
            angular_hit_vertices.add(vkey)
        if both_hits:
            both_vertex_keys.add(vkey)
        endpoint = nearest_row(official_safe_by_ts[ts], p)
        if endpoint is None:
            endpoint_match_failures += 1
        attempt = nearest_row(production_attempts_by_ts[ts], p)
        vertex_rows.append({
            "timestamp": ts, "vertex_id": vertex_id,
            "p13_abs_kw": p[0], "p30_abs_kw": p[1],
            "polygon_status": vertex_status[vkey], "signed_turn_deg": vertex_turn[vkey],
            "angular_mesh_hit": bool(angular_hits), "angular_hit_count": len(angular_hits),
            "both_point_match": bool(both_hits), "both_match_count": len(both_hits),
            "missed_by_angular_mesh": not angular_hits,
            "prior_official_safe_endpoint": endpoint is not None,
            "prior_production_attempt_evidence": attempt is not None,
            "prior_production_solver_status": attempt[3]["solver_status"] if attempt else "",
        })

    for row in both_points:
        p = (f(row, "p13_abs_kw"), f(row, "p30_abs_kw"))
        if not any(coord_close(p, q)
                   for (ts, _), q in vertex_coord.items() if ts == row["timestamp"]):
            both_nonvertices += 1

    vertex_hypothesis = angular_hit_vertices == both_vertex_keys and both_nonvertices == 0
    check("OUTER_VERTEX_COUNT", len(vertex_coord) == 1689, str(len(vertex_coord)))
    check("BOTH_COUNT", len(both_points) == 1554, str(len(both_points)))
    check("BOTH_EQUALS_ANGULAR_HIT_OUTER_VERTICES", vertex_hypothesis,
          f"angular_hits={len(angular_hit_vertices)}, both_vertex_keys={len(both_vertex_keys)}, both_nonvertices={both_nonvertices}")
    check("ALL_VERTICES_HAVE_PRODUCTION_ENDPOINT", endpoint_match_failures == 0,
          f"missing={endpoint_match_failures}")

    topology_coeff: dict[tuple[int, int], float] = {}
    topology_base_mva = 10.0
    for row in topology:
        topology_coeff[(int(row["candidate_bus"]), int(row["injection_bus"]))] = f(row, "topology_reconstructed_coefficient_pu_per_pu")
        topology_base_mva = f(row, "base_mva")

    edge_rows: list[dict] = []
    edge_metric: dict[tuple[str, str], dict] = {}
    ownership_bad = 0
    nonconvex_owner = 0
    nonpositive_cap = 0

    for key in sorted(edge_by_key):
        ts, edge_id = key
        row = edge_by_key[key]
        a = (f(row, "endpoint_a_p13_abs_kw"), f(row, "endpoint_a_p30_abs_kw"))
        b = (f(row, "endpoint_b_p13_abs_kw"), f(row, "endpoint_b_p30_abs_kw"))
        v = sub(b, a)
        length = norm(v)
        orient = polygon_orientation[ts]
        inward = ((-v[1] / length) * orient, (v[0] / length) * orient)
        eps = 1e-12
        if inward[0] <= eps and inward[1] <= eps:
            sign_pattern = "componentwise_nonpositive"
        elif inward[0] >= -eps and inward[1] >= -eps:
            sign_pattern = "componentwise_positive"
        elif inward[0] * inward[1] < 0:
            sign_pattern = "mixed_sign"
        else:
            sign_pattern = "axis_or_near_zero"

        owners = []
        caps = []
        facets = []
        for ckey, verts in cell_vertices.items():
            if ckey[0] != ts:
                continue
            n = len(verts)
            for i in range(n):
                x, y = verts[i], verts[(i + 1) % n]
                direct = coord_close(x, a) and coord_close(y, b)
                reverse = coord_close(x, b) and coord_close(y, a)
                if direct or reverse:
                    owners.append(ckey[1])
                    facets.append(f"C{ckey[1]}:F{i}")
                    cap = max(dot(inward, sub(q, a)) for q in verts)
                    caps.append(cap)
                    if not all(truth(r["cell_convex"]) for r in cell_rows[ckey]):
                        nonconvex_owner += 1
                    break
        if len(owners) != 1:
            ownership_bad += 1
        cap = min(caps) if caps else math.nan
        if not finite(cap) or cap <= 0:
            nonpositive_cap += 1

        fractions = unique_fractions([f(r, "edge_interpolation_fraction") for r in angular_prov_by_edge[key]])
        current_gaps = gaps(fractions)
        max_gap = max(current_gaps)
        sorted_with_endpoints = unique_fractions([0.0, 1.0, *fractions])
        gap_pairs = [(sorted_with_endpoints[i + 1] - sorted_with_endpoints[i], sorted_with_endpoints[i], sorted_with_endpoints[i + 1]) for i in range(len(sorted_with_endpoints) - 1)]
        gap_pairs.sort(reverse=True)
        largest, left, right = gap_pairs[0]
        h2_t = (left + right) / 2
        h2_fractions = unique_fractions([*fractions, h2_t])
        h2_gap = max(gaps(h2_fractions))

        h1_new: list[float] = []
        center = centers[ts]
        seg = sub(b, a)
        for k in range(720):
            theta = math.radians(0.25 + 0.5 * k)
            direction = (math.cos(theta), math.sin(theta))
            den = cross(direction, seg)
            if abs(den) <= 1e-14:
                continue
            ac = sub(a, center)
            ray_s = cross(ac, seg) / den
            t = cross(ac, direction) / den
            if ray_s >= -COORD_TOL_KW and 1e-12 < t < 1 - 1e-12:
                h1_new.append(t)
        h1_new = unique_fractions(h1_new)
        h1_all = unique_fractions([*fractions, *h1_new])
        h1_gap = max(gaps(h1_all))

        akey = (ts, row["endpoint_a_id"])
        bkey = (ts, row["endpoint_b_id"])
        combo = f"{vertex_status[akey]}-{vertex_status[bkey]}"
        mean_abs_turn = (abs(vertex_turn[akey]) + abs(vertex_turn[bkey])) / 2
        max_abs_turn = max(abs(vertex_turn[akey]), abs(vertex_turn[bkey]))
        metric = {
            "timestamp": ts, "edge_id": edge_id,
            "endpoint_a_id": row["endpoint_a_id"], "endpoint_b_id": row["endpoint_b_id"],
            "boundary_class": row["boundary_class"], "guard_relation": row["guard_relation"],
            "edge_length_kw": length, "edge_length_squared_kw2": length * length,
            "angular_span_deg": f(row, "angular_span_deg"),
            "inward_normal_p13": inward[0], "inward_normal_p30": inward[1],
            "normal_sign_category": sign_pattern,
            "owner_cell_count": len(owners), "owner_cell_ids": ";".join(owners),
            "facet_identities": ";".join(facets), "parallel_retreat_cap_kw": cap,
            "convexity_implication": "CONVEX_FOR_0_LE_D_LT_CAP;DEGENERATE_AT_CAP" if finite(cap) and cap > 0 else "UNDEFINED",
            "endpoint_status_combination": combo,
            "endpoint_a_status": vertex_status[akey], "endpoint_b_status": vertex_status[bkey],
            "endpoint_a_signed_turn_deg": vertex_turn[akey], "endpoint_b_signed_turn_deg": vertex_turn[bkey],
            "mean_abs_endpoint_turn_deg": mean_abs_turn, "max_abs_endpoint_turn_deg": max_abs_turn,
            "n_e": len(fractions), "sorted_fractions": ";".join(fmt(x) for x in fractions),
            "zero_sample_flag": len(fractions) == 0, "low_sample_flag": len(fractions) < 3,
            "g_e": max_gap,
            "h1_new_sample_count": len([x for x in h1_new if all(abs(x - y) > 1e-12 for y in fractions)]),
            "h1_g_e": h1_gap, "h1_gap_reduction": max_gap - h1_gap,
            "h2_new_sample_count": 1, "h2_midpoint_t": h2_t,
            "h2_g_e": h2_gap, "h2_gap_reduction": max_gap - h2_gap,
            "h1_information_gain": "INFORMATION_GAINING" if max_gap - h1_gap > 1e-12 else "NEARLY_REDUNDANT",
            "h2_information_gain": "INFORMATION_GAINING" if max_gap - h2_gap > 1e-12 else "NEARLY_REDUNDANT",
        }
        edge_metric[key] = metric
        edge_rows.append(metric)

    check("EXACTLY_ONE_OWNER_CELL_PER_OUTER_EDGE", ownership_bad == 0,
          f"inconsistent_edges={ownership_bad}")
    check("ALL_OWNER_CELLS_CONVEX", nonconvex_owner == 0,
          f"nonconvex_owner_occurrences={nonconvex_owner}")
    check("ALL_RETREAT_CAPS_POSITIVE", nonpositive_cap == 0,
          f"nonpositive_or_undefined={nonpositive_cap}")

    def find_edge_for_point(row: dict[str, str]) -> tuple[tuple[str, str] | None, float, float]:
        ts = row["timestamp"]
        source = row.get("source_polygon_edge_id", "")
        if source and (ts, source) in edge_by_key:
            e = edge_by_key[(ts, source)]
            t, d = projection_fraction_distance(
                (f(row, "p13_abs_kw"), f(row, "p30_abs_kw")),
                (f(e, "endpoint_a_p13_abs_kw"), f(e, "endpoint_a_p30_abs_kw")),
                (f(e, "endpoint_b_p13_abs_kw"), f(e, "endpoint_b_p30_abs_kw")),
            )
            return (ts, source), t, d
        candidates = []
        p = (f(row, "p13_abs_kw"), f(row, "p30_abs_kw"))
        for e in edges_by_ts[ts]:
            t, d = projection_fraction_distance(
                p,
                (f(e, "endpoint_a_p13_abs_kw"), f(e, "endpoint_a_p30_abs_kw")),
                (f(e, "endpoint_b_p13_abs_kw"), f(e, "endpoint_b_p30_abs_kw")),
            )
            if -1e-10 <= t <= 1 + 1e-10:
                candidates.append((d, int(e["source_polygon_edge_id"][1:]), (ts, e["source_polygon_edge_id"]), t))
        if not candidates:
            return None, math.nan, math.inf
        best = min(candidates)
        return best[2], best[3], best[0]

    angular_points = [r for r in points if truth(r["has_angular_boundary_provenance"])]
    angular_points_by_edge: dict[tuple[str, str], list[tuple[dict, float]]] = defaultdict(list)
    point_edge_map: dict[str, tuple[tuple[str, str] | None, float, float]] = {}
    for row in points:
        if truth(row["on_main_angular_polygon_boundary"]):
            point_edge_map[row["validation_point_id"]] = find_edge_for_point(row)
    for row in angular_points:
        key, t, d = point_edge_map[row["validation_point_id"]]
        if key is not None:
            angular_points_by_edge[key].append((row, t))

    margin_summary_rows: list[dict] = []
    margin_groups: dict[tuple[str, str], list[float]] = defaultdict(list)
    for row in angular_points:
        for channel in channels_for_class(row["boundary_class"]):
            margin_groups[(row["boundary_class"], channel)].append(margin(row, channel))
    for (boundary_class, channel), values in sorted(margin_groups.items()):
        s = stats(values)
        margin_summary_rows.append({
            "boundary_class": boundary_class, "margin_channel": channel, **s,
            "fraction_below_1e-5": sum(x < 1e-5 for x in values) / len(values),
            "fraction_below_1e-4": sum(x < 1e-4 for x in values) / len(values),
            "fraction_below_1e-3": sum(x < 1e-3 for x in values) / len(values),
            "negative_margin_count": sum(x < 0 for x in values),
        })

    endpoint_cache: dict[tuple[str, str], dict | None] = {}
    for vkey, p in vertex_coord.items():
        match = nearest_row(official_safe_by_ts[vkey[0]], p)
        endpoint_cache[vkey] = match[3] if match else None

    fit_rows: list[dict] = []
    fit_by_edge_channel: dict[tuple[tuple[str, str], str], dict] = {}
    sufficient_fit_count = 0
    for key in sorted(edge_by_key):
        e = edge_by_key[key]
        akey = (key[0], e["endpoint_a_id"])
        bkey = (key[0], e["endpoint_b_id"])
        ra, rb = endpoint_cache[akey], endpoint_cache[bkey]
        for channel in channels_for_class(e["boundary_class"]):
            samples = [(r, t) for r, t in angular_points_by_edge[key] if 1e-12 < t < 1 - 1e-12]
            enough = len(samples) >= 3 and ra is not None and rb is not None
            ya = margin(ra, channel) if ra else math.nan
            yb = margin(rb, channel) if rb else math.nan
            s_e = math.nan
            chord_rmse = model_rmse = max_abs = improvement = r2 = math.nan
            if enough:
                basis = [t * (1 - t) for _, t in samples]
                observed = [margin(r, channel) for r, _ in samples]
                chords = [(1 - t) * ya + t * yb for _, t in samples]
                denom = sum(x * x for x in basis)
                s_e = sum(x * (y - c) for x, y, c in zip(basis, observed, chords)) / denom
                predictions = [c + s_e * x for c, x in zip(chords, basis)]
                chord_sse = sum((y - c) ** 2 for y, c in zip(observed, chords))
                model_sse = sum((y - p) ** 2 for y, p in zip(observed, predictions))
                chord_rmse = math.sqrt(chord_sse / len(samples))
                model_rmse = math.sqrt(model_sse / len(samples))
                max_abs = max(abs(y - p) for y, p in zip(observed, predictions))
                improvement = 1 - model_sse / chord_sse if chord_sse else math.nan
                mean_y = statistics.fmean(observed)
                sst = sum((y - mean_y) ** 2 for y in observed)
                r2 = 1 - model_sse / sst if sst else math.nan
                sufficient_fit_count += 1

            buses = []
            for token in e["endpoint_binding_classes"].split(";"):
                if channel.startswith("VMAX") and token.startswith("VMAX_BUS_"):
                    buses.append(int(token.rsplit("_", 1)[1]))
                if channel.startswith("VMIN") and token.startswith("VMIN_BUS_"):
                    buses.append(int(token.rsplit("_", 1)[1]))
            buses = sorted(set(buses))
            grad_scales = []
            em = edge_metric[key]
            for bus in buses:
                c13 = topology_coeff.get((bus, 13), math.nan) / (topology_base_mva * 1000)
                c30 = topology_coeff.get((bus, 30), math.nan) / (topology_base_mva * 1000)
                sign = -1 if channel == "VMAX_MARGIN" else 1
                grad_scales.append(abs(sign * (c13 * em["inward_normal_p13"] + c30 * em["inward_normal_p30"])))
            topology_scale = statistics.fmean(grad_scales) if grad_scales else math.nan
            out = {
                "timestamp": key[0], "edge_id": key[1],
                "boundary_class": e["boundary_class"], "guard_relation": e["guard_relation"],
                "margin_channel": channel, "interior_sample_count": len(samples),
                "fit_sufficient": enough, "endpoint_a_margin": ya, "endpoint_b_margin": yb,
                "s_e_pu": s_e, "abs_s_e_pu": abs(s_e) if finite(s_e) else math.nan,
                "chord_rmse_pu": chord_rmse, "model_rmse_pu": model_rmse,
                "model_max_abs_residual_pu": max_abs,
                "sse_improvement_fraction": improvement, "model_r2": r2,
                "edge_length_squared_kw2": em["edge_length_squared_kw2"],
                "angular_span_deg": em["angular_span_deg"],
                "mean_abs_endpoint_turn_deg": em["mean_abs_endpoint_turn_deg"],
                "max_abs_endpoint_turn_deg": em["max_abs_endpoint_turn_deg"],
                "topology_normal_margin_sensitivity_pu_per_kw": topology_scale,
                "interpretation": "DIAGNOSTIC_ASSOCIATION_NOT_MECHANISM_PROOF",
            }
            fit_rows.append(out)
            fit_by_edge_channel[(key, channel)] = out

    check("WITHIN_EDGE_FITS_AVAILABLE", sufficient_fit_count > 0,
          f"sufficient_fits={sufficient_fit_count}")

    numerical_replay_values = [abs(f(r, "primary_replay_voltage_difference_pu")) for r in validation_attempts]
    median_replay = statistics.median(numerical_replay_values)
    sufficient_fits = [r for r in fit_rows if truth(str(r["fit_sufficient"])) if finite(r["s_e_pu"])]
    improvements = [r["sse_improvement_fraction"] for r in sufficient_fits if finite(r["sse_improvement_fraction"])]
    abs_s = [r["abs_s_e_pu"] for r in sufficient_fits]
    pattern_supported = (
        len(sufficient_fits) >= 100
        and improvements
        and sum(x > 0 for x in improvements) / len(improvements) >= 0.75
        and statistics.median(improvements) >= 0.50
        and statistics.median(abs_s) > 10 * median_replay
    )
    secondary_label = "PATTERN_CONSISTENT_WITH_CHORD_INTERPOLATION_ERROR" if pattern_supported else "NO_SECONDARY_PATTERN_LABEL_ASSIGNED"

    scaling_rows: list[dict] = []
    predictor_names = [
        "edge_length_squared_kw2", "angular_span_deg",
        "mean_abs_endpoint_turn_deg", "max_abs_endpoint_turn_deg",
        "topology_normal_margin_sensitivity_pu_per_kw",
    ]
    scaling_groups = {"ALL": sufficient_fits}
    for channel in ("VMAX_MARGIN", "VMIN_MARGIN"):
        scaling_groups[channel] = [r for r in sufficient_fits if r["margin_channel"] == channel]
    for group, rows in scaling_groups.items():
        for response in ("s_e_pu", "abs_s_e_pu"):
            ys = [r[response] for r in rows]
            for predictor in predictor_names:
                xs = [r[predictor] for r in rows]
                slope, intercept, r2 = regression(xs, ys)
                scaling_rows.append({
                    "group": group, "response": response, "predictor": predictor,
                    "n": sum(finite(x) and finite(y) for x, y in zip(xs, ys)),
                    "pearson_r": pearson(xs, ys), "spearman_rho": spearman(xs, ys),
                    "ols_slope": slope, "ols_intercept": intercept, "ols_r2": r2,
                    "interpretation": "DIAGNOSTIC_SCALING_ONLY_NOT_AUTHORITATIVE_RETREAT",
                })

    guard_rows: list[dict] = []
    angular_by_relation: dict[str, list[dict]] = defaultdict(list)
    for row in angular_points:
        angular_by_relation[row["guard_relation"]].append(row)
    for relation in ("CROSSES_GUARD_LIMITED_RAY", "ADJACENT_TO_GUARD_LIMITED_EDGE", "NONE"):
        erows = [r for r in edge_rows if r["guard_relation"] == relation]
        prows = angular_by_relation[relation]
        failures = [r for r in prows if r["final_status"] == "CONVERGED_INFEASIBLE"]
        fits = [r for r in sufficient_fits if r["guard_relation"] == relation]
        row = {
            "guard_relation": relation, "edge_count": len(erows),
            "boundary_point_count": len(prows), "failure_count": len(failures),
            "failure_rate": len(failures) / len(prows) if prows else math.nan,
            "violation_magnitude_median_pu": statistics.median([f(r, "voltage_violation_magnitude_pu") for r in failures]) if failures else math.nan,
            "violation_magnitude_max_pu": max([f(r, "voltage_violation_magnitude_pu") for r in failures], default=math.nan),
            "edge_length_median_kw": statistics.median([r["edge_length_kw"] for r in erows]) if erows else math.nan,
            "angular_span_median_deg": statistics.median([r["angular_span_deg"] for r in erows]) if erows else math.nan,
            "n_e_median": statistics.median([r["n_e"] for r in erows]) if erows else math.nan,
            "g_e_median": statistics.median([r["g_e"] for r in erows]) if erows else math.nan,
            "abs_s_e_median_pu": statistics.median([r["abs_s_e_pu"] for r in fits]) if fits else math.nan,
            "abs_s_e_max_pu": max([r["abs_s_e_pu"] for r in fits], default=math.nan),
            "association_statement": "ASSOCIATION_OBSERVED_CAUSAL_MECHANISM_NOT_ESTABLISHED",
        }
        guard_rows.append(row)
    guard_lookup = {r["guard_relation"]: r for r in guard_rows}
    check("GUARD_CROSSING_RECONSTRUCTION",
          guard_lookup["CROSSES_GUARD_LIMITED_RAY"]["boundary_point_count"] == 1371 and guard_lookup["CROSSES_GUARD_LIMITED_RAY"]["failure_count"] == 0,
          f"points={guard_lookup['CROSSES_GUARD_LIMITED_RAY']['boundary_point_count']},failures={guard_lookup['CROSSES_GUARD_LIMITED_RAY']['failure_count']}")
    check("GUARD_ADJACENT_FAILURE_RECONSTRUCTION",
          guard_lookup["ADJACENT_TO_GUARD_LIMITED_EDGE"]["failure_count"] == 576,
          f"failures={guard_lookup['ADJACENT_TO_GUARD_LIMITED_EDGE']['failure_count']}")
    check("NONGUARD_FAILURE_RECONSTRUCTION",
          guard_lookup["NONE"]["failure_count"] == 6484,
          f"failures={guard_lookup['NONE']['failure_count']}")

    reflex_groups: dict[str, list[dict]] = defaultdict(list)
    boundary_mapping_failures = 0
    for row in points:
        if not truth(row["on_main_angular_polygon_boundary"]):
            continue
        key, t, d = point_edge_map[row["validation_point_id"]]
        if key is None or d > COORD_TOL_KW:
            boundary_mapping_failures += 1
            continue
        reflex_groups[edge_metric[key]["endpoint_status_combination"]].append(row)
    reflex_rows = []
    for combo, rows in sorted(reflex_groups.items()):
        failures = [r for r in rows if r["final_status"] == "CONVERGED_INFEASIBLE"]
        vmax_fail = [r for r in failures if r["primary_violation_mechanism"].startswith("VMAX")]
        vmin_fail = [r for r in failures if r["primary_violation_mechanism"].startswith("VMIN")]
        reflex_rows.append({
            "endpoint_status_combination": combo,
            "edge_count": sum(r["endpoint_status_combination"] == combo for r in edge_rows),
            "boundary_point_count": len(rows), "failure_count": len(failures),
            "failure_rate": len(failures) / len(rows),
            "vmax_failure_count": len(vmax_fail), "vmin_failure_count": len(vmin_fail),
            "interpretation": "ASSOCIATIONAL_FALSIFIABLE_DIAGNOSTIC_NOT_THEOREM",
        })
    check("ALL_BOUNDARY_POINTS_MAP_TO_EDGE", boundary_mapping_failures == 0,
          f"unmapped={boundary_mapping_failures}")

    validation_angular_ids = {r["validation_point_id"] for r in angular_points}
    official_coords_by_ts = {
        ts: [(f(r, "p13_abs_kw"), f(r, "p30_abs_kw")) for r in rows]
        for ts, rows in official_safe_by_ts.items()
    }

    def is_official_attempt(row: dict[str, str]) -> bool:
        p = (f(row, "p13_abs_kw"), f(row, "p30_abs_kw"))
        return any(coord_close(p, q) for q in official_coords_by_ts[row["timestamp"]])

    numerical_groups = {
        "VALIDATION_ALL_ATTEMPTS": validation_attempts,
        "VALIDATION_SUBSTANTIVE_ATTEMPTS": [r for r in validation_attempts if r["external_kind"] == "SUBSTANTIVE"],
        "VALIDATION_ANGULAR_BOUNDARY_ATTEMPTS": [r for r in validation_attempts if r["external_id"] in validation_angular_ids],
        "PRODUCTION_ALL_ATTEMPTS": production_attempts,
        "PRODUCTION_OFFICIAL_SAFE_ENDPOINT_ATTEMPTS": [r for r in production_attempts if is_official_attempt(r)],
    }
    numerical_rows = []
    numerical_metrics = [
        "primary_replay_voltage_difference_pu", "maximum_residual",
        "primary_iterations", "replay_iterations", "runtime_ms",
    ]
    for group, rows in numerical_groups.items():
        for metric_name in numerical_metrics:
            values = [abs(f(r, metric_name)) for r in rows if r[metric_name] not in ("", "NaN")]
            numerical_rows.append({"group": group, "metric": metric_name, **stats(values)})

    runtime_rows = []
    component_keys = [
        ("setup", "setup_seconds"), ("controls", "control_execution_seconds"),
        ("retained_substantive_ac", "substantive_ac_execution_seconds"),
        ("checkpoint_io", "checkpoint_io_seconds"),
        ("postprocessing", "summary_postprocessing_seconds"),
    ]
    total_wall = runtime["total_wall_seconds"]
    attributable = sum(runtime[k] for _, k in component_keys)
    unattributed = total_wall - attributable
    for label, keyname in component_keys:
        runtime_rows.append({
            "component": label, "seconds": runtime[keyname],
            "fraction_of_total": runtime[keyname] / total_wall,
            "timer_scope": "ADDITIVE_MEASURED_COMPONENT",
            "evidence": keyname,
        })
    runtime_rows.extend([
        {"component": "active_measured_total", "seconds": attributable,
         "fraction_of_total": attributable / total_wall, "timer_scope": "ADDITIVE_SUM",
         "evidence": "sum of five measured components"},
        {"component": "operational_resume_and_uninstrumented", "seconds": unattributed,
         "fraction_of_total": unattributed / total_wall, "timer_scope": "RESIDUAL_NOT_DECOMPOSABLE",
         "evidence": "total wall minus active measured components"},
        {"component": "final_resume_wall_nonadditive", "seconds": runtime["final_resume_wall_seconds"],
         "fraction_of_total": runtime["final_resume_wall_seconds"] / total_wall,
         "timer_scope": "NONADDITIVE_LAST_PROCESS_SCOPE",
         "evidence": "final_resume_wall_seconds"},
    ])
    check("RUNTIME_ACTIVE_SUM_MATCH", abs(attributable - runtime["active_measured_component_seconds"]) < 1e-9,
          f"computed={fmt(attributable)},stored={fmt(runtime['active_measured_component_seconds'])}")
    check("RUNTIME_UNATTRIBUTED_MATCH", abs(unattributed - runtime["operational_resume_and_uninstrumented_seconds"]) < 1e-9,
          f"computed={fmt(unattributed)},stored={fmt(runtime['operational_resume_and_uninstrumented_seconds'])}")

    timer_scope_rows = []
    for row in timer_inventory:
        timer_scope_rows.append({
            "scope_family": "COMMITTED_BENCHMARK_VS_PRODUCTION_INVENTORY",
            "operation": row["operation"],
            "timer_scope": f"benchmark={row['benchmark_timer_scope']};production={row['production_full_run_scope']}",
            "additive_in_validation_runtime": "NOT_DIRECTLY_APPLICABLE",
            "evidence": row["evidence"], "detail": row["detail"],
        })
    timer_scope_rows.extend([
        {"scope_family": "VALIDATION_CAMPAIGN", "operation": "setup",
         "timer_scope": "SCRIPT_START_TO_POST_NETWORK_PROFILE_SETUP_ON_FINAL_RESUME",
         "additive_in_validation_runtime": "YES_AS_STORED_FINAL_RESUME_SCOPE",
         "evidence": "validation_script:3,468,499",
         "detail": "Includes imports, launch/manifest verification, committed CSV reads, network/profile construction; the stored scalar is not a per-resume decomposition."},
        {"scope_family": "VALIDATION_CAMPAIGN", "operation": "control/substantive evaluation wrapper",
         "timer_scope": "EVALUATE_PHYSICAL_CALL_ONLY",
         "additive_in_validation_runtime": "YES_ACCUMULATED_THROUGH_CHECKPOINT_PAYLOAD",
         "evidence": "validation_script:286-289,513,540-545,575-582",
         "detail": "Ends immediately after evaluate_physical!; subsequent external-ID mapping and attempt-row merges are outside this timer."},
        {"scope_family": "VALIDATION_CAMPAIGN", "operation": "checkpoint serialization and manifest",
         "timer_scope": "FULL_GROWING_PAYLOAD_SERIALIZE_HASH_AND_MANIFEST_WRITE",
         "additive_in_validation_runtime": "YES_ACCUMULATED_THROUGH_CHECKPOINT_PAYLOAD",
         "evidence": "validation_script:258-267,513,545,582,589",
         "detail": "Includes state serialization, checkpoint SHA-256, and checkpoint-manifest CSV write."},
        {"scope_family": "VALIDATION_CAMPAIGN", "operation": "summary postprocessing",
         "timer_scope": "FINAL_RESUME_POST_STARTED_TO_PRE_FINAL_RUNTIME_REWRITE",
         "additive_in_validation_runtime": "YES",
         "evidence": "validation_script:596-664",
         "detail": "Includes final tables, integrity checks, and report generation through the measured boundary; later final report/runtime rewrites and manifest hashing are outside."},
        {"scope_family": "VALIDATION_CAMPAIGN", "operation": "final resume wall",
         "timer_scope": "SCRIPT_START_TO_FINAL_SUMMARY_BOUNDARY_ON_LAST_PROCESS",
         "additive_in_validation_runtime": "NO_NONADDITIVE_SCOPE",
         "evidence": "validation_script:3,627,664",
         "detail": "A last-process wall scope; it is not the 393.033326 s multi-resume campaign total and must not be added to component timers."},
        {"scope_family": "VALIDATION_CAMPAIGN", "operation": "campaign total wall",
         "timer_scope": "LOCKED_EXTERNAL_MULTI_RESUME_END_TO_END_SCALAR",
         "additive_in_validation_runtime": "DENOMINATOR_ONLY",
         "evidence": "validation_script:24,631,670",
         "detail": "The residual after additive timers is operational resume and uninstrumented time; committed artifacts do not identify its internal allocation."},
    ])

    capability_rows = []
    for r in edge_rows:
        capability_rows.append({
            "timestamp": r["timestamp"], "edge_id": r["edge_id"],
            "boundary_class": r["boundary_class"], "guard_relation": r["guard_relation"],
            "calibration_n_e": r["n_e"], "calibration_g_e": r["g_e"],
            "zero_sample_flag": r["zero_sample_flag"], "low_sample_flag": r["low_sample_flag"],
            "h1_definition": "INTERLACED_0.25_PLUS_0.5K_DEGREE_RAYS",
            "h1_new_sample_count": r["h1_new_sample_count"], "h1_g_e": r["h1_g_e"],
            "h1_gap_reduction": r["h1_gap_reduction"], "h1_information_gain": r["h1_information_gain"],
            "h2_definition": "MIDPOINT_OF_CURRENT_LARGEST_T_GAP",
            "h2_new_sample_count": r["h2_new_sample_count"], "h2_midpoint_t": r["h2_midpoint_t"],
            "h2_g_e": r["h2_g_e"], "h2_gap_reduction": r["h2_gap_reduction"],
            "h2_information_gain": r["h2_information_gain"],
            "criterion": "PURELY_GEOMETRIC_GAP_NO_STOCHASTIC_POWER_CLAIM",
        })

    cap_summary_rows = []
    strata = [("ALL", "ALL", edge_rows)]
    for field in ("boundary_class", "guard_relation", "normal_sign_category"):
        for value in sorted({r[field] for r in edge_rows}):
            strata.append((field, value, [r for r in edge_rows if r[field] == value]))
    for dimension, value, rows in strata:
        values = [r["parallel_retreat_cap_kw"] for r in rows]
        cap_summary_rows.append({
            "stratum_dimension": dimension, "stratum_value": value, **stats(values),
            "count_below_0_5_kw": sum(x < 0.5 for x in values),
            "count_below_1_kw": sum(x < 1 for x in values),
            "count_below_2_kw": sum(x < 2 for x in values),
            "count_below_5_kw": sum(x < 5 for x in values),
            "threshold_interpretation": "DESCRIPTIVE_HEURISTIC_NOT_BLOCKER",
        })

    locked = interpretation["C_failure_localization"]
    check("LOCKED_TOTAL_FAILURES", locked["total_counterexamples"] == 9420, str(locked["total_counterexamples"]))
    check("LOCKED_DIRECT_ANGULAR_FAILURES", locked["boundary_inter_ray_counterexamples"] == 7060, str(locked["boundary_inter_ray_counterexamples"]))
    check("LOCKED_CELL_EDGE_FAILURES", locked["cell_edge_counterexamples"] == 2360, str(locked["cell_edge_counterexamples"]))
    check("LOCKED_STRICT_INTERIOR_FAILURES", locked["strict_cell_interior_counterexamples"] == 0, str(locked["strict_cell_interior_counterexamples"]))

    n_values = [r["n_e"] for r in edge_rows]
    g_values = [r["g_e"] for r in edge_rows]
    cap_values = [r["parallel_retreat_cap_kw"] for r in edge_rows]
    missed_vertices = [r for r in vertex_rows if r["missed_by_angular_mesh"]]
    missed_with_evidence = [r for r in missed_vertices if r["prior_production_attempt_evidence"]]
    convex_convex = next((r for r in reflex_rows if r["endpoint_status_combination"] == "CONVEX-CONVEX"), None)
    margin_by_class = {(r["boundary_class"], r["margin_channel"]): r for r in margin_summary_rows}

    blocker_checks = [r for r in checks if r["status"] == "BLOCKER"]
    failed_checks = [r for r in checks if r["status"] == "FAIL"]
    overall = "BLOCKED_BEFORE_REPAIR_PREREGISTRATION" if blocker_checks else "NO_AUDIT_BLOCKER_DETECTED"

    summary = {
        "schema_version": 1,
        "artifact": "DSO_VPP_INTEGRATED_REPAIRABILITY_INTERPOLATION_AUDIT",
        "source_commit": SOURCE_COMMIT,
        "artifact_only": True,
        "new_ac_solves_replays_probes_repairs": 0,
        "overall_blocker_status": overall,
        "blocker_checks": [r["check_id"] for r in blocker_checks],
        "locked_campaign_classification": "MAIN_COUPLED_DOE_GEOMETRIC_CANDIDATE_FALSIFIED_BY_AC_COUNTEREXAMPLE",
        "secondary_diagnostic_label": secondary_label,
        "edge_repairability": {
            "edge_count": len(edge_rows), "ownership_inconsistencies": ownership_bad,
            "nonpositive_caps": nonpositive_cap, "cap_distribution_kw": stats(cap_values),
            "cap_threshold_counts": {"below_0.5": sum(x < 0.5 for x in cap_values),
                                     "below_1": sum(x < 1 for x in cap_values),
                                     "below_2": sum(x < 2 for x in cap_values),
                                     "below_5": sum(x < 5 for x in cap_values)},
        },
        "sampling": {
            "n_e_distribution": stats([float(x) for x in n_values]),
            "g_e_distribution": stats(g_values),
            "zero_sample_edges": sum(x == 0 for x in n_values),
            "low_sample_edges_n_lt_3": sum(x < 3 for x in n_values),
        },
        "vertex_both_mapping": {
            "outer_vertices_total": len(vertex_coord),
            "angular_hit_outer_vertices": len(angular_hit_vertices),
            "missed_outer_vertices": len(missed_vertices),
            "both_count": len(both_points),
            "both_non_outer_vertex_coincidences": both_nonvertices,
            "hypothesis_both_equals_angular_hit_outer_vertices": vertex_hypothesis,
            "missed_vertices_with_prior_production_ac_evidence": len(missed_with_evidence),
        },
        "within_edge_interpolation": {
            "sufficient_fit_count": len(sufficient_fits),
            "positive_improvement_fraction": sum(x > 0 for x in improvements) / len(improvements) if improvements else math.nan,
            "median_sse_improvement_fraction": statistics.median(improvements) if improvements else math.nan,
            "median_abs_s_e_pu": statistics.median(abs_s) if abs_s else math.nan,
            "interpretation": "DIAGNOSTIC_ASSOCIATION_NOT_MECHANISM_PROOF",
        },
        "guard": {r["guard_relation"]: r for r in guard_rows},
        "reflex_convex": {"convex_convex": convex_convex},
        "runtime": {
            "total_wall_seconds": total_wall, "attributable_seconds": attributable,
            "unattributed_seconds": unattributed,
            "checkpoint_io_seconds": runtime["checkpoint_io_seconds"],
            "substantive_ac_seconds": runtime["substantive_ac_execution_seconds"],
            "checkpoint_to_ac_ratio": runtime["checkpoint_io_seconds"] / runtime["substantive_ac_execution_seconds"],
            "missing_wall_time_identifiability": "NOT_SEPARATELY_IDENTIFIABLE_FROM_COMMITTED_TIMERS",
            "ac_core_rate_identifiability": runtime_reconciliation["ac_core_rate"],
            "timer_scope_inventory_rows": len(timer_scope_rows),
        },
        "policy": {
            "safe_box": "SAFE_BOX_EXTRACTION_STRICTLY_AFTER_FINAL_REPAIRED_COUPLED_DOE_FREEZE",
            "future_metrics": ["repair_area_loss", "hosting_capacity_loss"],
            "headroom": {
                "h_design": "CONSERVATIVE_DESIGN_HEADROOM_USED_TO_CONSTRUCT_REPAIR_NOT_SET_HERE",
                "assessment": "LATER_PREREGISTRATION_MAY_VALIDATE_ORIGINAL_AC_LIMITS_AND_OR_A_HEADROOM_CLAIM",
                "replay_tolerance_floor": "NO_MANDATORY_FLOOR_INFERRED",
            },
        },
        "caveats": [
            "No AC inference is made from geometry alone.",
            "The fitted interpolation term is diagnostic association, not mechanism proof.",
            "Topology-derived coefficients are diagnostic scaling context only and do not determine authoritative retreat.",
            "Guard association is observed; causal mechanism is not established.",
            "Reflex/convex results are associational and do not establish a theorem.",
            "Capability tiers use deterministic geometric gap reduction, not probability or statistical power.",
            "cap below a descriptive threshold is not a blocker; the future blocker is d_e_star greater than cap_e after AC calibration.",
            "No authoritative AC retreat or h_design is estimated in this audit.",
        ],
    }

    OUTDIR.mkdir(parents=True, exist_ok=True)
    outputs: list[Path] = []

    def emit_csv(name: str, fields: list[str], rows: list[dict]):
        path = OUTDIR / name
        write_csv(path, fields, rows)
        outputs.append(path)

    emit_csv("detailed_checks.csv", ["check_id", "status", "detail"], checks)
    emit_csv("edge_repairability_sampling.csv", list(edge_rows[0].keys()), edge_rows)
    emit_csv("vertex_both_mapping.csv", list(vertex_rows[0].keys()), vertex_rows)
    emit_csv("signed_boundary_margin_summary.csv", list(margin_summary_rows[0].keys()), margin_summary_rows)
    emit_csv("edge_interpolation_fits.csv", list(fit_rows[0].keys()), fit_rows)
    emit_csv("between_edge_scaling.csv", list(scaling_rows[0].keys()), scaling_rows)
    emit_csv("guard_anomaly_decomposition.csv", list(guard_rows[0].keys()), guard_rows)
    emit_csv("reflex_convex_association.csv", list(reflex_rows[0].keys()), reflex_rows)
    emit_csv("numerical_replay_diagnostics.csv", list(numerical_rows[0].keys()), numerical_rows)
    emit_csv("runtime_attribution.csv", list(runtime_rows[0].keys()), runtime_rows)
    emit_csv("timer_scope_analysis.csv", list(timer_scope_rows[0].keys()), timer_scope_rows)
    emit_csv("holdout_geometric_capability.csv", list(capability_rows[0].keys()), capability_rows)
    emit_csv("geometric_retreat_cap_summary.csv", list(cap_summary_rows[0].keys()), cap_summary_rows)

    summary_path = OUTDIR / "summary.json"
    write_text(summary_path, json.dumps(json_safe(summary), indent=2, sort_keys=True, allow_nan=False) + "\n")
    outputs.append(summary_path)

    source_files = []
    for path in sorted(PATHS.values()):
        data = git("show", f"{SOURCE_COMMIT}:{path}")
        source_files.append({"path": path, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()})
    source_manifest_path = OUTDIR / "source_manifest.json"
    write_text(source_manifest_path, json.dumps({
        "source_commit": SOURCE_COMMIT,
        "read_semantics": "DIRECT_GIT_OBJECT_BYTES_NOT_WORKING_TREE",
        "files": source_files,
    }, indent=2, sort_keys=True) + "\n")
    outputs.append(source_manifest_path)

    vmax13 = margin_by_class.get(("VMAX13", "VMAX_MARGIN"), {})
    vmax30 = margin_by_class.get(("VMAX30", "VMAX_MARGIN"), {})
    vmin18 = margin_by_class.get(("VMIN18", "VMIN_MARGIN"), {})
    vmin33 = margin_by_class.get(("VMIN33", "VMIN_MARGIN"), {})
    report = f"""# Integrated Repairability & Interpolation Audit

Source commit: `{SOURCE_COMMIT}`

This audit is deterministic and artifact-only. It performed **zero** new AC
solves, replays, probes, or repairs. Every scientific input was read directly
from the source commit through Git object bytes, so working-tree line endings
cannot affect the result.

## Decision status

Overall status: `{overall}`

Locked campaign classification (unchanged):

`MAIN_COUPLED_DOE_GEOMETRIC_CANDIDATE_FALSIFIED_BY_AC_COUNTEREXAMPLE`

Secondary diagnostic label: `{secondary_label}`. This label, when present,
is diagnostic-only and never replaces the locked falsification classification.

## 1. Edge-to-cell repairability

- outer edges: {len(edge_rows)}
- ownership inconsistencies: {ownership_bad}
- non-convex owner occurrences: {nonconvex_owner}
- nonpositive/undefined geometric caps: {nonpositive_cap}

For an edge with owner cell `C`, `cap_e` is the maximum inward support distance
from the edge facet to any vertex of `C`. Moving only that facet in parallel by
`0 <= d < cap_e` preserves convexity of the clipped cell; at `d = cap_e` the
remaining support becomes degenerate. This is a geometry-only limit. It is not
an AC retreat estimate.

Cap distribution (kW): min {fmt(min(cap_values))}, Q1 {fmt(quantile(cap_values, .25))},
median {fmt(statistics.median(cap_values))}, Q3 {fmt(quantile(cap_values, .75))},
max {fmt(max(cap_values))}. Counts below 0.5/1/2/5 kW are
{sum(x < .5 for x in cap_values)}/{sum(x < 1 for x in cap_values)}/
{sum(x < 2 for x in cap_values)}/{sum(x < 5 for x in cap_values)}.
These thresholds are descriptive only. `cap_e < 5 kW` is not a blocker; the
future real blocker is `d_e* > cap_e` after AC calibration.

## 2. Sampling density and deterministic holdout geometry

- zero-sample edges: {sum(x == 0 for x in n_values)}
- low-sample edges (`n_e < 3`): {sum(x < 3 for x in n_values)}
- median `n_e`: {fmt(statistics.median(n_values))}
- median/max `g_e`: {fmt(statistics.median(g_values))} / {fmt(max(g_values))}

Gap accounting always includes synthetic endpoints `t=0` and `t=1`. H1 is
the interlaced angular mesh `0.25 + 0.5k` degrees intersected with each stored
edge; H2 is one sample at the midpoint of the current largest `t` gap. The
capability table reports exact new-sample counts and gap reductions. It makes
no probability or statistical-power claim.

## 3. Exact vertex/BOTH mapping

- outer vertices: {len(vertex_coord)}
- angular-hit outer vertices: {len(angular_hit_vertices)}
- missed outer vertices: {len(missed_vertices)}
- BOTH points: {len(both_points)}
- BOTH non-outer-vertex coincidences: {both_nonvertices}
- missed vertices with prior production AC evidence: {len(missed_with_evidence)}

At the locked `{COORD_TOL_KW:g} kW` tolerance, the hypothesis
`BOTH = outer vertices hit by the angular mesh` is
`{'CONFIRMED' if vertex_hypothesis else 'FALSIFIED/BLOCKER'}`. Downstream
statistics use the independently reconstructed true sets.

## 4. Signed boundary margins

Margins use `1.05 - Vmax` for VMAX and `Vmin - 0.90` for VMIN. CLASS_TRANSITION
points contribute to both channels. Selected medians (p.u.): VMAX13
{fmt(vmax13.get('median', math.nan))}, VMAX30 {fmt(vmax30.get('median', math.nan))},
VMIN18 {fmt(vmin18.get('median', math.nan))}, VMIN33
{fmt(vmin33.get('median', math.nan))}. The complete min/Q1/median/Q3/max and
fractions below `1e-5`, `1e-4`, and `1e-3` are in the margin table. VMAX/VMIN
asymmetry is interpreted only in light of these stored-margin distributions;
no physical mechanism is claimed.

## 5-6. Within-edge interpolation and between-edge scaling

For each sufficiently sampled edge/channel, the stored endpoint margins are
used in the chord baseline and are never set to zero:

`r(t) = (1-t) r_a + t r_b + s_e t(1-t)`.

- sufficient fits: {len(sufficient_fits)}
- fraction improving on the endpoint chord: {fmt(sum(x > 0 for x in improvements) / len(improvements) if improvements else math.nan)}
- median SSE improvement: {fmt(statistics.median(improvements) if improvements else math.nan)}
- median `|s_e|`: {fmt(statistics.median(abs_s) if abs_s else math.nan)} p.u.

Scaling tables compare signed and absolute `s_e` with edge length squared,
angular span, local turn-angle curvature proxies, and topology-derived
LinDistFlow normal sensitivity. The coefficient reconstruction is artifact-only
and diagnostic. It does not determine authoritative facet retreat. Association
is not mechanism proof.

## 7. Guard anomaly decomposition

- crossing: {guard_lookup['CROSSES_GUARD_LIMITED_RAY']['failure_count']}/
  {guard_lookup['CROSSES_GUARD_LIMITED_RAY']['boundary_point_count']} failures
- adjacent: {guard_lookup['ADJACENT_TO_GUARD_LIMITED_EDGE']['failure_count']} failures
- non-guard: {guard_lookup['NONE']['failure_count']} failures

Edge length, angular span, `n_e`, `g_e`, fitted amplitude, and violation
statistics are reported side by side. **Association observed; causal mechanism
not established.**

## 8. Reflex/convex association

Endpoint-status combinations and boundary-point failure rates are reported as
an associational, falsifiable diagnostic. Convex-convex edges have
{convex_convex['failure_count'] if convex_convex else 0} failures among
{convex_convex['boundary_point_count'] if convex_convex else 0} mapped boundary
points. This is not a theorem.

## 9. Numerical/replay diagnostics and headroom concepts

The numerical table gives actual distributions of primary-vs-replay voltage
difference, maximum residual, primary/replay iterations, and runtime for all
validation attempts, angular-boundary validation points, all production
attempts, and production official SAFE endpoints.

`h_design` means conservative design headroom used later to construct a repair.
Assessment may later validate the original AC limits and/or a headroom claim,
depending on preregistration. This audit sets no `h`, and it infers no mandatory
headroom floor from replay-match tolerance.

## 10. Runtime attribution and checkpoint redesign

- end-to-end wall: {fmt(total_wall)} s
- attributable measured components: {fmt(attributable)} s
- unattributed operational resume/uninstrumented residual: {fmt(unattributed)} s
- retained substantive AC: {fmt(runtime['substantive_ac_execution_seconds'])} s
- checkpoint/I/O: {fmt(runtime['checkpoint_io_seconds'])} s
- checkpoint/I/O to substantive-AC ratio: {fmt(runtime['checkpoint_io_seconds'] / runtime['substantive_ac_execution_seconds'])}x

The last-process `final_resume_wall_seconds` is non-additive and cannot be
subtracted again. Committed source establishes 500 operationally reexecuted AC
calls, multiple resume-compatible script hashes, and timers around evaluation
and checkpoint serialization, but it does not separately time process startup,
resume orchestration, lost pre-checkpoint work, or all work between those
scopes. The {fmt(unattributed)} s residual therefore cannot be apportioned
further without guessing.

Deterministic future recommendation: write immutable append-only result shards
with stable IDs; checkpoint only a compact cursor and solver state; seal one
shard per completed timestamp; if within-timestamp recovery is required, use
fixed 2,000-row chunks rather than serializing the accumulated campaign every
250 points; concatenate and hash once in final postprocessing. AC compute is
cheap here, while repeated growing-state I/O is measured as expensive.

## 11-12. Holdout capability and cap distribution

The edge-level H1/H2 capability table resolves geometric information gain
without stochastic claims. The cap summary is stratified by boundary class,
guard relation, and normal-sign category. Neither table preregisters repair or
changes official validation classification.

## Locked evidence and policy

Validation commit `4612cac` remains locked at 65,494 points: 56,074 feasible,
9,420 converged-infeasible, zero unresolved, and 128/128 controls passing. All
9,420 failures are VMAX. Interpretation commit `5538146` remains locked at
7,060 direct 0.5-degree angular failures plus 2,360 cell-edge points coincident
with the outer boundary, zero strict-interior failures, 9,156 infeasible points
inside the residual fallback, and 1,554 BOTH points reproducing prior feasible
production RAY points.

Independent policy conclusion:

`SAFE_BOX_EXTRACTION_STRICTLY_AFTER_FINAL_REPAIRED_COUPLED_DOE_FREEZE`

Future paper metrics should include repair area loss and hosting-capacity loss.
Neither is computed here.
"""
    report_path = OUTDIR / "report.md"
    write_text(report_path, report)
    outputs.append(report_path)

    manifest_entries = []
    for path in sorted(outputs, key=lambda p: p.name):
        data = path.read_bytes()
        manifest_entries.append({"path": path.name, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()})
    manifest_path = OUTDIR / "manifest.json"
    write_text(manifest_path, json.dumps({
        "schema_version": 1,
        "artifact": "DSO_VPP_INTEGRATED_REPAIRABILITY_INTERPOLATION_AUDIT",
        "source_commit": SOURCE_COMMIT,
        "files": manifest_entries,
    }, indent=2, sort_keys=True) + "\n")

    print(f"checks: {len(checks)}")
    print(f"blockers: {len(blocker_checks)}")
    print(f"internal failures: {len(failed_checks)}")
    print(f"edges: {len(edge_rows)}")
    print(f"outer/angular-hit/BOTH: {len(vertex_coord)}/{len(angular_hit_vertices)}/{len(both_points)}")
    print(f"sufficient interpolation fits: {len(sufficient_fits)}")
    print(f"manifest payloads: {len(manifest_entries)}")
    return 1 if failed_checks else 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--verify-index", action="store_true")
    args = parser.parse_args()
    sys.exit(verify_index() if args.verify_index else main())
