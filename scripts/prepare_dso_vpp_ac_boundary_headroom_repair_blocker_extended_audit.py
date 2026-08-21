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


AUDIT_BASE_COMMIT = "32fc5697fdeb5a2a2fb0395d09e56db7c47250e2"
CALIBRATION_COMMIT = "82ccd0f20693c90c39904f6016d85cf62433f4f0"
PREREGISTRATION_COMMIT = "fc15fbf7bf93ca89c2ab4a45145f937abbc70f63"
GEOMETRY_SOURCE_COMMIT = "ba88f54f52f7bcd03df2466ce69dff2b9b1c538b"
SOURCE_BRANCH = "codex/dso-vpp-ac-map-pilot"
METHOD = "ARTIFACT_ONLY_ZERO_AC_PYTHON_STANDARD_LIBRARY"

ORIGINAL_VMIN = 0.90
ORIGINAL_VMAX = 1.05
DESIGN_VMIN = 0.90015
DESIGN_VMAX = 1.04985
INITIAL_STEP_KW = 0.5
MAX_BRACKET_CALLS = 16
MAX_EXTRA_CALLS = 8
COORD_TOL_KW = 1e-8
MONOTONIC_TOL_PU = 1e-12
GEOMETRY_TOL_KW = 1e-7

ROOT = Path(__file__).resolve().parents[1]
GENERATOR_PATH = (
    "scripts/prepare_dso_vpp_ac_boundary_headroom_repair_blocker_extended_audit.py"
)
CALIBRATION_DIR = (
    "results/dso_vpp_ac_map_pilot/doe_ac_boundary_headroom_repair_calibration"
)
PREREGISTRATION_DIR = (
    "results/dso_vpp_ac_map_pilot/doe_ac_boundary_headroom_repair_preregistration"
)
HISTORICAL_DIR = "results/dso_vpp_ac_map_pilot/doe_ac_interior_validation"
CELL_DIR = (
    "results/dso_vpp_ac_map_pilot/doe_construction_policy_preregistration/"
    "convex_piecewise_architecture_audit"
)
INTERPRETATION_DIR = (
    "results/dso_vpp_ac_map_pilot/"
    "doe_ac_interior_validation_interpretation_audit"
)
OUTDIR = ROOT / (
    "results/dso_vpp_ac_map_pilot/"
    "doe_ac_boundary_headroom_repair_blocker_extended_audit"
)
IMPLEMENTATION_PATH = (
    "scripts/run_dso_vpp_ac_boundary_headroom_repair_calibration.jl"
)

SOURCE_ARTIFACTS = [
    (CALIBRATION_COMMIT, f"{CALIBRATION_DIR}/edge_retreats.csv",
     "authoritative edge outcomes and recorded limiting IDs"),
    (CALIBRATION_COMMIT, f"{CALIBRATION_DIR}/calibration_attempts.csv",
     "authoritative executed attempt trajectories"),
    (PREREGISTRATION_COMMIT, f"{PREREGISTRATION_DIR}/calibration_fraction_inventory.csv",
     "locked calibration memberships and d=0 coordinates"),
    (PREREGISTRATION_COMMIT, f"{PREREGISTRATION_DIR}/edge_repair_policy.csv",
     "locked normals and strict geometric caps"),
    (PREREGISTRATION_COMMIT, f"{PREREGISTRATION_DIR}/repair_config.json",
     "locked voltage bands and search-control configuration"),
    (CALIBRATION_COMMIT, f"{HISTORICAL_DIR}/validation_point_results.csv",
     "committed historical d=0 validation baselines"),
    (CALIBRATION_COMMIT, IMPLEMENTATION_PATH,
     "actual executed Julia search-control implementation"),
    (GEOMETRY_SOURCE_COMMIT, f"{CELL_DIR}/merged_convex_cells.csv",
     "committed CCW convex-cell vertices used by the executed repair implementation"),
    (GEOMETRY_SOURCE_COMMIT,
     "results/dso_vpp_ac_map_pilot/doe_ac_interior_validation_preregistration/validation_polygon_edges.csv",
     "committed source facet endpoints and geometric edge relationships"),
    (CALIBRATION_COMMIT, f"{INTERPRETATION_DIR}/interpretation_audit_summary.json",
     "prior committed AC-failure localization reference"),
]

CONTENT_NAMES = {
    "generation_assertion_summary.csv",
    "blocker_trajectory_audit.csv",
    "blocker_edge_id_concentration.csv",
    "blocker_edge_geometric_relationships.csv",
    "failing_point_full_cell_membership.csv",
    "implementation_semantics_checks.csv",
    "limiting_calibration_id_downstream_use.csv",
    "limiting_calibration_id_global_audit.csv",
    "limiting_calibration_id_offset_summary.csv",
    "normal_orientation_audit.csv",
    "original_limit_sample_bounds.csv",
    "report.md",
    "reverse_direction_linear_hypothesis.csv",
    "source_artifact_inventory.csv",
    "summary.json",
    "trajectory_observations.csv",
}
EXPECTED_NAMES = CONTENT_NAMES | {"hashes.sha256", "manifest.json"}
OBSOLETE_NAMES = {"audit_validation_checks.csv", "original_limit_trajectory_summary.csv"}


def git(*args: str) -> bytes:
    return subprocess.check_output(["git", *args], cwd=ROOT)


def git_bytes(commit: str, path: str) -> bytes:
    return git("show", f"{commit}:{path}")


def staged_bytes(path: str) -> bytes:
    return git("show", f":{path}")


def read_csv_bytes(data: bytes) -> list[dict[str, str]]:
    return list(csv.DictReader(io.StringIO(data.decode("utf-8-sig"))))


def read_csv_git(commit: str, path: str) -> list[dict[str, str]]:
    return read_csv_bytes(git_bytes(commit, path))


def read_json_git(commit: str, path: str):
    return json.loads(git_bytes(commit, path).decode("utf-8-sig"))


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def fmt(value) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, float):
        if math.isnan(value):
            return "NaN"
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


def original_pass(vmin: float, vmax: float) -> bool:
    return vmin >= ORIGINAL_VMIN and vmax <= ORIGINAL_VMAX


def design_pass(vmin: float, vmax: float) -> bool:
    return vmin >= DESIGN_VMIN and vmax <= DESIGN_VMAX


def normalize(text: str) -> str:
    return " ".join(text.split())


def line_number(source: str, needle: str) -> int:
    first = needle.strip().splitlines()[0].strip()
    for index, line in enumerate(source.splitlines(), 1):
        if first in line.strip():
            return index
    raise RuntimeError(f"source evidence line not found: {first}")


def implementation_checks() -> list[dict]:
    source = git_bytes(CALIBRATION_COMMIT, IMPLEMENTATION_PATH).decode("utf-8")
    normalized = normalize(source)
    definitions = [
        (
            "ANCHOR_SEARCH_DOUBLING_PROGRESSION",
            [
                "step = INITIAL_STEP_KW",
                "upper = lower + step",
                "lower = upper\n        step *= 2\n        upper = start_d + step",
            ],
            "after each failed candidate, step doubles and the next upper candidate is start_d + step",
        ),
        (
            "STRICT_GEOMETRIC_CAP_PRECHECK",
            [
                "upper < cap || return (status=\"LOCAL_PARALLEL_EDGE_REPAIR_INSUFFICIENT\"",
                "point = evaluate(upper)",
            ],
            "upper must be strictly less than cap before evaluation; cap_e itself is not admitted",
        ),
        (
            "ANCHOR_BRACKET_CALL_BUDGET",
            [
                "const MAX_BRACKET_CALLS = 16",
                "phase=\"ANCHOR_SEARCH\", max_extra=MAX_BRACKET_CALLS+MAX_BISECTION_CALLS",
                "while bracket_calls < min(MAX_BRACKET_CALLS, max_extra)",
            ],
            "anchor bracket evaluation is limited to min(MAX_BRACKET_CALLS, max_extra), with MAX_BRACKET_CALLS=16",
        ),
        (
            "VERIFY_ESCALATION_EXTRA_CALL_BUDGET",
            [
                "const MAX_EXTRA_CALLS = 8",
                "phase=\"VERIFY_ESCALATE\", max_extra=MAX_EXTRA_CALLS",
            ],
            "verify escalation invokes the same search with max_extra=8",
        ),
        (
            "VERIFY_ESCALATION_CANDIDATE_PROGRESSION",
            [
                "current = evaluate(start_d)",
                "step = INITIAL_STEP_KW",
                "upper = lower + step",
                "upper = start_d + step",
                "phase=\"VERIFY_ESCALATE\", max_extra=MAX_EXTRA_CALLS",
            ],
            "escalation evaluates start_d, then start_d+0.5 kW, and doubles the offset from start_d after failures",
        ),
        (
            "PREBISECTION_UNRESOLVED_RETURNS",
            [
                "current.solver_status == \"UNRESOLVED\" && return",
                "point.solver_status == \"UNRESOLVED\" && return",
            ],
            "an unresolved start or bracket candidate returns UNRESOLVED before bisection",
        ),
        (
            "NO_BRACKET_PREBISECTION_RETURN",
            [
                "while bracket_calls < min(MAX_BRACKET_CALLS, max_extra)",
                "bracket_pass ||\n        return (status=\"LOCAL_PARALLEL_EDGE_REPAIR_INSUFFICIENT\"",
            ],
            "exhausting the applicable bracket-call loop without a pass returns insufficient before bisection",
        ),
    ]
    rows = []
    for check_id, snippets, semantics in definitions:
        missing = [snippet for snippet in snippets if normalize(snippet) not in normalized]
        if missing:
            raise RuntimeError(f"executed implementation check failed: {check_id}: {missing}")
        rows.append(
            {
                "check_id": check_id,
                "status": "PASS",
                "source_commit": CALIBRATION_COMMIT,
                "source_path": IMPLEMENTATION_PATH,
                "first_evidence_line": line_number(source, snippets[0]),
                "verified_semantics": semantics,
                "matched_source_logic": " ; ".join(normalize(item) for item in snippets),
            }
        )
    return rows


def source_inventory() -> list[dict]:
    rows = []
    for commit, path, role in SOURCE_ARTIFACTS:
        data = git_bytes(commit, path)
        suffix = Path(path).suffix.lower()
        row_count = len(read_csv_bytes(data)) if suffix == ".csv" else 1
        if suffix == ".json":
            json.loads(data.decode("utf-8-sig"))
        rows.append(
            {
                "artifact_path": path,
                "source_commit": commit,
                "artifact_role": role,
                "artifact_format": suffix.lstrip(".").upper(),
                "row_or_record_count": row_count,
                "bytes": len(data),
                "sha256": sha256(data),
            }
        )
    return rows


def truth(value: str) -> bool:
    return value.lower() == "true"


def logical_call_number(row: dict[str, str]) -> int:
    return int(row["logical_call_id"].split("_")[-1])


def replay_search(rows: list[dict[str, str]]) -> dict:
    """Replay only the result-bearing state transitions of search_retreat!."""
    ordered = sorted(rows, key=logical_call_number)
    if not ordered:
        return {"status": "NO_ATTEMPTS", "d_star": None}
    first = ordered[0]
    if first["solver_status"] == "UNRESOLVED":
        return {"status": "UNRESOLVED", "d_star": None}
    if design_pass(float(first["vmin_pu"]), float(first["vmax_pu"])):
        return {"status": "PASS", "d_star": float(first["d_kw"])}
    lower = float(first["d_kw"])
    upper = None
    pass_seen = False
    for row in ordered[1:]:
        if row["solver_status"] == "UNRESOLVED":
            return {"status": "UNRESOLVED", "d_star": None}
        d_kw = float(row["d_kw"])
        passed = design_pass(float(row["vmin_pu"]), float(row["vmax_pu"]))
        if not pass_seen:
            if passed:
                upper = d_kw
                pass_seen = True
            else:
                lower = d_kw
        elif passed:
            upper = d_kw
        else:
            lower = d_kw
    return (
        {"status": "PASS", "d_star": upper, "lower_fail": lower}
        if pass_seen
        else {"status": "INSUFFICIENT", "d_star": None, "lower_fail": lower}
    )


def polygon_area(vertices: list[tuple[float, float]]) -> float:
    return 0.5 * sum(
        a[0] * b[1] - b[0] * a[1]
        for a, b in zip(vertices, vertices[1:] + vertices[:1])
    )


def facet_slacks(
    vertices: list[tuple[float, float]], point: tuple[float, float]
) -> list[float]:
    slacks = []
    for a, b in zip(vertices, vertices[1:] + vertices[:1]):
        dx = b[0] - a[0]
        dy = b[1] - a[1]
        length = math.hypot(dx, dy)
        if length <= GEOMETRY_TOL_KW:
            raise RuntimeError("degenerate committed cell facet")
        slacks.append((dx * (point[1] - a[1]) - dy * (point[0] - a[0])) / length)
    return slacks


def classify_cell(
    vertices: list[tuple[float, float]], point: tuple[float, float]
) -> dict:
    slacks = facet_slacks(vertices, point)
    violated = [index for index, value in enumerate(slacks) if value < -GEOMETRY_TOL_KW]
    active = [index for index, value in enumerate(slacks) if abs(value) <= GEOMETRY_TOL_KW]
    if violated:
        classification = "OUTSIDE_CELL"
    elif any(value < 0 for value in slacks):
        classification = "AMBIGUOUS_WITHIN_TOLERANCE"
    elif len(active) == 0:
        classification = "STRICT_CELL_INTERIOR"
    elif len(active) == 1:
        classification = "CELL_BOUNDARY_SINGLE_FACET"
    else:
        classification = "CELL_BOUNDARY_EDGE_OR_VERTEX"
    return {
        "classification": classification,
        "min_slack_kw": min(slacks),
        "active_facets": active,
        "violated_facets": violated,
        "inside_with_tolerance": not violated,
        "strict": classification == "STRICT_CELL_INTERIOR",
    }


def calibration_number(value: str) -> int | None:
    if value.startswith("CAL_") and value[4:].isdigit():
        return int(value[4:])
    return None


def classify_stop(
    phase: str, ordered_attempts: list[dict[str, str]], cap_kw: float
) -> dict:
    ordered = sorted(ordered_attempts, key=lambda row: float(row["d_kw"]))
    if not ordered:
        return {
            "mechanism": "EVIDENCE_GAP",
            "reason": "NO_BLOCKING_TRAJECTORY_ATTEMPTS",
            "next_candidate_kw": None,
            "next_candidate_below_cap": None,
        }
    if any(row["solver_status"] == "UNRESOLVED" for row in ordered):
        return {
            "mechanism": "UNRESOLVED_EXECUTION_STOP",
            "reason": "UNRESOLVED_ATTEMPT_OBSERVED_BEFORE_BISECTION",
            "next_candidate_kw": None,
            "next_candidate_below_cap": None,
        }
    start_d = float(ordered[0]["d_kw"])
    bracket_calls = len(ordered) - 1
    expected = [start_d] + [
        start_d + INITIAL_STEP_KW * (2**index) for index in range(bracket_calls)
    ]
    observed = [float(row["d_kw"]) for row in ordered]
    if any(abs(a - b) > 1e-12 for a, b in zip(observed, expected)):
        return {
            "mechanism": "EVIDENCE_GAP",
            "reason": "OBSERVED_SEQUENCE_NOT_IDENTIFIED_AS_PREBISECTION_DOUBLING",
            "next_candidate_kw": None,
            "next_candidate_below_cap": None,
        }
    next_candidate = start_d + INITIAL_STEP_KW * (2**bracket_calls)
    limit = MAX_BRACKET_CALLS if phase == "ANCHOR_SEARCH" else MAX_EXTRA_CALLS
    if bracket_calls >= limit and next_candidate < cap_kw:
        prefix = "ANCHOR" if phase == "ANCHOR_SEARCH" else "VERIFY_ESCALATION"
        return {
            "mechanism": "SEARCH_BUDGET_LIMITED",
            "reason": f"{prefix}_BRACKET_CALL_BUDGET_EXHAUSTED_WITH_NEXT_CANDIDATE_STRICTLY_BELOW_CAP",
            "next_candidate_kw": next_candidate,
            "next_candidate_below_cap": True,
        }
    if bracket_calls < limit and next_candidate >= cap_kw:
        return {
            "mechanism": "GEOMETRIC_CAP_PRECHECK_LIMITED",
            "reason": "NEXT_DOUBLING_CANDIDATE_REJECTED_BY_STRICT_GEOMETRIC_CAP_PRECHECK",
            "next_candidate_kw": next_candidate,
            "next_candidate_below_cap": False,
        }
    if bracket_calls >= limit and next_candidate >= cap_kw:
        return {
            "mechanism": "EVIDENCE_GAP",
            "reason": "BUDGET_EXHAUSTED_BUT_UNSAMPLED_NEXT_CANDIDATE_NOT_CAP_ADMISSIBLE",
            "next_candidate_kw": next_candidate,
            "next_candidate_below_cap": False,
        }
    return {
        "mechanism": "EVIDENCE_GAP",
        "reason": "IMPLEMENTATION_REACHABLE_STOP_NOT_IDENTIFIED_FROM_ARTIFACTS",
        "next_candidate_kw": next_candidate,
        "next_candidate_below_cap": next_candidate < cap_kw,
    }


def build_audit():
    branch = git("branch", "--show-current").decode().strip()
    ancestor_ok = subprocess.run(
        ["git", "merge-base", "--is-ancestor", AUDIT_BASE_COMMIT, "HEAD"],
        cwd=ROOT,
        check=False,
    ).returncode == 0
    if branch != SOURCE_BRANCH or not ancestor_ok:
        raise RuntimeError(
            f"source lock failed: branch={branch}, base_is_ancestor={ancestor_ok}"
        )

    edges = read_csv_git(CALIBRATION_COMMIT, f"{CALIBRATION_DIR}/edge_retreats.csv")
    attempts = read_csv_git(CALIBRATION_COMMIT, f"{CALIBRATION_DIR}/calibration_attempts.csv")
    members = read_csv_git(
        PREREGISTRATION_COMMIT,
        f"{PREREGISTRATION_DIR}/calibration_fraction_inventory.csv",
    )
    policies = read_csv_git(
        PREREGISTRATION_COMMIT, f"{PREREGISTRATION_DIR}/edge_repair_policy.csv"
    )
    historical = read_csv_git(
        CALIBRATION_COMMIT, f"{HISTORICAL_DIR}/validation_point_results.csv"
    )
    config = read_json_git(
        PREREGISTRATION_COMMIT, f"{PREREGISTRATION_DIR}/repair_config.json"
    )
    cell_rows = read_csv_git(
        GEOMETRY_SOURCE_COMMIT, f"{CELL_DIR}/merged_convex_cells.csv"
    )
    polygon_rows = read_csv_git(
        GEOMETRY_SOURCE_COMMIT,
        "results/dso_vpp_ac_map_pilot/doe_ac_interior_validation_preregistration/validation_polygon_edges.csv",
    )
    prior = read_json_git(
        CALIBRATION_COMMIT, f"{INTERPRETATION_DIR}/interpretation_audit_summary.json"
    )
    prior_failure = prior["C_failure_localization"]
    if (
        prior_failure["total_counterexamples"] != 9420
        or prior_failure["boundary_inter_ray_counterexamples"] != 7060
        or prior_failure["cell_edge_counterexamples"] != 2360
        or prior_failure["strict_cell_interior_counterexamples"] != 0
    ):
        raise RuntimeError("prior failure-localization reference changed")

    search = config["calibration"]["anchor_search"]
    escalation = config["calibration"]["verify_escalate"]
    halfspace = config["repair_geometry"]["halfspace_semantics"]
    if (
        search["initial_step_kw"] != INITIAL_STEP_KW
        or search["maximum_bracket_calls_per_edge"] != MAX_BRACKET_CALLS
        or escalation["maximum_extra_calls_per_interior_membership"] != MAX_EXTRA_CALLS
        or halfspace != "n_in_dot_x_minus_a_ge_d_e"
    ):
        raise RuntimeError("locked config does not match implementation audit")

    blocked = sorted(
        [row for row in edges if row["final_status"] == "LOCAL_PARALLEL_EDGE_REPAIR_INSUFFICIENT"],
        key=lambda row: (row["timestamp"], row["edge_id"]),
    )
    if len(edges) != 1689 or len(attempts) != 51773 or len(blocked) != 15:
        raise RuntimeError("authoritative row count mismatch")

    member_by_id = {row["calibration_membership_id"]: row for row in members}
    policy_by_key = {(row["timestamp"], row["edge_id"]): row for row in policies}
    polygon_by_key = {
        (row["timestamp"], row["source_polygon_edge_id"]): row
        for row in polygon_rows
    }
    attempts_by_key: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    for row in attempts:
        if row["edge_id"]:
            attempts_by_key[(row["timestamp"], row["edge_id"])].append(row)

    cells: dict[str, dict[int, list[tuple[float, float]]]] = defaultdict(dict)
    grouped_cells: dict[tuple[str, int], list[dict[str, str]]] = defaultdict(list)
    for row in cell_rows:
        grouped_cells[(row["timestamp"], int(row["cell_index"]))].append(row)
    for (timestamp, cell_id), rows in grouped_cells.items():
        ordered = sorted(rows, key=lambda row: int(row["cell_vertex_index_ccw"]))
        vertices = [(float(row["p13_abs_kw"]), float(row["p30_abs_kw"])) for row in ordered]
        if polygon_area(vertices) <= 0 or not all(truth(row["cell_convex"]) for row in ordered):
            raise RuntimeError(f"committed cell is not verified convex CCW: {(timestamp, cell_id)}")
        cells[timestamp][cell_id] = vertices

    audit_rows = []
    observation_rows = []
    sample_bound_rows = []
    orientation_rows = []
    membership_rows = []
    reverse_rows = []
    max_direction_error = 0.0
    for edge in blocked:
        key = (edge["timestamp"], edge["edge_id"])
        policy = policy_by_key[key]
        phase = "VERIFY_ESCALATE" if truth(edge["escalated"]) else "ANCHOR_SEARCH"
        trajectory = [row for row in attempts_by_key[key] if row["phase"] == phase]
        ids = sorted({row["calibration_id"] for row in trajectory})
        if len(ids) != 1 or not trajectory:
            raise RuntimeError(f"blocking membership is not unique for {key}: {ids}")
        blocking_id = ids[0]
        member = member_by_id[blocking_id]
        n13 = float(policy["inward_normal_p13"])
        n30 = float(policy["inward_normal_p30"])
        p13_0 = float(member["p13_abs_kw_at_source_geometry"])
        p30_0 = float(member["p30_abs_kw_at_source_geometry"])
        cap = float(policy["parallel_retreat_cap_kw"])
        owner_cell = int(policy["owner_cell_id"])

        for row in trajectory:
            d_kw = float(row["d_kw"])
            error = max(
                abs(float(row["p13_abs_kw"]) - (p13_0 + d_kw * n13)),
                abs(float(row["p30_abs_kw"]) - (p30_0 + d_kw * n30)),
            )
            max_direction_error = max(max_direction_error, error)
            if error > COORD_TOL_KW:
                raise RuntimeError(f"registered direction mismatch for {row['attempt_id']}: {error}")

        direct_baselines = [row for row in trajectory if abs(float(row["d_kw"])) <= 1e-15]
        if direct_baselines:
            if len(direct_baselines) != 1:
                raise RuntimeError(f"non-unique direct d=0 baseline for {key}")
            base = direct_baselines[0]
            baseline = {
                "source_kind": "CALIBRATION_ATTEMPT_D0",
                "source_path": f"{CALIBRATION_DIR}/calibration_attempts.csv",
                "source_id": base["attempt_id"],
                "match_timestamp": base["timestamp"],
                "match_count": 1,
                "coordinate_delta_kw": 0.0,
                "vmin_pu": float(base["vmin_pu"]),
                "vmax_pu": float(base["vmax_pu"]),
                "vmin_bus": base["vmin_bus"],
                "vmax_bus": base["vmax_bus"],
            }
        else:
            matches = []
            for row in historical:
                if row["timestamp"] != edge["timestamp"]:
                    continue
                delta = max(
                    abs(float(row["p13_abs_kw"]) - p13_0),
                    abs(float(row["p30_abs_kw"]) - p30_0),
                )
                if delta <= COORD_TOL_KW:
                    matches.append((row, delta))
            if len(matches) != 1:
                raise RuntimeError(
                    f"timestamp+coordinate historical match count for {key}: {len(matches)}"
                )
            base, delta = matches[0]
            baseline = {
                "source_kind": "HISTORICAL_VALIDATION_UNIQUE_TIMESTAMP_COORDINATE_MATCH",
                "source_path": f"{HISTORICAL_DIR}/validation_point_results.csv",
                "source_id": base["validation_point_id"],
                "match_timestamp": base["timestamp"],
                "match_count": len(matches),
                "coordinate_delta_kw": delta,
                "vmin_pu": float(base["vmin_pu"]),
                "vmax_pu": float(base["vmax_pu"]),
                "vmin_bus": base["vmin_bus"],
                "vmax_bus": base["vmax_bus"],
            }

        baseline_original = original_pass(baseline["vmin_pu"], baseline["vmax_pu"])
        baseline_design = design_pass(baseline["vmin_pu"], baseline["vmax_pu"])
        target_status = "DESIGN_HEADROOM" if baseline_original and not baseline_design else "ORIGINAL_LIMIT"
        binding = (
            "VMIN"
            if baseline["vmin_pu"] - DESIGN_VMIN <= DESIGN_VMAX - baseline["vmax_pu"]
            else "VMAX"
        )
        binding_slack = (
            baseline["vmin_pu"] - ORIGINAL_VMIN
            if binding == "VMIN"
            else ORIGINAL_VMAX - baseline["vmax_pu"]
        )

        points = [{
            "d_kw": 0.0,
            "p13_abs_kw": p13_0,
            "p30_abs_kw": p30_0,
            "vmin_pu": baseline["vmin_pu"],
            "vmax_pu": baseline["vmax_pu"],
            "vmin_bus": baseline["vmin_bus"],
            "vmax_bus": baseline["vmax_bus"],
            "source_kind": baseline["source_kind"],
            "source_id": baseline["source_id"],
        }]
        for row in trajectory:
            if abs(float(row["d_kw"])) <= 1e-15:
                continue
            points.append({
                "d_kw": float(row["d_kw"]),
                "p13_abs_kw": float(row["p13_abs_kw"]),
                "p30_abs_kw": float(row["p30_abs_kw"]),
                "vmin_pu": float(row["vmin_pu"]),
                "vmax_pu": float(row["vmax_pu"]),
                "vmin_bus": row["vmin_bus"],
                "vmax_bus": row["vmax_bus"],
                "source_kind": "CALIBRATION_ATTEMPT",
                "source_id": row["attempt_id"],
            })
        points.sort(key=lambda item: (item["d_kw"], item["source_id"]))
        binding_margins = [
            point["vmin_pu"] - DESIGN_VMIN
            if binding == "VMIN"
            else DESIGN_VMAX - point["vmax_pu"]
            for point in points
        ]
        opposite_margins = [
            DESIGN_VMAX - point["vmax_pu"]
            if binding == "VMIN"
            else point["vmin_pu"] - DESIGN_VMIN
            for point in points
        ]
        binding_worsens = all(
            later <= earlier + MONOTONIC_TOL_PU
            for earlier, later in zip(binding_margins, binding_margins[1:])
        )
        opposite_improves = all(
            later + MONOTONIC_TOL_PU >= earlier
            for earlier, later in zip(opposite_margins, opposite_margins[1:])
        )
        any_design_pass = any(
            design_pass(point["vmin_pu"], point["vmax_pu"]) for point in points
        )
        directional = (
            "DIRECTIONAL_NO_PASS_OBSERVED_MONOTONIC_BINDING_MARGIN_WORSENING"
            if not any_design_pass and binding_worsens
            else "OTHER_OBSERVED_DIRECTIONAL_PATTERN"
        )

        positive_failures = [
            point for point in points
            if point["d_kw"] > 0 and not original_pass(point["vmin_pu"], point["vmax_pu"])
        ]
        first_fail = positive_failures[0] if positive_failures else None
        prior_passes = [
            point for point in points
            if first_fail and point["d_kw"] < first_fail["d_kw"]
            and original_pass(point["vmin_pu"], point["vmax_pu"])
        ]
        last_pass = prior_passes[-1] if prior_passes else None
        failure_channel = ""
        if first_fail:
            failure_channel = "VMIN" if first_fail["vmin_pu"] < ORIGINAL_VMIN else "VMAX"

        stop = classify_stop(phase, trajectory, cap)
        if stop["mechanism"] == "EVIDENCE_GAP":
            raise RuntimeError(f"unsupported blocker stop evidence for {key}: {stop['reason']}")
        if stop["mechanism"] == "SEARCH_BUDGET_LIMITED" and not stop["next_candidate_below_cap"]:
            raise RuntimeError(f"budget classification lacks cap-admissible next candidate: {key}")
        mismatch = edge["limiting_calibration_id"] != blocking_id

        polygon = polygon_by_key[key]
        a = (
            float(polygon["endpoint_a_p13_abs_kw"]),
            float(polygon["endpoint_a_p30_abs_kw"]),
        )
        b = (
            float(polygon["endpoint_b_p13_abs_kw"]),
            float(polygon["endpoint_b_p30_abs_kw"]),
        )
        owner_vertices = cells[edge["timestamp"]][owner_cell]
        witness = (
            sum(point[0] for point in owner_vertices) / len(owner_vertices),
            sum(point[1] for point in owner_vertices) / len(owner_vertices),
        )
        witness_check = classify_cell(owner_vertices, witness)
        if witness_check["classification"] != "STRICT_CELL_INTERIOR":
            raise RuntimeError(f"interior witness verification failed for {key}")
        baseline_owner_result = classify_cell(owner_vertices, (p13_0, p30_0))
        signed_orientation = n13 * (witness[0] - a[0]) + n30 * (witness[1] - a[1])
        facet_endpoint_residual = abs(n13 * (b[0] - a[0]) + n30 * (b[1] - a[1]))
        orientation_consistent = signed_orientation >= -GEOMETRY_TOL_KW
        orientation_rows.append({
            "timestamp": edge["timestamp"],
            "edge_id": edge["edge_id"],
            "owner_cell_id": owner_cell,
            "orientation_result": "INWARD_ORIENTATION_CONSISTENT" if orientation_consistent else "INWARD_ORIENTATION_INCONSISTENT",
            "signed_n_in_dot_c_minus_a_kw": signed_orientation,
            "tolerance_kw": GEOMETRY_TOL_KW,
            "facet_endpoint_offset_residual_kw": facet_endpoint_residual,
            "facet_point_a_source": "validation_polygon_edges.csv:endpoint_a",
            "interior_witness_source": "ARITHMETIC_MEAN_OF_COMMITTED_CCW_CELL_VERTICES_VERIFIED_STRICT_INTERIOR",
            "interior_witness_p13_kw": witness[0],
            "interior_witness_p30_kw": witness[1],
            "halfspace_convention": halfspace,
            "expected_interior_sign": "NONNEGATIVE",
            "stored_normal_orientation_consistent": orientation_consistent,
        })

        for point in points:
            observation_rows.append({
                "timestamp": edge["timestamp"],
                "edge_id": edge["edge_id"],
                "blocking_calibration_id": blocking_id,
                "blocking_phase": phase,
                "d_kw": point["d_kw"],
                "p13_abs_kw": point["p13_abs_kw"],
                "p30_abs_kw": point["p30_abs_kw"],
                "vmin_pu": point["vmin_pu"],
                "vmax_pu": point["vmax_pu"],
                "original_limit_status": "PASS" if original_pass(point["vmin_pu"], point["vmax_pu"]) else "FAIL",
                "design_headroom_status": "PASS" if design_pass(point["vmin_pu"], point["vmax_pu"]) else "FAIL",
                "source_kind": point["source_kind"],
                "source_id": point["source_id"],
            })
            if point["d_kw"] <= 0:
                continue
            cell_results = {
                cell_id: classify_cell(vertices, (point["p13_abs_kw"], point["p30_abs_kw"]))
                for cell_id, vertices in sorted(cells[edge["timestamp"]].items())
            }
            containing = [cell_id for cell_id, result in cell_results.items() if result["inside_with_tolerance"]]
            strict = [cell_id for cell_id, result in cell_results.items() if result["strict"]]
            if strict:
                overall = "STRICT_CELL_INTERIOR"
            elif containing:
                contained_classes = {cell_results[cell_id]["classification"] for cell_id in containing}
                if "AMBIGUOUS_WITHIN_TOLERANCE" in contained_classes:
                    overall = "AMBIGUOUS_WITHIN_TOLERANCE"
                elif "CELL_BOUNDARY_EDGE_OR_VERTEX" in contained_classes:
                    overall = "CELL_BOUNDARY_EDGE_OR_VERTEX"
                else:
                    overall = "CELL_BOUNDARY_SINGLE_FACET"
            else:
                overall = "OUTSIDE_CELL"
            owner_result = cell_results[owner_cell]
            original_status = "PASS" if original_pass(point["vmin_pu"], point["vmax_pu"]) else "FAIL"
            membership_rows.append({
                "timestamp": edge["timestamp"],
                "edge_id": edge["edge_id"],
                "blocking_calibration_id": blocking_id,
                "d_kw": point["d_kw"],
                "p13_abs_kw": point["p13_abs_kw"],
                "p30_abs_kw": point["p30_abs_kw"],
                "original_limit_status": original_status,
                "source_owner_cell_id": owner_cell,
                "full_cell_location": overall,
                "containing_cell_ids": ";".join(map(str, containing)),
                "strict_interior_cell_ids": ";".join(map(str, strict)),
                "lies_in_at_least_one_valid_cell": bool(containing),
                "lies_in_strict_interior_of_any_cell": bool(strict),
                "owner_cell_classification": owner_result["classification"],
                "owner_cell_min_signed_facet_slack_kw": owner_result["min_slack_kw"],
                "owner_cell_active_facet_ids": ";".join(f"{owner_cell}:F{i}" for i in owner_result["active_facets"]),
                "owner_cell_violated_facet_ids": ";".join(f"{owner_cell}:F{i}" for i in owner_result["violated_facets"]),
                "geometry_tolerance_kw": GEOMETRY_TOL_KW,
                "materially_new_vs_prior_strict_interior_failure_zero": original_status == "FAIL" and bool(strict),
            })

        sample_bound_rows.append({
            "timestamp": edge["timestamp"],
            "edge_id": edge["edge_id"],
            "blocking_calibration_id": blocking_id,
            "original_limit_failure_channel": failure_channel,
            "last_sampled_original_limit_pass_d_kw": last_pass["d_kw"] if last_pass else None,
            "first_sampled_original_limit_fail_d_kw": first_fail["d_kw"] if first_fail else None,
            "sampled_transition_interval_lower_kw": last_pass["d_kw"] if last_pass else None,
            "sampled_transition_interval_upper_kw": first_fail["d_kw"] if first_fail else None,
            "first_sampled_fail_vmin_pu": first_fail["vmin_pu"] if first_fail else None,
            "first_sampled_fail_vmax_pu": first_fail["vmax_pu"] if first_fail else None,
            "unsampled_interval_width_kw": first_fail["d_kw"] - last_pass["d_kw"] if first_fail and last_pass else None,
            "continuous_crossing_location_claim": False,
        })

        d1 = points[1]["d_kw"]
        binding_slope = (binding_margins[1] - binding_margins[0]) / d1
        opposite_slope = (opposite_margins[1] - opposite_margins[0]) / d1
        deficit = max(0.0, -binding_margins[0])
        reverse_distance = deficit / abs(binding_slope) if binding_slope < 0 else None
        reverse_rows.append({
            "timestamp": edge["timestamp"],
            "edge_id": edge["edge_id"],
            "blocking_calibration_id": blocking_id,
            "hypothesis_label": "UNSAMPLED_REVERSE_DIRECTION_LINEAR_EXTRAPOLATION",
            "binding_channel": binding,
            "slope_definition": "(binding_design_margin_at_first_positive_sample-binding_design_margin_at_d0)/first_positive_d_kw",
            "d0_kw": 0.0,
            "d1_kw": d1,
            "binding_design_margin_d0_pu": binding_margins[0],
            "binding_design_margin_d1_pu": binding_margins[1],
            "local_positive_direction_slope_pu_per_kw": binding_slope,
            "design_headroom_deficit_pu": deficit,
            "estimated_reverse_distance_kw": reverse_distance,
            "opposite_design_margin_d0_pu": opposite_margins[0],
            "opposite_margin_slope_pu_per_kw": opposite_slope,
            "opposite_margin_linear_extrapolation_at_reverse_distance_pu": opposite_margins[0] - reverse_distance * opposite_slope if reverse_distance is not None else None,
            "ac_validated": False,
        })

        audit_rows.append({
            "timestamp": edge["timestamp"],
            "edge_id": edge["edge_id"],
            "blocking_phase": phase,
            "recorded_summary_limiting_calibration_id": edge["limiting_calibration_id"],
            "attempt_derived_blocking_calibration_id": blocking_id,
            "summary_limiting_id_mismatch": mismatch,
            "baseline_source_kind": baseline["source_kind"],
            "baseline_source_path": baseline["source_path"],
            "baseline_match_timestamp": baseline["match_timestamp"],
            "baseline_source_validation_point_or_attempt_id": baseline["source_id"],
            "baseline_timestamp_coordinate_match_count": baseline["match_count"],
            "baseline_max_coordinate_delta_kw": baseline["coordinate_delta_kw"],
            "baseline_vmin_pu": baseline["vmin_pu"],
            "baseline_vmax_pu": baseline["vmax_pu"],
            "baseline_original_limit_status": "PASS" if baseline_original else "FAIL",
            "baseline_design_headroom_status": "PASS" if baseline_design else "FAIL",
            "target_status": target_status,
            "binding_channel": binding,
            "binding_original_limit_slack_pu": binding_slack,
            "requested_design_headroom_increment_pu": DESIGN_VMIN - ORIGINAL_VMIN,
            "binding_slack_to_requested_headroom_ratio": binding_slack / (DESIGN_VMIN - ORIGINAL_VMIN),
            "baseline_owner_cell_classification": baseline_owner_result["classification"],
            "baseline_owner_cell_min_signed_facet_slack_kw": baseline_owner_result["min_slack_kw"],
            "observed_point_count_including_d0": len(points),
            "maximum_observed_d_kw": max(point["d_kw"] for point in points),
            "cap_e_kw": cap,
            "next_implementation_candidate_kw": stop["next_candidate_kw"],
            "next_candidate_strictly_below_cap": stop["next_candidate_below_cap"],
            "cap_e_sampled": any(abs(point["d_kw"] - cap) <= 1e-12 for point in points),
            "stop_mechanism": stop["mechanism"],
            "stopping_reason": stop["reason"],
            "observed_pass_fail_bracket_formed": any_design_pass,
            "bisection_or_resolution_refinement_event_observed": False,
            "resolution_claim_boundary": "NO_PASS_FAIL_BRACKET_OR_RESOLUTION_REFINEMENT_EVENT_OBSERVED",
            "directional_evidence": directional,
            "opposite_margin_monotonic_improvement": opposite_improves,
            "sampled_original_limit_fail_present": bool(first_fail),
            "original_limit_failure_channel": failure_channel,
            "first_sampled_original_limit_fail_d_kw": first_fail["d_kw"] if first_fail else None,
            "continuous_crossing_location_claim": False,
        })

    concentration_rows = []
    for edge_id in sorted({row["edge_id"] for row in audit_rows}):
        rows = [row for row in audit_rows if row["edge_id"] == edge_id]
        concentration_rows.append({
            "edge_id": edge_id,
            "blocking_membership_count": len(rows),
            "timestamps": ";".join(row["timestamp"] for row in rows),
            "binding_channel_split": ";".join(f"{key}={value}" for key, value in sorted(Counter(row["binding_channel"] for row in rows).items())),
            "blocking_phase_split": ";".join(f"{key}={value}" for key, value in sorted(Counter(row["blocking_phase"] for row in rows).items())),
            "stop_mechanism_split": ";".join(f"{key}={value}" for key, value in sorted(Counter(row["stop_mechanism"] for row in rows).items())),
        })

    def same_point(row_a, prefix_a, row_b, prefix_b) -> bool:
        return max(
            abs(float(row_a[f"{prefix_a}_p13_abs_kw"]) - float(row_b[f"{prefix_b}_p13_abs_kw"])),
            abs(float(row_a[f"{prefix_a}_p30_abs_kw"]) - float(row_b[f"{prefix_b}_p30_abs_kw"])),
        ) <= COORD_TOL_KW

    unique_edge_ids = sorted({row["edge_id"] for row in audit_rows})
    relationship_rows = []
    blocked_timestamp_by_edge = {
        edge_id: {row["timestamp"] for row in audit_rows if row["edge_id"] == edge_id}
        for edge_id in unique_edge_ids
    }
    polygon_all = {(row["timestamp"], row["source_polygon_edge_id"]): row for row in polygon_rows}
    for index, edge_a in enumerate(unique_edge_ids):
        for edge_b in unique_edge_ids[index + 1:]:
            common = sorted(
                timestamp for timestamp in cells
                if (timestamp, edge_a) in polygon_all and (timestamp, edge_b) in polygon_all
            )
            adjacent = []
            for timestamp in common:
                arow = polygon_all[(timestamp, edge_a)]
                brow = polygon_all[(timestamp, edge_b)]
                adjacent.append(any([
                    same_point(arow, "endpoint_a", brow, "endpoint_a"),
                    same_point(arow, "endpoint_a", brow, "endpoint_b"),
                    same_point(arow, "endpoint_b", brow, "endpoint_a"),
                    same_point(arow, "endpoint_b", brow, "endpoint_b"),
                ]))
            co_block = sorted(blocked_timestamp_by_edge[edge_a] & blocked_timestamp_by_edge[edge_b])
            relationship_rows.append({
                "edge_id_a": edge_a,
                "edge_id_b": edge_b,
                "common_geometry_timestamp_count": len(common),
                "adjacent_common_timestamp_count": sum(adjacent),
                "adjacent_at_all_common_timestamps": bool(common) and all(adjacent),
                "relationship_basis": "SHARED_COMMITTED_SOURCE_ENDPOINT_WITHIN_1E-8_KW",
                "co_temporal_blocker_timestamps": ";".join(co_block),
                "co_temporal_blocker_count": len(co_block),
                "co_temporal_blocker_adjacent_count": sum(
                    1 for timestamp in co_block
                    if common and adjacent[common.index(timestamp)]
                ),
            })

    global_id_rows = []
    for edge in sorted(edges, key=lambda row: (row["timestamp"], row["edge_id"])):
        key = (edge["timestamp"], edge["edge_id"])
        key_attempts = attempts_by_key[key]
        comparator = edge["anchor_id"]
        comparator_phase = "ANCHOR_SEARCH"
        basis = "UNIQUE_EXECUTED_ANCHOR_MEMBERSHIP"
        comparable = True
        if truth(edge["escalated"]):
            anchor_rows = [
                row for row in key_attempts
                if row["phase"] == "ANCHOR_SEARCH" and row["calibration_id"] == edge["anchor_id"]
            ]
            anchor_result = replay_search(anchor_rows)
            if anchor_result["status"] != "PASS":
                comparable = False
                basis = "NOT_COMPARABLE_FROM_EXISTING_ARTIFACTS"
            else:
                current_d = anchor_result["d_star"]
                groups: dict[str, list[dict[str, str]]] = defaultdict(list)
                for row in key_attempts:
                    if row["phase"] == "VERIFY_ESCALATE":
                        groups[row["calibration_id"]].append(row)
                ordered_groups = sorted(groups.items(), key=lambda item: min(logical_call_number(row) for row in item[1]))
                for calibration_id, rows in ordered_groups:
                    result = replay_search(rows)
                    if result["status"] == "INSUFFICIENT":
                        comparator = calibration_id
                        comparator_phase = "VERIFY_ESCALATE"
                        basis = "UNIQUE_FAILED_VERIFY_ESCALATE_MEMBERSHIP"
                        break
                    if result["status"] != "PASS":
                        comparable = False
                        basis = "NOT_COMPARABLE_FROM_EXISTING_ARTIFACTS"
                        break
                    if result["d_star"] > current_d:
                        current_d = result["d_star"]
                        comparator = calibration_id
                        comparator_phase = "VERIFY_ESCALATE"
                        basis = "SOURCE_REPLAYED_STRICTLY_INCREASING_SUCCESSFUL_ESCALATION_LIMITER"
        recorded_number = calibration_number(edge["limiting_calibration_id"])
        comparator_number = calibration_number(comparator) if comparable else None
        offset = recorded_number - comparator_number if recorded_number is not None and comparator_number is not None else None
        global_id_rows.append({
            "timestamp": edge["timestamp"],
            "edge_id": edge["edge_id"],
            "population": "BLOCKER" if edge["final_status"] == "LOCAL_PARALLEL_EDGE_REPAIR_INSUFFICIENT" else "NON_BLOCKER",
            "final_status": edge["final_status"],
            "phase": comparator_phase if comparable else "NOT_COMPARABLE_FROM_EXISTING_ARTIFACTS",
            "recorded_limiting_calibration_id": edge["limiting_calibration_id"],
            "attempt_derived_relevant_calibration_id": comparator if comparable else "",
            "numeric_recorded_minus_attempt_derived": offset,
            "comparison_status": ("MATCH" if edge["limiting_calibration_id"] == comparator else "MISMATCH") if comparable else "NOT_COMPARABLE_FROM_EXISTING_ARTIFACTS",
            "offset_equals_plus_20": offset == 20,
            "comparator_basis": basis,
        })

    offset_groups = Counter(
        (
            row["population"], row["phase"], row["final_status"],
            row["numeric_recorded_minus_attempt_derived"], row["comparison_status"],
        )
        for row in global_id_rows
    )
    offset_rows = [
        {
            "population": key[0],
            "phase": key[1],
            "final_status": key[2],
            "numeric_recorded_minus_attempt_derived": key[3],
            "comparison_status": key[4],
            "offset_equals_plus_20": key[3] == 20,
            "row_count": count,
        }
        for key, count in sorted(offset_groups.items(), key=lambda item: tuple(str(x) for x in item[0]))
    ]

    grep_output = git(
        "grep", "-n", "limiting_calibration_id", CALIBRATION_COMMIT,
        "--", "scripts", "src", "test"
    ).decode("utf-8", errors="replace").splitlines()
    downstream_rows = []
    for match in grep_output:
        remainder = match.split(":", 1)[1]
        path, line, text_value = remainder.split(":", 2)
        if path.endswith("prepare_dso_vpp_ac_boundary_headroom_repair_preregistration.py"):
            use = "OUTPUT_SCHEMA_DECLARATION"
        elif path.endswith("run_dso_vpp_ac_boundary_headroom_repair_calibration.jl"):
            use = "PRODUCER_WRITE_TO_EDGE_SUMMARY"
        else:
            use = "UNCLASSIFIED_SOURCE_REFERENCE"
        downstream_rows.append({
            "source_commit": CALIBRATION_COMMIT,
            "path": path,
            "line": int(line),
            "source_text": text_value.strip(),
            "use_classification": use,
            "demonstrated_downstream_decision_read": False,
            "impact_assessment": "NO_DOWNSTREAM_DECISION_READ_FOUND_IN_COMMITTED_SCRIPTS_SRC_TEST_SEARCH;IMPACT_OUTSIDE_SEARCH_SCOPE_UNRESOLVED",
        })

    implementation_rows = implementation_checks()
    target_counts = Counter(row["target_status"] for row in audit_rows)
    stop_counts = Counter(row["stop_mechanism"] for row in audit_rows)
    failure_channels = Counter(row["original_limit_failure_channel"] for row in audit_rows)
    membership_counts = Counter(row["full_cell_location"] for row in membership_rows)
    original_fail_membership_counts = Counter(
        row["full_cell_location"] for row in membership_rows if row["original_limit_status"] == "FAIL"
    )
    slack_values = [row["binding_original_limit_slack_pu"] for row in audit_rows]
    concentration = {row["edge_id"]: row["blocking_membership_count"] for row in concentration_rows}
    global_mismatches = [row for row in global_id_rows if row["comparison_status"] == "MISMATCH"]
    comparable_count = sum(row["comparison_status"] != "NOT_COMPARABLE_FROM_EXISTING_ARTIFACTS" for row in global_id_rows)
    first_fail_at_or_before_2 = sum(
        row["first_sampled_original_limit_fail_d_kw"] is not None
        and row["first_sampled_original_limit_fail_d_kw"] <= 2.0
        for row in sample_bound_rows
    )
    counts = {
        "blocking_memberships": len(audit_rows),
        "unique_blocker_edge_ids": len(concentration_rows),
        "target_status": {"DESIGN_HEADROOM": target_counts["DESIGN_HEADROOM"], "ORIGINAL_LIMIT": target_counts["ORIGINAL_LIMIT"]},
        "stop_mechanism": {"GEOMETRIC_CAP_PRECHECK_LIMITED": stop_counts["GEOMETRIC_CAP_PRECHECK_LIMITED"], "SEARCH_BUDGET_LIMITED": stop_counts["SEARCH_BUDGET_LIMITED"]},
        "observed_pass_fail_brackets": sum(row["observed_pass_fail_bracket_formed"] for row in audit_rows),
        "bisection_or_resolution_refinement_events_observed": sum(row["bisection_or_resolution_refinement_event_observed"] for row in audit_rows),
        "escalation_baseline_timestamp_coordinate_recoveries": sum(row["baseline_source_kind"] == "HISTORICAL_VALIDATION_UNIQUE_TIMESTAMP_COORDINATE_MATCH" for row in audit_rows),
        "blocker_summary_id_mismatches": sum(row["summary_limiting_id_mismatch"] for row in audit_rows),
        "directional_evidence": dict(sorted(Counter(row["directional_evidence"] for row in audit_rows).items())),
        "sampled_original_limit_fail_memberships": sum(row["sampled_original_limit_fail_present"] for row in audit_rows),
        "sampled_original_limit_failure_channel": {"VMIN": failure_channels["VMIN"], "VMAX": failure_channels["VMAX"]},
        "first_sampled_original_limit_failure_at_or_before_2_kw": first_fail_at_or_before_2,
        "edge_id_concentration": concentration,
        "normal_orientation_consistent": sum(row["stored_normal_orientation_consistent"] for row in orientation_rows),
        "positive_sample_full_cell_location": dict(sorted(membership_counts.items())),
        "original_limit_fail_sample_full_cell_location": dict(sorted(original_fail_membership_counts.items())),
        "strict_cell_interior_original_limit_fail_samples": sum(row["original_limit_status"] == "FAIL" and row["lies_in_strict_interior_of_any_cell"] for row in membership_rows),
        "global_limiting_id_comparable_rows": comparable_count,
        "global_limiting_id_mismatches": len(global_mismatches),
        "global_limiting_id_plus_20_mismatches": sum(row["offset_equals_plus_20"] and row["comparison_status"] == "MISMATCH" for row in global_id_rows),
        "binding_original_limit_slack_pu": {"min": min(slack_values), "median": statistics.median(slack_values), "max": max(slack_values)},
        "reverse_linear_hypotheses": sum(row["estimated_reverse_distance_kw"] is not None for row in reverse_rows),
    }
    regression_references = {
        "target_status": {"DESIGN_HEADROOM": 15, "ORIGINAL_LIMIT": 0},
        "stop_mechanism": {"GEOMETRIC_CAP_PRECHECK_LIMITED": 13, "SEARCH_BUDGET_LIMITED": 2},
        "observed_pass_fail_brackets": 0,
        "bisection_or_resolution_refinement_events_observed": 0,
        "escalation_baseline_timestamp_coordinate_recoveries": 2,
        "blocker_summary_id_mismatches": 2,
        "directional_evidence": {"DIRECTIONAL_NO_PASS_OBSERVED_MONOTONIC_BINDING_MARGIN_WORSENING": 15},
        "sampled_original_limit_fail_memberships": 15,
        "sampled_original_limit_failure_channel": {"VMIN": 4, "VMAX": 11},
        "edge_id_concentration": {"E0019": 10, "E0021": 1, "E0044": 2, "E0045": 1, "E0046": 1},
    }
    for key, reference in regression_references.items():
        if counts[key] != reference:
            raise RuntimeError(f"regression-reference contradiction for {key}: {counts[key]} != {reference}")
    if any(row["cap_e_sampled"] for row in audit_rows):
        raise RuntimeError("a blocker sampled cap_e contrary to strict precheck evidence")
    if counts["normal_orientation_consistent"] != 15:
        raise RuntimeError("stored normal orientation inconsistency found")
    if comparable_count != len(edges):
        raise RuntimeError("global limiting ID comparator evidence gap")

    assertion_rows = [
        {"assertion_id": "SOURCE_BRANCH", "epistemic_role": "SOURCE_CONSISTENCY_ASSERTION", "status": "PASS", "observed": branch, "reference": SOURCE_BRANCH, "interpretation": "generation is restricted to the expected branch"},
        {"assertion_id": "AUDIT_BASE_ANCESTRY", "epistemic_role": "SOURCE_CONSISTENCY_ASSERTION", "status": "PASS", "observed": ancestor_ok, "reference": f"{AUDIT_BASE_COMMIT} is ancestor of HEAD", "interpretation": "allows deterministic reproduction from descendant commits while scientific inputs remain fixed git objects"},
        {"assertion_id": "FIXED_SCIENTIFIC_INPUT_COMMITS", "epistemic_role": "PROVENANCE_ASSERTION", "status": "PASS", "observed": f"calibration={CALIBRATION_COMMIT};preregistration={PREREGISTRATION_COMMIT};geometry={GEOMETRY_SOURCE_COMMIT}", "reference": "git show reads only", "interpretation": "working-tree scientific inputs are not substituted"},
        {"assertion_id": "IMPLEMENTATION_SEMANTICS", "epistemic_role": "IMPLEMENTATION_SEMANTICS_ASSERTION", "status": "PASS", "observed": len(implementation_rows), "reference": 7, "interpretation": "exact source snippets matched; not an independent execution test"},
        {"assertion_id": "REGISTERED_DIRECTION_COORDINATES", "epistemic_role": "PROVENANCE_ASSERTION", "status": "PASS", "observed": max_direction_error, "reference": f"<= {COORD_TOL_KW}", "interpretation": "selected attempts match p(d)=p(0)+d*n_in"},
        {"assertion_id": "BASELINE_TIMESTAMP_COORDINATE_RECOVERY", "epistemic_role": "PROVENANCE_ASSERTION", "status": "PASS", "observed": counts["escalation_baseline_timestamp_coordinate_recoveries"], "reference": 2, "interpretation": "each recovery requires exactly one same-timestamp componentwise coordinate match"},
        {"assertion_id": "TARGET_STATUS_SPLIT", "epistemic_role": "REGRESSION_REFERENCE", "status": "PASS", "observed": json.dumps(counts["target_status"], sort_keys=True), "reference": json.dumps(regression_references["target_status"], sort_keys=True), "interpretation": "previously observed count retained as a regression guard, not preregistration or independent proof"},
        {"assertion_id": "STOP_MECHANISM_SPLIT", "epistemic_role": "REGRESSION_REFERENCE", "status": "PASS", "observed": json.dumps(counts["stop_mechanism"], sort_keys=True), "reference": json.dumps(regression_references["stop_mechanism"], sort_keys=True), "interpretation": "previously observed count retained as a regression guard"},
        {"assertion_id": "ORIGINAL_LIMIT_SAMPLE_CHANNEL_SPLIT", "epistemic_role": "REGRESSION_REFERENCE", "status": "PASS", "observed": json.dumps(counts["sampled_original_limit_failure_channel"], sort_keys=True), "reference": json.dumps(regression_references["sampled_original_limit_failure_channel"], sort_keys=True), "interpretation": "discrete sampled failures only; no continuous crossing location"},
        {"assertion_id": "EDGE_ID_CONCENTRATION", "epistemic_role": "REGRESSION_REFERENCE", "status": "PASS", "observed": json.dumps(counts["edge_id_concentration"], sort_keys=True), "reference": json.dumps(regression_references["edge_id_concentration"], sort_keys=True), "interpretation": "descriptive concentration; no independence, n_eff, or uniform-null test"},
        {"assertion_id": "NORMAL_ORIENTATION", "epistemic_role": "STRUCTURAL_RECONSTRUCTION_ASSERTION", "status": "PASS", "observed": counts["normal_orientation_consistent"], "reference": 15, "interpretation": "committed owner-cell vertex-mean witnesses were independently checked strict interior"},
        {"assertion_id": "GLOBAL_LIMITING_ID_COMPARABILITY", "epistemic_role": "IMPLEMENTATION_SEMANTICS_ASSERTION", "status": "PASS", "observed": comparable_count, "reference": len(edges), "interpretation": "attempt-derived comparator reconstructed through executed anchor/escalation control flow"},
        {"assertion_id": "DETERMINISM_SCOPE", "epistemic_role": "DETERMINISM_CHECK", "status": "EXTERNAL_RERUN_REQUIRED", "observed": "not established by a single generator run", "reference": "clean second run and byte comparison", "interpretation": "byte identity proves determinism only, not scientific validity"},
    ]
    return {
        "audit_rows": audit_rows,
        "observation_rows": observation_rows,
        "sample_bound_rows": sample_bound_rows,
        "concentration_rows": concentration_rows,
        "relationship_rows": relationship_rows,
        "orientation_rows": orientation_rows,
        "membership_rows": membership_rows,
        "global_id_rows": global_id_rows,
        "offset_rows": offset_rows,
        "downstream_rows": downstream_rows,
        "reverse_rows": reverse_rows,
        "implementation_rows": implementation_rows,
        "assertion_rows": assertion_rows,
        "counts": counts,
    }


def generate(outdir: Path) -> int:
    data = build_audit()
    counts = data["counts"]
    outdir.mkdir(parents=True, exist_ok=True)
    for name in OBSOLETE_NAMES:
        obsolete = outdir / name
        if obsolete.exists():
            obsolete.unlink()
    unexpected = sorted(path.name for path in outdir.iterdir() if path.name not in EXPECTED_NAMES)
    if unexpected:
        raise RuntimeError(f"unexpected files in output directory: {unexpected}")

    output_rows = {
        "generation_assertion_summary.csv": data["assertion_rows"],
        "blocker_trajectory_audit.csv": data["audit_rows"],
        "trajectory_observations.csv": data["observation_rows"],
        "original_limit_sample_bounds.csv": data["sample_bound_rows"],
        "blocker_edge_id_concentration.csv": data["concentration_rows"],
        "blocker_edge_geometric_relationships.csv": data["relationship_rows"],
        "normal_orientation_audit.csv": data["orientation_rows"],
        "failing_point_full_cell_membership.csv": data["membership_rows"],
        "limiting_calibration_id_global_audit.csv": data["global_id_rows"],
        "limiting_calibration_id_offset_summary.csv": data["offset_rows"],
        "limiting_calibration_id_downstream_use.csv": data["downstream_rows"],
        "reverse_direction_linear_hypothesis.csv": data["reverse_rows"],
        "implementation_semantics_checks.csv": data["implementation_rows"],
    }
    for name, rows in output_rows.items():
        write_csv(outdir / name, list(rows[0]), rows)
    write_csv(outdir / "source_artifact_inventory.csv", [
        "artifact_path", "source_commit", "artifact_role", "artifact_format",
        "row_or_record_count", "bytes", "sha256",
    ], source_inventory())
    summary = {
        "artifact": "DSO_VPP_AC_BOUNDARY_HEADROOM_REPAIR_BLOCKER_EXTENDED_AUDIT",
        "method": METHOD,
        "source_lock": {
            "required_branch": SOURCE_BRANCH,
            "audit_base_must_be_ancestor_of_head": AUDIT_BASE_COMMIT,
            "fixed_calibration_commit": CALIBRATION_COMMIT,
            "fixed_preregistration_commit": PREREGISTRATION_COMMIT,
            "fixed_geometry_commit": GEOMETRY_SOURCE_COMMIT,
        },
        "counts": counts,
        "prior_failure_localization_reference": {
            "total_counterexamples": 9420,
            "boundary_inter_ray_counterexamples": 7060,
            "cell_edge_counterexamples": 2360,
            "strict_cell_interior_counterexamples": 0,
        },
        "claim_boundaries": [
            "DISCRETE_OBSERVED_LOCAL_DIRECTIONAL_EVIDENCE_ONLY",
            "NO_TRUE_DIRECTIONAL_LIMITATION_CLAIM",
            "NO_GLOBAL_MONOTONICITY_CLAIM",
            "NO_CONTINUOUS_CROSSING_LOCATION_CLAIM",
            "NO_NEGATIVE_DIRECTION_AC_FEASIBILITY_CLAIM",
            "NO_RESOLUTION_FAILURE_RULED_OUT_CLAIM",
            "NO_INDEPENDENCE_OR_UNIFORM_EDGE_NULL_MODEL_CLAIM",
        ],
        "determinism_note": "A byte-identical rerun establishes determinism only, not scientific validity.",
    }
    write_text(outdir / "summary.json", json.dumps(summary, indent=2, sort_keys=True) + "\n")

    slack = counts["binding_original_limit_slack_pu"]
    membership = counts["positive_sample_full_cell_location"]
    fail_membership = counts["original_limit_fail_sample_full_cell_location"]
    strict_failure_count = counts["strict_cell_interior_original_limit_fail_samples"]
    strict_failure_statement = (
        f"`{strict_failure_count}` sampled original-limit failures lie in the strict interior of at least one committed full cell. This is materially new evidence relative to the earlier validation audit's `0` strict-cell-interior failures."
        if strict_failure_count
        else "No sampled original-limit failure lies in the strict interior of any committed full cell, so this audit does not add a strict-cell-interior counterexample to the earlier audit's zero count."
    )
    structural_case_statement = (
        "All positive blocker samples lie outside every committed full cell; their owner-cell diagnostics identify violation of another facet immediately after leaving the source vertex/edge neighborhood. With all stored normals oriented inward relative to the registered facet, this supports Case 3: the registered-normal path leaves the full cell through another facet. It does not support a stored-normal sign defect or a strict-interior geometry/AC mismatch."
        if membership == {"OUTSIDE_CELL": len(data["membership_rows"])}
        else "The sampled full-cell classifications are mixed; the per-point evidence is retained without forcing one structural case."
    )
    report = [
        "# Final zero-AC structural and provenance blocker audit",
        "",
        "## Scope",
        "",
        f"This deterministic audit is `{METHOD}`. It reads immutable committed artifacts and does not execute Julia, a solver, calibration, replay, H1/H2, hosting-capacity analysis, or Safe-Box analysis.",
        "",
        "The generator requires the expected branch and requires the audit base commit to be an ancestor of `HEAD`; it does not require exact `HEAD` equality. Scientific inputs are always read from fixed commits with `git show`, so a descendant audit commit can reproduce the same bytes.",
        "",
        "## Hardening results",
        "",
        "- Both escalation baselines have exactly one same-timestamp, componentwise coordinate match within `1e-8 kW` to committed historical validation points.",
        "- Stop classification follows the executed source control: 13 anchor searches reach the strict cap precheck before their call budget; 2 escalation searches exhaust eight extra calls while their next candidate remains strictly below `cap_e`.",
        "- The classifier supports anchor cap-precheck, anchor budget, escalation budget, unresolved stops, and explicit evidence gaps before bisection. No blocker was silently mapped from an unsupported path.",
        "- The supported resolution statement is `NO_PASS_FAIL_BRACKET_OR_RESOLUTION_REFINEMENT_EVENT_OBSERVED`. An unsampled narrow pass is not ruled out.",
        "- Original-limit evidence is reported as sampled pass/fail bounds. Every row sets `continuous_crossing_location_claim=false`.",
        "- `generation_assertion_summary.csv` identifies generator assertions, provenance assertions, regression references, and the externally required determinism check. It is not presented as independent validation.",
        "",
        "## Blocking-membership results",
        "",
        "- Blocking memberships: `15` (not all memberships of the affected edges).",
        "- Target status: `15 DESIGN_HEADROOM / 0 ORIGINAL_LIMIT`.",
        "- Stop mechanism: `13 GEOMETRIC_CAP_PRECHECK_LIMITED / 2 SEARCH_BUDGET_LIMITED`.",
        "- Observed pass/fail brackets: `0`; bisection or resolution-refinement events: `0`.",
        "- Every membership has at least one sampled positive-`d` original-limit failure: `4 VMIN / 11 VMAX`.",
        f"- First sampled original-limit failure is at or before 2 kW for `{counts['first_sampled_original_limit_failure_at_or_before_2_kw']}` memberships. This is a sample-location count, not a continuous crossing claim.",
        "",
        "## Edge-ID concentration and topology",
        "",
        "Blocking-membership concentration is `E0019=10, E0044=2, E0021=1, E0045=1, E0046=1`. This is descriptive only: edge numbers are not treated as independent samples, no effective sample size is computed, and no uniform-null significance test is used.",
        "",
        "Committed endpoint geometry shows which unique edge IDs share a facet endpoint; `blocker_edge_geometric_relationships.csv` reports that separately. The only timestamp with two simultaneous blockers is tested directly rather than inferred from ID adjacency.",
        "",
        "## Normal orientation and full-cell location",
        "",
        f"All `{counts['normal_orientation_consistent']}/15` stored normals are orientation-consistent with `n_in·(x-a)>=0`, using the arithmetic mean of the committed CCW owner-cell vertices as a witness and independently verifying each witness is strict cell interior at the executed `1e-7 kW` geometry tolerance.",
        "",
        f"Positive sampled-point full-cell classifications are `{json.dumps(membership, sort_keys=True)}`. Original-limit-failing sampled-point classifications are `{json.dumps(fail_membership, sort_keys=True)}`.",
        "",
        strict_failure_statement + " The earlier `9,420` failures were `7,060` direct angular-boundary points plus `2,360` cell-mesh edge points, not strict-interior counterexamples.",
        "",
        structural_case_statement,
        "",
        "Where a point belongs to more than one cell within tolerance, all containing cells are retained. Owner-cell slack, active facets, violated facets, and strict-interior cell IDs are reported per sample.",
        "",
        "## Local directional fact and baseline slack",
        "",
        "At all 15 blocking memberships, the sampled positive registered-normal direction is locally adverse to the already-binding design-margin channel. This is an observed local fact, not a global mechanism proof.",
        "",
        f"Binding original-limit slack at `d=0` has min/median/max `{fmt(slack['min'])}/{fmt(slack['median'])}/{fmt(slack['max'])}` p.u. Each baseline slack is below the requested `1.5e-4` p.u. design headroom, so these are boundary-like blocking memberships with insufficient initial slack for the requested design headroom, not independent physical failures at `d=0`.",
        "",
        "## Limiting calibration ID audit",
        "",
        f"All `{counts['global_limiting_id_comparable_rows']}` edge rows are comparable through the executed anchor/escalation state transitions. There are `{counts['global_limiting_id_mismatches']}` mismatches, both blocker escalation rows and both numeric offset `+20`. The repeated offset is suspicious provenance evidence, not proof of a deterministic indexing bug.",
        "",
        "Committed `scripts/src/test` search finds schema declaration and producer-write references, but no downstream decision read. Thus the demonstrated code role is summary output; impact outside that search scope remains unresolved.",
        "",
        "## Unsampled reverse-direction hypothesis",
        "",
        f"`reverse_direction_linear_hypothesis.csv` contains `{counts['reverse_linear_hypotheses']}` first-order estimates using the `d=0` and first positive-`d` binding-margin samples. Every row is labeled `UNSAMPLED_REVERSE_DIRECTION_LINEAR_EXTRAPOLATION` and `ac_validated=false`. No negative-`d` AC call was made, and feasibility is not claimed.",
        "",
        "## Validation and epistemic boundary",
        "",
        "A clean byte-identical rerun is an external determinism check only; it does not establish scientific validity. Manifest, payload, generator, index, source-artifact, protected-file, and scope checks are performed separately from generation.",
        "",
        "This audit does not claim `TRUE_DIRECTIONAL_LIMITATION`, global monotonicity, a continuous crossing location, negative-direction AC feasibility, full-edge feasibility from one membership, blocker independence, `n_eff=2`, statistical significance, resolution failure ruled out, or an indexing bug proved by two `+20` offsets.",
        "",
        "## Output map",
        "",
        "- `blocker_trajectory_audit.csv`: one row per blocking membership, including baseline slack and stop provenance.",
        "- `trajectory_observations.csv`: every reconstructed/observed blocker trajectory sample.",
        "- `original_limit_sample_bounds.csv`: last sampled pass, first sampled fail, and unsampled interval bounds.",
        "- `blocker_edge_id_concentration.csv`: descriptive blocker distribution by edge ID.",
        "- `blocker_edge_geometric_relationships.csv`: endpoint-grounded relationships among unique blocker edge IDs.",
        "- `normal_orientation_audit.csv`: facet point, interior witness, signed orientation, convention, and tolerance.",
        "- `failing_point_full_cell_membership.csv`: every positive sample located against all committed full cells.",
        "- `limiting_calibration_id_global_audit.csv`: global recorded-vs-attempt-derived comparison.",
        "- `limiting_calibration_id_offset_summary.csv`: mismatch/match aggregation by population, phase, status, and offset.",
        "- `limiting_calibration_id_downstream_use.csv`: deterministic committed-code search results.",
        "- `reverse_direction_linear_hypothesis.csv`: unvalidated first-order reverse-direction hypotheses.",
        "- `generation_assertion_summary.csv`: epistemically labeled generation assertions and regression references.",
        "- `implementation_semantics_checks.csv`: exact executed-source logic matched by the generator.",
        "- `source_artifact_inventory.csv`, `hashes.sha256`, and `manifest.json`: immutable provenance and integrity metadata.",
        "",
    ]
    write_text(outdir / "report.md", "\n".join(report))

    hash_lines = [f"{sha256((outdir / name).read_bytes())}  {name}" for name in sorted(CONTENT_NAMES)]
    write_text(outdir / "hashes.sha256", "\n".join(hash_lines) + "\n")
    manifest_files = []
    for name in sorted(EXPECTED_NAMES - {"manifest.json"}):
        data = (outdir / name).read_bytes()
        item = {"path": name, "bytes": len(data), "sha256": sha256(data)}
        if name.endswith(".csv"):
            item["row_count"] = len(read_csv_bytes(data))
        manifest_files.append(item)
    manifest = {
        "artifact": "DSO_VPP_AC_BOUNDARY_HEADROOM_REPAIR_BLOCKER_EXTENDED_AUDIT",
        "schema_version": 1,
        "source_branch": SOURCE_BRANCH,
        "audit_base_commit": AUDIT_BASE_COMMIT,
        "calibration_commit": CALIBRATION_COMMIT,
        "preregistration_commit": PREREGISTRATION_COMMIT,
        "geometry_source_commit": GEOMETRY_SOURCE_COMMIT,
        "method": METHOD,
        "generator": {"path": GENERATOR_PATH, "sha256": sha256((ROOT / GENERATOR_PATH).read_bytes())},
        "counts": counts,
        "files": manifest_files,
    }
    write_text(outdir / "manifest.json", json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    print(f"wrote {outdir.relative_to(ROOT) if outdir.is_relative_to(ROOT) else outdir}")
    print(json.dumps(counts, sort_keys=True))
    return 0


def parse_hashes(data: bytes) -> dict[str, str]:
    result = {}
    for line in data.decode("utf-8").splitlines():
        digest, name = line.split("  ", 1)
        result[name] = digest
    return result


def verify_source_inventory(data: bytes) -> list[str]:
    mismatches = []
    for row in read_csv_bytes(data):
        actual = git_bytes(row["source_commit"], row["artifact_path"])
        if len(actual) != int(row["bytes"]) or sha256(actual) != row["sha256"]:
            mismatches.append(row["artifact_path"])
    return mismatches


def verify_disk(outdir: Path = OUTDIR) -> int:
    manifest = json.loads((outdir / "manifest.json").read_text(encoding="utf-8"))
    mismatches = []
    expected = {item["path"] for item in manifest["files"]} | {"manifest.json"}
    actual_names = {path.name for path in outdir.iterdir() if path.is_file()}
    if actual_names != expected:
        mismatches.append("unexpected_or_missing_files")
    for item in manifest["files"]:
        data = (outdir / item["path"]).read_bytes()
        if len(data) != item["bytes"] or sha256(data) != item["sha256"]:
            mismatches.append(item["path"])
    hash_mismatches = [
        name for name, digest in parse_hashes((outdir / "hashes.sha256").read_bytes()).items()
        if sha256((outdir / name).read_bytes()) != digest
    ]
    generator = manifest["generator"]
    generator_ok = (
        generator["path"] == GENERATOR_PATH
        and sha256((ROOT / GENERATOR_PATH).read_bytes()) == generator["sha256"]
    )
    source_mismatches = verify_source_inventory((outdir / "source_artifact_inventory.csv").read_bytes())
    print(f"manifest verification: {'PASS' if not mismatches else 'FAIL'}")
    print(f"hashes.sha256 verification: {'PASS' if not hash_mismatches else 'FAIL'}")
    print(f"generator SHA verification on disk: {'PASS' if generator_ok else 'FAIL'}")
    print(f"source-artifact verification: {'PASS' if not source_mismatches else 'FAIL'}")
    print(f"unexpected-file check: {'PASS' if actual_names == expected else 'FAIL'}")
    return 1 if mismatches or hash_mismatches or not generator_ok or source_mismatches else 0


def verify_index() -> int:
    manifest_path = f"{OUTDIR.relative_to(ROOT).as_posix()}/manifest.json"
    manifest = json.loads(staged_bytes(manifest_path).decode("utf-8"))
    mismatches = []
    for item in manifest["files"]:
        path = f"{OUTDIR.relative_to(ROOT).as_posix()}/{item['path']}"
        data = staged_bytes(path)
        if len(data) != item["bytes"] or sha256(data) != item["sha256"]:
            mismatches.append(path)
    staged_hashes = parse_hashes(staged_bytes(f"{OUTDIR.relative_to(ROOT).as_posix()}/hashes.sha256"))
    hash_mismatches = [
        name for name, digest in staged_hashes.items()
        if sha256(staged_bytes(f"{OUTDIR.relative_to(ROOT).as_posix()}/{name}")) != digest
    ]
    generator = manifest["generator"]
    generator_ok = (
        generator["path"] == GENERATOR_PATH
        and sha256(staged_bytes(GENERATOR_PATH)) == generator["sha256"]
    )
    source_path = f"{OUTDIR.relative_to(ROOT).as_posix()}/source_artifact_inventory.csv"
    source_mismatches = verify_source_inventory(staged_bytes(source_path))
    expected_paths = {GENERATOR_PATH, manifest_path} | {
        f"{OUTDIR.relative_to(ROOT).as_posix()}/{item['path']}" for item in manifest["files"]
    }
    staged_paths = set(
        git("diff", "--cached", "--name-only", "--diff-filter=ACMR").decode().splitlines()
    )
    unexpected_ok = staged_paths == expected_paths
    print(f"staged manifest verification: {'PASS' if not mismatches else 'FAIL'}")
    print(f"staged hashes.sha256 verification: {'PASS' if not hash_mismatches else 'FAIL'}")
    print(f"generator SHA verification in index: {'PASS' if generator_ok else 'FAIL'}")
    print(f"staged source-artifact verification: {'PASS' if not source_mismatches else 'FAIL'}")
    print(f"staged unexpected-file check: {'PASS' if unexpected_ok else 'FAIL'}")
    return 1 if mismatches or hash_mismatches or not generator_ok or source_mismatches or not unexpected_ok else 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=OUTDIR)
    parser.add_argument("--verify-disk", action="store_true")
    parser.add_argument("--verify-index", action="store_true")
    args = parser.parse_args()
    if args.verify_disk and args.verify_index:
        parser.error("choose only one verification mode")
    if args.verify_disk:
        return verify_disk(args.output_dir.resolve())
    if args.verify_index:
        return verify_index()
    return generate(args.output_dir.resolve())


if __name__ == "__main__":
    raise SystemExit(main())
