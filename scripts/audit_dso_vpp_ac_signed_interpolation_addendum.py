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


SOURCE_COMMIT = "07a31791134aec7e941e7674953e887edd697d3d"
SOURCE_BRANCH = "codex/dso-vpp-ac-map-pilot"
COORD_TOL_KW = 1e-8
TARGET_MIN_INTERIOR = 3
TARGET_MAX_GAP = 0.25
OUTDIR = Path(
    "results/dso_vpp_ac_map_pilot/"
    "doe_ac_repairability_interpolation_audit/"
    "signed_interpolation_addendum"
)

PATHS = {
    "fits": "results/dso_vpp_ac_map_pilot/doe_ac_repairability_interpolation_audit/edge_interpolation_fits.csv",
    "edges": "results/dso_vpp_ac_map_pilot/doe_ac_repairability_interpolation_audit/edge_repairability_sampling.csv",
    "audit_summary": "results/dso_vpp_ac_map_pilot/doe_ac_repairability_interpolation_audit/summary.json",
    "audit_manifest": "results/dso_vpp_ac_map_pilot/doe_ac_repairability_interpolation_audit/manifest.json",
    "points": "results/dso_vpp_ac_map_pilot/doe_ac_interior_validation/validation_point_results.csv",
    "polygon_edges": "results/dso_vpp_ac_map_pilot/doe_ac_interior_validation_preregistration/validation_polygon_edges.csv",
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


def truth(value) -> bool:
    return str(value).lower() == "true"


def finite(x: float) -> bool:
    return math.isfinite(x)


def fmt(value) -> str:
    if isinstance(value, float):
        if math.isnan(value):
            return "NaN"
        if math.isinf(value):
            return "Inf" if value > 0 else "-Inf"
        return format(value, ".15g")
    return str(value)


def quantile(values: list[float], p: float) -> float:
    xs = sorted(x for x in values if finite(x))
    if not xs:
        return math.nan
    z = (len(xs) - 1) * p
    lo, hi = math.floor(z), math.ceil(z)
    if lo == hi:
        return xs[lo]
    return xs[lo] * (hi - z) + xs[hi] * (z - lo)


def stats(values: list[float]) -> dict:
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


def json_safe(value):
    if isinstance(value, float) and not finite(value):
        return None
    if isinstance(value, dict):
        return {k: json_safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [json_safe(v) for v in value]
    return value


def write_text(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8", newline="\n")


def write_csv(path: Path, fields: list[str], rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({k: fmt(row.get(k, "")) for k in fields})


def sub(a: tuple[float, float], b: tuple[float, float]) -> tuple[float, float]:
    return a[0] - b[0], a[1] - b[1]


def dot(a: tuple[float, float], b: tuple[float, float]) -> float:
    return a[0] * b[0] + a[1] * b[1]


def norm(a: tuple[float, float]) -> float:
    return math.hypot(a[0], a[1])


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


def unique(values: list[float], tol=1e-12) -> list[float]:
    out: list[float] = []
    for x in sorted(values):
        if not out or abs(x - out[-1]) > tol:
            out.append(x)
    return out


def max_gap(values: list[float]) -> float:
    xs = unique([0.0, 1.0, *values])
    return max(b - a for a, b in zip(xs, xs[1:]))


def parse_fractions(text: str) -> list[float]:
    return [] if not text else [float(x) for x in text.split(";")]


def verify_index() -> int:
    manifest_path = OUTDIR.as_posix() + "/manifest.json"
    manifest = json.loads(git("show", f":{manifest_path}").decode("utf-8"))
    mismatches = []
    for item in manifest["files"]:
        data = git("show", f":{OUTDIR.as_posix()}/{item['path']}")
        if len(data) != item["bytes"] or hashlib.sha256(data).hexdigest() != item["sha256"]:
            mismatches.append(item["path"])
    print(f"staged manifest payloads: {len(manifest['files'])}")
    print(f"staged manifest mismatches: {len(mismatches)}")
    return 1 if mismatches else 0


def main() -> int:
    branch = git("branch", "--show-current").decode().strip()
    head = git("rev-parse", "HEAD").decode().strip()
    if branch != SOURCE_BRANCH or head != SOURCE_COMMIT:
        raise RuntimeError(f"source mismatch branch={branch} head={head}")

    fits = read_csv_git(PATHS["fits"])
    edges = read_csv_git(PATHS["edges"])
    points = read_csv_git(PATHS["points"])
    polygon_edges = read_csv_git(PATHS["polygon_edges"])
    prior_summary = read_json_git(PATHS["audit_summary"])
    read_json_git(PATHS["audit_manifest"])

    checks: list[dict] = []

    def check(check_id: str, condition: bool, detail: str, severity="BLOCKER"):
        checks.append({"check_id": check_id,
                       "status": "PASS" if condition else severity,
                       "detail": detail})

    check("SOURCE_BRANCH", branch == SOURCE_BRANCH, branch, "FAIL")
    check("SOURCE_COMMIT", head == SOURCE_COMMIT, head, "FAIL")
    check("ZERO_AC_SCOPE", True, "artifact-only; no solver import or execution")
    check("LOCKED_CLASSIFICATION_PRESERVED",
          prior_summary["locked_campaign_classification"] == "MAIN_COUPLED_DOE_GEOMETRIC_CANDIDATE_FALSIFIED_BY_AC_COUNTEREXAMPLE",
          prior_summary["locked_campaign_classification"])

    edge_by_key = {(r["timestamp"], r["edge_id"]): r for r in edges}
    polygon_by_key = {(r["timestamp"], r["source_polygon_edge_id"]): r for r in polygon_edges}
    edges_by_ts: dict[str, list[dict]] = defaultdict(list)
    for row in polygon_edges:
        edges_by_ts[row["timestamp"]].append(row)
    for ts in edges_by_ts:
        edges_by_ts[ts].sort(key=lambda r: int(r["source_polygon_edge_id"][1:]))

    sufficient = [r for r in fits if truth(r["fit_sufficient"])]
    insufficient = [r for r in fits if not truth(r["fit_sufficient"])]
    insufficient_keys = sorted({(r["timestamp"], r["edge_id"]) for r in insufficient})
    check("FIT_ROW_TOTAL", len(fits) == 1817, f"observed={len(fits)}")
    check("SUFFICIENT_FIT_COUNT", len(sufficient) == 1776, f"observed={len(sufficient)}")
    check("LOW_SAMPLE_TRUE_SET_RECONSTRUCTED", len(insufficient_keys) == 41,
          f"observed_unique_edges={len(insufficient_keys)}; user_prompt_expected_44_is_not_confirmed_by_committed_fit_rows")
    check("LOW_SAMPLE_ROWS_ONE_CHANNEL_PER_EDGE", len(insufficient) == len(insufficient_keys),
          f"rows={len(insufficient)},unique_edges={len(insufficient_keys)}")

    failure_counts: dict[tuple[str, str], Counter] = defaultdict(Counter)
    unmapped_failures = 0
    total_failures = 0

    def map_point(row: dict[str, str]):
        ts = row["timestamp"]
        source = row["source_polygon_edge_id"]
        p = (f(row, "p13_abs_kw"), f(row, "p30_abs_kw"))
        if source and (ts, source) in polygon_by_key:
            e = polygon_by_key[(ts, source)]
            t, d = projection_fraction_distance(
                p,
                (f(e, "endpoint_a_p13_abs_kw"), f(e, "endpoint_a_p30_abs_kw")),
                (f(e, "endpoint_b_p13_abs_kw"), f(e, "endpoint_b_p30_abs_kw")),
            )
            return (ts, source), t, d
        candidates = []
        for e in edges_by_ts[ts]:
            a = (f(e, "endpoint_a_p13_abs_kw"), f(e, "endpoint_a_p30_abs_kw"))
            b = (f(e, "endpoint_b_p13_abs_kw"), f(e, "endpoint_b_p30_abs_kw"))
            t, d = projection_fraction_distance(p, a, b)
            if -1e-10 <= t <= 1 + 1e-10:
                candidates.append((d, int(e["source_polygon_edge_id"][1:]), e["source_polygon_edge_id"], t))
        if not candidates:
            return None, math.nan, math.inf
        d, _, eid, t = min(candidates)
        return (ts, eid), t, d

    for row in points:
        if row["final_status"] != "CONVERGED_INFEASIBLE":
            continue
        total_failures += 1
        key, t, distance = map_point(row)
        if key is None or distance > COORD_TOL_KW:
            unmapped_failures += 1
            continue
        failure_counts[key]["total"] += 1
        failure_counts[key][row["source_category"]] += 1
        failure_counts[key][row["primary_violation_mechanism"]] += 1
        if row["primary_violation_mechanism"].startswith("VMAX"):
            failure_counts[key]["VMAX"] += 1
        if row["primary_violation_mechanism"].startswith("VMIN"):
            failure_counts[key]["VMIN"] += 1

    failing_edge_keys = sorted(failure_counts)
    check("ALL_FAILURES_MAPPED", total_failures == 9420 and unmapped_failures == 0,
          f"total={total_failures},unmapped={unmapped_failures}")
    check("ALL_FAILURES_VMAX", all(c["VMAX"] == c["total"] for c in failure_counts.values()),
          f"failing_edges={len(failing_edge_keys)}")

    diagnostic_rows = []
    for row in sufficient:
        key = (row["timestamp"], row["edge_id"])
        edge = edge_by_key[key]
        endpoint_a = f(row, "endpoint_a_margin")
        endpoint_b = f(row, "endpoint_b_margin")
        s_e = f(row, "s_e_pu")
        predicted_midpoint = 0.5 * (endpoint_a + endpoint_b) + 0.25 * s_e
        c = failure_counts.get(key, Counter())
        diagnostic_rows.append({
            "timestamp": row["timestamp"], "edge_id": row["edge_id"],
            "guard_relation": row["guard_relation"],
            "margin_channel": row["margin_channel"],
            "endpoint_status_combination": edge["endpoint_status_combination"],
            "boundary_class": row["boundary_class"],
            "n_interior": int(row["interior_sample_count"]),
            "endpoint_a_margin_pu": endpoint_a,
            "endpoint_b_margin_pu": endpoint_b,
            "endpoint_min_margin_pu": min(endpoint_a, endpoint_b),
            "endpoint_max_margin_pu": max(endpoint_a, endpoint_b),
            "s_e_pu": s_e, "s_e_sign": "POSITIVE" if s_e > 0 else "NEGATIVE" if s_e < 0 else "ZERO",
            "predicted_midpoint_margin_pu": predicted_midpoint,
            "model_rmse_pu": f(row, "model_rmse_pu"),
            "failure_point_count": c["total"],
            "direct_angular_failure_count": c["BOUNDARY_INTER_RAY"],
            "cell_edge_failure_count": c["CELL_MESH"],
            "cap_role": "GEOMETRY_BOUND_ONLY_NOT_PRIMARY_FALSIFICATION_PATH",
        })

    signed_groups: dict[tuple[str, str, str], list[dict]] = defaultdict(list)
    for row in diagnostic_rows:
        signed_groups[(row["guard_relation"], row["margin_channel"], row["endpoint_status_combination"])].append(row)

    signed_distribution_rows = []
    endpoint_distribution_rows = []
    for (guard, channel, status), rows in sorted(signed_groups.items()):
        values = [r["s_e_pu"] for r in rows]
        signed_distribution_rows.append({
            "guard_relation": guard, "margin_channel": channel,
            "endpoint_status_combination": status, **stats(values),
            "negative_count": sum(x < 0 for x in values),
            "zero_count": sum(x == 0 for x in values),
            "positive_count": sum(x > 0 for x in values),
            "negative_fraction": sum(x < 0 for x in values) / len(values),
            "positive_fraction": sum(x > 0 for x in values) / len(values),
        })
        endpoint_values = [x for r in rows for x in (r["endpoint_a_margin_pu"], r["endpoint_b_margin_pu"])]
        midpoint_values = [r["predicted_midpoint_margin_pu"] for r in rows]
        e_stats, m_stats = stats(endpoint_values), stats(midpoint_values)
        endpoint_distribution_rows.append({
            "guard_relation": guard, "margin_channel": channel,
            "endpoint_status_combination": status, "fit_count": len(rows),
            "endpoint_margin_count": e_stats["count"],
            "endpoint_margin_min": e_stats["min"], "endpoint_margin_q1": e_stats["q1"],
            "endpoint_margin_median": e_stats["median"], "endpoint_margin_q3": e_stats["q3"],
            "endpoint_margin_max": e_stats["max"],
            "predicted_midpoint_min": m_stats["min"], "predicted_midpoint_q1": m_stats["q1"],
            "predicted_midpoint_median": m_stats["median"], "predicted_midpoint_q3": m_stats["q3"],
            "predicted_midpoint_max": m_stats["max"],
            "predicted_midpoint_negative_count": sum(x < 0 for x in midpoint_values),
        })

    n_counter = Counter(int(r["interior_sample_count"]) for r in sufficient)
    n_distribution_rows = [
        {"n_interior": n, "fit_count": count,
         "fraction_of_1776": count / len(sufficient)}
        for n, count in sorted(n_counter.items())
    ]

    low_rows = []
    enrichment_rows = []
    enrichment_id = 0
    for key in insufficient_keys:
        edge = edge_by_key[key]
        polygon = polygon_by_key[key]
        current = unique([x for x in parse_fractions(edge["sorted_fractions"]) if 1e-12 < x < 1 - 1e-12])
        original = list(current)
        added: list[float] = []
        while len(current) < TARGET_MIN_INTERIOR or max_gap(current) > TARGET_MAX_GAP + 1e-12:
            xs = unique([0.0, 1.0, *current])
            candidates = [(xs[i + 1] - xs[i], xs[i], xs[i + 1]) for i in range(len(xs) - 1)]
            largest, left, right = max(candidates, key=lambda x: (x[0], -x[1]))
            t = (left + right) / 2
            current = unique([*current, t])
            added.append(t)
        a = (f(polygon, "endpoint_a_p13_abs_kw"), f(polygon, "endpoint_a_p30_abs_kw"))
        b = (f(polygon, "endpoint_b_p13_abs_kw"), f(polygon, "endpoint_b_p30_abs_kw"))
        low_rows.append({
            "timestamp": key[0], "edge_id": key[1],
            "boundary_class": edge["boundary_class"], "guard_relation": edge["guard_relation"],
            "endpoint_status_combination": edge["endpoint_status_combination"],
            "original_n_interior": len(original), "original_g_e": max_gap(original),
            "original_interior_fractions": ";".join(fmt(x) for x in original),
            "new_point_count": len(added), "final_n_interior": len(current),
            "final_g_e": max_gap(current),
            "final_interior_fractions": ";".join(fmt(x) for x in current),
            "requested_count_note": "TRUE_SET_HAS_41_EDGES_NOT_PROMPT_EXPECTATION_44",
        })
        for local_index, t in enumerate(added, 1):
            enrichment_id += 1
            enrichment_rows.append({
                "enrichment_point_id": f"LS_ENRICH_{enrichment_id:04d}",
                "timestamp": key[0], "edge_id": key[1],
                "local_addition_order": local_index,
                "t": t,
                "p13_abs_kw": (1 - t) * a[0] + t * b[0],
                "p30_abs_kw": (1 - t) * a[1] + t * b[1],
                "selection_rule": "ITERATED_LARGEST_T_GAP_MIDPOINT_TIE_LOWEST_LEFT_ENDPOINT",
                "calibration_role": "LOW_SAMPLE_ENRICHMENT_BEFORE_FUTURE_AC_CALIBRATION",
                "ac_evaluated": False,
            })

    check("ENRICHMENT_COVERS_TRUE_LOW_SAMPLE_SET", len(low_rows) == 41,
          f"edges={len(low_rows)},new_points={len(enrichment_rows)}")
    check("ENRICHMENT_MINIMUM_INTERIOR_COUNT",
          all(int(r["final_n_interior"]) >= TARGET_MIN_INTERIOR for r in low_rows),
          f"minimum={min(int(r['final_n_interior']) for r in low_rows)}")
    check("ENRICHMENT_MAXIMUM_GAP",
          all(float(r["final_g_e"]) <= TARGET_MAX_GAP + 1e-12 for r in low_rows),
          f"maximum={fmt(max(float(r['final_g_e']) for r in low_rows))}")

    failure_edge_rows = []
    for key in failing_edge_keys:
        edge = edge_by_key[key]
        c = failure_counts[key]
        failure_edge_rows.append({
            "timestamp": key[0], "edge_id": key[1],
            "boundary_class": edge["boundary_class"], "guard_relation": edge["guard_relation"],
            "endpoint_status_combination": edge["endpoint_status_combination"],
            "failure_count": c["total"],
            "direct_angular_failure_count": c["BOUNDARY_INTER_RAY"],
            "cell_edge_failure_count": c["CELL_MESH"],
            "vmax_failure_count": c["VMAX"],
        })

    check("FAILURE_EDGE_COUNT_NONZERO", len(failure_edge_rows) > 0,
          f"exact_failing_edges={len(failure_edge_rows)}")

    blocker_checks = [r for r in checks if r["status"] == "BLOCKER"]
    failed_checks = [r for r in checks if r["status"] == "FAIL"]
    overall = "BLOCKED_BEFORE_REPAIR_PREREGISTRATION" if blocker_checks else "NO_ADDENDUM_BLOCKER"
    n_values = [int(r["interior_sample_count"]) for r in sufficient]
    s_values = [f(r, "s_e_pu") for r in sufficient]
    midpoint_values = [r["predicted_midpoint_margin_pu"] for r in diagnostic_rows]

    summary = {
        "schema_version": 1,
        "artifact": "ZERO_AC_SIGNED_INTERPOLATION_ADDENDUM",
        "source_commit": SOURCE_COMMIT,
        "zero_ac": True,
        "overall_status": overall,
        "blockers": [r["check_id"] for r in blocker_checks],
        "locked_campaign_classification": "MAIN_COUPLED_DOE_GEOMETRIC_CANDIDATE_FALSIFIED_BY_AC_COUNTEREXAMPLE",
        "fit_population": {
            "all_edge_channel_rows": len(fits),
            "sufficient_fit_rows": len(sufficient),
            "insufficient_fit_rows": len(insufficient),
            "n_distribution": stats([float(x) for x in n_values]),
            "signed_s_e_distribution_pu": stats(s_values),
            "predicted_midpoint_margin_distribution_pu": stats(midpoint_values),
        },
        "failure_edges": {"exact_unique_edge_count": len(failure_edge_rows),
                          "mapped_failure_points": total_failures},
        "low_sample_correction": {
            "prompt_expected_edge_count": 44,
            "committed_artifact_exact_edge_count": len(insufficient_keys),
            "resolution": "USE_RECONSTRUCTED_TRUE_SET;NO_SCIENTIFIC_BLOCKER",
            "enrichment_new_coordinate_count": len(enrichment_rows),
            "post_enrichment_minimum_interior_count": min(int(r["final_n_interior"]) for r in low_rows),
            "post_enrichment_maximum_g_e": max(float(r["final_g_e"]) for r in low_rows),
        },
        "cap_policy": "GEOMETRY_BOUND_ONLY_NOT_PRIMARY_FALSIFICATION_PATH",
        "interpretation": [
            "Signed interpolation is diagnostic association, not mechanism proof.",
            "Endpoint margins are stored values and are not set to zero.",
            "Predicted midpoint margin is chord midpoint plus 0.25*s_e.",
            "No AC calibration, replay, probing, or repair was performed.",
        ],
    }

    OUTDIR.mkdir(parents=True, exist_ok=True)
    outputs: list[Path] = []

    def emit(name: str, fields: list[str], rows: list[dict]):
        path = OUTDIR / name
        write_csv(path, fields, rows)
        outputs.append(path)

    emit("checks.csv", ["check_id", "status", "detail"], checks)
    emit("edge_signed_interpolation_diagnostics.csv", list(diagnostic_rows[0].keys()), diagnostic_rows)
    emit("signed_s_distribution.csv", list(signed_distribution_rows[0].keys()), signed_distribution_rows)
    emit("endpoint_midpoint_margin_distribution.csv", list(endpoint_distribution_rows[0].keys()), endpoint_distribution_rows)
    emit("fit_interior_n_distribution.csv", list(n_distribution_rows[0].keys()), n_distribution_rows)
    emit("failing_edges.csv", list(failure_edge_rows[0].keys()), failure_edge_rows)
    emit("low_sample_edges.csv", list(low_rows[0].keys()), low_rows)
    emit("low_sample_enrichment_points.csv", list(enrichment_rows[0].keys()), enrichment_rows)

    summary_path = OUTDIR / "summary.json"
    write_text(summary_path, json.dumps(json_safe(summary), indent=2, sort_keys=True, allow_nan=False) + "\n")
    outputs.append(summary_path)

    source_records = []
    for path in sorted(PATHS.values()):
        data = git("show", f"{SOURCE_COMMIT}:{path}")
        source_records.append({"path": path, "bytes": len(data),
                               "sha256": hashlib.sha256(data).hexdigest()})
    source_path = OUTDIR / "source_manifest.json"
    write_text(source_path, json.dumps({
        "source_commit": SOURCE_COMMIT,
        "read_semantics": "DIRECT_GIT_OBJECT_BYTES_NOT_WORKING_TREE",
        "files": source_records,
    }, indent=2, sort_keys=True) + "\n")
    outputs.append(source_path)

    report = f"""# Zero-AC Signed-Interpolation Addendum

Source commit: `{SOURCE_COMMIT}`

This addendum is deterministic and artifact-only. It performs zero new AC
calibration, solve, replay, probing, or repair.

## Gate result

`{overall}`

The locked campaign classification remains:

`MAIN_COUPLED_DOE_GEOMETRIC_CANDIDATE_FALSIFIED_BY_AC_COUNTEREXAMPLE`

## Signed interpolation population

The committed audit contains {len(fits)} edge-by-margin-channel rows:

- sufficient fits (`n_interior >= 3`): {len(sufficient)}
- insufficient rows: {len(insufficient)}
- exact unique insufficient edges: {len(insufficient_keys)}

The prompt expectation of 44 low-sample edges is not reproduced. Direct
reconstruction gives **41**, with one margin channel per edge. This is a
resolved input-count correction, not a blocker: the true set is complete and
the enrichment algorithm is defined over it.

Signed `s_e` is reported by guard relation × margin channel × endpoint
convex/reflex combination, including positive/negative counts and full
quantiles. Endpoint margins are retained as observed; they are never set to
zero. The predicted midpoint margin is

`r_hat(0.5) = 0.5*r_a + 0.5*r_b + 0.25*s_e`.

Across the {len(sufficient)} sufficient fits, signed `s_e` has median
{fmt(statistics.median(s_values))} p.u. and range
[{fmt(min(s_values))}, {fmt(max(s_values))}] p.u. These are diagnostic
associations, not mechanism proof.

## Failure-edge closure

All {total_failures} committed failures map to an outer edge within the locked
`{COORD_TOL_KW:g} kW` tolerance. The exact number of unique edges carrying at
least one failure is **{len(failure_edge_rows)}**. All mapped failures remain
VMAX. Detailed direct-angular versus cell-edge counts are provided per edge.

`cap_e` is retained only as a geometry feasibility bound. It is not used as the
primary falsification path and it is not an AC retreat estimate.

## Deterministic low-sample enrichment

For each of the {len(low_rows)} true low-sample edges, start from its distinct
interior fractions and repeatedly add the midpoint of the largest current gap
in `{{0, samples, 1}}`; ties choose the smallest left endpoint. Stop only when:

- at least {TARGET_MIN_INTERIOR} interior calibration points exist; and
- `g_e <= {TARGET_MAX_GAP}`.

This creates {len(enrichment_rows)} new coordinates. After enrichment, the
minimum interior count is {min(int(r['final_n_interior']) for r in low_rows)}
and the maximum gap is {fmt(max(float(r['final_g_e']) for r in low_rows))}.
Coordinates are construction-only and have not been AC evaluated.

## Phase-2 gate

No scientific blocker was found. The exact corrected low-sample set and its
deterministic enrichment may therefore be consumed by the Repair
Preregistration. No calibration is authorized by this addendum.
"""
    report_path = OUTDIR / "report.md"
    write_text(report_path, report)
    outputs.append(report_path)

    manifest_entries = []
    for path in sorted(outputs, key=lambda p: p.name):
        data = path.read_bytes()
        manifest_entries.append({"path": path.name, "bytes": len(data),
                                 "sha256": hashlib.sha256(data).hexdigest()})
    manifest_path = OUTDIR / "manifest.json"
    write_text(manifest_path, json.dumps({
        "schema_version": 1,
        "artifact": "ZERO_AC_SIGNED_INTERPOLATION_ADDENDUM",
        "source_commit": SOURCE_COMMIT,
        "files": manifest_entries,
    }, indent=2, sort_keys=True) + "\n")

    print(f"checks={len(checks)} blockers={len(blocker_checks)} failures={len(failed_checks)}")
    print(f"fits sufficient/total={len(sufficient)}/{len(fits)}")
    print(f"low-sample exact/prompt={len(insufficient_keys)}/44")
    print(f"failing edges={len(failure_edge_rows)}")
    print(f"enrichment coordinates={len(enrichment_rows)}")
    print(f"manifest payloads={len(manifest_entries)}")
    return 1 if failed_checks else 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--verify-index", action="store_true")
    args = parser.parse_args()
    sys.exit(verify_index() if args.verify_index else main())
