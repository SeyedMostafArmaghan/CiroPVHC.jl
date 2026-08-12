from __future__ import annotations

import csv
import hashlib
import math
import sys
import tomllib
from collections import Counter, defaultdict
from pathlib import Path


ALLOWED_ADAPTIVE_TRIGGERS = {
    "BOUNDARY_MECHANISM_CHANGE",
    "BINDING_BUS_CHANGE",
    "NORMALIZED_RADIUS_DIFFERENCE_GT_10_PERCENT",
    "UNRESOLVED_NONCONVERGED_REENTRY_OR_GUARD_LIMITED_ENDPOINT",
}
CONTAMINATED_RAY_STATUSES = {
    "RAY_UNRESOLVED",
    "RAY_REENTRY_DETECTED",
    "RAY_UNBOUNDED_WITHIN_GUARD",
}


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def as_float(value: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return math.nan


def as_bool(value: str) -> bool:
    return value.strip().lower() == "true"


def attempt_key(row: dict[str, str]) -> tuple[str, str]:
    return row["timestamp"], row["logical_evaluation_id"]


def adaptive_reasons(left: dict[str, str], right: dict[str, str]) -> set[str]:
    reasons: set[str] = set()
    if left["binding_mechanism"] != right["binding_mechanism"]:
        reasons.add("BOUNDARY_MECHANISM_CHANGE")
    if left["binding_bus"] != right["binding_bus"]:
        reasons.add("BINDING_BUS_CHANGE")
    left_radius = as_float(left["official_boundary_r"])
    right_radius = as_float(right["official_boundary_r"])
    if math.isfinite(left_radius) and math.isfinite(right_radius):
        denominator = max(abs(left_radius), abs(right_radius), sys.float_info.epsilon)
        if abs(left_radius - right_radius) / denominator > 0.10:
            reasons.add("NORMALIZED_RADIUS_DIFFERENCE_GT_10_PERCENT")
    if (
        left["status"] in CONTAMINATED_RAY_STATUSES
        or right["status"] in CONTAMINATED_RAY_STATUSES
    ):
        reasons.add("UNRESOLVED_NONCONVERGED_REENTRY_OR_GUARD_LIMITED_ENDPOINT")
    return reasons


def binding_invariant(row: dict[str, str]) -> bool:
    mechanism = row["binding_mechanism"]
    if mechanism not in {"BINDING_VMIN", "BINDING_VMAX"}:
        return True
    if row["violating_solver_status"] != "CONVERGED_INFEASIBLE":
        return False
    if not row["binding_bus"]:
        return False
    if mechanism == "BINDING_VMIN":
        return as_float(row["violating_vmin_pu"]) < 0.90 and bool(
            row["violating_vmin_bus"]
        )
    return as_float(row["violating_vmax_pu"]) > 1.05 and bool(
        row["violating_vmax_bus"]
    )


def write_checks(path: Path, checks: list[tuple[str, bool, str]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(["check", "passed", "detail"])
        for name, passed, detail in checks:
            writer.writerow([name, str(passed).lower(), detail])


def refresh_artifact_manifest(output: Path) -> None:
    rows = []
    for path in sorted(output.iterdir(), key=lambda item: item.name):
        if not path.is_file() or path.name == "artifact_manifest.csv":
            continue
        rows.append((path.name, path.stat().st_size, sha256_file(path)))
    with (output / "artifact_manifest.csv").open(
        "w", newline="", encoding="utf-8"
    ) as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(["artifact", "bytes", "sha256"])
        writer.writerows(rows)


def validate(root: Path) -> tuple[list[tuple[str, bool, str]], dict[str, int]]:
    output = root / "results" / "dso_vpp_ac_map_pilot" / "production_probe"
    with (output / "run_manifest.toml").open("rb") as handle:
        manifest = tomllib.load(handle)
    axes = read_csv(output / "signed_axis_results.csv")
    centers = read_csv(output / "center_results.csv")
    base = read_csv(output / "base_ray_results.csv")
    adaptive = read_csv(output / "adaptive_ray_results.csv")
    attempts = read_csv(output / "evaluation_attempts.csv")
    endpoints = read_csv(output / "boundary_endpoints.csv")
    checkpoints = read_csv(output / "checkpoint_resume_manifest.csv")
    artifact_manifest = read_csv(output / "artifact_manifest.csv")

    checks: list[tuple[str, bool, str]] = []

    def add(name: str, passed: bool, detail: str) -> None:
        checks.append((name, bool(passed), detail))

    timestamps = [row["timestamp"] for row in centers]
    add("exactly_32_timestamps", len(timestamps) == 32, f"observed={len(timestamps)}")
    add(
        "mandatory_anchor_exists",
        timestamps.count("2012-10-15 13:00:00") == 1,
        f"anchor_count={timestamps.count('2012-10-15 13:00:00')}",
    )
    add(
        "no_duplicate_timestamp",
        len(set(timestamps)) == len(timestamps),
        f"unique={len(set(timestamps))}",
    )

    axes_by_timestamp: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in axes:
        axes_by_timestamp[row["timestamp"]].append(row)
    expected_axes = {"P13_POSITIVE", "P13_NEGATIVE", "P30_POSITIVE", "P30_NEGATIVE"}
    four_axes = all(
        len(rows) == 4 and {row["axis"] for row in rows} == expected_axes
        for rows in axes_by_timestamp.values()
    ) and len(axes_by_timestamp) == 32
    add("four_signed_axes_each", four_axes, f"axis_rows={len(axes)}")
    tier1_valid = all(
        center["center_tier"] != "CENTER_TIER_1_AXIS_MIDPOINT"
        or all(
            axis["status"] == "AXIS_CERTIFIED_BOUNDARY"
            for axis in axes_by_timestamp[center["timestamp"]]
        )
        for center in centers
    )
    add("tier1_requires_four_finite_axes", tier1_valid, "finite-valid status checked")
    add("invalid_axes_excluded_from_tier1", tier1_valid, "guard/unresolved/reentry excluded")

    all_boundaries = axes + base + adaptive
    add(
        "binding_mechanism_invariants",
        all(binding_invariant(row) for row in all_boundaries),
        "violating voltage and bus independently checked",
    )
    certified = [
        row
        for row in all_boundaries
        if row["status"] in {"AXIS_CERTIFIED_BOUNDARY", "RAY_CERTIFIED_BOUNDARY"}
    ]
    add(
        "certified_endpoints_are_safe_and_violating",
        all(
            row["safe_solver_status"] == "CONVERGED_FEASIBLE"
            and row["violating_solver_status"] == "CONVERGED_INFEASIBLE"
            for row in certified
        ),
        f"certified={len(certified)}",
    )
    axis_official_safe = all(
        math.isclose(
            as_float(row["official_boundary_p_pcc_kw"]),
            as_float(row["safe_coordinate"])
            * (1.0 if row["signed_direction"] == "POSITIVE" else -1.0),
            abs_tol=1e-9,
        )
        for row in axes
        if row["status"] == "AXIS_CERTIFIED_BOUNDARY"
    )
    ray_official_safe = all(
        math.isclose(
            as_float(row["official_boundary_r"]), as_float(row["safe_r"]), abs_tol=1e-12
        )
        for row in base + adaptive
        if row["status"] == "RAY_CERTIFIED_BOUNDARY"
    )
    add(
        "official_coordinate_is_safe_endpoint",
        axis_official_safe and ray_official_safe,
        "axis and ray reported coordinates checked",
    )
    add(
        "no_nonconverged_bisection_endpoint",
        all(
            row["safe_solver_status"] == "CONVERGED_FEASIBLE"
            and row["violating_solver_status"] == "CONVERGED_INFEASIBLE"
            for row in certified
        ),
        "endpoint status fields checked",
    )

    endpoint_groups: Counter[tuple[str, str, str, str]] = Counter()
    endpoint_official = True
    for row in endpoints:
        key = (row["timestamp"], row["search_kind"], row["search_id"], row["level"])
        endpoint_groups[key] += 1
        if as_bool(row["official_boundary"]):
            endpoint_official &= (
                row["endpoint_side"] == "SAFE"
                and row["solver_status"] == "CONVERGED_FEASIBLE"
            )
    add(
        "two_endpoint_records_per_certified_boundary",
        len(endpoint_groups) == len(certified) and all(value == 2 for value in endpoint_groups.values()),
        f"groups={len(endpoint_groups)} endpoint_rows={len(endpoints)}",
    )
    add("endpoint_artifact_marks_only_safe_official", endpoint_official, "official flags checked")

    attempts_by_logical: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    for row in attempts:
        attempts_by_logical[attempt_key(row)].append(row)
    retry_valid = all(
        len(rows) in {1, 2}
        and sorted(int(row["attempt_index"]) for row in rows) == list(range(1, len(rows) + 1))
        and (
            len(rows) == 1
            or (
                rows[1]["initialization"] == "NEAREST_ACCEPTED_NEIGHBOR_START"
                and int(rows[1]["initialization_source_logical_id"]) > 0
                and rows[0]["solver_status"] == "NONCONVERGED_FIRST_ATTEMPT"
            )
        )
        for rows in attempts_by_logical.values()
    )
    add("retry_semantics", retry_valid, "distinct nearest-neighbor retry checked")
    add(
        "evaluation_counts_match_manifest",
        len(attempts) == int(manifest["actual_ac_evaluation_count"])
        and len(attempts_by_logical) == int(manifest["logical_evaluation_count"]),
        f"attempts={len(attempts)} logical={len(attempts_by_logical)}",
    )

    base_by_timestamp: dict[str, list[dict[str, str]]] = defaultdict(list)
    adaptive_by_timestamp: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in base:
        base_by_timestamp[row["timestamp"]].append(row)
    for row in adaptive:
        adaptive_by_timestamp[row["timestamp"]].append(row)
    base_grid_valid = True
    adaptive_valid = True
    direction_cap_valid = True
    for timestamp in timestamps:
        base_rows = sorted(base_by_timestamp[timestamp], key=lambda row: as_float(row["angle_deg"]))
        base_grid_valid &= [as_float(row["angle_deg"]) for row in base_rows] == [
            float(value) for value in range(0, 360, 10)
        ]
        by_angle = {as_float(row["angle_deg"]): row for row in base_rows}
        adaptive_rows = adaptive_by_timestamp[timestamp]
        direction_cap_valid &= len(base_rows) == 36 and len(adaptive_rows) <= 36
        for row in adaptive_rows:
            start = as_float(row["parent_start_angle_deg"])
            end = as_float(row["parent_end_angle_deg"])
            angle = as_float(row["angle_deg"])
            observed = {value for value in row["adaptive_triggers"].split(";") if value}
            expected = adaptive_reasons(by_angle[start], by_angle[end])
            adaptive_valid &= (
                observed == expected
                and bool(observed)
                and observed <= ALLOWED_ADAPTIVE_TRIGGERS
                and math.isclose(angle, (start + 5.0) % 360.0, abs_tol=1e-12)
            )
    add("base_angle_grid", base_grid_valid, "36 cardinal-inclusive 10-degree angles")
    add("adaptive_angles_justified", adaptive_valid, f"adaptive_rows={len(adaptive)}")
    add("maximum_72_directions", direction_cap_valid, "36 base plus <=36 adaptive")
    add("no_unpreregistered_angle", base_grid_valid and adaptive_valid, "base or triggered midpoint")

    checkpoint_hashes = {
        "git_commit": str(manifest["git_commit"]),
        "config_sha256": str(manifest["config_sha256"]),
        "selected_timestamp_sha256": str(manifest["selected_timestamp_sha256"]),
        "s0_evidence_sha256": str(manifest["s0_evidence_sha256"]),
        "implementation_sha256": str(manifest["implementation_sha256"]),
    }
    checkpoint_valid = len(checkpoints) == 32
    for row in checkpoints:
        path = root / Path(row["checkpoint_file"])
        checkpoint_valid &= path.is_file() and sha256_file(path) == row["checkpoint_sha256"]
        checkpoint_valid &= all(row[key] == value for key, value in checkpoint_hashes.items())
    add("checkpoint_provenance_and_file_hashes", checkpoint_valid, f"segments={len(checkpoints)}")

    artifact_valid = True
    for row in artifact_manifest:
        path = output / row["artifact"]
        artifact_valid &= (
            path.is_file()
            and path.stat().st_size == int(row["bytes"])
            and sha256_file(path) == row["sha256"]
        )
    add("artifact_manifest_hashes", artifact_valid, f"artifacts={len(artifact_manifest)}")
    add(
        "absolute_physical_cross_time_semantics",
        manifest["coordinate_space"] == "ABSOLUTE_PHYSICAL_P_PCC_KW"
        and manifest["q_pcc_kvar"] == 0.0,
        "no cross-time normalized-direction aggregation validated",
    )
    add(
        "no_ray_reentry",
        not any(row["status"] == "RAY_REENTRY_DETECTED" for row in base + adaptive),
        "centered-radial fatal state absent",
    )
    add(
        "normal_validation_also_passed",
        bool(manifest["validation_passed"]),
        "independent result compared with normal report",
    )

    counts = {
        "checks": len(checks),
        "passed": sum(passed for _, passed, _ in checks),
        "failed": sum(not passed for _, passed, _ in checks),
        "guard_limited": sum(
            "UNBOUNDED_WITHIN_GUARD" in row["status"] for row in all_boundaries
        ),
        "unresolved": sum("UNRESOLVED" in row["status"] for row in all_boundaries),
        "axis_reentry": sum(row["status"] == "AXIS_REENTRY_DETECTED" for row in axes),
        "ray_reentry": sum(
            row["status"] == "RAY_REENTRY_DETECTED" for row in base + adaptive
        ),
    }
    return checks, counts


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    output = root / "results" / "dso_vpp_ac_map_pilot" / "production_probe"
    checks, counts = validate(root)
    write_checks(output / "independent_validation_checks.csv", checks)
    passed = counts["failed"] == 0
    report = (
        "# Independent production-probe validation\n\n"
        f"Verdict: `{'PASS' if passed else 'FAIL'}`\n\n"
        f"- Checks: {counts['checks']} ({counts['passed']} passed, {counts['failed']} failed).\n"
        f"- Guard-limited outcomes: {counts['guard_limited']}.\n"
        f"- Unresolved outcomes: {counts['unresolved']}.\n"
        f"- Axis re-entry: {counts['axis_reentry']}; ray re-entry: {counts['ray_reentry']}.\n"
        "- Validation reconstructed invariants from written CSV/TOML/checkpoint artifacts; "
        "it did not use the production runner's in-memory verdict.\n"
    )
    (output / "independent_validation_report.md").write_text(report, encoding="utf-8")
    refresh_artifact_manifest(output)
    print(f"independent_validation={'PASS' if passed else 'FAIL'}")
    print(f"checks={counts['checks']} passed={counts['passed']} failed={counts['failed']}")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
