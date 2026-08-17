from __future__ import annotations

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

SOURCE_COMMIT = "4612cac821f63c9bdcc838f4cc097387dfd617ad"
COORD_TOL_KW = 1e-8

OUTDIR = Path(
    "results/dso_vpp_ac_map_pilot/"
    "doe_ac_interior_validation_interpretation_audit"
)

PATHS = {
    "points":
        "results/dso_vpp_ac_map_pilot/doe_ac_interior_validation/"
        "validation_point_results.csv",
    "provenance":
        "results/dso_vpp_ac_map_pilot/"
        "doe_ac_interior_validation_preregistration/"
        "validation_point_provenance.csv",
    "edges":
        "results/dso_vpp_ac_map_pilot/"
        "doe_ac_interior_validation_preregistration/"
        "validation_polygon_edges.csv",
    "attempts":
        "results/dso_vpp_ac_map_pilot/production_probe/"
        "evaluation_attempts.csv",
    "boundary_endpoints":
        "results/dso_vpp_ac_map_pilot/production_probe/"
        "boundary_endpoints.csv",
    "guards":
        "results/dso_vpp_ac_map_pilot/production_probe/"
        "unresolved_guard_cases.csv",
    "fallback_summary":
        "results/dso_vpp_ac_map_pilot/doe_ac_interior_validation/"
        "validation_fallback_membership_summary.csv",
    "guard_summary":
        "results/dso_vpp_ac_map_pilot/doe_ac_interior_validation/"
        "validation_guard_summary.csv",
}

def git(*args: str) -> bytes:
    return subprocess.check_output(["git", *args])

def git_text(path: str) -> str:
    return git("show", f"{SOURCE_COMMIT}:{path}").decode("utf-8-sig")

def read_csv_git(path: str):
    return list(csv.DictReader(io.StringIO(git_text(path))))

def fail(msg: str):
    raise AssertionError(msg)

def require(cond: bool, msg: str):
    if not cond:
        fail(msg)

def f(row, key):
    return float(row[key])

def b(row, key):
    return row[key].lower() == "true"

def q(values, p):
    xs = sorted(values)
    if not xs:
        return math.nan
    n = len(xs)
    x = (n - 1) * p
    lo = math.floor(x)
    hi = math.ceil(x)
    if lo == hi:
        return xs[lo]
    return xs[lo] * (hi - x) + xs[hi] * (x - lo)

# Confirm source commit exists and is an ancestor of current HEAD.
subprocess.check_call(
    ["git", "merge-base", "--is-ancestor", SOURCE_COMMIT, "HEAD"]
)

tree_paths = git(
    "ls-tree", "-r", "--name-only", SOURCE_COMMIT
).decode().splitlines()

def unique_suffix(suffix: str) -> str:
    hits = [p for p in tree_paths if p.endswith(suffix)]
    require(len(hits) == 1, f"{suffix}: expected one path, got {hits}")
    return hits[0]

pocket_facets_path = unique_suffix("/pocket_exact_facets.csv")
hulled_geometry_path = unique_suffix(
    "/doe_vmax_pocket_hulling_audit/hulled_pocket_geometry.csv"
)

points = read_csv_git(PATHS["points"])
prov = read_csv_git(PATHS["provenance"])
edges = read_csv_git(PATHS["edges"])
attempts = read_csv_git(PATHS["attempts"])
boundary_endpoints = read_csv_git(PATHS["boundary_endpoints"])
guards = read_csv_git(PATHS["guards"])
fallback_summary = read_csv_git(PATHS["fallback_summary"])
guard_summary = read_csv_git(PATHS["guard_summary"])
pocket_facets = read_csv_git(pocket_facets_path)
hulled_geometry = read_csv_git(hulled_geometry_path)

require(len(points) == 65494, f"point count {len(points)} != 65494")

checks = []

def check(name, cond, detail):
    checks.append({
        "check": name,
        "status": "PASS" if cond else "FAIL",
        "detail": str(detail),
    })
    if not cond:
        fail(f"{name}: {detail}")

# ------------------------------------------------------------------
# A. Reconstruct fallback membership directly from halfspaces
# ------------------------------------------------------------------

def parse_halfspaces(s):
    if not s:
        return []
    out = []
    for item in s.split(";"):
        a, bb, rhs = item.split("|")
        out.append((float(a), float(bb), float(rhs)))
    return out

pockets = {}

for r in pocket_facets:
    cls = r["boundary_run_classification"]
    if not cls.startswith("VMAX"):
        continue
    key = (r["timestamp"], r["component_id"])
    pockets.setdefault(key, []).append((
        float(r["normal_p13"]),
        float(r["normal_p30"]),
        float(r["rhs_kw"]),
    ))

for r in hulled_geometry:
    key = (r["timestamp"], r["component_id"])
    pockets[key] = parse_halfspaces(
        r["hulled_halfspaces_normal_p13_normal_p30_rhs_kw"]
    )

pockets_by_ts = defaultdict(list)
for (ts, component_id), halfspaces in pockets.items():
    pockets_by_ts[ts].append((component_id, halfspaces))

def recompute_fallback(row):
    ts = row["timestamp"]
    p13 = f(row, "p13_abs_kw")
    p30 = f(row, "p30_abs_kw")
    require(ts in pockets_by_ts, f"missing fallback pockets for {ts}")
    for _, hs in pockets_by_ts[ts]:
        residuals = [a*p13 + bb*p30 - rhs for a, bb, rhs in hs]
        if all(v < -COORD_TOL_KW for v in residuals):
            return False
    return True

fallback_mismatch = 0
for r in points:
    if recompute_fallback(r) != b(r, "inside_pocket_fallback"):
        fallback_mismatch += 1

inside_fb = [r for r in points if b(r, "inside_pocket_fallback")]
outside_fb = [r for r in points if not b(r, "inside_pocket_fallback")]

inside_fb_inf = [
    r for r in inside_fb if r["final_feasibility"] == "INFEASIBLE"
]
outside_fb_inf = [
    r for r in outside_fb if r["final_feasibility"] == "INFEASIBLE"
]

check("A01_FALLBACK_RECONSTRUCTION_MATCH",
      fallback_mismatch == 0,
      f"mismatches={fallback_mismatch}")

check("A02_FALLBACK_INSIDE_COUNT",
      len(inside_fb) == 64923,
      len(inside_fb))

check("A03_FALLBACK_INSIDE_INFEASIBLE",
      len(inside_fb_inf) == 9156,
      len(inside_fb_inf))

check("A04_FALLBACK_OUTSIDE_COUNT",
      len(outside_fb) == 571,
      len(outside_fb))

check("A05_FALLBACK_OUTSIDE_INFEASIBLE",
      len(outside_fb_inf) == 264,
      len(outside_fb_inf))

# ------------------------------------------------------------------
# B. BOTH provenance and prior production reproduction
# ------------------------------------------------------------------

both = [r for r in points if r["source_category"] == "BOTH"]

check("B01_BOTH_COUNT", len(both) == 1554, len(both))
check("B02_BOTH_ALL_CELL_VERTEX",
      all(r["geometric_provenance_category"] == "CELL_VERTEX"
          for r in both),
      "all CELL_VERTEX")
check("B03_BOTH_ALL_ON_BOUNDARY",
      all(b(r, "on_main_angular_polygon_boundary") for r in both),
      "all on boundary")
check("B04_BOTH_ALL_VALIDATION_FEASIBLE",
      all(r["final_status"] == "CONVERGED_FEASIBLE" for r in both),
      "all CONVERGED_FEASIBLE")
check("B05_BOTH_ALL_PRIOR_DUPLICATES",
      all(b(r, "duplicates_previously_ac_evaluated_committed_point")
          for r in both),
      "1554/1554 true")

# Raw provenance membership accounting.
prov_by_id = defaultdict(list)
for r in prov:
    prov_by_id[r["validation_point_id"]].append(r)

raw_membership_counts = Counter()
angular_memberships = 0
cell_memberships = 0

for r in both:
    items = prov_by_id[r["validation_point_id"]]
    raw_membership_counts[len(items)] += 1
    angular_memberships += sum(
        x["source_kind"] == "ANGULAR_BOUNDARY" for x in items
    )
    cell_memberships += sum(
        x["source_kind"] == "CELL_BARYCENTRIC" for x in items
    )

check("B06_BOTH_RAW_MEMBERSHIP_3",
      raw_membership_counts[3] == 866,
      raw_membership_counts[3])
check("B07_BOTH_RAW_MEMBERSHIP_5",
      raw_membership_counts[5] == 688,
      raw_membership_counts[5])
check("B08_BOTH_ANGULAR_MEMBERSHIPS",
      angular_memberships == 1554,
      angular_memberships)
check("B09_BOTH_CELL_MEMBERSHIPS",
      cell_memberships == 4484,
      cell_memberships)

attempts_by_ts = defaultdict(list)
for r in attempts:
    attempts_by_ts[r["timestamp"]].append(r)

prior_phase = Counter()
prior_kind = Counter()
prior_init = Counter()
prior_attempt_index = Counter()
prior_matches_total = 0
prior_bad_status = 0
prior_match_multiplicity = Counter()

for r in both:
    ts = r["timestamp"]
    p13 = f(r, "p13_abs_kw")
    p30 = f(r, "p30_abs_kw")

    matches = []
    for a in attempts_by_ts[ts]:
        if (abs(float(a["p13_abs_kw"]) - p13) <= COORD_TOL_KW and
            abs(float(a["p30_abs_kw"]) - p30) <= COORD_TOL_KW):
            matches.append(a)

    prior_match_multiplicity[len(matches)] += 1
    prior_matches_total += len(matches)

    if len(matches) != 1:
        continue

    a = matches[0]
    prior_phase[a["phase"]] += 1
    prior_kind[a["search_kind"]] += 1
    prior_init[a["initialization"]] += 1
    prior_attempt_index[a["attempt_index"]] += 1
    if a["solver_status"] != "CONVERGED_FEASIBLE":
        prior_bad_status += 1

check("B10_BOTH_EXACTLY_ONE_PRIOR_MATCH",
      prior_match_multiplicity[1] == 1554,
      dict(prior_match_multiplicity))

check("B11_PRIOR_MATCHES_ALL_RAY",
      prior_kind == Counter({"RAY": 1554}),
      dict(prior_kind))

check("B12_PRIOR_MATCHES_ALL_FLAT_START",
      prior_init == Counter({"FLAT_START": 1554}),
      dict(prior_init))

check("B13_PRIOR_MATCHES_ALL_ATTEMPT_1",
      prior_attempt_index == Counter({"1": 1554}),
      dict(prior_attempt_index))

check("B14_PRIOR_MATCHES_ALL_FEASIBLE",
      prior_bad_status == 0,
      f"bad_status={prior_bad_status}")

check("B15_PRIOR_PHASE_SPLIT",
      prior_phase["bisection"] == 1552 and
      prior_phase["coarse_sweep"] == 2,
      dict(prior_phase))

# ------------------------------------------------------------------
# C. Failure localization to outer polygon boundary
# ------------------------------------------------------------------

failures = [
    r for r in points if r["final_status"] == "CONVERGED_INFEASIBLE"
]

cell_edge_failures = [
    r for r in failures
    if r["geometric_provenance_category"] == "CELL_EDGE"
]

strict_interior_failures = [
    r for r in failures
    if r["geometric_provenance_category"] == "STRICT_CELL_INTERIOR"
]

distances = [
    float(r["distance_to_angular_polygon_boundary_kw"])
    for r in cell_edge_failures
]

check("C01_TOTAL_FAILURES", len(failures) == 9420, len(failures))
check("C02_CELL_EDGE_FAILURES",
      len(cell_edge_failures) == 2360,
      len(cell_edge_failures))
check("C03_STRICT_INTERIOR_FAILURES_ZERO",
      len(strict_interior_failures) == 0,
      len(strict_interior_failures))
check("C04_CELL_EDGE_FAILURES_ALL_CELL_MESH",
      all(r["source_category"] == "CELL_MESH"
          for r in cell_edge_failures),
      "all CELL_MESH")
check("C05_CELL_EDGE_FAILURES_ALL_ON_BOUNDARY",
      all(b(r, "on_main_angular_polygon_boundary")
          for r in cell_edge_failures),
      "all true")
check("C06_CELL_EDGE_DISTANCE_WITHIN_TOLERANCE",
      max(distances) < COORD_TOL_KW,
      f"max={max(distances):.15g}")

all_failure_boundary = [
    r for r in failures if b(r, "on_main_angular_polygon_boundary")
]

check("C07_ALL_FAILURES_ON_OUTER_BOUNDARY",
      len(all_failure_boundary) == 9420,
      len(all_failure_boundary))

failure_sources = Counter(r["source_category"] for r in failures)

check("C08_FAILURE_SOURCE_SPLIT",
      failure_sources == Counter({
          "BOUNDARY_INTER_RAY": 7060,
          "CELL_MESH": 2360,
      }),
      dict(failure_sources))

# ------------------------------------------------------------------
# D. Guard provenance and boundary-only violation magnitude
# ------------------------------------------------------------------

edge_relation = Counter(r["guard_relation"] for r in edges)

check("D01_CROSSING_EDGE_COUNT",
      edge_relation["CROSSES_GUARD_LIMITED_RAY"] == 64,
      edge_relation["CROSSES_GUARD_LIMITED_RAY"])
check("D02_ADJACENT_EDGE_COUNT",
      edge_relation["ADJACENT_TO_GUARD_LIMITED_EDGE"] == 128,
      edge_relation["ADJACENT_TO_GUARD_LIMITED_EDGE"])
check("D03_TOUCHING_EDGE_COUNT_ZERO",
      edge_relation["TOUCHES_GUARD_LIMITED_RAY"] == 0,
      edge_relation["TOUCHES_GUARD_LIMITED_RAY"])

crossing_edges = [
    r for r in edges
    if r["guard_relation"] == "CROSSES_GUARD_LIMITED_RAY"
]
adjacent_edges = [
    r for r in edges
    if r["guard_relation"] == "ADJACENT_TO_GUARD_LIMITED_EDGE"
]

check("D04_CROSSING_ALL_CLASS_TRANSITION",
      all(r["boundary_class"] == "CLASS_TRANSITION"
          for r in crossing_edges),
      "all CLASS_TRANSITION")

adjacent_class_counts = Counter(
    r["boundary_class"] for r in adjacent_edges
)

check("D05_ADJACENT_CLASS_SPLIT",
      adjacent_class_counts == Counter({
          "VMAX13": 32,
          "VMAX30": 32,
          "VMIN18": 32,
          "VMIN33": 32,
      }),
      dict(adjacent_class_counts))

# Verify guard-related polygon endpoints are real SAFE official RAY endpoints.
safe_endpoints_by_ts = defaultdict(list)
for r in boundary_endpoints:
    if (r["endpoint_side"] == "SAFE" and
        r["official_boundary"].lower() == "true"):
        safe_endpoints_by_ts[r["timestamp"]].append(r)

guard_endpoint_match_failures = 0
guard_endpoint_nonray = 0

for e in crossing_edges + adjacent_edges:
    for suffix in ("a", "b"):
        p13 = float(e[f"endpoint_{suffix}_p13_abs_kw"])
        p30 = float(e[f"endpoint_{suffix}_p30_abs_kw"])
        matches = [
            r for r in safe_endpoints_by_ts[e["timestamp"]]
            if abs(float(r["p13_abs_kw"]) - p13) <= COORD_TOL_KW
            and abs(float(r["p30_abs_kw"]) - p30) <= COORD_TOL_KW
        ]
        if not matches:
            guard_endpoint_match_failures += 1
        elif not any(r["search_kind"] == "RAY" for r in matches):
            guard_endpoint_nonray += 1

check("D06_GUARD_ENDPOINTS_MATCH_SAFE_OFFICIAL",
      guard_endpoint_match_failures == 0,
      guard_endpoint_match_failures)
check("D07_GUARD_ENDPOINTS_ARE_RAY",
      guard_endpoint_nonray == 0,
      guard_endpoint_nonray)

# Guard case count itself.
check("D08_GUARD_CASE_COUNT", len(guards) == 73, len(guards))

# Guard summary is defined over all points carrying angular-boundary
# provenance, including deduplicated BOTH points.  The BOTH points are
# all validation-feasible, so failure counts remain identical to the
# direct BOUNDARY_INTER_RAY failure counts, but point-count denominators
# must include them.
angular_boundary_points = [
    r for r in points if b(r, "has_angular_boundary_provenance")
]

crossing_points = [
    r for r in angular_boundary_points
    if r["guard_relation"] == "CROSSES_GUARD_LIMITED_RAY"
]
adjacent_points = [
    r for r in angular_boundary_points
    if r["guard_relation"] == "ADJACENT_TO_GUARD_LIMITED_EDGE"
]
nonguard_points = [
    r for r in angular_boundary_points if r["guard_relation"] == "NONE"
]

crossing_fail = [
    r for r in crossing_points
    if r["final_status"] == "CONVERGED_INFEASIBLE"
]
adjacent_fail = [
    r for r in adjacent_points
    if r["final_status"] == "CONVERGED_INFEASIBLE"
]
nonguard_fail = [
    r for r in nonguard_points
    if r["final_status"] == "CONVERGED_INFEASIBLE"
]

check("D09_CROSSING_POINTS_ALL_FEASIBLE",
      len(crossing_points) == 1371 and len(crossing_fail) == 0,
      f"points={len(crossing_points)}, failures={len(crossing_fail)}")

check("D10_ADJACENT_FAILURE_COUNT",
      len(adjacent_fail) == 576,
      len(adjacent_fail))

check("D11_NONGUARD_FAILURE_COUNT",
      len(nonguard_fail) == 6484,
      len(nonguard_fail))

adj_fail_class = Counter(r["boundary_class"] for r in adjacent_fail)
check("D12_ADJACENT_FAILURE_CLASS_SPLIT",
      adj_fail_class == Counter({"VMAX13": 288, "VMAX30": 288}),
      dict(adj_fail_class))

def mags(rows):
    return [
        float(r["voltage_violation_magnitude_pu"])
        for r in rows
    ]

adj_m = mags(adjacent_fail)
non_m = mags(nonguard_fail)

adj_median = statistics.median(adj_m)
adj_max = max(adj_m)
non_median = statistics.median(non_m)
non_max = max(non_m)

def close(a, bb, tol=5e-15):
    return abs(a - bb) <= tol

check("D13_ADJACENT_MEDIAN",
      close(adj_median, 4.61135857205e-05),
      f"{adj_median:.15g}")
check("D14_ADJACENT_MAX",
      close(adj_max, 1.42248109239e-04),
      f"{adj_max:.15g}")
check("D15_NONGUARD_MEDIAN",
      close(non_median, 5.08027073676e-06),
      f"{non_median:.15g}")
check("D16_NONGUARD_MAX",
      close(non_max, 4.33223324872e-05),
      f"{non_max:.15g}")

# ------------------------------------------------------------------
# Output
# ------------------------------------------------------------------

summary = {
    "schema_version": 1,
    "artifact": "DSO_VPP_AC_INTERIOR_VALIDATION_INTERPRETATION_AUDIT",
    "source_validation_commit": SOURCE_COMMIT,
    "coordinate_tolerance_kw": COORD_TOL_KW,
    "A_fallback": {
        "semantic":
            "inside main validation domain and not in strict interior "
            "of any convex-hulled VMAX pocket",
        "inside_count": len(inside_fb),
        "inside_feasible": sum(
            r["final_status"] == "CONVERGED_FEASIBLE" for r in inside_fb
        ),
        "inside_infeasible": len(inside_fb_inf),
        "outside_count": len(outside_fb),
        "outside_infeasible": len(outside_fb_inf),
        "classification":
            "POCKET_FALLBACK_FALSIFIED_BY_AC_COUNTEREXAMPLES",
    },
    "B_both": {
        "count": len(both),
        "all_cell_vertex": True,
        "all_outer_boundary": True,
        "all_validation_feasible": True,
        "all_prior_committed_duplicate": True,
        "prior_unique_matches": prior_match_multiplicity[1],
        "prior_search_kind": dict(prior_kind),
        "prior_phase": dict(prior_phase),
        "classification":
            "PRODUCTION_BOUNDARY_POINT_REPRODUCTION_1554_OF_1554_FEASIBLE",
    },
    "C_failure_localization": {
        "total_counterexamples": len(failures),
        "boundary_inter_ray_counterexamples":
            failure_sources["BOUNDARY_INTER_RAY"],
        "cell_edge_counterexamples": len(cell_edge_failures),
        "strict_cell_interior_counterexamples":
            len(strict_interior_failures),
        "cell_edge_distance_kw": {
            "min": min(distances),
            "q1": q(distances, 0.25),
            "median": statistics.median(distances),
            "q3": q(distances, 0.75),
            "max": max(distances),
            "mean": statistics.mean(distances),
        },
        "all_counterexamples_on_outer_polygon_boundary_within_tolerance":
            True,
        "wording_caveat":
            "7060 are direct 0.5-degree angular samples; 2360 are "
            "cell-mesh edge points geometrically coincident with the "
            "outer polygon boundary.",
    },
    "D_guard": {
        "edge_relation_counts": dict(edge_relation),
        "crossing_edges": len(crossing_edges),
        "adjacent_edges": len(adjacent_edges),
        "crossing_boundary_points": len(crossing_points),
        "crossing_failures": len(crossing_fail),
        "adjacent_failures": len(adjacent_fail),
        "nonguard_failures": len(nonguard_fail),
        "adjacent_failure_class_counts": dict(adj_fail_class),
        "boundary_only_violation_pu": {
            "guard_adjacent_median": adj_median,
            "guard_adjacent_max": adj_max,
            "nonguard_median": non_median,
            "nonguard_max": non_max,
        },
        "causal_interpretation":
            "ASSOCIATION_OBSERVED_CAUSAL_MECHANISM_NOT_ESTABLISHED",
    },
    "caveats": [
        "Finite-mesh validation is not a continuous AC-safety proof.",
        "The pocket fallback is not AC-safe or AC-certified.",
        "VMAX concentration does not establish a physical loss/voltage mechanism.",
        "Boundary coincidence is established only at the locked numerical tolerance.",
        "Guard adjacency association does not establish guard causality.",
        "Raw-byte checkpoint compatibility across LF/CRLF working trees is not claimed.",
    ],
}

OUTDIR.mkdir(parents=True, exist_ok=True)

def write_text(path: Path, text: str):
    path.write_text(text, encoding="utf-8", newline="\n")

summary_path = OUTDIR / "interpretation_audit_summary.json"
write_text(
    summary_path,
    json.dumps(summary, indent=2, sort_keys=True) + "\n"
)

checks_path = OUTDIR / "interpretation_audit_checks.csv"
with checks_path.open("w", encoding="utf-8", newline="") as fh:
    w = csv.DictWriter(
        fh, fieldnames=["check", "status", "detail"],
        lineterminator="\n"
    )
    w.writeheader()
    w.writerows(checks)

source_paths = list(PATHS.values()) + [
    pocket_facets_path,
    hulled_geometry_path,
]

source_records = []
for path in sorted(set(source_paths)):
    data = git("show", f"{SOURCE_COMMIT}:{path}")
    source_records.append({
        "path": path,
        "bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
    })

source_path = OUTDIR / "source_files.json"
write_text(
    source_path,
    json.dumps({
        "source_commit": SOURCE_COMMIT,
        "files": source_records,
    }, indent=2, sort_keys=True) + "\n"
)

report = f"""# AC Interior Validation Interpretation Audit

Source validation commit: `{SOURCE_COMMIT}`

This audit is deterministic and artifact-only. It performs no AC solve,
replay, probing, or repair.

## A. Pocket fallback semantic closure

`inside_pocket_fallback=true` denotes the residual region obtained by
excluding the strict interiors of the convex-hulled VMAX pockets from the
already-admissible Main validation domain, using the locked coordinate
tolerance of `{COORD_TOL_KW:g} kW`.

The stored membership was independently reconstructed from pocket halfspaces
with zero mismatches.

- inside residual fallback: {len(inside_fb)}
- AC-feasible inside: {len(inside_fb)-len(inside_fb_inf)}
- AC-infeasible inside: {len(inside_fb_inf)}
- strict pocket-interior / outside fallback: {len(outside_fb)}
- AC-infeasible outside: {len(outside_fb_inf)}

Therefore the compact pocket fallback is itself falsified by observed AC
counterexamples and must not be described as AC-safe or AC-certified.

## B. BOTH provenance closure

All {len(both)} `BOTH` points are deduplicated overlaps between angular-boundary
and cell-barycentric provenance. All are `CELL_VERTEX`, all lie on the outer
polygon boundary, and all reconverged feasible in the validation campaign.

Every one of the {len(both)} points has exactly one coordinate-matched committed
production `RAY` evaluation within `{COORD_TOL_KW:g} kW`; all were
`CONVERGED_FEASIBLE`. Phase split:

- bisection: {prior_phase["bisection"]}
- coarse sweep: {prior_phase["coarse_sweep"]}

Locked interpretation:

`PRODUCTION_BOUNDARY_POINT_REPRODUCTION_1554_OF_1554_FEASIBLE`

## C. Failure localization

All {len(failures)} converged AC counterexamples lie on the outer polygon
boundary within the locked numerical tolerance.

- direct angular-boundary failures: {failure_sources["BOUNDARY_INTER_RAY"]}
- cell-mesh edge failures: {len(cell_edge_failures)}
- strict cell-interior failures: {len(strict_interior_failures)}
- maximum cell-edge failure distance to outer boundary:
  {max(distances):.15g} kW

The wording must remain precise: the first 7,060 are direct 0.5-degree angular
samples; the other 2,360 are cell-mesh edge points geometrically coincident
with the same outer polygon boundary.

This is numerical/tolerance-level boundary coincidence, not an analytic
continuous proof.

## D. Guard provenance closure

Polygon edge relations:

- crossing edges: {len(crossing_edges)}
- adjacent edges: {len(adjacent_edges)}
- touching edges: {edge_relation["TOUCHES_GUARD_LIMITED_RAY"]}

All crossing edges are class transitions. The adjacent-edge class split is
32 each for VMAX13, VMAX30, VMIN18, and VMIN33.

For boundary-only validation points:

- crossing-labelled points: {len(crossing_points)}
- crossing failures: {len(crossing_fail)}
- adjacent failures: {len(adjacent_fail)}
- non-guard failures: {len(nonguard_fail)}

Adjacent failures are 288 VMAX13 and 288 VMAX30.

Violation magnitude among angular-boundary-provenance failures:

- guard-adjacent median: {adj_median:.15g} p.u.
- guard-adjacent maximum: {adj_max:.15g} p.u.
- non-guard median: {non_median:.15g} p.u.
- non-guard maximum: {non_max:.15g} p.u.

This establishes a guard-adjacent VMAX association only. It does not establish
a causal guard mechanism.

## Scientific caveats

- The finite mesh is not a proof of continuous AC safety.
- The pocket fallback is falsified and is not AC-certified.
- VMAX concentration does not establish a physical loss-induced mechanism.
- Boundary coincidence is asserted only at the locked numerical tolerance.
- Guard adjacency is an observed association, not a causal explanation.
- Raw-byte checkpoint compatibility across LF/CRLF working trees is not claimed.
"""

report_path = OUTDIR / "interpretation_audit_report.md"
write_text(report_path, report)

payloads = [
    checks_path,
    report_path,
    source_path,
    summary_path,
]

manifest_entries = []
for path in sorted(payloads):
    data = path.read_bytes()
    manifest_entries.append({
        "path": path.name,
        "bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
    })

manifest = {
    "schema_version": 1,
    "artifact": "DSO_VPP_AC_INTERIOR_VALIDATION_INTERPRETATION_AUDIT",
    "source_validation_commit": SOURCE_COMMIT,
    "files": manifest_entries,
}

manifest_path = OUTDIR / "manifest.json"
write_text(
    manifest_path,
    json.dumps(manifest, indent=2, sort_keys=True) + "\n"
)

failed = [x for x in checks if x["status"] != "PASS"]

print(f"checks: {len(checks)}")
print(f"failed: {len(failed)}")
print(f"fallback infeasible inside: {len(inside_fb_inf)}")
print(f"BOTH prior reproduced: {prior_match_multiplicity[1]}")
print(f"total boundary-localized failures: {len(all_failure_boundary)}")
print(f"crossing failures: {len(crossing_fail)}")
print(f"adjacent failures: {len(adjacent_fail)}")
print(f"manifest payloads: {len(manifest_entries)}")

sys.exit(1 if failed else 0)
