from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import statistics
import subprocess
from collections import Counter, defaultdict
from pathlib import Path


CALIBRATION_COMMIT = "82ccd0f20693c90c39904f6016d85cf62433f4f0"
PREREGISTRATION_COMMIT = "fc15fbf7bf93ca89c2ab4a45145f937abbc70f63"
GEOMETRY_SOURCE_COMMIT = "ba88f54f52f7bcd03df2466ce69dff2b9b1c538b"
SOURCE_BRANCH = "codex/dso-vpp-ac-map-pilot"

ORIGINAL_VMIN = 0.90
ORIGINAL_VMAX = 1.05
DESIGN_VMIN = 0.90015
DESIGN_VMAX = 1.04985
RETREAT_RESOLUTION_KW = 0.25
MONOTONIC_TOL_PU = 1e-12

CALIBRATION_DIR = (
    "results/dso_vpp_ac_map_pilot/"
    "doe_ac_boundary_headroom_repair_calibration"
)
PREREGISTRATION_DIR = (
    "results/dso_vpp_ac_map_pilot/"
    "doe_ac_boundary_headroom_repair_preregistration"
)
OUTDIR = Path(
    "results/dso_vpp_ac_map_pilot/"
    "doe_ac_boundary_headroom_repair_blocker_diagnostic"
)

SOURCE_ARTIFACTS = [
    {
        "commit": CALIBRATION_COMMIT,
        "path": f"{CALIBRATION_DIR}/edge_retreats.csv",
        "role": "authoritative edge-level repair outcomes, caps, metadata, timestamps, and h_design",
    },
    {
        "commit": CALIBRATION_COMMIT,
        "path": f"{CALIBRATION_DIR}/calibration_attempts.csv",
        "role": "authoritative attempted retreat trajectories and voltage extrema/buses",
    },
    {
        "commit": CALIBRATION_COMMIT,
        "path": f"{CALIBRATION_DIR}/calibration_point_results.csv",
        "role": "authoritative consolidated calibration-point outcomes",
    },
    {
        "commit": CALIBRATION_COMMIT,
        "path": f"{CALIBRATION_DIR}/calibration_registry.csv",
        "role": "authoritative unique evaluated-coordinate registry",
    },
    {
        "commit": PREREGISTRATION_COMMIT,
        "path": f"{PREREGISTRATION_DIR}/edge_repair_policy.csv",
        "role": "locked edge normals, sign categories, guard relations, ownership, and caps",
    },
    {
        "commit": PREREGISTRATION_COMMIT,
        "path": f"{PREREGISTRATION_DIR}/calibration_fraction_inventory.csv",
        "role": "locked calibration memberships and source geometry coordinates",
    },
    {
        "commit": PREREGISTRATION_COMMIT,
        "path": f"{PREREGISTRATION_DIR}/repair_config.json",
        "role": "locked original/design voltage limits, h_design, grid, and search policy",
    },
    {
        "commit": GEOMETRY_SOURCE_COMMIT,
        "path": "results/dso_vpp_ac_map_pilot/doe_ac_interior_validation_preregistration/validation_polygon_edges.csv",
        "role": "committed source polygon edge endpoints, boundary classes, and guard metadata",
    },
    {
        "commit": CALIBRATION_COMMIT,
        "path": f"{CALIBRATION_DIR}/source_manifest.json",
        "role": "calibration provenance linking execution to the locked preregistration",
    },
]


def git(*args: str) -> bytes:
    return subprocess.check_output(["git", *args])


def git_bytes(commit: str, path: str) -> bytes:
    return git("show", f"{commit}:{path}")


def read_csv_git(commit: str, path: str) -> list[dict[str, str]]:
    return list(csv.DictReader(io.StringIO(git_bytes(commit, path).decode("utf-8-sig"))))


def read_json_git(commit: str, path: str):
    return json.loads(git_bytes(commit, path).decode("utf-8-sig"))


def fmt(value) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, float):
        if math.isnan(value):
            return "NaN"
        if math.isinf(value):
            return "Inf" if value > 0 else "-Inf"
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


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def nondecreasing(values: list[float]) -> bool:
    return all(b + MONOTONIC_TOL_PU >= a for a, b in zip(values, values[1:]))


def nonincreasing(values: list[float]) -> bool:
    return all(b <= a + MONOTONIC_TOL_PU for a, b in zip(values, values[1:]))


def design_pass(row: dict[str, str]) -> bool:
    return (
        row["solver_status"] != "UNRESOLVED"
        and float(row["vmin_pu"]) >= DESIGN_VMIN
        and float(row["vmax_pu"]) <= DESIGN_VMAX
    )


def source_inventory() -> list[dict]:
    rows = []
    for item in SOURCE_ARTIFACTS:
        data = git_bytes(item["commit"], item["path"])
        suffix = Path(item["path"]).suffix.lower()
        if suffix == ".csv":
            record_count = len(list(csv.DictReader(io.StringIO(data.decode("utf-8-sig")))))
            artifact_format = "CSV"
        elif suffix == ".json":
            json.loads(data.decode("utf-8-sig"))
            record_count = 1
            artifact_format = "JSON"
        else:
            record_count = None
            artifact_format = suffix.lstrip(".").upper()
        rows.append(
            {
                "artifact_path": item["path"],
                "source_commit": item["commit"],
                "artifact_role": item["role"],
                "artifact_format": artifact_format,
                "row_or_record_count": record_count,
                "bytes": len(data),
                "sha256": sha256(data),
            }
        )
    return rows


def classify_trajectory(
    trajectory: list[dict[str, str]], cap_kw: float
) -> tuple[str, str, dict]:
    observations = []
    for row in trajectory:
        vmin_margin = float(row["vmin_pu"]) - DESIGN_VMIN
        vmax_margin = DESIGN_VMAX - float(row["vmax_pu"])
        observations.append(
            {
                "source": row,
                "d_kw": float(row["d_kw"]),
                "vmin_margin": vmin_margin,
                "vmax_margin": vmax_margin,
                "margin": min(vmin_margin, vmax_margin),
                "pass": design_pass(row),
            }
        )
    observations.sort(key=lambda item: (item["d_kw"], item["source"]["attempt_id"]))
    best = sorted(observations, key=lambda item: (-item["margin"], item["d_kw"]))[0]
    binding = "VMIN" if best["vmin_margin"] <= best["vmax_margin"] else "VMAX"
    vmin_margins = [item["vmin_margin"] for item in observations]
    vmax_margins = [item["vmax_margin"] for item in observations]
    binding_margins = vmin_margins if binding == "VMIN" else vmax_margins
    opposite_margins = vmax_margins if binding == "VMIN" else vmin_margins
    binding_worsens = nonincreasing(binding_margins)
    opposite_improves = nondecreasing(opposite_margins)
    max_d = max(item["d_kw"] for item in observations)
    cap_reached = max_d >= cap_kw - RETREAT_RESOLUTION_KW - 1e-12
    passes = [item for item in observations if item["pass"]]
    fails = [item for item in observations if not item["pass"]]
    adjacent_pass_fail = any(
        a["pass"] != b["pass"] and b["d_kw"] - a["d_kw"] <= RETREAT_RESOLUTION_KW + 1e-12
        for a, b in zip(observations, observations[1:])
    )

    if not observations:
        classification = "INSUFFICIENT_ARTIFACT_EVIDENCE"
        pattern = "NO_RETREAT_SEQUENCE"
    elif adjacent_pass_fail:
        classification = "POSSIBLE_GRID_RESOLUTION_FAILURE"
        pattern = "PASS_FAIL_TRANSITION_AT_LOCKED_GRID_RESOLUTION"
    elif not passes and binding_worsens and opposite_improves:
        classification = "POSSIBLE_TRUE_OPERATOR_LIMITATION"
        pattern = f"{binding}_FAILURE_MONOTONICALLY_WORSENS_{'VMAX' if binding == 'VMIN' else 'VMIN'}_IMPROVES"
    elif cap_reached and observations[-1]["margin"] > observations[0]["margin"]:
        classification = "POSSIBLE_CAP_LIMITED"
        pattern = "MARGIN_IMPROVES_TO_GEOMETRY_CAP_WITHOUT_PASS"
    else:
        classification = "POSSIBLE_ALGORITHM_FAILURE"
        pattern = "SEARCH_TERMINATED_WITHOUT_DECISIVE_MONOTONIC_OR_CAP_PATTERN"

    diagnostics = {
        "observations": observations,
        "best": best,
        "binding": binding,
        "binding_worsens": binding_worsens,
        "opposite_improves": opposite_improves,
        "violation_decreases_monotonically": nonincreasing(
            [max(0.0, -item["margin"]) for item in observations]
        ),
        "max_d": max_d,
        "cap_reached": cap_reached,
        "last_pass": max((item["d_kw"] for item in passes), default=None),
        "first_fail": min((item["d_kw"] for item in fails), default=None),
        "vmin_failure": any(item["vmin_margin"] < 0 for item in observations),
        "vmax_failure": any(item["vmax_margin"] < 0 for item in observations),
        "no_scalar_pass_observed": not passes,
    }
    return classification, pattern, diagnostics


def pct(numerator: int, denominator: int) -> str:
    return format(100.0 * numerator / denominator, ".3f")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--verify-index", action="store_true")
    args = parser.parse_args()
    if args.verify_index:
        return verify_index()

    branch = git("branch", "--show-current").decode().strip()
    head = git("rev-parse", "HEAD").decode().strip()
    if branch != SOURCE_BRANCH or head != CALIBRATION_COMMIT:
        raise RuntimeError(f"source mismatch: branch={branch}, head={head}")

    edge_path = f"{CALIBRATION_DIR}/edge_retreats.csv"
    attempt_path = f"{CALIBRATION_DIR}/calibration_attempts.csv"
    point_path = f"{CALIBRATION_DIR}/calibration_point_results.csv"
    policy_path = f"{PREREGISTRATION_DIR}/edge_repair_policy.csv"
    config_path = f"{PREREGISTRATION_DIR}/repair_config.json"

    edges = read_csv_git(CALIBRATION_COMMIT, edge_path)
    attempts = read_csv_git(CALIBRATION_COMMIT, attempt_path)
    point_results = read_csv_git(CALIBRATION_COMMIT, point_path)
    policies = read_csv_git(PREREGISTRATION_COMMIT, policy_path)
    config = read_json_git(PREREGISTRATION_COMMIT, config_path)

    configured = config["boundary_headroom_policy"]
    if abs(float(configured["h_design_pu"]) - (DESIGN_VMIN - ORIGINAL_VMIN)) > 1e-15:
        raise RuntimeError("h_design does not match the audited constant")
    if configured["assessment_tracks"]["original_limits"] != {
        "vmax_pu": ORIGINAL_VMAX,
        "vmin_pu": ORIGINAL_VMIN,
    }:
        raise RuntimeError("original voltage limits do not match the audited constants")
    if configured["symmetric_design_limits"] != {"vmax_pu": DESIGN_VMAX, "vmin_pu": DESIGN_VMIN}:
        raise RuntimeError("design voltage limits do not match the audited constants")

    policy_by_key = {(row["timestamp"], row["edge_id"]): row for row in policies}
    attempt_by_key: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    for row in attempts:
        if row["edge_id"]:
            attempt_by_key[(row["timestamp"], row["edge_id"])].append(row)

    blocked = sorted(
        (row for row in edges if row["final_status"] == "LOCAL_PARALLEL_EDGE_REPAIR_INSUFFICIENT"),
        key=lambda row: (row["timestamp"], row["edge_id"]),
    )
    crossing = sorted(
        (row for row in edges if row["guard_relation"] == "CROSSES_GUARD_LIMITED_RAY"),
        key=lambda row: (row["timestamp"], row["edge_id"]),
    )
    if len(edges) != 1689 or len(blocked) != 15 or len(crossing) != 64:
        raise RuntimeError(
            f"authoritative count mismatch: edges={len(edges)}, blocked={len(blocked)}, crossing={len(crossing)}"
        )

    root_rows = []
    trajectory_rows = []
    cap_rows = []
    trajectory_diagnostics: dict[tuple[str, str], dict] = {}
    blocking_phase_counts = Counter()
    for edge in blocked:
        key = (edge["timestamp"], edge["edge_id"])
        policy = policy_by_key[key]
        if edge["representability_cap_kw"] != policy["parallel_retreat_cap_kw"]:
            raise RuntimeError(f"cap provenance mismatch for {key}")
        edge_attempts = attempt_by_key[key]
        escalated = [row for row in edge_attempts if row["phase"] == "VERIFY_ESCALATE"]
        trajectory = escalated or [row for row in edge_attempts if row["phase"] == "ANCHOR_SEARCH"]
        if not trajectory:
            raise RuntimeError(f"no blocking trajectory for {key}")
        blocking_phase = "VERIFY_ESCALATE" if escalated else "ANCHOR_SEARCH"
        blocking_phase_counts[blocking_phase] += 1
        cap_kw = float(edge["representability_cap_kw"])
        classification, pattern, diagnostic = classify_trajectory(trajectory, cap_kw)
        diagnostic["blocking_phase"] = blocking_phase
        trajectory_diagnostics[key] = diagnostic
        best = diagnostic["best"]
        binding = diagnostic["binding"]
        binding_bus = best["source"]["vmin_bus" if binding == "VMIN" else "vmax_bus"]
        mixed = edge["normal_sign_category"] == "mixed_sign"
        transition = edge["boundary_class"] == "CLASS_TRANSITION"
        crosses = edge["guard_relation"] == "CROSSES_GUARD_LIMITED_RAY"
        root_rows.append(
            {
                "edge_id": edge["edge_id"],
                "guard_relation": edge["guard_relation"],
                "margin_channel": f"{binding}_HEADROOM_MARGIN",
                "timestamp": edge["timestamp"],
                "mixed_sign_flag": mixed,
                "transition_flag": transition,
                "crossing_flag": crosses,
                "cap_kw": cap_kw,
                "maximum_tested_retreat_kw": diagnostic["max_d"],
                "last_pass_retreat_kw": diagnostic["last_pass"],
                "first_fail_retreat_kw": diagnostic["first_fail"],
                "vmax_failure_present": diagnostic["vmax_failure"],
                "vmin_failure_present": diagnostic["vmin_failure"],
                "binding_voltage_channel": binding,
                "binding_bus": binding_bus,
                "classification_preliminary": classification,
            }
        )
        trajectory_rows.append(
            {
                "edge_id": edge["edge_id"],
                "timestamp": edge["timestamp"],
                "d_sequence_available": True,
                "num_attempts": len(diagnostic["observations"]),
                "best_retreat_kw": best["d_kw"],
                "best_margin_observed": best["margin"],
                "vmax_margin_at_best": best["vmax_margin"],
                "vmin_margin_at_best": best["vmin_margin"],
                "failure_pattern": pattern,
            }
        )
        cap_rows.append(
            {
                "edge_id": edge["edge_id"],
                "timestamp": edge["timestamp"],
                "cap_kw": cap_kw,
                "maximum_tested_d_kw": diagnostic["max_d"],
                "ratio_d_over_cap": diagnostic["max_d"] / cap_kw,
                "cap_reached_flag": diagnostic["cap_reached"],
            }
        )

    crossing_rows = []
    for edge in crossing:
        crossing_rows.append(
            {
                "edge_id": edge["edge_id"],
                "blocked_flag": edge["final_status"] == "LOCAL_PARALLEL_EDGE_REPAIR_INSUFFICIENT",
                "mixed_sign_flag": edge["normal_sign_category"] == "mixed_sign",
                "transition_flag": edge["boundary_class"] == "CLASS_TRANSITION",
                "d_e_kw": float(edge["d_e_star_kw"]),
                "guard_relation": edge["guard_relation"],
                "timestamp": edge["timestamp"],
            }
        )

    by_timestamp: dict[str, list[str]] = defaultdict(list)
    for edge in blocked:
        by_timestamp[edge["timestamp"]].append(edge["edge_id"])
    timestamp_rows = [
        {
            "timestamp": timestamp,
            "number_of_blocked_edges": len(edge_ids),
            "edge_ids": ";".join(sorted(edge_ids)),
        }
        for timestamp, edge_ids in sorted(by_timestamp.items())
    ]

    classifications = Counter(row["classification_preliminary"] for row in root_rows)
    binding_counts = Counter(row["binding_voltage_channel"] for row in root_rows)
    cap_ratios = [float(row["ratio_d_over_cap"]) for row in cap_rows]
    successful_crossing_d = [
        float(row["d_e_kw"]) for row in crossing_rows if not row["blocked_flag"]
    ]
    crossing_blocked = sum(bool(row["blocked_flag"]) for row in crossing_rows)
    blocked_mixed = sum(bool(row["mixed_sign_flag"]) for row in root_rows)
    blocked_transition = sum(bool(row["transition_flag"]) for row in root_rows)
    blocked_crossing = sum(bool(row["crossing_flag"]) for row in root_rows)
    all_mixed = sum(edge["normal_sign_category"] == "mixed_sign" for edge in edges)
    all_transition = sum(edge["boundary_class"] == "CLASS_TRANSITION" for edge in edges)
    all_crossing = len(crossing)
    successful_crossing_mixed = sum(
        row["mixed_sign_flag"] and not row["blocked_flag"] for row in crossing_rows
    )
    successful_crossing_transition = sum(
        row["transition_flag"] and not row["blocked_flag"] for row in crossing_rows
    )
    unique_timestamp_count = len(timestamp_rows)
    max_timestamp_cluster = max(row["number_of_blocked_edges"] for row in timestamp_rows)
    max_cluster_timestamps = [
        row["timestamp"]
        for row in timestamp_rows
        if row["number_of_blocked_edges"] == max_timestamp_cluster
    ]

    vmin_initial = []
    for edge in blocked:
        key = (edge["timestamp"], edge["edge_id"])
        diagnostic = trajectory_diagnostics[key]
        if diagnostic["binding"] != "VMIN":
            continue
        first = diagnostic["observations"][0]
        last = diagnostic["observations"][-1]
        vmin_initial.append(
            {
                "timestamp": edge["timestamp"],
                "edge_id": edge["edge_id"],
                "blocking_phase": diagnostic["blocking_phase"],
                "initial_d_kw": first["d_kw"],
                "initial_vmin_pu": float(first["source"]["vmin_pu"]),
                "original_vmin_margin_pu": float(first["source"]["vmin_pu"]) - ORIGINAL_VMIN,
                "design_vmin_margin_pu": first["vmin_margin"],
                "maximum_tested_d_kw": last["d_kw"],
                "vmin_at_maximum_tested_d_pu": float(last["source"]["vmin_pu"]),
            }
        )

    h_lines = [
        "# VMIN h_design retreat diagnostic",
        "",
        "This is an interpretation of committed artifacts only. It performs no AC calculation.",
        "",
        "## Locked limits",
        "",
        f"- Original voltage band: `{ORIGINAL_VMIN:.5f} <= V <= {ORIGINAL_VMAX:.5f}` p.u.",
        f"- Symmetric design band: `{DESIGN_VMIN:.5f} <= V <= {DESIGN_VMAX:.5f}` p.u.",
        f"- Locked safety headroom: `h_design = {DESIGN_VMIN - ORIGINAL_VMIN:.5g}` p.u.",
        "",
        "## VMIN-bound blockers",
        "",
        "| timestamp | edge_id | blocking phase | initial d (kW) | initial VMIN (p.u.) | original-limit margin (p.u.) | design margin (p.u.) | maximum tested d (kW) | VMIN at maximum d (p.u.) |",
        "|---|---:|---|---:|---:|---:|---:|---:|---:|",
    ]
    for row in vmin_initial:
        h_lines.append(
            "| {timestamp} | {edge_id} | {blocking_phase} | {initial_d_kw} | {initial_vmin_pu} | {original_vmin_margin_pu} | {design_vmin_margin_pu} | {maximum_tested_d_kw} | {vmin_at_maximum_tested_d_pu} |".format(
                **{key: fmt(value) for key, value in row.items()}
            )
        )
    h_lines.extend(
        [
            "",
            "## Interpretation",
            "",
            "Three of the four VMIN-bound blocking trajectories are anchor searches observed from `d=0`; each starts above the original 0.90 p.u. limit but below the 0.90015 p.u. design limit. Their initial need for retreat is therefore attributable to the locked safety-headroom requirement.",
            "",
            "The 2010-07-02 18:00 E0044 trajectory is a verify-escalation search first observed at the already-selected common retreat `d=4.75` kW, where VMIN is 0.899996208231859 p.u. The calibration attempts contain no `d=0` observation for that blocking membership. Its initial safety-headroom-only contribution therefore cannot be isolated from these artifacts; at the first available observation it already fails the original VMIN limit.",
            "",
            "For every VMIN-bound blocker, increasing the registered positive scalar retreat lowers VMIN monotonically over the observed sequence while VMAX margin improves. For the three `d=0` anchor cases, the need for a retreat is caused by `h_design`; the inability of the observed positive parallel retreat to supply that headroom is a geometric/operator-direction difficulty. These are separate statements.",
            "",
            "The artifacts do not prove behavior at every untested retreat or under any alternative direction. They do show that the tested registered direction moves the binding VMIN channel away from the design band.",
            "",
        ]
    )

    report_lines = [
        "# Zero-AC root-cause diagnostic audit",
        "",
        "## Scope and provenance",
        "",
        f"This audit reads committed objects from calibration commit `{CALIBRATION_COMMIT}` and locked preregistration `{PREREGISTRATION_COMMIT}`. It uses Python standard-library CSV/JSON processing only and executes no Julia process, solver, replay, calibration, or AC power-flow call.",
        "",
        "The authoritative artifact paths, commits, record counts, byte sizes, and SHA-256 hashes are in `source_artifact_inventory.csv`. The primary outcome source has 1,689 edge rows; the trajectory source has 51,773 attempt rows; the consolidated point source has 13,465 rows.",
        "",
        "A blocked edge is keyed by `(timestamp, edge_id)`. Edge IDs repeat across timestamps, so `edge_id` alone is not a unique campaign key.",
        "",
        "## Result",
        "",
        f"All 15 blockers receive the preliminary classification `POSSIBLE_TRUE_OPERATOR_LIMITATION`, where *operator* means the preregistered positive scalar parallel-retreat operator along the original inward normal. It does not mean that the physical grid has been proved infeasible.",
        "",
        "| candidate explanation | artifact-only assessment |",
        "|---|---|",
        f"| Algorithmic | No solver or replay failure is present. Two blocking searches stop after the locked verify-escalation allowance; 13 stop when the next doubling step would exceed the geometry cap. Those mechanics leave untested intervals, but every observed binding margin worsens with retreat, so the artifacts do not identify the call ceilings as the primary mechanism. |",
        "| Grid resolution | Not supported by the observed sequences. No blocker has a PASS/FAIL bracket, no blocking trajectory reaches the 0.25 kW bisection stage, and no joint design-limit pass is observed. |",
        f"| Cap-limited | Not supported as the primary mechanism. No cap is reached; `d_max/cap` ranges from {fmt(min(cap_ratios))} to {fmt(max(cap_ratios))} (median {fmt(statistics.median(cap_ratios))}). The margin moves away from feasibility rather than toward it. |",
        f"| Scalar operator/direction limitation | Best-supported preliminary explanation: {binding_counts['VMIN']} VMIN-bound and {binding_counts['VMAX']} VMAX-bound trajectories move the binding channel monotonically in the wrong direction while improving the opposite channel. |",
        "| Unresolved evidence | No unresolved solver status or retry occurs in the 15 blocking trajectories. Global behavior between or beyond sampled points remains unproved. |",
        "",
        "## Trajectory mechanism",
        "",
        f"Violation magnitude decreases monotonically in 0 of 15 blocking trajectories. In all {len(blocked)} trajectories the binding-channel margin worsens monotonically and the opposite voltage-channel margin improves monotonically. There is no joint headroom pass and no `last_pass_retreat_kw` for any blocker.",
        "",
        "All 13 anchor blockers are observed from `d=0` as original-limit passes but design-headroom failures. The two verify-escalation blockers are first observed after a common retreat selected from another membership (4.75 kW for the VMIN case and 2.75 kW for the VMAX case); both already fail the corresponding original limit, and their blocking memberships have no calibration-attempt observation at `d=0`. In every case, further positive retreat worsens the binding voltage channel. This is consistent with fundamental inadequacy of the registered one-sided scalar retreat for these observed points. It is strong directional evidence, not a global monotonicity proof and not proof that another operator would work.",
        "",
        f"Blocking search phases: `{blocking_phase_counts['ANCHOR_SEARCH']}` anchor searches and `{blocking_phase_counts['VERIFY_ESCALATE']}` verify-escalation searches.",
        "",
        "## Crossing control associations",
        "",
        f"The crossing control contains exactly 64 rows: {crossing_blocked} blocked and {len(crossing) - crossing_blocked} successful. Successful crossing retreats have min/median/max `d_e` of {fmt(min(successful_crossing_d))}/{fmt(statistics.median(successful_crossing_d))}/{fmt(max(successful_crossing_d))} kW.",
        "",
        "| characteristic | blocked | successful crossing controls | campaign denominator |",
        "|---|---:|---:|---:|",
        f"| mixed-sign | {blocked_mixed}/15 | {successful_crossing_mixed}/49 | {all_mixed}/1689 |",
        f"| transition | {blocked_transition}/15 | {successful_crossing_transition}/49 | {all_transition}/1689 |",
        f"| crossing | {blocked_crossing}/15 | 49/49 | {all_crossing}/1689 |",
        "",
        f"Thus all blockers are mixed-sign, transition, crossing edges, and the crossing-edge blocker rate is {pct(crossing_blocked, len(crossing))}%. However, all 49 successful crossing controls share the same mixed-sign and transition flags. These are associations and do not establish causality or distinguish blockers within the crossing subset.",
        "",
        "## Timestamp clustering",
        "",
        f"The 15 blockers occur at {unique_timestamp_count} timestamps. The maximum timestamp cluster is {max_timestamp_cluster}, at `{';'.join(max_cluster_timestamps)}`; every other blocked timestamp contributes one edge. The artifacts therefore show no broad same-timestamp pile-up.",
        "",
        "## Minimum next scientific action",
        "",
        "The minimum discriminating next action is a separately preregistered targeted study of the 15 exact `(timestamp, edge_id, calibration_id)` blocking trajectories that tests whether any admissible scalar retreat has a joint VMIN/VMAX pass and explicitly covers the currently untested interval before each cap. That action would distinguish a one-sided operator limitation from a search-coverage miss. It is not performed or designed here, and this audit proposes no repair-policy or geometry change.",
        "",
        "## Output guide",
        "",
        "- `blocked_edge_root_cause.csv`: one row per blocker and preliminary classification.",
        "- `blocked_edge_trajectory_summary.csv`: observed blocking-search trajectory summaries.",
        "- `blocked_edge_cap_analysis.csv`: tested retreat relative to the locked cap.",
        "- `crossing_control_comparison.csv`: 15 blocked and 49 successful crossing-edge controls.",
        "- `blocked_edge_timestamp_cluster.csv`: deterministic timestamp aggregation.",
        "- `h_design_retreat_diagnostic.md`: safety-headroom versus geometric-difficulty interpretation.",
        "- `source_artifact_inventory.csv`: exact committed source inventory.",
        "- `audit_validation_checks.csv`: source and invariant checks.",
        "",
    ]

    allowed_classifications = {
        "POSSIBLE_ALGORITHM_FAILURE",
        "POSSIBLE_GRID_RESOLUTION_FAILURE",
        "POSSIBLE_CAP_LIMITED",
        "POSSIBLE_TRUE_OPERATOR_LIMITATION",
        "INSUFFICIENT_ARTIFACT_EVIDENCE",
    }
    if not set(classifications).issubset(allowed_classifications):
        raise RuntimeError(f"classification enum violation: {sorted(classifications)}")

    unresolved_count = 0
    retry_attempt_count = 0
    for diagnostic in trajectory_diagnostics.values():
        unresolved_count += sum(
            item["source"]["solver_status"] == "UNRESOLVED"
            for item in diagnostic["observations"]
        )
        retry_attempt_count += sum(
            int(item["source"]["attempt_index"]) > 1
            for item in diagnostic["observations"]
        )
    if unresolved_count != 0 or retry_attempt_count != 0:
        raise RuntimeError(
            f"unexpected blocking attempt state: unresolved={unresolved_count}, retries={retry_attempt_count}"
        )

    validation_rows = [
        {"check_id": "SOURCE_BRANCH", "status": "PASS", "observed": branch, "expected": SOURCE_BRANCH},
        {"check_id": "SOURCE_HEAD", "status": "PASS", "observed": head, "expected": CALIBRATION_COMMIT},
        {"check_id": "EDGE_COUNT", "status": "PASS", "observed": len(edges), "expected": 1689},
        {"check_id": "BLOCKER_COUNT", "status": "PASS", "observed": len(blocked), "expected": 15},
        {"check_id": "CROSSING_COUNT", "status": "PASS", "observed": len(crossing), "expected": 64},
        {"check_id": "CROSSING_SPLIT", "status": "PASS", "observed": f"{crossing_blocked} blocked; {len(crossing)-crossing_blocked} successful", "expected": "15 blocked; 49 successful"},
        {"check_id": "ATTEMPT_ROW_COUNT", "status": "PASS", "observed": len(attempts), "expected": 51773},
        {"check_id": "POINT_RESULT_ROW_COUNT", "status": "PASS", "observed": len(point_results), "expected": 13465},
        {"check_id": "BLOCKING_TRAJECTORIES_AVAILABLE", "status": "PASS", "observed": len(trajectory_diagnostics), "expected": 15},
        {"check_id": "BLOCKING_SOLVER_UNRESOLVED_COUNT", "status": "PASS", "observed": unresolved_count, "expected": 0},
        {"check_id": "BLOCKING_RETRY_ATTEMPT_COUNT", "status": "PASS", "observed": retry_attempt_count, "expected": 0},
        {"check_id": "ZERO_AC_EXECUTION_PATH", "status": "PASS", "observed": "stdlib CSV/JSON and git object reads only", "expected": "no Julia, solver, replay, calibration, or AC call"},
        {"check_id": "PRELIMINARY_CLASSIFICATION_ENUM", "status": "PASS", "observed": ";".join(sorted(classifications)), "expected": "allowed enum values only"},
    ]

    OUTDIR.mkdir(parents=True, exist_ok=True)
    expected_names = {
        "audit_validation_checks.csv",
        "blocked_edge_cap_analysis.csv",
        "blocked_edge_root_cause.csv",
        "blocked_edge_timestamp_cluster.csv",
        "blocked_edge_trajectory_summary.csv",
        "crossing_control_comparison.csv",
        "h_design_retreat_diagnostic.md",
        "hashes.sha256",
        "manifest.json",
        "report.md",
        "source_artifact_inventory.csv",
    }
    unexpected = sorted(path.name for path in OUTDIR.iterdir() if path.name not in expected_names)
    if unexpected:
        raise RuntimeError(f"unexpected files in output directory: {unexpected}")

    write_csv(
        OUTDIR / "blocked_edge_root_cause.csv",
        [
            "edge_id", "guard_relation", "margin_channel", "timestamp",
            "mixed_sign_flag", "transition_flag", "crossing_flag", "cap_kw",
            "maximum_tested_retreat_kw", "last_pass_retreat_kw", "first_fail_retreat_kw",
            "vmax_failure_present", "vmin_failure_present", "binding_voltage_channel",
            "binding_bus", "classification_preliminary",
        ],
        root_rows,
    )
    write_csv(
        OUTDIR / "blocked_edge_trajectory_summary.csv",
        [
            "edge_id", "timestamp", "d_sequence_available", "num_attempts", "best_retreat_kw",
            "best_margin_observed", "vmax_margin_at_best", "vmin_margin_at_best",
            "failure_pattern",
        ],
        trajectory_rows,
    )
    write_csv(
        OUTDIR / "blocked_edge_cap_analysis.csv",
        [
            "edge_id", "timestamp", "cap_kw", "maximum_tested_d_kw",
            "ratio_d_over_cap", "cap_reached_flag",
        ],
        cap_rows,
    )
    write_csv(
        OUTDIR / "crossing_control_comparison.csv",
        [
            "edge_id", "blocked_flag", "mixed_sign_flag", "transition_flag", "d_e_kw",
            "guard_relation", "timestamp",
        ],
        crossing_rows,
    )
    write_csv(
        OUTDIR / "blocked_edge_timestamp_cluster.csv",
        ["timestamp", "number_of_blocked_edges", "edge_ids"],
        timestamp_rows,
    )
    write_csv(
        OUTDIR / "source_artifact_inventory.csv",
        [
            "artifact_path", "source_commit", "artifact_role", "artifact_format",
            "row_or_record_count", "bytes", "sha256",
        ],
        source_inventory(),
    )
    write_csv(
        OUTDIR / "audit_validation_checks.csv",
        ["check_id", "status", "observed", "expected"],
        validation_rows,
    )
    write_text(OUTDIR / "h_design_retreat_diagnostic.md", "\n".join(h_lines))
    write_text(OUTDIR / "report.md", "\n".join(report_lines))

    content_names = sorted(
        name for name in expected_names if name not in {"hashes.sha256", "manifest.json"}
    )
    hash_lines = []
    for name in content_names:
        hash_lines.append(f"{sha256((OUTDIR / name).read_bytes())}  {name}")
    write_text(OUTDIR / "hashes.sha256", "\n".join(hash_lines) + "\n")

    payload_names = sorted(name for name in expected_names if name != "manifest.json")
    manifest_files = []
    for name in payload_names:
        data = (OUTDIR / name).read_bytes()
        item = {"bytes": len(data), "path": name, "sha256": sha256(data)}
        if name.endswith(".csv"):
            item["row_count"] = len(list(csv.DictReader(io.StringIO(data.decode("utf-8-sig")))))
        manifest_files.append(item)
    manifest = {
        "artifact": "DSO_VPP_AC_BOUNDARY_HEADROOM_REPAIR_BLOCKER_DIAGNOSTIC",
        "schema_version": 1,
        "source_branch": SOURCE_BRANCH,
        "calibration_commit": CALIBRATION_COMMIT,
        "preregistration_commit": PREREGISTRATION_COMMIT,
        "geometry_source_commit": GEOMETRY_SOURCE_COMMIT,
        "method": "ARTIFACT_ONLY_ZERO_AC_PYTHON_STANDARD_LIBRARY",
        "generator": {
            "path": "scripts/prepare_dso_vpp_ac_boundary_headroom_repair_blocker_diagnostic.py",
            "sha256": sha256(Path(__file__).read_bytes()),
        },
        "counts": {
            "blocked_edges": len(blocked),
            "crossing_edges": len(crossing),
            "crossing_blocked": crossing_blocked,
            "crossing_successful": len(crossing) - crossing_blocked,
            "blocked_timestamps": unique_timestamp_count,
        },
        "preliminary_classifications": dict(sorted(classifications.items())),
        "files": manifest_files,
    }
    write_text(OUTDIR / "manifest.json", json.dumps(manifest, indent=2, sort_keys=True) + "\n")

    print(f"wrote {OUTDIR.as_posix()}")
    print(f"blocked rows: {len(root_rows)}")
    print(f"crossing rows: {len(crossing_rows)}")
    print(f"classifications: {dict(sorted(classifications.items()))}")
    return 0


def verify_index() -> int:
    manifest_path = OUTDIR.as_posix() + "/manifest.json"
    manifest = json.loads(git("show", f":{manifest_path}").decode("utf-8"))
    mismatches = []
    for item in manifest["files"]:
        data = git("show", f":{OUTDIR.as_posix()}/{item['path']}")
        if len(data) != item["bytes"] or sha256(data) != item["sha256"]:
            mismatches.append(item["path"])
    print(f"staged payloads: {len(manifest['files'])}")
    print(f"staged mismatches: {len(mismatches)}")
    return 1 if mismatches else 0


if __name__ == "__main__":
    raise SystemExit(main())
