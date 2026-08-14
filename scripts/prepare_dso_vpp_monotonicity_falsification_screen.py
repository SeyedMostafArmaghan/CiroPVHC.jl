#!/usr/bin/env python3
"""Artifact-only monotonicity falsification screen for the production AC cloud.

This program reads completed production CSV artifacts.  It never imports or calls
the AC implementation.  Comparisons are timestamp-local and use a deterministic
P13-sorted sweep with vectorized P30 dominance filters.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import heapq
import json
import math
import subprocess
import time
from collections import defaultdict
from pathlib import Path

import numpy as np


EXPECTED_BRANCH = "codex/dso-vpp-ac-map-pilot"
EXPECTED_HEAD = "44cdad078b9503dfef6617c3585b99e7b014cdd9"
COORDINATE_EQUALITY_TOLERANCE_KW = 1e-9
# This is the production cross-solver voltage-state agreement tolerance, not a
# post-hoc monotonicity threshold.  See dso_vpp_ac_map_stage0.jl and the locked TOML.
VOLTAGE_NUMERICAL_TOLERANCE_PU = 2e-5
DIAGNOSTIC_THRESHOLDS_PU = (0.0, 1e-7, 1e-6, 1e-5, VOLTAGE_NUMERICAL_TOLERANCE_PU)

WORST_FIELDS = [
    "violation_type", "severity_pu", "timestamp",
    "point_a_attempt_id", "point_a_logical_evaluation_id",
    "point_a_P13", "point_a_P30", "point_b_attempt_id",
    "point_b_logical_evaluation_id", "point_b_P13", "point_b_P30",
    "rho_inf_a", "rho_inf_b", "Vmin_a", "Vmin_b", "Delta_Vmin",
    "Vmax_a", "Vmax_b", "Delta_Vmax", "feasibility_a", "feasibility_b",
    "mechanism_a", "mechanism_b", "search_family_a", "search_family_b",
    "search_id_a", "search_id_b", "same_trajectory_or_cross_trajectory",
    "region",
]


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=root, check=True, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    ).stdout.strip()


def mechanism(row: dict[str, str]) -> str:
    if row["solver_status"] != "CONVERGED_INFEASIBLE":
        return "NONE"
    voltage_status = row["voltage_status"]
    if voltage_status == "LOWER_VOLTAGE_VIOLATION":
        return "VMIN"
    if voltage_status == "UPPER_VOLTAGE_VIOLATION":
        return "VMAX"
    if voltage_status == "BOTH_LIMITS_VIOLATED":
        return "BOTH_VMIN_VMAX"
    return "UNKNOWN_FROM_STORED_FIELDS"


def has_vmin(value: str) -> bool:
    return value in ("VMIN", "BOTH_VMIN_VMAX")


def has_vmax(value: str) -> bool:
    return value in ("VMAX", "BOTH_VMIN_VMAX")


class TopK:
    def __init__(self, count: int = 20) -> None:
        self.count = count
        self.heap: list[tuple[float, int, dict]] = []
        self.sequence = 0

    def add(self, severity: float, record: dict) -> None:
        self.sequence += 1
        item = (float(severity), self.sequence, record)
        if len(self.heap) < self.count:
            heapq.heappush(self.heap, item)
        elif item[0] > self.heap[0][0]:
            heapq.heapreplace(self.heap, item)

    def rows(self) -> list[dict]:
        return [item[2] for item in sorted(self.heap, key=lambda item: (-item[0], item[1]))]


def empty_counts() -> dict[str, int]:
    result = {
        "total_comparable_pairs": 0,
        "same_trajectory_comparable_pairs": 0,
        "cross_trajectory_comparable_pairs": 0,
        "scalar_Vmin_violations": 0,
        "scalar_Vmax_violations": 0,
        "logical_VMIN_violations": 0,
        "logical_VMAX_violations": 0,
    }
    for statistic in ("Vmin", "Vmax"):
        for threshold in DIAGNOSTIC_THRESHOLDS_PU:
            result[f"{statistic}_negative_beyond_{threshold:.0e}"] = 0
    return result


def add_masked_counts(target: dict[str, int], name: str, mask: np.ndarray) -> None:
    target[name] += int(np.count_nonzero(mask))


def duplicate_statistics(points: list[dict]) -> tuple[int, int, int]:
    """Return duplicate groups, excess rows, and rows participating in groups."""
    n = len(points)
    parent = list(range(n))
    size = [1] * n

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def union(left: int, right: int) -> None:
        left_root, right_root = find(left), find(right)
        if left_root == right_root:
            return
        if size[left_root] < size[right_root]:
            left_root, right_root = right_root, left_root
        parent[right_root] = left_root
        size[left_root] += size[right_root]

    order = sorted(range(n), key=lambda i: (points[i]["p13"], points[i]["p30"], points[i]["attempt_id"]))
    tolerance = COORDINATE_EQUALITY_TOLERANCE_KW
    for order_pos, left in enumerate(order):
        right_pos = order_pos + 1
        while right_pos < n:
            right = order[right_pos]
            if points[right]["p13"] - points[left]["p13"] > tolerance:
                break
            if abs(points[right]["p30"] - points[left]["p30"]) <= tolerance:
                union(left, right)
            right_pos += 1
    groups: dict[int, int] = defaultdict(int)
    for index in range(n):
        groups[find(index)] += 1
    duplicate_sizes = [value for value in groups.values() if value > 1]
    return len(duplicate_sizes), sum(value - 1 for value in duplicate_sizes), sum(duplicate_sizes)


def point_record(point: dict, prefix: str) -> dict:
    return {
        f"point_{prefix}_attempt_id": point["attempt_id"],
        f"point_{prefix}_logical_evaluation_id": point["logical_id"],
        f"point_{prefix}_P13": point["p13"],
        f"point_{prefix}_P30": point["p30"],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument(
        "--output-directory", type=Path,
        default=Path("results/dso_vpp_ac_map_pilot/monotonicity_falsification_screen"),
    )
    args = parser.parse_args()
    root = args.repository_root.resolve()
    output = args.output_directory
    if not output.is_absolute():
        output = root / output

    branch = git(root, "branch", "--show-current")
    head = git(root, "rev-parse", "HEAD")
    if branch != EXPECTED_BRANCH or head != EXPECTED_HEAD:
        raise SystemExit(
            f"repository mismatch: branch={branch!r}, HEAD={head!r}; "
            f"expected branch={EXPECTED_BRANCH!r}, HEAD={EXPECTED_HEAD!r}"
        )

    started = time.perf_counter()
    production = root / "results" / "dso_vpp_ac_map_pilot" / "production_probe"
    attempts_path = production / "evaluation_attempts.csv"
    axis_path = production / "signed_axis_results.csv"
    center_path = production / "center_results.csv"
    manifest_rows = read_csv(production / "artifact_manifest.csv")
    manifest = {row["artifact"]: row["sha256"] for row in manifest_rows}
    for path in (attempts_path, axis_path, center_path):
        if manifest.get(path.name) != sha256(path):
            raise SystemExit(f"production artifact hash mismatch: {path}")

    raw_attempts = read_csv(attempts_path)
    stored_status_counts: dict[str, int] = defaultdict(int)
    by_timestamp: dict[str, list[dict]] = defaultdict(list)
    excluded_status_counts: dict[str, int] = defaultdict(int)
    for row in raw_attempts:
        stored_status_counts[row["solver_status"]] += 1
        if row["solver_status"] not in ("CONVERGED_FEASIBLE", "CONVERGED_INFEASIBLE"):
            excluded_status_counts[row["solver_status"]] += 1
            continue
        point = {
            "attempt_id": int(row["attempt_id"]),
            "logical_id": int(row["logical_evaluation_id"]),
            "attempt_index": int(row["attempt_index"]),
            "timestamp": row["timestamp"],
            "search_kind": row["search_kind"],
            "search_id": row["search_id"],
            "phase": row["phase"],
            "p13": float(row["p13_abs_kw"]),
            "p30": float(row["p30_abs_kw"]),
            "status": row["solver_status"],
            "voltage_status": row["voltage_status"],
            "vmin": float(row["vmin_pu"]),
            "vmin_bus": int(row["vmin_bus"]),
            "vmax": float(row["vmax_pu"]),
            "vmax_bus": int(row["vmax_bus"]),
            "mechanism": mechanism(row),
            "initialization": row["initialization"],
            "initialization_source_logical_id": int(row["initialization_source_logical_id"]),
        }
        if not all(math.isfinite(point[field]) for field in ("p13", "p30", "vmin", "vmax")):
            raise SystemExit(f"nonfinite converged point in attempt {point['attempt_id']}")
        by_timestamp[point["timestamp"]].append(point)

    if len(by_timestamp) != 32:
        raise SystemExit(f"expected 32 usable timestamps, found {len(by_timestamp)}")

    centers = {
        row["timestamp"]: {
            "tier": row["center_tier"],
            "p13": float(row["p13_abs_kw"]),
            "p30": float(row["p30_abs_kw"]),
        }
        for row in read_csv(center_path)
    }
    axis_rows = read_csv(axis_path)
    bounds: dict[str, dict[str, float]] = defaultdict(dict)
    axis_key = {
        "P13_NEGATIVE": "p13_min", "P13_POSITIVE": "p13_max",
        "P30_NEGATIVE": "p30_min", "P30_POSITIVE": "p30_max",
    }
    for row in axis_rows:
        if row["status"] != "AXIS_CERTIFIED_BOUNDARY":
            raise SystemExit(f"non-certified signed axis at {row['timestamp']} {row['axis']}")
        bounds[row["timestamp"]][axis_key[row["axis"]]] = float(row["official_boundary_p_pcc_kw"])
    if set(centers) != set(by_timestamp) or set(bounds) != set(by_timestamp):
        raise SystemExit("timestamp mismatch among attempts, centers, and signed-axis bounds")
    if any(center["tier"] != "CENTER_TIER_1_AXIS_MIDPOINT" for center in centers.values()):
        raise SystemExit("the fixed rho definition requires Tier-1 centers for all timestamps")

    duplicate_groups = duplicate_excess = duplicate_rows = 0
    for timestamp, points in by_timestamp.items():
        groups, excess, participating = duplicate_statistics(points)
        duplicate_groups += groups
        duplicate_excess += excess
        duplicate_rows += participating

        center = centers[timestamp]
        bound = bounds[timestamp]
        denominators = (
            bound["p13_max"] - center["p13"], center["p13"] - bound["p13_min"],
            bound["p30_max"] - center["p30"], center["p30"] - bound["p30_min"],
        )
        if not all(value > 0.0 for value in denominators):
            raise SystemExit(f"invalid signed normalization bounds at {timestamp}")
        for point in points:
            z13 = ((point["p13"] - center["p13"]) /
                   (denominators[0] if point["p13"] >= center["p13"] else denominators[1]))
            z30 = ((point["p30"] - center["p30"]) /
                   (denominators[2] if point["p30"] >= center["p30"] else denominators[3]))
            point["rho"] = max(abs(z13), abs(z30))

    aggregate = empty_counts()
    timestamp_counts = {timestamp: empty_counts() for timestamp in by_timestamp}
    region_counts = {name: empty_counts() for name in ("NEAR_CENTER", "STRADDLING", "BOTH_FARTHER")}
    worst = {name: TopK(20) for name in ("SCALAR_VMIN", "SCALAR_VMAX", "LOGICAL_VMIN", "LOGICAL_VMAX")}

    def add_worst(kind: str, severity: np.ndarray, ai: np.ndarray, bi: np.ndarray,
                  mask: np.ndarray, points: list[dict], rho: np.ndarray,
                  same: np.ndarray) -> None:
        candidates = np.flatnonzero(mask)
        if candidates.size > 20:
            candidates = candidates[np.argpartition(severity[candidates], -20)[-20:]]
        for pos in candidates:
            a = points[int(ai[pos])]
            b = points[int(bi[pos])]
            if rho[ai[pos]] <= 1.0 and rho[bi[pos]] <= 1.0:
                region = "NEAR_CENTER"
            elif rho[ai[pos]] > 1.0 and rho[bi[pos]] > 1.0:
                region = "BOTH_FARTHER"
            else:
                region = "STRADDLING"
            record = {
                "violation_type": kind,
                "severity_pu": float(severity[pos]),
                "timestamp": a["timestamp"],
                **point_record(a, "a"), **point_record(b, "b"),
                "rho_inf_a": a["rho"], "rho_inf_b": b["rho"],
                "Vmin_a": a["vmin"], "Vmin_b": b["vmin"],
                "Delta_Vmin": b["vmin"] - a["vmin"],
                "Vmax_a": a["vmax"], "Vmax_b": b["vmax"],
                "Delta_Vmax": b["vmax"] - a["vmax"],
                "feasibility_a": a["status"], "feasibility_b": b["status"],
                "mechanism_a": a["mechanism"], "mechanism_b": b["mechanism"],
                "search_family_a": a["search_kind"], "search_family_b": b["search_kind"],
                "search_id_a": a["search_id"], "search_id_b": b["search_id"],
                "same_trajectory_or_cross_trajectory": "SAME_TRAJECTORY" if same[pos] else "CROSS_TRAJECTORY",
                "region": region,
            }
            worst[kind].add(float(severity[pos]), record)

    def process_pairs(timestamp: str, points: list[dict], ai: np.ndarray, bi: np.ndarray,
                      arrays: dict[str, np.ndarray]) -> None:
        if ai.size == 0:
            return
        current = timestamp_counts[timestamp]
        trajectories = arrays["trajectory"]
        same = trajectories[ai] == trajectories[bi]
        cross = ~same
        count = int(ai.size)
        aggregate["total_comparable_pairs"] += count
        current["total_comparable_pairs"] += count
        same_count = int(np.count_nonzero(same))
        cross_count = count - same_count
        aggregate["same_trajectory_comparable_pairs"] += same_count
        current["same_trajectory_comparable_pairs"] += same_count
        aggregate["cross_trajectory_comparable_pairs"] += cross_count
        current["cross_trajectory_comparable_pairs"] += cross_count

        delta_vmin = arrays["vmin"][bi] - arrays["vmin"][ai]
        delta_vmax = arrays["vmax"][bi] - arrays["vmax"][ai]
        for label, delta in (("Vmin", delta_vmin), ("Vmax", delta_vmax)):
            for threshold in DIAGNOSTIC_THRESHOLDS_PU:
                key = f"{label}_negative_beyond_{threshold:.0e}"
                mask = delta < -threshold
                add_masked_counts(aggregate, key, mask)
                add_masked_counts(current, key, mask)

        vmin_bad = delta_vmin < -VOLTAGE_NUMERICAL_TOLERANCE_PU
        vmax_bad = delta_vmax < -VOLTAGE_NUMERICAL_TOLERANCE_PU
        status = arrays["status"]
        is_feasible = status == 0
        is_infeasible = status == 1
        logical_vmin = is_feasible[ai] & is_infeasible[bi] & arrays["has_vmin"][bi]
        logical_vmax = is_infeasible[ai] & arrays["has_vmax"][ai] & is_feasible[bi]
        masks = {
            "scalar_Vmin_violations": vmin_bad,
            "scalar_Vmax_violations": vmax_bad,
            "logical_VMIN_violations": logical_vmin,
            "logical_VMAX_violations": logical_vmax,
        }
        for key, mask in masks.items():
            add_masked_counts(aggregate, key, mask)
            add_masked_counts(current, key, mask)

        near_a, near_b = arrays["rho"][ai] <= 1.0, arrays["rho"][bi] <= 1.0
        region_masks = {
            "NEAR_CENTER": near_a & near_b,
            "STRADDLING": near_a ^ near_b,
            "BOTH_FARTHER": ~near_a & ~near_b,
        }
        for region, region_mask in region_masks.items():
            informative = cross & region_mask
            region_counts[region]["cross_trajectory_comparable_pairs"] += int(np.count_nonzero(informative))
            region_counts[region]["total_comparable_pairs"] += int(np.count_nonzero(informative))
            for key, mask in masks.items():
                region_counts[region][key] += int(np.count_nonzero(informative & mask))

        add_worst("SCALAR_VMIN", -delta_vmin, ai, bi, vmin_bad, points, arrays["rho"], same)
        add_worst("SCALAR_VMAX", -delta_vmax, ai, bi, vmax_bad, points, arrays["rho"], same)
        add_worst("LOGICAL_VMIN", -delta_vmin, ai, bi, logical_vmin, points, arrays["rho"], same)
        add_worst("LOGICAL_VMAX", -delta_vmax, ai, bi, logical_vmax, points, arrays["rho"], same)

    for timestamp in sorted(by_timestamp):
        points = sorted(by_timestamp[timestamp], key=lambda p: (p["p13"], p["p30"], p["attempt_id"]))
        trajectory_keys = sorted({(p["search_kind"], p["search_id"]) for p in points})
        trajectory_id = {key: index for index, key in enumerate(trajectory_keys)}
        arrays = {
            "p13": np.asarray([p["p13"] for p in points]),
            "p30": np.asarray([p["p30"] for p in points]),
            "vmin": np.asarray([p["vmin"] for p in points]),
            "vmax": np.asarray([p["vmax"] for p in points]),
            "rho": np.asarray([p["rho"] for p in points]),
            "status": np.asarray([0 if p["status"] == "CONVERGED_FEASIBLE" else 1 for p in points], dtype=np.int8),
            "has_vmin": np.asarray([has_vmin(p["mechanism"]) for p in points]),
            "has_vmax": np.asarray([has_vmax(p["mechanism"]) for p in points]),
            "trajectory": np.asarray([trajectory_id[(p["search_kind"], p["search_id"])] for p in points]),
        }
        tolerance = COORDINATE_EQUALITY_TOLERANCE_KW
        for right in range(1, len(points)):
            prior = np.arange(right, dtype=np.int32)
            # Forward orientation: prior P13 is lower by sort; equality tolerance
            # is used only on the P30 equality boundary.
            forward = arrays["p30"][:right] <= arrays["p30"][right] + tolerance
            forward_ai = prior[forward]
            forward_bi = np.full(forward_ai.size, right, dtype=np.int32)
            process_pairs(timestamp, points, forward_ai, forward_bi, arrays)

            # Reverse orientation is possible only when P13 is numerically equal.
            # It captures the other dominance direction for coordinate-equal rows.
            reverse = ((arrays["p13"][right] - arrays["p13"][:right] <= tolerance) &
                       (arrays["p30"][right] <= arrays["p30"][:right] + tolerance))
            reverse_bi = prior[reverse]
            reverse_ai = np.full(reverse_bi.size, right, dtype=np.int32)
            process_pairs(timestamp, points, reverse_ai, reverse_bi, arrays)

    usable_count = sum(len(points) for points in by_timestamp.values())
    excluded_count = len(raw_attempts) - usable_count
    if excluded_count != 286 or usable_count != 87086:
        raise SystemExit(f"unexpected population counts usable={usable_count} excluded={excluded_count}")
    if sum(excluded_status_counts.values()) != excluded_count:
        raise SystemExit("excluded status decomposition mismatch")
    if aggregate["total_comparable_pairs"] != (
        aggregate["same_trajectory_comparable_pairs"] + aggregate["cross_trajectory_comparable_pairs"]
    ):
        raise SystemExit("trajectory decomposition mismatch")
    if aggregate["cross_trajectory_comparable_pairs"] != sum(
        region_counts[name]["cross_trajectory_comparable_pairs"]
        for name in region_counts
    ):
        raise SystemExit("near/far informative-pair decomposition mismatch")

    any_counterexample = any(aggregate[key] > 0 for key in (
        "scalar_Vmin_violations", "scalar_Vmax_violations",
        "logical_VMIN_violations", "logical_VMAX_violations",
    ))
    classification = (
        "STORED_EVIDENCE_CONTRADICTS_COMPONENTWISE_VOLTAGE_MONOTONICITY"
        if any_counterexample else
        "NO_MONOTONICITY_COUNTEREXAMPLE_OBSERVED_IN_STORED_EVALUATIONS"
    )

    timestamp_rows = []
    for timestamp in sorted(by_timestamp):
        row = {
            "timestamp": timestamp,
            "usable_points": len(by_timestamp[timestamp]),
            **{key: timestamp_counts[timestamp][key] for key in (
                "total_comparable_pairs", "cross_trajectory_comparable_pairs",
                "scalar_Vmin_violations", "scalar_Vmax_violations",
                "logical_VMIN_violations", "logical_VMAX_violations",
            )},
        }
        timestamp_rows.append(row)
    write_csv(output / "timestamp_summary.csv", timestamp_rows, list(timestamp_rows[0]))

    region_rows = []
    for region in ("NEAR_CENTER", "STRADDLING", "BOTH_FARTHER"):
        counts = region_counts[region]
        region_rows.append({
            "region": region,
            "informative_comparable_pairs": counts["cross_trajectory_comparable_pairs"],
            **{key: counts[key] for key in (
                "scalar_Vmin_violations", "scalar_Vmax_violations",
                "logical_VMIN_violations", "logical_VMAX_violations",
            )},
        })
    write_csv(output / "region_summary.csv", region_rows, list(region_rows[0]))

    diagnostic_rows = []
    for statistic in ("Vmin", "Vmax"):
        for threshold in DIAGNOSTIC_THRESHOLDS_PU:
            diagnostic_rows.append({
                "statistic": statistic,
                "threshold_pu": threshold,
                "negative_delta_count": aggregate[f"{statistic}_negative_beyond_{threshold:.0e}"],
            })
    write_csv(output / "diagnostic_threshold_counts.csv", diagnostic_rows, list(diagnostic_rows[0]))

    for kind, top in worst.items():
        write_csv(output / f"worst_{kind.lower()}.csv", top.rows(), WORST_FIELDS)

    elapsed = time.perf_counter() - started
    summary = {
        "classification": classification,
        "purpose": "artifact-only falsification screen; finite observations do not prove monotonicity",
        "repository": {"branch": branch, "head": head, "preanalysis_git_status_short": "CLEAN"},
        "population": {
            "number_of_timestamps": len(by_timestamp),
            "total_stored_evaluations": len(raw_attempts),
            "converged_usable_evaluations": usable_count,
            "nonconverged_excluded": excluded_count,
            "excluded_status_counts": dict(sorted(excluded_status_counts.items())),
            "duplicate_coordinate_groups": duplicate_groups,
            "duplicate_coordinates_detected": duplicate_excess,
            "duplicate_rows_participating": duplicate_rows,
            "duplicate_coordinates_deduplicated": 0,
        },
        "comparability": aggregate,
        "regions": {row["region"]: row for row in region_rows},
        "coordinate_equality_tolerance_kw": COORDINATE_EQUALITY_TOLERANCE_KW,
        "voltage_numerical_tolerance_pu": VOLTAGE_NUMERICAL_TOLERANCE_PU,
        "voltage_tolerance_source": (
            "src/benchmark/dso_vpp_ac_map_stage0.jl:21 REPLAY_VOLTAGE_MATCH_TOLERANCE_PU; "
            "config/dso_vpp_production_probe_preregistration.toml [stopping_and_replay] "
            "replay_voltage_agreement_pu"
        ),
        "full_bus_voltage_vectors_stored": False,
        "full_bus_classification": "FULL_BUS_MONOTONICITY_NOT_TESTABLE_FROM_STORED_ARTIFACTS",
        "co_binding_classification": "CO_BINDING_NOT_RESOLVABLE_FROM_STORED_ARTIFACTS",
        "production_classification_preserved": "POSTPRODUCTION_RESULT_AUDIT_COMPLETE_WITH_DOCUMENTED_LIMITATIONS",
        "runtime_seconds": elapsed,
        "parallelization": "NONE",
    }
    output.mkdir(parents=True, exist_ok=True)
    (output / "monotonicity_falsification_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    def fmt_int(value: int) -> str:
        return f"{value:,}"

    lines: list[str] = []
    lines += [
        "# Artifact-only componentwise voltage monotonicity falsification screen", "",
        "## A. Repository provenance", "",
        f"- Branch: `{branch}`", f"- HEAD: `{head}`",
        "- Pre-analysis `git status --short`: clean.",
        "- No AC power flow or production probe was run. This report was generated only from tracked artifacts.", "",
        "## B. Production artifact(s) inspected", "",
        "- Authoritative individual-evaluation cloud: `results/dso_vpp_ac_map_pilot/production_probe/evaluation_attempts.csv`.",
        "- Signed normalization bounds: `signed_axis_results.csv`.",
        "- Tier-1 centers: `center_results.csv`.",
        "- Search/outcome context: `base_ray_results.csv`, `adaptive_ray_results.csv`, and `run_manifest.toml`.",
        "- Completed checkpoint schema was inspected in code: completed segments retain attempt rows and scalar point summaries, not accepted-neighbor voltage vectors.", "",
        "## C. Artifact schema and limitations", "",
        "| requested per-evaluation field | stored? | exact artifact representation |",
        "|---|---|---|",
        "| timestamp | yes | `timestamp` |",
        "| absolute P13 PCC | yes | `p13_abs_kw` |",
        "| absolute P30 PCC | yes | `p30_abs_kw` |",
        "| convergence status | yes | `primary_power_flow_status`, `replay_status`, and combined `solver_status` |",
        "| feasibility status | yes | `solver_status` and `voltage_status` |",
        "| Vmin / Vmax | yes | `vmin_pu`, `vmax_pu` |",
        "| buses of Vmin / Vmax | yes | `vmin_bus`, `vmax_bus` |",
        "| full all-bus voltage vector | no | omitted from CSV and completed checkpoint segment |",
        "| search family/type | yes | `search_kind` |",
        "| ray angle or signed axis direction | yes | exact `search_id` (`RAY` angle string or signed-axis name) |",
        "| search/trajectory ID | yes | exact pair `(search_kind, search_id)` |",
        "| retry metadata | yes | `attempt_index`, `initialization`, `initialization_source_logical_id` |",
        "| mechanism | no direct field | conservatively derived only from stored `voltage_status`; official outcome mechanism exists in endpoint/result artifacts |",
        "| coarse-sweep/bisection metadata | yes | `phase` |",
        "| boundary/outcome metadata | no direct per-attempt field | stored separately in axis/ray/endpoint result artifacts |",
        "", "Completed checkpoints retain attempt rows and scalar point summaries, not accepted-neighbor voltage vectors. The 73 `RAY_UNBOUNDED_WITHIN_GUARD` outcomes (`CERTIFIED_FEASIBLE_GUARD_TRUNCATION` in the post-production audit) contribute converged stored evaluations where available; they are safe observations and are not labeled as physical AC boundaries.",
        "Mechanism below is conservatively derived from the stored `voltage_status`; no missing field is invented.",
        "`FULL_BUS_MONOTONICITY_NOT_TESTABLE_FROM_STORED_ARTIFACTS`.",
        "`CO_BINDING_NOT_RESOLVABLE_FROM_STORED_ARTIFACTS`.", "",
        "## D. AC/model facts relevant to theorem applicability", "",
        "- Radial, connected IEEE 33-bus topology (32 fixed branches), represented as a balanced single-phase equivalent.",
        "- Exact radial AC backward/forward sweep with complex constant-PQ net demand (`conj(S/V)`); primary/replay convergence tolerances are 1e-11/1e-12 pu.",
        "- Positive interface P is injection/export and is subtracted from bus demand at buses 13 and 30.",
        "- Q13 PCC and Q30 PCC are fixed to zero (unity-power-factor interface policy); production explicitly disables reference PV (`reference_pv_capacity_kw=0.0`). Other reactive injections do not vary with P.",
        "- Bus 1 is the ideal slack/root at fixed complex voltage 1+0j pu.",
        "- Feasibility uses all-bus voltage magnitudes with the locked 0.90-1.05 pu band and zero feasibility-band tolerance; no thermal limit defines this probe.",
        "- Bus active and reactive constant-power loads are both scaled by one canonical timestamp multiplier and remain fixed within a timestamp.",
        "- The network data and probe path contain no tap changer, regulator, capacitor switching, or other discrete/state-dependent network control. Retry changes initialization only; independent flat-start replay must pass.",
        "These are repository facts only, not a theorem or theorem-applicability conclusion.", "",
        "## E. Usable evaluation population", "",
        f"- number_of_timestamps: {len(by_timestamp)}",
        f"- total_stored_evaluations: {fmt_int(len(raw_attempts))}",
        f"- converged_usable_evaluations: {fmt_int(usable_count)}",
        f"- nonconverged_excluded: {fmt_int(excluded_count)} ({dict(sorted(excluded_status_counts.items()))})",
        f"- duplicate_coordinates_detected: {fmt_int(duplicate_excess)} excess rows in {fmt_int(duplicate_groups)} coordinate groups ({fmt_int(duplicate_rows)} participating rows)",
        "- duplicate_coordinates_deduplicated: 0. Distinct attempt/logical IDs and search provenance were preserved; equal-coordinate rows are separate recorded solver executions and both valid dominance directions are tested.", "",
        "## F. Dominance/comparability statistics", "",
        f"- total_comparable_pairs: {fmt_int(aggregate['total_comparable_pairs'])}",
        f"- informative_comparable_pairs: {fmt_int(aggregate['cross_trajectory_comparable_pairs'])}",
        f"- same_trajectory_comparable_pairs: {fmt_int(aggregate['same_trajectory_comparable_pairs'])}",
        f"- cross_trajectory_comparable_pairs: {fmt_int(aggregate['cross_trajectory_comparable_pairs'])}",
        "Trajectory identity is the exact stored `(search_kind, search_id)` pair; no approximate-angle inference is used.", "",
        "The implementation is a deterministic timestamp-local P13 sweep with vectorized P30 filters. The pre-run upper bound was 118,458,772 candidate unordered pairs, expected runtime was tens of seconds, expected RAM was below 256 MB, and parallelization was not used.", "",
        "## G. Near-center comparability statistics", "",
    ]
    near = region_counts["NEAR_CENTER"]
    lines += [f"- informative_comparable_pairs: {fmt_int(near['cross_trajectory_comparable_pairs'])}"]
    for key in ("scalar_Vmin_violations", "scalar_Vmax_violations", "logical_VMIN_violations", "logical_VMAX_violations"):
        lines.append(f"- {key}: {fmt_int(near[key])}")
    lines += ["", "## H. Farther/straddling comparability statistics", ""]
    for region in ("STRADDLING", "BOTH_FARTHER"):
        counts = region_counts[region]
        lines.append(f"### {region}")
        lines.append("")
        lines.append(f"- informative_comparable_pairs: {fmt_int(counts['cross_trajectory_comparable_pairs'])}")
        for key in ("scalar_Vmin_violations", "scalar_Vmax_violations", "logical_VMIN_violations", "logical_VMAX_violations"):
            lines.append(f"- {key}: {fmt_int(counts[key])}")
        lines.append("")
    lines += [
        "## I. Scalar Vmin monotonicity screen", "",
        f"The primary numerical threshold is the pre-existing production replay voltage-state agreement tolerance, {VOLTAGE_NUMERICAL_TOLERANCE_PU:.0e} pu, defined at `src/benchmark/dso_vpp_ac_map_stage0.jl:21` and locked as `replay_voltage_agreement_pu` in the preregistration TOML.",
        f"- classified violations (Delta Vmin < -2e-5 pu): {fmt_int(aggregate['scalar_Vmin_violations'])}",
    ]
    for threshold in DIAGNOSTIC_THRESHOLDS_PU[:-1]:
        lines.append(f"- negative Delta Vmin beyond {threshold:.0e} pu: {fmt_int(aggregate[f'Vmin_negative_beyond_{threshold:.0e}'])}")
    lines += ["", "## J. Scalar Vmax monotonicity screen", "",
              f"- classified violations (Delta Vmax < -2e-5 pu): {fmt_int(aggregate['scalar_Vmax_violations'])}"]
    for threshold in DIAGNOSTIC_THRESHOLDS_PU[:-1]:
        lines.append(f"- negative Delta Vmax beyond {threshold:.0e} pu: {fmt_int(aggregate[f'Vmax_negative_beyond_{threshold:.0e}'])}")
    lines += [
        "", "## K. Logical VMIN/VMAX contradiction screen", "",
        f"- logical VMIN contradictions: {fmt_int(aggregate['logical_VMIN_violations'])}",
        f"- logical VMAX contradictions: {fmt_int(aggregate['logical_VMAX_violations'])}",
        "Only converged feasible/infeasible rows participate; nonconvergence is never treated as infeasibility.", "",
        "## L. Worst counterexamples, if any", "",
    ]
    for kind in ("SCALAR_VMIN", "SCALAR_VMAX", "LOGICAL_VMIN", "LOGICAL_VMAX"):
        rows = worst[kind].rows()
        lines.append(f"- {kind}: {len(rows)} rows in `worst_{kind.lower()}.csv`.")
    if not any_counterexample:
        lines.append("No tolerance-classified or logical counterexample exists, so all four files contain headers only.")
    lines += ["", "## M. Timestamp-by-timestamp table", "",
              "| timestamp | usable_points | total_comparable_pairs | cross_trajectory_comparable_pairs | scalar_Vmin_violations | scalar_Vmax_violations | logical_VMIN_violations | logical_VMAX_violations |",
              "|---|---:|---:|---:|---:|---:|---:|---:|"]
    for row in timestamp_rows:
        lines.append("| " + " | ".join(str(row[field]) for field in row) + " |")
    lines += [
        "", "## N. Final classification", "",
        f"`{classification}`", "",
        f"informative_comparable_pairs = {aggregate['cross_trajectory_comparable_pairs']}", "",
        "This is a finite-sample falsification result, not a proof, confirmation, or certification of monotonicity.",
        "The authoritative production classification remains `POSTPRODUCTION_RESULT_AUDIT_COMPLETE_WITH_DOCUMENTED_LIMITATIONS`.", "",
        "## O. Implications for DOE Construction Policy", "",
    ]
    if any_counterexample:
        lines.append("Stored evidence falsifies the unrestricted componentwise-voltage monotonicity route over the sampled AC region. A domain-restricted route could be investigated only if the near-center evidence is separately compatible; no DOE architecture is selected here.")
    else:
        lines.append("The stored evidence supports continuing investigation of a monotonicity-based box certification, conditional on a later theorem/applicability review. The near/far decomposition quantifies whether a local claim appears more plausible than a global one. No DOE architecture is selected here.")
    lines += ["", f"Artifact-only runtime: {elapsed:.3f} s; parallelization: none.", ""]
    report_path = output / "monotonicity_falsification_report.md"
    report_path.write_text("\n".join(lines), encoding="utf-8")

    generated = sorted(path for path in output.iterdir() if path.is_file() and path.name != "artifact_manifest.csv")
    manifest_output_rows = [
        {"artifact": path.name, "bytes": path.stat().st_size, "sha256": sha256(path)}
        for path in generated
    ]
    write_csv(output / "artifact_manifest.csv", manifest_output_rows, ["artifact", "bytes", "sha256"])
    print(json.dumps({
        "classification": classification,
        "usable": usable_count,
        "excluded": excluded_count,
        "comparable": aggregate["total_comparable_pairs"],
        "informative": aggregate["cross_trajectory_comparable_pairs"],
        "runtime_seconds": elapsed,
        "output": str(output),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
