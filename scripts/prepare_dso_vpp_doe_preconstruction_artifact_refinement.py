#!/usr/bin/env python3
"""Artifact-only DOE preconstruction refinement for the production AC cloud.

The program reads completed CSV/JSON/source artifacts and never imports or calls
the AC implementation. Pair enumeration intentionally matches the completed
timestamp-local monotonicity falsification screen.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
import shutil
import statistics
import subprocess
import time
from collections import Counter, defaultdict
from decimal import Decimal
from pathlib import Path
from typing import Any

import numpy as np


EXPECTED_BRANCH = "codex/dso-vpp-ac-map-pilot"
EXPECTED_HEAD = "44cdad078b9503dfef6617c3585b99e7b014cdd9"
COORD_TOL_KW = 1e-9
PRIMARY_TOL_PU = 1e-11
PRIMARY_MAX_ITERATIONS = 2000
REPLAY_TOL_PU = 1e-12
REPLAY_MAX_ITERATIONS = 4000
REPLAY_VOLTAGE_MATCH_TOLERANCE_PU = 2e-5
ANCHOR = "2012-10-15 13:00:00"
CORNER = (934.6080433530186, 1610.2756675516089)
PAIR_DTYPE = np.dtype([("dvmin", "<f8"), ("dvmax", "<f8"), ("pair_class", "u1"), ("region", "u1")])
PAIR_CLASSES = {0: "EQUALITY_ONLY", 1: "P13_STRICT_ONLY", 2: "P30_STRICT_ONLY", 3: "STRICT_2D"}
REGIONS = {0: "WITHIN_AXIS_NORMALIZED_CORE", 1: "STRADDLING", 2: "BOTH_FARTHER"}
PERCENTILES = (("minimum_positive", None), ("p0_001", 0.00001), ("p0_01", 0.0001),
               ("p0_1", 0.001), ("p1", 0.01), ("p5", 0.05), ("median", 0.5))
THRESHOLDS = (1e-8, 1e-7, 1e-6, 1e-5, 2e-5)
BOUNDARY_BRACKET_WIDTH_KW = 1.0
ENDPOINT_VOLTAGE_DISTANCE_PU = 1e-5
MAXIMUM_BISECTION_REFINEMENTS = 60


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if fields is None:
        fields = list(rows[0]) if rows else []
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def git(root: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=root, check=True, text=True,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE).stdout.strip()


def f(value: str | float | int) -> float:
    return float(value)


def reconstruct_sensitivity_topology(root: Path, output: Path) -> dict[str, Any]:
    """Reconstruct the stored squared-voltage coefficients from raw case33bw data."""
    case_path = root / "data_raw/case33bw.m"
    lines = case_path.read_text(encoding="utf-8").splitlines()
    base_mva = None
    buses: dict[int, float] = {}
    branches: list[dict[str, Any]] = []
    section = None
    for source_line, raw_line in enumerate(lines, start=1):
        line = raw_line.strip()
        match = re.match(r"mpc\.baseMVA\s*=\s*([0-9.eE+-]+)\s*;", line)
        if match:
            base_mva = float(match.group(1))
        if line.startswith("mpc.bus = ["):
            section = "bus"
            continue
        if line.startswith("mpc.branch = ["):
            section = "branch"
            continue
        if section and line == "];":
            section = None
            continue
        if not section or not line or line.startswith("%"):
            continue
        fields = line.rstrip(";").split()
        if section == "bus" and len(fields) >= 13:
            buses[int(fields[0])] = float(fields[9])
        elif section == "branch" and len(fields) >= 11:
            branches.append({
                "branch_id": len(branches) + 1,
                "from_bus": int(fields[0]),
                "to_bus": int(fields[1]),
                "resistance_ohm": float(fields[2]),
                "status": int(fields[10]),
                "case33bw_source_line": source_line,
            })
    if base_mva != 10.0 or len(buses) != 33 or set(buses.values()) != {12.66}:
        raise SystemExit("unexpected case33bw base or bus data")
    active = [branch for branch in branches if branch["status"] == 1]
    if len(active) != len(buses) - 1 or any(branch["resistance_ohm"] <= 0 for branch in active):
        raise SystemExit("case33bw active network is not a positive-resistance radial candidate")
    parent = {}
    for branch in active:
        child = branch["to_bus"]
        if child in parent:
            raise SystemExit(f"multiple active parent branches for case33bw bus {child}")
        parent[child] = branch
    if set(parent) != set(buses) - {1}:
        raise SystemExit("case33bw active branches do not define one parent for every non-root bus")

    def root_path(bus: int) -> list[dict[str, Any]]:
        path = []
        seen = set()
        current = bus
        while current != 1:
            if current in seen or current not in parent:
                raise SystemExit(f"invalid case33bw root path for bus {bus}")
            seen.add(current)
            branch = parent[current]
            path.append(branch)
            current = branch["from_bus"]
        return list(reversed(path))

    target_buses = (13, 18, 30, 33)
    injection_buses = (13, 30)
    paths = {bus: root_path(bus) for bus in set(target_buses + injection_buses)}
    zbase_ohm = buses[1] ** 2 / base_mva
    stored_rows = read_csv(root / "results/dso_vpp_ac_map_pilot/ac_anchored_linear_corner_audit_corner_margins.csv")
    stored = {int(row["bus"]): row for row in stored_rows}
    rows = []
    for candidate_bus in target_buses:
        for injection_bus in injection_buses:
            injection_ids = {branch["branch_id"] for branch in paths[injection_bus]}
            shared = [branch for branch in paths[candidate_bus] if branch["branch_id"] in injection_ids]
            resistance_ohm = sum(branch["resistance_ohm"] for branch in shared)
            resistance_pu = resistance_ohm / zbase_ohm
            coefficient = 2.0 * resistance_pu
            field = f"coefficient_{injection_bus}_pu_per_pu"
            stored_coefficient = f(stored[candidate_bus][field])
            absolute_difference = abs(coefficient - stored_coefficient)
            rows.append({
                "coefficient": f"c_{candidate_bus}_{injection_bus}",
                "candidate_bus": candidate_bus,
                "injection_bus": injection_bus,
                "candidate_root_path_branch_ids": ";".join(str(branch["branch_id"]) for branch in paths[candidate_bus]),
                "injection_root_path_branch_ids": ";".join(str(branch["branch_id"]) for branch in paths[injection_bus]),
                "shared_root_path_branches": ";".join(
                    f"{branch['branch_id']}:{branch['from_bus']}->{branch['to_bus']}" for branch in shared
                ),
                "shared_case33bw_source_lines": ";".join(str(branch["case33bw_source_line"]) for branch in shared),
                "shared_resistance_sum_ohm": resistance_ohm,
                "base_mva": base_mva,
                "base_kv": buses[1],
                "zbase_ohm": zbase_ohm,
                "shared_resistance_sum_pu": resistance_pu,
                "historical_factor": 2.0,
                "topology_reconstructed_coefficient_pu_per_pu": coefficient,
                "stored_coefficient_pu_per_pu": stored_coefficient,
                "absolute_difference": absolute_difference,
                "relative_difference": absolute_difference / abs(stored_coefficient),
                "comparison_within_tolerance": absolute_difference <= 1e-12,
            })
    write_csv(output / "sensitivity_topology_reconstruction.csv", rows)
    by_name = {row["coefficient"]: row for row in rows}
    structural_specs = (
        ("c_18_13", "c_13_13"), ("c_18_30", "c_13_30"),
        ("c_33_13", "c_30_13"), ("c_33_30", "c_30_30"),
        ("c_13_30", "c_30_13"),
    )
    structural = []
    for left, right in structural_specs:
        difference = abs(
            by_name[left]["topology_reconstructed_coefficient_pu_per_pu"]
            - by_name[right]["topology_reconstructed_coefficient_pu_per_pu"]
        )
        structural.append({"relationship": f"{left} = {right}", "absolute_difference": difference,
                           "verified_within_tolerance": difference <= 1e-12})
    consistent = all(row["comparison_within_tolerance"] for row in rows) and all(
        row["verified_within_tolerance"] for row in structural
    )
    return {
        "classification": "SENSITIVITY_MATRIX_TOPOLOGY_CONSISTENT" if consistent else "SENSITIVITY_MATRIX_TOPOLOGY_INCONSISTENT",
        "source_network_data": case_path.relative_to(root).as_posix(),
        "source_network_sha256": sha256(case_path),
        "historical_convention_source": "src/benchmark/dso_vpp_export_side_axis_scan.jl: topology_coefficient",
        "historical_independent_reconstruction_source": "src/benchmark/dso_vpp_operating_point_provenance.jl: independent_coefficient",
        "convention": "c_ij = 2 * sum(r_ohm on shared root paths) / Zbase_ohm",
        "quantity": "squared-voltage p.u. response per active-power p.u.",
        "base_mva": base_mva, "base_kv": buses[1], "zbase_ohm": zbase_ohm,
        "coefficient_absolute_tolerance": 1e-12,
        "maximum_stored_vs_topology_absolute_difference": max(row["absolute_difference"] for row in rows),
        "root_paths": [{
            "bus": bus,
            "branch_ids": ";".join(str(branch["branch_id"]) for branch in paths[bus]),
            "branches": ";".join(f"{branch['from_bus']}->{branch['to_bus']}" for branch in paths[bus]),
        } for bus in target_buses],
        "coefficient_comparisons": rows,
        "structural_relationships": structural,
        "scope_limitation": "direct check of the stored LinDistFlow sensitivity construction only",
    }


def numeric_summary(values: list[float]) -> dict[str, float | int]:
    return {
        "count": len(values), "mean": statistics.fmean(values), "median": statistics.median(values),
        "std": statistics.stdev(values) if len(values) > 1 else 0.0,
        "min": min(values), "max": max(values),
    }


RESOLUTION_QUANTILES = (
    ("min", 0.0), ("Q01", 0.01), ("Q05", 0.05), ("Q25", 0.25),
    ("median", 0.5), ("Q75", 0.75), ("Q95", 0.95), ("Q99", 0.99), ("max", 1.0),
)


def type7_quantile(values: list[float], probability: float) -> float:
    """Deterministic Hyndman-Fan type-7 quantile (NumPy/R default)."""
    ordered = sorted(values)
    if not ordered:
        raise ValueError("quantile requires at least one value")
    index = probability * (len(ordered) - 1)
    lower = math.floor(index)
    upper = math.ceil(index)
    fraction = index - lower
    return ordered[lower] + fraction * (ordered[upper] - ordered[lower])


def resolution_distribution_row(group: str, rows: list[dict[str, Any]], field: str,
                                quantity: str, unit: str) -> dict[str, Any]:
    values = [f(row[field]) for row in rows]
    return {
        "group": group, "quantity": quantity, "unit": unit, "count": len(values),
        **{label: type7_quantile(values, probability) for label, probability in RESOLUTION_QUANTILES},
        "quantile_definition": "HYNDMAN_FAN_TYPE_7_LINEAR",
    }


def boundary_resolution_analysis(base: list[dict[str, str]], adaptive: list[dict[str, str]],
                                 axes: list[dict[str, str]], centers: dict[str, dict[str, float]],
                                 bounds: dict[str, dict[str, float]], endpoints: list[dict[str, str]],
                                 output: Path) -> dict[str, Any]:
    """Extract stored boundary brackets and map radial widths into physical coordinates."""
    endpoint_index = {
        (row["timestamp"], row["search_kind"], row["search_id"], row["endpoint_side"]): row
        for row in endpoints
    }

    def scales(timestamp: str) -> dict[str, float]:
        center, bound = centers[timestamp], bounds[timestamp]
        return {
            "p13_positive": bound["p13_max"] - center["p13"],
            "p13_negative": center["p13"] - bound["p13_min"],
            "p30_positive": bound["p30_max"] - center["p30"],
            "p30_negative": center["p30"] - bound["p30_min"],
        }

    physical, guards = [], []
    for source in base + adaptive:
        if source["status"] == "RAY_UNBOUNDED_WITHIN_GUARD":
            guards.append(source)
            continue
        if source["status"] != "RAY_CERTIFIED_BOUNDARY":
            raise SystemExit(f"unexpected ray status in resolution analysis: {source['status']}")
        timestamp = source["timestamp"]
        angle = f(source["angle_deg"])
        search_id = f"{angle:.6f}"
        safe_endpoint = endpoint_index.get((timestamp, "RAY", search_id, "SAFE"))
        violating_endpoint = endpoint_index.get((timestamp, "RAY", search_id, "VIOLATING"))
        if safe_endpoint is None or violating_endpoint is None:
            raise SystemExit(f"missing stored ray endpoints for {timestamp} angle {search_id}")
        safe_r, violating_r = f(source["safe_r"]), f(source["violating_r"])
        width_r = float(Decimal(source["violating_r"]) - Decimal(source["safe_r"]))
        if width_r <= 0 or safe_endpoint["radius"] != source["safe_r"] or violating_endpoint["radius"] != source["violating_r"]:
            raise SystemExit(f"ray endpoint mismatch for {timestamp} angle {search_id}")
        theta = math.radians(angle)
        cosine, sine = math.cos(theta), math.sin(theta)
        local_scales = scales(timestamp)
        sx = local_scales["p13_positive"] if cosine >= 0 else local_scales["p13_negative"]
        sy = local_scales["p30_positive"] if sine >= 0 else local_scales["p30_negative"]
        vx, vy = cosine * sx, sine * sy
        component_p13, component_p30 = width_r * vx, width_r * vy
        physical_length = math.hypot(component_p13, component_p30)
        if abs(physical_length - f(source["bracket_width_kw"])) > 1e-9:
            raise SystemExit(f"stored/derived physical ray width mismatch for {timestamp} angle {search_id}")
        physical.append({
            "timestamp": timestamp, "level": source["level"], "angle_deg": source["angle_deg"],
            "search_id": search_id, "final_feasible_r": source["safe_r"],
            "final_violating_r": source["violating_r"], "normalized_r_bracket_width": width_r,
            "bisection_steps": int(source["refinement_steps"]),
            "final_feasible_p13_kw": source["safe_p13_abs_kw"],
            "final_feasible_p30_kw": source["safe_p30_abs_kw"],
            "final_violating_p13_kw": source["violating_p13_abs_kw"],
            "final_violating_p30_kw": source["violating_p30_abs_kw"],
            "binding_mechanism": source["binding_mechanism"], "binding_bus": int(source["binding_bus"]),
            "direction_cosine": cosine, "direction_sine": sine,
            "signed_normalization_scale_p13_kw": sx, "signed_normalization_scale_p30_kw": sy,
            "delta_p13_bracket_component_kw": component_p13,
            "delta_p30_bracket_component_kw": component_p30,
            "physical_bracket_length_kw": physical_length,
            "resolution_classification": "BOUNDARY_LOCATION_BRACKETING_RESOLUTION",
        })
    if len(physical) != 1561 or len(guards) != 73:
        raise SystemExit(f"unexpected ray resolution populations physical={len(physical)} guards={len(guards)}")
    write_csv(output / "ray_boundary_resolution.csv", physical)

    ray_groups = {
        "ALL_PHYSICAL_RAYS": physical,
        "BASE": [row for row in physical if row["level"] == "BASE"],
        "ADAPTIVE": [row for row in physical if row["level"] == "ADAPTIVE"],
        "VMAX": [row for row in physical if row["binding_mechanism"] == "BINDING_VMAX"],
        "VMIN": [row for row in physical if row["binding_mechanism"] == "BINDING_VMIN"],
    }
    ray_distribution = []
    for group, selected in ray_groups.items():
        ray_distribution.append(resolution_distribution_row(
            group, selected, "normalized_r_bracket_width", "NORMALIZED_R_BRACKET_WIDTH", "normalized_r",
        ))
        ray_distribution.append(resolution_distribution_row(
            group, selected, "physical_bracket_length_kw", "PHYSICAL_BRACKET_LENGTH", "kW",
        ))
    for row in ray_distribution:
        row["source_termination_rule"] = "PHYSICAL_WIDTH_LE_1_KW_AND_BOTH_ACTIVE_LIMIT_ENDPOINT_DISTANCES_LE_1E-5_PU"
        row["empirical_asymmetry_classification"] = "VMAX_BOUNDARY_BRACKETS_COARSER_THAN_VMIN_IN_PRODUCTION"
    write_csv(output / "ray_boundary_resolution_distribution.csv", ray_distribution)

    axis_rows = []
    short_axis = {"P13_POSITIVE": "P13+", "P13_NEGATIVE": "P13-",
                  "P30_POSITIVE": "P30+", "P30_NEGATIVE": "P30-"}
    for source in axes:
        if source["status"] != "AXIS_CERTIFIED_BOUNDARY":
            raise SystemExit(f"unexpected signed-axis status: {source['status']}")
        timestamp, search_id = source["timestamp"], source["axis"]
        safe_endpoint = endpoint_index.get((timestamp, "AXIS", search_id, "SAFE"))
        violating_endpoint = endpoint_index.get((timestamp, "AXIS", search_id, "VIOLATING"))
        if safe_endpoint is None or violating_endpoint is None:
            raise SystemExit(f"missing stored signed-axis endpoints for {timestamp} {search_id}")
        safe_coordinate, violating_coordinate = f(source["safe_coordinate"]), f(source["violating_coordinate"])
        width = violating_coordinate - safe_coordinate
        if width <= 0 or abs(width - f(source["bracket_width_kw"])) > 1e-12:
            raise SystemExit(f"signed-axis bracket mismatch for {timestamp} {search_id}")
        coordinate_field = "p13_abs_kw" if source["axis_bus"] == "13" else "p30_abs_kw"
        axis_rows.append({
            "timestamp": timestamp, "axis_direction": short_axis[search_id], "search_id": search_id,
            "final_feasible_search_coordinate_kw": source["safe_coordinate"],
            "final_violating_search_coordinate_kw": source["violating_coordinate"],
            "final_feasible_signed_pcc_coordinate_kw": safe_endpoint[coordinate_field],
            "final_violating_signed_pcc_coordinate_kw": violating_endpoint[coordinate_field],
            "axis_bracket_width_kw": width, "bisection_steps": int(source["refinement_steps"]),
            "binding_mechanism": source["binding_mechanism"], "binding_bus": int(source["binding_bus"]),
            "resolution_classification": "AXIS_BOUNDARY_LOCATION_BRACKET_WIDTH",
        })
    if len(axis_rows) != 128:
        raise SystemExit(f"unexpected signed-axis resolution population: {len(axis_rows)}")
    write_csv(output / "axis_boundary_resolution.csv", axis_rows)
    axis_groups = {"ALL_SIGNED_AXES": axis_rows}
    axis_groups.update({label: [row for row in axis_rows if row["axis_direction"] == label]
                        for label in ("P13+", "P13-", "P30+", "P30-")})
    axis_distribution = [resolution_distribution_row(
        group, selected, "axis_bracket_width_kw", "AXIS_BOUNDARY_LOCATION_BRACKET_WIDTH", "kW",
    ) for group, selected in axis_groups.items()]
    for row in axis_distribution:
        row["source_termination_rule"] = "PHYSICAL_WIDTH_LE_1_KW_AND_BOTH_ACTIVE_LIMIT_ENDPOINT_DISTANCES_LE_1E-5_PU"
        row["empirical_asymmetry_classification"] = "VMAX_BOUNDARY_BRACKETS_COARSER_THAN_VMIN_IN_PRODUCTION"
    write_csv(output / "axis_boundary_resolution_distribution.csv", axis_distribution)

    cardinal_rows = [row.copy() for row in physical
                     if row["timestamp"] == ANCHOR and int(f(row["angle_deg"])) in (0, 90, 180, 270)]
    cardinal_rows.sort(key=lambda row: int(f(row["angle_deg"])))
    if len(cardinal_rows) != 4:
        raise SystemExit(f"unexpected anchor cardinal resolution records: {len(cardinal_rows)}")
    write_csv(output / "cardinal_boundary_resolution.csv", cardinal_rows)
    return {
        "interpretation": "BOUNDARY_LOCATION_CONSERVATIVE_BRACKET_WIDTH",
        "endpoint_classification": "CERTIFIED_FEASIBLE_INWARD_BRACKET_ENDPOINT",
        "endpoint_semantics": "The stored boundary cloud uses the certified-feasible side of each final AC bracket, yielding one-sided conservative boundary-location representatives along the individually searched trajectories.",
        "endpoint_limitation": "This property does not certify line segments, facets, convex combinations, or unsampled angular interiors between those endpoints.",
        "not_statistical_uncertainty": True,
        "cardinal_boundaries": cardinal_rows,
        "ray_population": {
            "total_ray_searches": len(base) + len(adaptive), "physical_ray_boundaries": len(physical),
            "guard_truncations": len(guards), "guard_classification": "GUARD_TRUNCATION_NO_PHYSICAL_BOUNDARY_BRACKET",
            "guard_base": sum(row["level"] == "BASE" for row in guards),
            "guard_adaptive": sum(row["level"] == "ADAPTIVE" for row in guards),
        },
        "ray_distributions": ray_distribution, "axis_distributions": axis_distribution,
        "doe_policy": {
            "distinction": "BOUNDARY_LOCATION_BRACKETING != FACET_INTERIOR_VALIDATION_RISK",
            "statement": "The bracket width quantifies unresolved outward distance between the stored certified-feasible endpoint and the first certified-infeasible endpoint after bisection. It is relevant to boundary-location precision but does not by itself determine the contraction required for facets connecting multiple feasible endpoints.",
            "permitted_uses": ["numerical tolerance selection", "avoiding meaningless sub-bracket geometric refinements", "interpreting very small differences between candidate facets", "defining numerical indistinguishability at the search resolution"],
            "prohibited_substitution": "MUST_NOT_SUBSTITUTE_FOR_AC_VALIDATION_OF_CANDIDATE_FACET_INTERIORS",
        },
    }


def boundary_bisection_termination_audit(production: Path, base: list[dict[str, str]],
                                         adaptive: list[dict[str, str]], axes: list[dict[str, str]],
                                         output: Path) -> dict[str, Any]:
    """Replay stored search metadata only; no AC implementation is imported or run."""
    attempts = read_csv(production / "evaluation_attempts.csv")
    final_attempt: dict[tuple[str, int], dict[str, str]] = {}
    for attempt in attempts:
        key = (attempt["timestamp"], int(attempt["logical_evaluation_id"]))
        if key not in final_attempt or int(attempt["attempt_index"]) > int(final_attempt[key]["attempt_index"]):
            final_attempt[key] = attempt
    histories: dict[tuple[str, str, str], list[dict[str, str]]] = defaultdict(list)
    for key in sorted(final_attempt):
        attempt = final_attempt[key]
        if attempt["search_kind"] in {"RAY", "AXIS"}:
            histories[(attempt["timestamp"], attempt["search_kind"], attempt["search_id"])].append(attempt)

    def is_safe(point: dict[str, str]) -> bool:
        return point["solver_status"] == "CONVERGED_FEASIBLE"

    def is_violating(point: dict[str, str]) -> bool:
        return point["solver_status"] == "CONVERGED_INFEASIBLE"

    def voltage_state(safe: dict[str, str], violating: dict[str, str]) -> dict[str, Any]:
        vmin, vmax = f(violating["vmin_pu"]), f(violating["vmax_pu"])
        lower, upper = vmin < 0.90, vmax > 1.05
        if lower and not upper:
            mechanism = "BINDING_VMIN"
        elif upper and not lower:
            mechanism = "BINDING_VMAX"
        elif lower and upper:
            mechanism = "BINDING_VMIN" if 0.90 - vmin >= vmax - 1.05 else "BINDING_VMAX"
        else:
            raise SystemExit("stored violating endpoint has no registered voltage violation")
        if mechanism == "BINDING_VMIN":
            safe_distance = f(safe["vmin_pu"]) - 0.90
            violating_distance = 0.90 - vmin
        else:
            safe_distance = 1.05 - f(safe["vmax_pu"])
            violating_distance = vmax - 1.05
        return {
            "mechanism": mechanism,
            "safe_voltage_distance_pu": safe_distance,
            "violating_voltage_distance_pu": violating_distance,
            "voltage_condition_met": safe_distance <= ENDPOINT_VOLTAGE_DISTANCE_PU
                                     and violating_distance <= ENDPOINT_VOLTAGE_DISTANCE_PU,
        }

    def inspect(result: dict[str, str], kind: str) -> dict[str, Any]:
        search_id = result["axis"] if kind == "AXIS" else f"{f(result['angle_deg']):.6f}"
        history = histories[(result["timestamp"], kind, search_id)]
        sweep = sorted((point for point in history if point["phase"].startswith("coarse_sweep")),
                       key=lambda point: f(point["coordinate"]))
        bracket = next(((sweep[index - 1], sweep[index]) for index in range(1, len(sweep))
                        if is_safe(sweep[index - 1]) and is_violating(sweep[index])), None)
        if bracket is None:
            raise SystemExit(f"missing stored initial adjacent bracket for {result['timestamp']} {kind} {search_id}")
        safe, violating = bracket
        initial_width = f(violating["coordinate"]) - f(safe["coordinate"])
        if kind == "AXIS":
            physical_width_per_coordinate = 1.0
        else:
            final_coordinate_width = f(result["violating_r"]) - f(result["safe_r"])
            physical_width_per_coordinate = f(result["bracket_width_kw"]) / final_coordinate_width

        def state(step: int) -> dict[str, Any]:
            coordinate_width = f(violating["coordinate"]) - f(safe["coordinate"])
            physical_width = coordinate_width * physical_width_per_coordinate
            voltage = voltage_state(safe, violating)
            return {
                "step": step,
                "coordinate_width": coordinate_width,
                "physical_width_kw": physical_width,
                "physical_width_condition_met": physical_width <= BOUNDARY_BRACKET_WIDTH_KW,
                **voltage,
            }

        states = [state(0)]
        bisection = [point for point in history if point["phase"] == "bisection"]
        for step, point in enumerate(bisection, start=1):
            if is_safe(point):
                safe = point
            elif is_violating(point):
                violating = point
            else:
                raise SystemExit(f"unresolved stored bisection point for {result['timestamp']} {kind} {search_id}")
            states.append(state(step))
        expected_steps = int(result["refinement_steps"])
        if len(bisection) != expected_steps:
            raise SystemExit(f"stored bisection-count mismatch for {result['timestamp']} {kind} {search_id}")
        final = states[-1]
        if not final["physical_width_condition_met"] or not final["voltage_condition_met"]:
            raise SystemExit(f"stored certified boundary fails source termination rule: {result['timestamp']} {kind} {search_id}")
        if expected_steps and states[-2]["physical_width_condition_met"] and states[-2]["voltage_condition_met"]:
            raise SystemExit(f"stored certified boundary continued after source termination rule: {result['timestamp']} {kind} {search_id}")
        return {
            "timestamp": result["timestamp"], "kind": kind, "search_id": search_id,
            "binding_mechanism": result["binding_mechanism"],
            "initial_coordinate_width": initial_width,
            "physical_width_per_coordinate": physical_width_per_coordinate,
            "states": states,
        }

    ray_records = [inspect(row, "RAY") for row in base + adaptive if row["status"] == "RAY_CERTIFIED_BOUNDARY"]
    axis_records = [inspect(row, "AXIS") for row in axes if row["status"] == "AXIS_CERTIFIED_BOUNDARY"]
    if len(ray_records) != 1561 or len(axis_records) != 128:
        raise SystemExit("unexpected certified-boundary population in termination audit")

    ray_levels = Counter(record["states"][-1]["step"] for record in ray_records)
    ray_mechanism_steps = Counter((record["binding_mechanism"], record["states"][-1]["step"])
                                  for record in ray_records)
    ray_preceding_conditions = Counter(
        (record["states"][-1]["step"], record["states"][-2]["physical_width_condition_met"],
         record["states"][-2]["voltage_condition_met"]) for record in ray_records
    )
    axis_widths = Counter((record["search_id"], record["states"][-1]["physical_width_kw"])
                          for record in axis_records)
    axis_initial_widths = Counter((record["search_id"], record["initial_coordinate_width"])
                                  for record in axis_records)
    anchor = {int(f(record["search_id"])): record for record in ray_records
              if record["timestamp"] == ANCHOR and int(f(record["search_id"])) in {0, 90, 180, 270}}

    candidate_classifications = [
        ("fixed normalized-r tolerance", "RULED_OUT_BY_CODE", "No normalized-r stopping tolerance exists."),
        ("physical-coordinate/kW tolerance", "SUPPORTED_BY_CODE", "The shared stop requires physical width <= 1.0 kW."),
        ("relative tolerance", "RULED_OUT_BY_CODE", "No relative bracket tolerance exists."),
        ("voltage residual/margin tolerance", "SUPPORTED_BY_CODE", "Both active-limit endpoint distances must be <= 1e-5 p.u."),
        ("maximum-iteration cap", "NOT_RELEVANT", "Observed certified rays stop after 7/8/9, far below the cap of 60."),
        ("mechanism-specific termination", "RULED_OUT_BY_CODE", "Both families call refine_boundary!; endpoint_voltage_close selects the active limit but uses the same 1e-5 threshold."),
        ("different ray initial bracket widths", "RULED_OUT_BY_CODE", "Every certified ray starts from an adjacent 0.05 normalized-r sweep bracket."),
        ("different signed normalization scales", "SUPPORTED_BY_CODE", "Ray physical width is normalized-r width times hypot(vx, vy), but equal anchor scales do not imply equal steps."),
        ("floating-point threshold crossing", "NOT_RELEVANT", "Stored preceding/final values cross explicit 1 kW and 1e-5 p.u. inequalities without a borderline equality."),
        ("another explicit condition", "SUPPORTED_BY_CODE", "The endpoint-voltage-distance conjunction explains continued halving after the physical-width condition is met."),
    ]
    audit_rows = [
        {"scope": "SHARED", "item": "refinement function", "value": "refine_boundary!", "classification": "SUPPORTED_BY_CODE", "source_location": "src/benchmark/dso_vpp_production_probe.jl:434"},
        {"scope": "SHARED", "item": "bisection update", "value": "midpoint=(safe.coordinate+violating.coordinate)/2; feasible replaces safe; infeasible replaces violating; unresolved aborts", "classification": "SUPPORTED_BY_CODE", "source_location": "src/benchmark/dso_vpp_production_probe.jl:442-451"},
        {"scope": "SHARED", "item": "termination", "value": "physical_width_kw <= 1.0 AND both active voltage-limit endpoint distances <= 1e-5 p.u.", "classification": "SUPPORTED_BY_CODE", "source_location": "src/benchmark/dso_vpp_production_probe.jl:421-441; config/dso_vpp_production_probe_preregistration.toml:146-151"},
        {"scope": "SHARED", "item": "iteration cap", "value": "60", "classification": "SUPPORTED_BY_CODE", "source_location": "src/benchmark/dso_vpp_production_probe.jl:437-458"},
        {"scope": "RAY", "item": "initial certified bracket", "value": "first adjacent converged-feasible/converged-infeasible pair in full r=0:0.05:2 sweep; width 0.05", "classification": "SUPPORTED_BY_CODE", "source_location": "src/benchmark/dso_vpp_production_probe.jl:413-418,698-738"},
        {"scope": "RAY", "item": "physical width conversion", "value": "(violating_r-safe_r)*hypot(vx,vy)", "classification": "SUPPORTED_BY_CODE", "source_location": "src/benchmark/dso_vpp_production_probe.jl:673-679,705-707,735-738"},
        {"scope": "AXIS", "item": "initial certified bracket", "value": "first adjacent converged-feasible/converged-infeasible pair in coarse sweep; delta=transition_scale/20", "classification": "SUPPORTED_BY_CODE", "source_location": "src/benchmark/dso_vpp_production_probe.jl:486-525"},
        {"scope": "AXIS", "item": "physical width conversion", "value": "(violating_coordinate-safe_coordinate)*1.0", "classification": "SUPPORTED_BY_CODE", "source_location": "src/benchmark/dso_vpp_production_probe.jl:522-525"},
    ]
    audit_rows.extend({"scope": "RAY_CANDIDATE", "item": name, "value": explanation,
                       "classification": classification, "source_location": "src/benchmark/dso_vpp_production_probe.jl:421-458,698-738"}
                      for name, classification, explanation in candidate_classifications)
    for steps in sorted(ray_levels):
        audit_rows.append({"scope": "RAY_LEVEL", "item": f"{steps} bisections",
                           "value": f"0.05/2^{steps}={0.05/(2**steps):.12g}; count={ray_levels[steps]}",
                           "classification": "SUPPORTED_BY_STORED_HISTORY", "source_location": "results/dso_vpp_ac_map_pilot/production_probe/evaluation_attempts.csv"})
    for angle in (0, 90, 180, 270):
        record = anchor[angle]
        for label, state in (("preceding", record["states"][-2]), ("final", record["states"][-1])):
            audit_rows.append({"scope": "ANCHOR_RAY", "item": f"{angle} deg {label} state",
                               "value": json.dumps(state, sort_keys=True, separators=(",", ":")),
                               "classification": "SUPPORTED_BY_STORED_HISTORY", "source_location": "results/dso_vpp_ac_map_pilot/production_probe/evaluation_attempts.csv"})
    audit_rows.extend([
        {"scope": "AXIS_LEVEL", "item": direction, "value": f"initial_width_counts={dict(sorted((width, count) for (axis, width), count in axis_initial_widths.items() if axis == direction))}; final_width_counts={dict(sorted((width, count) for (axis, width), count in axis_widths.items() if axis == direction))}", "classification": "SUPPORTED_BY_STORED_HISTORY", "source_location": "results/dso_vpp_ac_map_pilot/production_probe/signed_axis_results.csv"}
        for direction in ("P13_POSITIVE", "P13_NEGATIVE", "P30_POSITIVE", "P30_NEGATIVE")
    ])
    audit_rows.append({"scope": "CAUSE", "item": "VMAX/VMIN bracket asymmetry",
                       "value": "Shared termination combines physical geometry with endpoint-voltage threshold crossings; axis initial brackets also differ. No separate VMAX/VMIN refinement path exists.",
                       "classification": "VMAX_VMIN_BRACKET_ASYMMETRY_EXPLAINED_BY_BOTH_GEOMETRY_AND_TERMINATION",
                       "source_location": "src/benchmark/dso_vpp_production_probe.jl:421-458,471-560,698-763"})
    write_csv(output / "boundary_bisection_termination_audit.csv", audit_rows)
    return {
        "shared_implementation": {
            "function": "refine_boundary!", "source": "src/benchmark/dso_vpp_production_probe.jl:434-459",
            "coordinate_tolerance": None, "normalized_r_tolerance": None,
            "physical_kw_tolerance": BOUNDARY_BRACKET_WIDTH_KW,
            "endpoint_voltage_distance_pu": ENDPOINT_VOLTAGE_DISTANCE_PU,
            "maximum_bisection_refinements": MAXIMUM_BISECTION_REFINEMENTS,
            "rounding_serialization": "Production CSV floats use @sprintf(\"%.12g\"); the in-memory Float64 inequalities are evaluated before serialization.",
        },
        "ray": {
            "initial_bracket": "first adjacent feasible/infeasible pair in full 0:0.05:2 coarse sweep",
            "initial_normalized_r_width": 0.05,
            "final_level_counts": {str(steps): ray_levels[steps] for steps in sorted(ray_levels)},
            "mechanism_step_counts": {f"{mechanism}|{steps}": count for (mechanism, steps), count in sorted(ray_mechanism_steps.items())},
            "preceding_condition_counts": {f"steps={steps}|physical={physical}|voltage={voltage}": count
                                           for (steps, physical, voltage), count in sorted(ray_preceding_conditions.items())},
            "candidate_classifications": [{"candidate": name, "classification": classification, "explanation": explanation}
                                          for name, classification, explanation in candidate_classifications],
            "anchor_threshold_crossings": {str(angle): {"physical_scale_kw_per_r": anchor[angle]["physical_width_per_coordinate"],
                                                         "preceding": anchor[angle]["states"][-2], "final": anchor[angle]["states"][-1]}
                                           for angle in (0, 90, 180, 270)},
        },
        "axis": {
            "initial_bracket": "first adjacent feasible/infeasible pair in coarse sweep with delta=transition_scale/20",
            "initial_width_counts_by_direction": {direction: {str(width): count for (axis, width), count in sorted(axis_initial_widths.items()) if axis == direction}
                                                   for direction in ("P13_POSITIVE", "P13_NEGATIVE", "P30_POSITIVE", "P30_NEGATIVE")},
            "final_width_counts_by_direction": {direction: {str(width): count for (axis, width), count in sorted(axis_widths.items()) if axis == direction}
                                                 for direction in ("P13_POSITIVE", "P13_NEGATIVE", "P30_POSITIVE", "P30_NEGATIVE")},
            "p30_positive_explanation": "P30+ initial brackets are 160 or 320 kW; the shared voltage condition becomes true at 0.625 or 0.3125 kW, so no P30+ search performs the additional halving needed to reach 0.15625 kW.",
            "stored_binding_sides": "Positive signed axes are BINDING_VMAX and negative signed axes are BINDING_VMIN for all 128 completed certified searches.",
        },
        "empirical_classification": "VMAX_BOUNDARY_BRACKETS_COARSER_THAN_VMIN_IN_PRODUCTION",
        "cause_classification": "VMAX_VMIN_BRACKET_ASYMMETRY_EXPLAINED_BY_BOTH_GEOMETRY_AND_TERMINATION",
        "separate_vmax_vmin_code_path": False,
    }


def verify_manifest(directory: Path, required: list[str]) -> list[dict[str, Any]]:
    manifest = {row["artifact"]: row["sha256"] for row in read_csv(directory / "artifact_manifest.csv")}
    inputs = []
    for name in required:
        path = directory / name
        digest = sha256(path)
        if name in manifest and manifest[name] != digest:
            raise SystemExit(f"artifact hash mismatch: {path}")
        inputs.append({"path": path.as_posix(), "bytes": path.stat().st_size, "sha256": digest,
                       "schema": list(read_csv(path)[0]) if path.suffix == ".csv" else None})
    return inputs


def load_population(production: Path) -> tuple[dict[str, list[dict[str, Any]]], dict[str, dict[str, float]], dict[str, dict[str, float]], dict[str, int]]:
    raw = read_csv(production / "evaluation_attempts.csv")
    by_time: dict[str, list[dict[str, Any]]] = defaultdict(list)
    excluded: Counter[str] = Counter()
    for row in raw:
        if row["solver_status"] not in ("CONVERGED_FEASIBLE", "CONVERGED_INFEASIBLE"):
            excluded[row["solver_status"]] += 1
            continue
        point = {
            "attempt_id": int(row["attempt_id"]), "logical_id": int(row["logical_evaluation_id"]),
            "attempt_index": int(row["attempt_index"]), "timestamp": row["timestamp"],
            "search_kind": row["search_kind"], "search_id": row["search_id"], "phase": row["phase"],
            "p13": f(row["p13_abs_kw"]), "p30": f(row["p30_abs_kw"]),
            "vmin": f(row["vmin_pu"]), "vmax": f(row["vmax_pu"]),
            "vmin_bus": int(row["vmin_bus"]), "vmax_bus": int(row["vmax_bus"]),
            "initialization": row["initialization"],
            "initialization_source_logical_id": row["initialization_source_logical_id"],
        }
        if not all(math.isfinite(point[k]) for k in ("p13", "p30", "vmin", "vmax")):
            raise SystemExit(f"nonfinite converged point {point['attempt_id']}")
        by_time[row["timestamp"]].append(point)
    centers = {row["timestamp"]: {"p13": f(row["p13_abs_kw"]), "p30": f(row["p30_abs_kw"])}
               for row in read_csv(production / "center_results.csv")}
    bounds: dict[str, dict[str, float]] = defaultdict(dict)
    keys = {"P13_NEGATIVE": "p13_min", "P13_POSITIVE": "p13_max",
            "P30_NEGATIVE": "p30_min", "P30_POSITIVE": "p30_max"}
    for row in read_csv(production / "signed_axis_results.csv"):
        if row["status"] != "AXIS_CERTIFIED_BOUNDARY":
            raise SystemExit("rho normalization requires certified signed axes")
        bounds[row["timestamp"]][keys[row["axis"]]] = f(row["official_boundary_p_pcc_kw"])
    for timestamp, points in by_time.items():
        c, b = centers[timestamp], bounds[timestamp]
        denominators = (b["p13_max"] - c["p13"], c["p13"] - b["p13_min"],
                        b["p30_max"] - c["p30"], c["p30"] - b["p30_min"])
        if not all(x > 0 for x in denominators):
            raise SystemExit(f"invalid rho normalization at {timestamp}")
        for point in points:
            z13 = (point["p13"] - c["p13"]) / (denominators[0] if point["p13"] >= c["p13"] else denominators[1])
            z30 = (point["p30"] - c["p30"]) / (denominators[2] if point["p30"] >= c["p30"] else denominators[3])
            point["rho"] = max(abs(z13), abs(z30))
    usable = sum(map(len, by_time.values()))
    if len(raw) != 87372 or usable != 87086 or sum(excluded.values()) != 286 or len(by_time) != 32:
        raise SystemExit(f"unexpected population stored={len(raw)} usable={usable} excluded={dict(excluded)} times={len(by_time)}")
    return by_time, centers, bounds, dict(sorted(excluded.items()))


def duplicate_groups(points: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    n = len(points)
    parent, size = list(range(n)), [1] * n
    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i
    def union(a: int, b: int) -> None:
        a, b = find(a), find(b)
        if a == b:
            return
        if size[a] < size[b]:
            a, b = b, a
        parent[b], size[a] = a, size[a] + size[b]
    order = sorted(range(n), key=lambda i: (points[i]["p13"], points[i]["p30"], points[i]["attempt_id"]))
    for pos, left in enumerate(order):
        for right in order[pos + 1:]:
            if points[right]["p13"] - points[left]["p13"] > COORD_TOL_KW:
                break
            if abs(points[right]["p30"] - points[left]["p30"]) <= COORD_TOL_KW:
                union(left, right)
    groups: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for i, point in enumerate(points):
        groups[find(i)].append(point)
    return [group for group in groups.values() if len(group) > 1]


def audit_duplicates(by_time: dict[str, list[dict[str, Any]]], output: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    rows, combo_counts = [], Counter()
    group_id = 0
    for timestamp in sorted(by_time):
        for group in sorted(duplicate_groups(by_time[timestamp]), key=lambda g: (g[0]["p13"], g[0]["p30"])):
            group_id += 1
            provenance = sorted({f"{p['search_kind']}|{p['search_id']}|{p['phase']}|attempt{p['attempt_index']}|{p['initialization']}" for p in group})
            combo = " || ".join(provenance)
            combo_counts[combo] += 1
            rows.append({
                "duplicate_group_id": group_id, "timestamp": timestamp,
                "p13_abs_kw": min(p["p13"] for p in group), "p30_abs_kw": min(p["p30"] for p in group),
                "evaluation_count": len(group), "excess_evaluation_count": len(group) - 1,
                "Vmin_spread_pu": max(p["vmin"] for p in group) - min(p["vmin"] for p in group),
                "Vmax_spread_pu": max(p["vmax"] for p in group) - min(p["vmax"] for p in group),
                "attempt_ids": ";".join(str(p["attempt_id"]) for p in sorted(group, key=lambda x: x["attempt_id"])),
                "provenance_combination": combo,
            })
    write_csv(output / "duplicate_coordinate_reproducibility.csv", rows)
    combo_rows = [{"provenance_combination": combo, "duplicate_group_count": count}
                  for combo, count in sorted(combo_counts.items(), key=lambda item: (-item[1], item[0]))]
    write_csv(output / "duplicate_provenance_combinations.csv", combo_rows,
              ["provenance_combination", "duplicate_group_count"])
    summary = {
        "classification": "SCALAR_VOLTAGE_EXTREMA_REPRODUCIBILITY_SUPPORTED",
        "number_of_duplicate_groups": len(rows),
        "number_of_duplicate_evaluations": sum(row["excess_evaluation_count"] for row in rows),
        "duplicate_rows_participating": sum(row["evaluation_count"] for row in rows),
        "groups_with_nonzero_Vmin_spread": sum(row["Vmin_spread_pu"] != 0 for row in rows),
        "groups_with_nonzero_Vmax_spread": sum(row["Vmax_spread_pu"] != 0 for row in rows),
        "maximum_Vmin_spread": max(row["Vmin_spread_pu"] for row in rows),
        "maximum_Vmax_spread": max(row["Vmax_spread_pu"] for row in rows),
        "full_voltage_vector_claimed": False,
    }
    return summary, rows


def enumerate_pairs(by_time: dict[str, list[dict[str, Any]]], temp: Path) -> tuple[dict[str, Any], int, dict[str, Any]]:
    counts = {"ALL": Counter(), **{name: Counter() for name in REGIONS.values()}}
    zero_counts = {"Vmin": Counter(), "Vmax": Counter()}
    zero_bus_pairs = {"Vmin": Counter(), "Vmax": Counter()}
    zero_bus_value_combinations = {"Vmin": Counter(), "Vmax": Counter()}
    zero_values = {"Vmin": Counter(), "Vmax": Counter()}
    pair_path = temp / "non_equality_pairs.bin"
    total_records = 0
    with pair_path.open("wb") as binary:
        for timestamp in sorted(by_time):
            points = sorted(by_time[timestamp], key=lambda p: (p["p13"], p["p30"], p["attempt_id"]))
            trajectories = sorted({(p["search_kind"], p["search_id"]) for p in points})
            trajectory_id = {key: i for i, key in enumerate(trajectories)}
            a = {
                "p13": np.asarray([p["p13"] for p in points]), "p30": np.asarray([p["p30"] for p in points]),
                "vmin": np.asarray([p["vmin"] for p in points]), "vmax": np.asarray([p["vmax"] for p in points]),
                "vmin_bus": np.asarray([p["vmin_bus"] for p in points], dtype=np.int16),
                "vmax_bus": np.asarray([p["vmax_bus"] for p in points], dtype=np.int16),
                "rho": np.asarray([p["rho"] for p in points]),
                "trajectory": np.asarray([trajectory_id[(p["search_kind"], p["search_id"])] for p in points]),
            }
            def process(ai: np.ndarray, bi: np.ndarray) -> None:
                nonlocal total_records
                if ai.size == 0:
                    return
                cross = a["trajectory"][ai] != a["trajectory"][bi]
                ai, bi = ai[cross], bi[cross]
                if ai.size == 0:
                    return
                d13, d30 = a["p13"][bi] - a["p13"][ai], a["p30"][bi] - a["p30"][ai]
                eq13, eq30 = np.abs(d13) <= COORD_TOL_KW, np.abs(d30) <= COORD_TOL_KW
                cls = np.full(ai.size, 255, dtype=np.uint8)
                cls[eq13 & eq30] = 0
                cls[(d13 > COORD_TOL_KW) & eq30] = 1
                cls[eq13 & (d30 > COORD_TOL_KW)] = 2
                cls[(d13 > COORD_TOL_KW) & (d30 > COORD_TOL_KW)] = 3
                if np.any(cls == 255):
                    raise SystemExit("pair failed coordinate-class partition")
                near_a, near_b = a["rho"][ai] <= 1.0, a["rho"][bi] <= 1.0
                region = np.where(near_a & near_b, 0, np.where(near_a ^ near_b, 1, 2)).astype(np.uint8)
                for class_id, name in PAIR_CLASSES.items():
                    mask = cls == class_id
                    n = int(np.count_nonzero(mask))
                    counts["ALL"][name] += n
                    for region_id, region_name in REGIONS.items():
                        counts[region_name][name] += int(np.count_nonzero(mask & (region == region_id)))
                keep = cls != 0
                if np.any(keep):
                    kept_ai, kept_bi = ai[keep], bi[keep]
                    records = np.empty(int(np.count_nonzero(keep)), dtype=PAIR_DTYPE)
                    records["dvmin"] = a["vmin"][kept_bi] - a["vmin"][kept_ai]
                    records["dvmax"] = a["vmax"][kept_bi] - a["vmax"][kept_ai]
                    records["pair_class"] = cls[keep]
                    records["region"] = region[keep]
                    if np.any(records["dvmin"] < 0) or np.any(records["dvmax"] < 0):
                        raise SystemExit("negative scalar delta found in non-equality primary evidence")
                    for label, metric, value_key, bus_key in (
                        ("Vmin", "dvmin", "vmin", "vmin_bus"),
                        ("Vmax", "dvmax", "vmax", "vmax_bus"),
                    ):
                        zero = records[metric] == 0
                        if not np.any(zero):
                            continue
                        va, vb = a[value_key][kept_ai[zero]], a[value_key][kept_bi[zero]]
                        ba, bb = a[bus_key][kept_ai[zero]], a[bus_key][kept_bi[zero]]
                        z = zero_counts[label]
                        z["zero_pairs_total"] += len(va)
                        z["both_endpoints_bus_1"] += int(np.count_nonzero((ba == 1) & (bb == 1)))
                        z["both_endpoints_value_exactly_1pu"] += int(np.count_nonzero((va == 1.0) & (vb == 1.0)))
                        z["both_bus_1_and_value_exactly_1pu"] += int(np.count_nonzero((ba == 1) & (bb == 1) & (va == 1.0) & (vb == 1.0)))
                        z["one_endpoint_bus_1_only"] += int(np.count_nonzero((ba == 1) ^ (bb == 1)))
                        neither = (ba != 1) & (bb != 1)
                        z["neither_endpoint_bus_1"] += int(np.count_nonzero(neither))
                        z["same_non_slack_bus"] += int(np.count_nonzero(neither & (ba == bb)))
                        z["different_non_slack_buses"] += int(np.count_nonzero(neither & (ba != bb)))
                        z["same_bus"] += int(np.count_nonzero(ba == bb))
                        z["different_buses"] += int(np.count_nonzero(ba != bb))
                        bus_pairs = np.rec.fromarrays((ba, bb), names="bus_a,bus_b")
                        unique, frequency = np.unique(bus_pairs, return_counts=True)
                        for item, count in zip(unique, frequency):
                            zero_bus_pairs[label][(int(item.bus_a), int(item.bus_b))] += int(count)
                        exact_values, frequency = np.unique(va, return_counts=True)
                        for value, count in zip(exact_values, frequency):
                            zero_values[label][float(value)] += int(count)
                        combinations = np.rec.fromarrays((ba, bb, va), names="bus_a,bus_b,value")
                        unique, frequency = np.unique(combinations, return_counts=True)
                        for item, count in zip(unique, frequency):
                            zero_bus_value_combinations[label][(int(item.bus_a), int(item.bus_b), float(item.value))] += int(count)
                    records.tofile(binary)
                    total_records += len(records)
            for right in range(1, len(points)):
                prior = np.arange(right, dtype=np.int32)
                forward = a["p30"][:right] <= a["p30"][right] + COORD_TOL_KW
                fai = prior[forward]
                process(fai, np.full(fai.size, right, dtype=np.int32))
                reverse = ((a["p13"][right] - a["p13"][:right] <= COORD_TOL_KW) &
                           (a["p30"][right] <= a["p30"][:right] + COORD_TOL_KW))
                rbi = prior[reverse]
                process(np.full(rbi.size, right, dtype=np.int32), rbi)
    total = sum(counts["ALL"].values())
    if total != 50641519 or total_records != total - counts["ALL"]["EQUALITY_ONLY"]:
        raise SystemExit(f"pair count mismatch total={total} records={total_records} counts={counts['ALL']}")
    if sum(sum(counts[r].values()) for r in REGIONS.values()) != total:
        raise SystemExit("region pair decomposition mismatch")
    if zero_counts["Vmin"]["zero_pairs_total"] != 56751 or zero_counts["Vmax"]["zero_pairs_total"] != 9255817:
        raise SystemExit(f"unexpected zero-delta counts: {zero_counts}")
    zero_summary: dict[str, Any] = {}
    for label in ("Vmin", "Vmax"):
        zero_summary[label] = {
            **dict(zero_counts[label]),
            "stored_exact_equality_criterion": f"parsed IEEE-754 float {label}_a == {label}_b; exactly 1 p.u. means parsed value == 1.0",
            "unique_exact_stored_zero_pair_values": len(zero_values[label]),
            "top_bus_pairs": [
                {f"{label.lower()}_bus_a": buses[0], f"{label.lower()}_bus_b": buses[1], "count": count}
                for buses, count in zero_bus_pairs[label].most_common(20)
            ],
            "top_bus_value_combinations": [
                {f"{label.lower()}_bus_a": key[0], f"{label.lower()}_bus_b": key[1],
                 f"{label}_a": key[2], f"{label}_b": key[2], "count": count}
                for key, count in zero_bus_value_combinations[label].most_common(20)
            ],
            "top_exact_stored_values": [
                {f"{label}_a": value, f"{label}_b": value, "count": count}
                for value, count in zero_values[label].most_common(20)
            ],
        }
    zero_summary["Vmax"].update({
        "classification": "SLACK_PINNED_VMAX_NON_INFORMATIVE_FOR_RESPONSE_STRENGTH",
        "Vmax_non_equality_pairs": total_records,
        "Vmax_slack_pinned_zero_pairs": zero_counts["Vmax"]["both_bus_1_and_value_exactly_1pu"],
        "Vmax_non_slack_or_positive_response_pairs": total_records - zero_counts["Vmax"]["both_bus_1_and_value_exactly_1pu"],
    })
    zero_summary["Vmin"].update({
        "classification": "SLACK_PINNED_VMIN_NON_INFORMATIVE_FOR_RESPONSE_STRENGTH",
        "Vmin_non_equality_pairs": total_records,
        "Vmin_slack_pinned_zero_pairs": zero_counts["Vmin"]["both_bus_1_and_value_exactly_1pu"],
        "Vmin_non_slack_or_positive_response_pairs": total_records - zero_counts["Vmin"]["both_bus_1_and_value_exactly_1pu"],
    })
    return {key: dict(value) for key, value in counts.items()}, total_records, zero_summary


def write_zero_delta_decomposition(zero_summary: dict[str, Any], output: Path) -> None:
    rows: list[dict[str, Any]] = []
    for label in ("Vmax", "Vmin"):
        summary = zero_summary[label]
        for category in (
            "zero_pairs_total", "both_endpoints_bus_1", "both_endpoints_value_exactly_1pu",
            "both_bus_1_and_value_exactly_1pu", "one_endpoint_bus_1_only", "neither_endpoint_bus_1",
            "same_non_slack_bus", "different_non_slack_buses", "same_bus", "different_buses",
        ):
            rows.append({"voltage_statistic": label, "record_type": "SUMMARY_CATEGORY",
                         "category": category, "count": summary[category], "criterion": summary["stored_exact_equality_criterion"]})
        for item in summary["top_bus_value_combinations"]:
            rows.append({"voltage_statistic": label, "record_type": "DOMINANT_BUS_VALUE_COMBINATION",
                         "category": "zero_delta_exact_stored_value", "count": item["count"],
                         "bus_a": item[f"{label.lower()}_bus_a"], "bus_b": item[f"{label.lower()}_bus_b"],
                         "value_a": item[f"{label}_a"], "value_b": item[f"{label}_b"],
                         "criterion": summary["stored_exact_equality_criterion"]})
    write_csv(output / "zero_delta_voltage_decomposition.csv", rows,
              ["voltage_statistic", "record_type", "category", "bus_a", "bus_b", "value_a", "value_b", "count", "criterion"])


def exact_positive_scale(records: np.memmap, metric: str, selector: np.ndarray, temp: Path) -> dict[str, Any]:
    values = records[metric]
    positive_count = 0
    zero_count = 0
    threshold_counts = {threshold: 0 for threshold in THRESHOLDS}
    chunk = 2_000_000
    for start in range(0, len(records), chunk):
        stop = min(start + chunk, len(records))
        mask = selector[start:stop]
        selected = values[start:stop][mask]
        positive_count += int(np.count_nonzero(selected > 0))
        zero_count += int(np.count_nonzero(selected == 0))
        for threshold in THRESHOLDS:
            threshold_counts[threshold] += int(np.count_nonzero((selected > 0) & (selected <= threshold)))
    result: dict[str, Any] = {"pair_count": int(np.count_nonzero(selector)),
                              "positive_count": positive_count, "zero_count": zero_count}
    result.update({f"count_0_lt_delta_le_{threshold:.0e}": count for threshold, count in threshold_counts.items()})
    if positive_count == 0:
        result.update({name: None for name, _ in PERCENTILES})
        return result
    scratch_path = temp / f"positive_{metric}.bin"
    scratch = np.memmap(scratch_path, dtype="<f8", mode="w+", shape=(positive_count,))
    cursor = 0
    for start in range(0, len(records), chunk):
        stop = min(start + chunk, len(records))
        selected = values[start:stop][selector[start:stop]]
        selected = selected[selected > 0]
        scratch[cursor:cursor + len(selected)] = selected
        cursor += len(selected)
    positions = []
    for _, probability in PERCENTILES:
        if probability is not None:
            x = (positive_count - 1) * probability
            positions.extend((math.floor(x), math.ceil(x)))
    kth = sorted(set([0, *positions]))
    scratch.partition(kth)
    result["minimum_positive"] = float(scratch[0])
    result["count_at_exact_minimum_positive"] = int(np.count_nonzero(scratch == scratch[0]))
    for name, probability in PERCENTILES:
        if probability is None:
            continue
        x = (positive_count - 1) * probability
        lower, upper = math.floor(x), math.ceil(x)
        weight = x - lower
        result[name] = float((1.0 - weight) * scratch[lower] + weight * scratch[upper])
        if name == "p0_001":
            result.update({
                "p0_001_requested_percentile_label": "0.001%",
                "p0_001_quantile_probability": probability,
                "p0_001_zero_based_fractional_index": x,
                "p0_001_zero_based_lower_index": lower,
                "p0_001_zero_based_upper_index": upper,
                "p0_001_one_based_lower_rank": lower + 1,
                "p0_001_one_based_upper_rank": upper + 1,
                "p0_001_interpolation_weight_on_upper": weight,
                "p0_001_lower_rank_value": float(scratch[lower]),
                "p0_001_upper_rank_value": float(scratch[upper]),
                "p0_001_quantile_interpolation_method": "Hyndman-Fan type 7 linear interpolation (NumPy default linear method)",
            })
    if result["p0_001"] == result["minimum_positive"] and result["count_at_exact_minimum_positive"] >= result["p0_001_one_based_upper_rank"]:
        result["p0_001_audit_classification"] = "PERCENTILE_RESULT_VALID_DUE_TO_TIES"
    elif result["p0_001_lower_rank_value"] != result["p0_001_upper_rank_value"]:
        result["p0_001_audit_classification"] = "PERCENTILE_INTERPOLATION_EFFECT"
    else:
        result["p0_001_audit_classification"] = "PERCENTILE_RESULT_VALID_AT_REQUESTED_RANK"
    del scratch
    scratch_path.unlink()
    return result


def separation_scales(temp: Path, record_count: int, output: Path) -> list[dict[str, Any]]:
    records = np.memmap(temp / "non_equality_pairs.bin", dtype=PAIR_DTYPE, mode="r", shape=(record_count,))
    slices = [("COORDINATE_CLASS", "ALL_NON_EQUALITY", np.ones(record_count, dtype=bool))]
    slices += [("COORDINATE_CLASS", name, records["pair_class"] == class_id)
               for class_id, name in PAIR_CLASSES.items() if class_id != 0]
    slices += [("RHO_REGION", name, records["region"] == region_id) for region_id, name in REGIONS.items()]
    rows = []
    for dimension, name, selector in slices:
        for metric in ("dvmin", "dvmax"):
            summary = exact_positive_scale(records, metric, selector, temp)
            rows.append({"scientific_name": "EMPIRICAL_SEPARATION_SCALE", "slice_dimension": dimension,
                         "slice": name, "voltage_statistic": "Delta_Vmin" if metric == "dvmin" else "Delta_Vmax",
                         **summary, "percentile_definition": "positive deltas only; deterministic NumPy type-7 linear quantile"})
    write_csv(output / "separation_scale_summary.csv", rows)
    del records
    return rows


def percentile_audit(separation: list[dict[str, Any]], output: Path) -> list[dict[str, Any]]:
    rows = []
    for statistic in ("Delta_Vmax", "Delta_Vmin"):
        source = next(row for row in separation if row["slice"] == "ALL_NON_EQUALITY" and row["voltage_statistic"] == statistic)
        rows.append({
            "voltage_statistic": statistic,
            "exact_minimum_positive": source["minimum_positive"],
            "count_at_exact_minimum_positive": source["count_at_exact_minimum_positive"],
            "positive_population_size": source["positive_count"],
            "requested_percentile_label": source["p0_001_requested_percentile_label"],
            "quantile_probability_actually_used": source["p0_001_quantile_probability"],
            "zero_based_fractional_index": source["p0_001_zero_based_fractional_index"],
            "zero_based_lower_index": source["p0_001_zero_based_lower_index"],
            "zero_based_upper_index": source["p0_001_zero_based_upper_index"],
            "one_based_lower_rank": source["p0_001_one_based_lower_rank"],
            "one_based_upper_rank": source["p0_001_one_based_upper_rank"],
            "interpolation_weight_on_upper": source["p0_001_interpolation_weight_on_upper"],
            "lower_rank_value": source["p0_001_lower_rank_value"],
            "upper_rank_value": source["p0_001_upper_rank_value"],
            "reported_quantile_value": source["p0_001"],
            "quantile_interpolation_method": source["p0_001_quantile_interpolation_method"],
            "classification": source["p0_001_audit_classification"],
            "label_implementation_check": "CONSISTENT: 0.001% = probability 0.00001; probability 0.001 would be 0.1%",
        })
    write_csv(output / "percentile_audit.csv", rows)
    return rows


def write_pair_summary(counts: dict[str, dict[str, int]], output: Path) -> list[dict[str, Any]]:
    rows = []
    for region in ("ALL", *REGIONS.values()):
        c = counts[region]
        rows.append({"rho_region": region, "cross_trajectory_pairs_total": sum(c.values()),
                     "equality_only_pairs": c["EQUALITY_ONLY"], "P13_strict_only_pairs": c["P13_STRICT_ONLY"],
                     "P30_strict_only_pairs": c["P30_STRICT_ONLY"], "strict_2D_pairs": c["STRICT_2D"],
                     "principal_non_equality_monotonicity_evidence_pairs": sum(c.values()) - c["EQUALITY_ONLY"]})
    write_csv(output / "pair_class_summary.csv", rows)
    return rows


def count_distinct_coordinates(rows: list[dict[str, Any]]) -> tuple[int, int, int]:
    """Return distinct coordinate clusters, duplicate outcomes, and cross-source overlap clusters."""
    clusters: list[list[dict[str, Any]]] = []
    by_time: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_time[row["timestamp"]].append(row)
    for timestamp in sorted(by_time):
        local: list[list[dict[str, Any]]] = []
        for row in sorted(by_time[timestamp], key=lambda item: (item["p13"], item["p30"], item["source"])):
            match = next((cluster for cluster in local
                          if abs(cluster[0]["p13"] - row["p13"]) <= COORD_TOL_KW
                          and abs(cluster[0]["p30"] - row["p30"]) <= COORD_TOL_KW), None)
            if match is None:
                local.append([row])
            else:
                match.append(row)
        clusters.extend(local)
    overlap = sum(len({row["source"] for row in cluster}) > 1 for cluster in clusters)
    return len(clusters), len(rows) - len(clusters), overlap


def boundary_input_reconciliation(axis: list[dict[str, str]], base: list[dict[str, str]],
                                  adaptive: list[dict[str, str]], output: Path) -> dict[str, Any]:
    ray_physical = [row for row in base + adaptive if row["status"] == "RAY_CERTIFIED_BOUNDARY"]
    guards = [row for row in base + adaptive if row["status"] == "RAY_UNBOUNDED_WITHIN_GUARD"]
    axis_physical = [row for row in axis if row["status"] == "AXIS_CERTIFIED_BOUNDARY"]
    coordinates = [
        {"timestamp": row["timestamp"], "p13": f(row["safe_p13_abs_kw"]), "p30": f(row["safe_p30_abs_kw"]), "source": "RAY"}
        for row in ray_physical
    ] + [
        {"timestamp": row["timestamp"], "p13": f(row["safe_p13_abs_kw"]), "p30": f(row["safe_p30_abs_kw"]), "source": "SIGNED_AXIS"}
        for row in axis_physical
    ]
    ray_distinct, ray_duplicates, _ = count_distinct_coordinates([row for row in coordinates if row["source"] == "RAY"])
    axis_distinct, axis_duplicates, _ = count_distinct_coordinates([row for row in coordinates if row["source"] == "SIGNED_AXIS"])
    total_distinct, total_duplicates, cross_source_overlaps = count_distinct_coordinates(coordinates)
    vmax_ray = sum(row["binding_mechanism"] == "BINDING_VMAX" for row in ray_physical)
    vmin_ray = sum(row["binding_mechanism"] == "BINDING_VMIN" for row in ray_physical)
    vmax_axis = sum(row["binding_mechanism"] == "BINDING_VMAX" for row in axis_physical)
    vmin_axis = sum(row["binding_mechanism"] == "BINDING_VMIN" for row in axis_physical)
    summary = {
        "purpose": "COMPLETE_DOE_FACET_INPUT_BOUNDARY_SET",
        "physical_ray_boundaries": len(ray_physical),
        "signed_axis_boundaries": len(axis_physical),
        "total_physical_boundaries": len(ray_physical) + len(axis_physical),
        "distinct_physical_coordinates": total_distinct,
        "duplicate_search_outcomes_at_same_physical_coordinate": total_duplicates,
        "ray_axis_coordinate_overlap_clusters": cross_source_overlaps,
        "physical_ray_distinct_coordinates": ray_distinct,
        "signed_axis_distinct_coordinates": axis_distinct,
        "physical_ray_duplicate_outcomes": ray_duplicates,
        "signed_axis_duplicate_outcomes": axis_duplicates,
        "guard_truncations": len(guards),
        "VMAX_total": vmax_ray + vmax_axis,
        "VMIN_total": vmin_ray + vmin_axis,
        "VMAX_ray": vmax_ray, "VMIN_ray": vmin_ray,
        "VMAX_signed_axis": vmax_axis, "VMIN_signed_axis": vmin_axis,
        "coordinate_equality_tolerance_kw": COORD_TOL_KW,
        "future_facet_point_cloud_policy": "DEDUPLICATE_IDENTICAL_PHYSICAL_COORDINATES_BEFORE_FACET_GENERATION",
    }
    if summary["total_physical_boundaries"] != 1689 or summary["VMAX_total"] != 851 or summary["VMIN_total"] != 838:
        raise SystemExit(f"unexpected complete boundary inventory: {summary}")
    rows = [
        {"inventory_item": "physical_ray_boundaries", "distinct_search_outcomes": len(ray_physical),
         "distinct_physical_coordinates": ray_distinct, "VMAX_count": vmax_ray, "VMIN_count": vmin_ray,
         "guard_truncations": 0, "purpose": summary["purpose"]},
        {"inventory_item": "signed_axis_boundaries", "distinct_search_outcomes": len(axis_physical),
         "distinct_physical_coordinates": axis_distinct, "VMAX_count": vmax_axis, "VMIN_count": vmin_axis,
         "guard_truncations": 0, "purpose": summary["purpose"]},
        {"inventory_item": "total_physical_boundaries", "distinct_search_outcomes": len(coordinates),
         "distinct_physical_coordinates": total_distinct, "VMAX_count": vmax_ray + vmax_axis,
         "VMIN_count": vmin_ray + vmin_axis, "guard_truncations": 0, "purpose": summary["purpose"]},
        {"inventory_item": "guard_truncations", "distinct_search_outcomes": len(guards),
         "distinct_physical_coordinates": "NOT_PHYSICAL_BOUNDARIES", "VMAX_count": 0, "VMIN_count": 0,
         "guard_truncations": len(guards), "purpose": "TRUNCATED_SECTORS_EXCLUDED_FROM_FACET_BOUNDARY_INPUT"},
    ]
    write_csv(output / "boundary_input_reconciliation.csv", rows)
    return summary


def boundary_order_screen(base: list[dict[str, str]], adaptive: list[dict[str, str]], output: Path) -> dict[str, Any]:
    rays = base + adaptive
    physical = [row for row in rays if row["status"] == "RAY_CERTIFIED_BOUNDARY"]
    guard = [row for row in rays if row["status"] == "RAY_UNBOUNDED_WITHIN_GUARD"]
    if len(guard) != 73 or len(physical) != 1561:
        raise SystemExit("unexpected physical/guard ray counts")
    detail_rows, summary_rows = [], []
    total_comparable = 0
    total_counterexamples = 0
    for mechanism in ("VMAX", "VMIN"):
        label = f"BINDING_{mechanism}"
        selected = [row for row in physical if row["binding_mechanism"] == label]
        safe = [(f(r["safe_p13_abs_kw"]), f(r["safe_p30_abs_kw"]), r) for r in selected]
        bad = [(f(r["violating_p13_abs_kw"]), f(r["violating_p30_abs_kw"]), r) for r in selected]
        comparable = counterexamples = 0
        for sp13, sp30, sr in safe:
            for bp13, bp30, br in bad:
                if sr["timestamp"] != br["timestamp"]:
                    continue
                safe_le_bad = sp13 <= bp13 + COORD_TOL_KW and sp30 <= bp30 + COORD_TOL_KW
                safe_ge_bad = sp13 + COORD_TOL_KW >= bp13 and sp30 + COORD_TOL_KW >= bp30
                if safe_le_bad or safe_ge_bad:
                    comparable += 1
                contradiction = safe_ge_bad if mechanism == "VMAX" else safe_le_bad
                if contradiction:
                    counterexamples += 1
                    detail_rows.append({"mechanism": mechanism, "timestamp": sr["timestamp"],
                                        "safe_level": sr["level"], "safe_angle_deg": sr["angle_deg"],
                                        "safe_p13_kw": sp13, "safe_p30_kw": sp30,
                                        "infeasible_level": br["level"], "infeasible_angle_deg": br["angle_deg"],
                                        "infeasible_p13_kw": bp13, "infeasible_p30_kw": bp30,
                                        "safe_source_status": sr["safe_solver_status"],
                                        "infeasible_source_status": br["violating_solver_status"]})
        total_comparable += comparable
        total_counterexamples += counterexamples
        summary_rows.append({"mechanism": mechanism, "physical_boundary_points": len(selected),
                             "boundary_order_comparable_pairs": comparable,
                             "order_closure_counterexamples": counterexamples})
    write_csv(output / "boundary_order_closure_summary.csv", summary_rows)
    if detail_rows:
        write_csv(output / "boundary_order_closure_counterexamples.csv", detail_rows)
    summary = {
        "classification": "NO_BOUNDARY_ORDER_CLOSURE_COUNTEREXAMPLE_OBSERVED" if total_counterexamples == 0 else "BOUNDARY_ORDER_CLOSURE_COUNTEREXAMPLE_OBSERVED",
        "physical_boundary_points_used": len(physical),
        "VMAX_boundary_points": sum(r["binding_mechanism"] == "BINDING_VMAX" for r in physical),
        "VMIN_boundary_points": sum(r["binding_mechanism"] == "BINDING_VMIN" for r in physical),
        "guard_truncations_excluded": len(guard), "boundary_order_comparable_pairs": total_comparable,
        "VMAX_order_closure_counterexamples": summary_rows[0]["order_closure_counterexamples"],
        "VMIN_order_closure_counterexamples": summary_rows[1]["order_closure_counterexamples"],
        "blind_spot": "73 guard-truncated mixed-sign sectors are excluded from this physical-boundary-only screen",
        "evidence_relationship": "BOUNDARY_ORDER_SCREEN_RESULT_IS_DERIVED_FROM_EXISTING_SCALAR_MONOTONICITY_SCREEN",
        "independent_monotonicity_evidence": False,
    }
    return summary


def cardinal_analysis(cardinal: list[dict[str, str]], centers: dict[str, dict[str, float]],
                      bounds: dict[str, dict[str, float]], asymmetry: list[dict[str, str]],
                      rays: list[dict[str, str]], output: Path) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    by_time: dict[str, dict[int, float]] = defaultdict(dict)
    for row in cardinal:
        by_time[row["timestamp"]][int(f(row["angle_deg"]))] = f(row["actual_boundary_delta_r"])
    asym = {row["timestamp"]: {"a13": f(row["a13"]), "a30": f(row["a30"])} for row in asymmetry}
    ray_cardinals = {(row["timestamp"], int(f(row["angle_deg"]))): row for row in rays
                     if row["status"] == "RAY_CERTIFIED_BOUNDARY" and int(f(row["angle_deg"])) in (0, 90, 180, 270)}
    rows, regression_data = [], []
    for timestamp in sorted(by_time):
        d = by_time[timestamp]
        r13, r30 = d[0] + d[180], d[90] + d[270]
        den13 = (abs(d[0]) + abs(d[180])) / 2
        den30 = (abs(d[90]) + abs(d[270])) / 2
        row = {"timestamp": timestamp, "delta_r_0": d[0], "delta_r_90": d[90],
               "delta_r_180": d[180], "delta_r_270": d[270],
               "R13": r13, "R30": r30, "absolute_R13": abs(r13), "absolute_R30": abs(r30),
               "relative_R13": abs(r13) / den13 if den13 else None,
               "relative_R30": abs(r30) / den30 if den30 else None}
        for angle in (0, 90, 180, 270):
            outcome = ray_cardinals[(timestamp, angle)]
            row[f"binding_mechanism_{angle}"] = outcome["binding_mechanism"]
            row[f"binding_bus_{angle}"] = int(outcome["binding_bus"])
        rows.append(row)
        c, b = centers[timestamp], bounds[timestamp]
        s13 = (b["p13_max"] - b["p13_min"]) / 2
        s30 = (b["p30_max"] - b["p30_min"]) / 2
        regression_data += [
            {"id": f"{timestamp}|P13", "timestamp": timestamp, "interface": "P13", "y": abs(r13),
             "orth": abs(c["p30"] / s13), "orth2": (c["p30"] / s13) ** 2,
             "own": abs(c["p13"] / s13), "asym": abs(asym[timestamp]["a13"])},
            {"id": f"{timestamp}|P30", "timestamp": timestamp, "interface": "P30", "y": abs(r30),
             "orth": abs(c["p13"] / s30), "orth2": (c["p13"] / s30) ** 2,
             "own": abs(c["p30"] / s30), "asym": abs(asym[timestamp]["a30"])},
        ]
    write_csv(output / "cardinal_antisymmetry_by_timestamp.csv", rows)
    aggregate = {}
    for key in ("R13", "R30", "absolute_R13", "absolute_R30", "relative_R13", "relative_R30"):
        aggregate[key] = numeric_summary([f(row[key]) for row in rows if row[key] is not None])
    aggregate["classification"] = "CENTERED_CARDINAL_PARAMETERIZATION_IDENTITY_CHECK"
    aggregate["residual_classification"] = "CARDINAL_LINEAR_ANTISYMMETRY_RESIDUAL"
    aggregate["axis_ray_cross_certification"] = "AXIS_RAY_CROSS_CERTIFICATION_NOT_PERFORMED"
    aggregate["causal_interpretation_assigned"] = False

    regression_rows = []
    for key, form in (("orth", "abs(R)=intercept+beta*abs(c_orth/s_own)"),
                      ("orth2", "abs(R)=intercept+beta*(c_orth/s_own)^2"),
                      ("own", "abs(R)=intercept+beta*abs(c_own/s_own)"),
                      ("asym", "abs(R)=intercept+beta*abs(axis_asymmetry)")):
        x = np.asarray([row[key] for row in regression_data])
        y = np.asarray([row["y"] for row in regression_data])
        design = np.column_stack((np.ones(len(x)), x))
        coefficients = np.linalg.lstsq(design, y, rcond=None)[0]
        predicted = design @ coefficients
        residual = y - predicted
        ss_res = float(residual @ residual)
        ss_tot = float(((y - y.mean()) ** 2).sum())
        largest = np.argsort(np.abs(residual))[-5:][::-1]
        regression_rows.append({"model_form": form, "N": len(x), "intercept": coefficients[0],
                                "beta": coefficients[1], "R_squared": 1 - ss_res / ss_tot,
                                "RMSE": math.sqrt(ss_res / len(x)),
                                "largest_residual_timestamps": ";".join(regression_data[i]["id"] for i in largest),
                                "scope": "EXPLORATORY_DIAGNOSTIC_ONLY"})
    write_csv(output / "cardinal_residual_scaling_regressions.csv", regression_rows)
    return aggregate, rows, regression_rows


def sensitivity_backcalculation(cardinal_rows: list[dict[str, Any]], centers: dict[str, dict[str, float]],
                                bounds: dict[str, dict[str, float]], root: Path, output: Path,
                                topology: dict[str, Any], resolution: dict[str, Any]) -> dict[str, Any]:
    stored_rows = read_csv(root / "results/dso_vpp_ac_map_pilot/ac_anchored_linear_corner_audit_corner_margins.csv")
    stored = {int(row["bus"]): row for row in stored_rows}
    anchor = next(row for row in cardinal_rows if row["timestamp"] == ANCHOR)
    c, b = centers[ANCHOR], bounds[ANCHOR]
    scales = {
        0: b["p13_max"] - c["p13"], 90: b["p30_max"] - c["p30"],
        180: c["p13"] - b["p13_min"], 270: c["p30"] - b["p30_min"],
    }
    specifications = [
        (0, "CARDINAL_0DEG_VMAX_BUS13_EFFECTIVE_COUPLING", 13, "VMAX", "coefficient_13_pu_per_pu", "coefficient_30_pu_per_pu", c["p30"], -1.0),
        (90, "CARDINAL_90DEG_VMAX_BUS30_EFFECTIVE_COUPLING", 30, "VMAX", "coefficient_30_pu_per_pu", "coefficient_13_pu_per_pu", c["p13"], -1.0),
        (180, "CARDINAL_180DEG_VMIN_BUS18_EFFECTIVE_COUPLING", 18, "VMIN", "coefficient_13_pu_per_pu", "coefficient_30_pu_per_pu", c["p30"], 1.0),
        (270, "CARDINAL_270DEG_VMIN_BUS33_EFFECTIVE_COUPLING", 33, "VMIN", "coefficient_30_pu_per_pu", "coefficient_13_pu_per_pu", c["p13"], 1.0),
    ]
    resolution_by_angle = {int(f(row["angle_deg"])): row for row in resolution["cardinal_boundaries"]}
    checks = []
    for angle, name, bus, mechanism, own_field, target_field, orthogonal_center, sign in specifications:
        actual_bus = anchor[f"binding_bus_{angle}"]
        actual_mechanism = anchor[f"binding_mechanism_{angle}"].removeprefix("BINDING_")
        if actual_bus != bus or actual_mechanism != mechanism:
            raise SystemExit(f"unexpected anchor cardinal binding at {angle}: {actual_mechanism} bus {actual_bus}")
        own = f(stored[bus][own_field]) if own_field in stored[bus] and stored[bus][own_field] != "" else None
        target = f(stored[bus][target_field]) if target_field in stored[bus] and stored[bus][target_field] != "" else None
        boundary = resolution_by_angle[angle]
        feasible_r, violating_r = f(boundary["final_feasible_r"]), f(boundary["final_violating_r"])
        delta_r = feasible_r - 1.0
        if abs(delta_r - anchor[f"delta_r_{angle}"]) > 1e-15:
            raise SystemExit(f"cardinal feasible-radius mismatch at {angle} degrees")
        transform = lambda radial_coordinate: (
            sign * own * (radial_coordinate - 1.0) * scales[angle] / orthogonal_center
            if own is not None and orthogonal_center != 0 else None
        )
        effective = transform(feasible_r)
        violating_effective = transform(violating_r)
        interval_lower = min(effective, violating_effective)
        interval_upper = max(effective, violating_effective)
        interval_width = interval_upper - interval_lower
        checks.append({
            "diagnostic": name, "timestamp": ANCHOR, "angle_deg": angle, "binding_mechanism": mechanism,
            "binding_bus": bus, "directional_delta_r": delta_r, "directional_scale_kw": scales[angle],
            "orthogonal_center_injection_kw": orthogonal_center, "own_coefficient_field": own_field,
            "own_stored_coefficient": own, "effective_target_coefficient_field": target_field,
            "directional_effective_coupling": effective, "corresponding_stored_coefficient": target,
            "absolute_difference": abs(effective - target) if effective is not None and target is not None else None,
            "relative_difference": abs(effective - target) / abs(target) if effective is not None and target not in (None, 0) else None,
            "final_feasible_r": feasible_r, "final_violating_r": violating_r,
            "normalized_r_bracket_width": f(boundary["normalized_r_bracket_width"]),
            "effective_coupling_at_feasible_endpoint": effective,
            "effective_coupling_at_violating_endpoint": violating_effective,
            "effective_coupling_interval_lower": interval_lower,
            "effective_coupling_interval_upper": interval_upper,
            "effective_coupling_bracket_width": interval_width,
            "relative_effective_coupling_bracket_width": interval_width / abs(effective),
            "effective_coupling_bracket_width_relative_to_stored_coefficient": interval_width / abs(target),
            "radial_interval_mapping": "ALGEBRAIC_MONOTONE_LINEAR_MAP_OF_STORED_R_INTERVAL; NOT_A_FEASIBILITY_CLAIM_AT_THE_VIOLATING_ENDPOINT",
            "comparison_availability": "CORRESPONDING_STORED_SENSITIVITY_AVAILABLE" if target is not None else "CORRESPONDING_STORED_SENSITIVITY_NOT_AVAILABLE",
            "interpretation": "DIRECTION_SPECIFIC_EQUAL_BOUNDARY_EFFECTIVE_COUPLING_DIAGNOSTIC",
        })
    topology_by_name = {row["coefficient"]: row for row in topology["coefficient_comparisons"]}
    check_by_angle = {row["angle_deg"]: row for row in checks}
    symmetrized = []
    pair_specs = (
        ("INTERFACE_13_ORIENTED", 0, 180, "c_13_30"),
        ("INTERFACE_30_ORIENTED", 90, 270, "c_30_13"),
    )
    for pair, positive_angle, opposite_angle, coefficient_name in pair_specs:
        positive = check_by_angle[positive_angle]["directional_effective_coupling"]
        opposite = check_by_angle[opposite_angle]["directional_effective_coupling"]
        stored_coefficient = topology_by_name[coefficient_name]["stored_coefficient_pu_per_pu"]
        reconstructed_coefficient = topology_by_name[coefficient_name]["topology_reconstructed_coefficient_pu_per_pu"]
        estimate = (positive + opposite) / 2.0
        absolute_difference = abs(estimate - stored_coefficient)
        half_spread = abs(positive - opposite) / 2.0
        interval_lower = (check_by_angle[positive_angle]["effective_coupling_interval_lower"]
                          + check_by_angle[opposite_angle]["effective_coupling_interval_lower"]) / 2.0
        interval_upper = (check_by_angle[positive_angle]["effective_coupling_interval_upper"]
                          + check_by_angle[opposite_angle]["effective_coupling_interval_upper"]) / 2.0
        inside = interval_lower <= stored_coefficient <= interval_upper
        minimum_difference = 0.0 if inside else min(
            abs(interval_lower - stored_coefficient), abs(interval_upper - stored_coefficient)
        )
        maximum_difference = max(
            abs(interval_lower - stored_coefficient), abs(interval_upper - stored_coefficient)
        )
        resolution_classification = (
            "RADIAL_LINEAR_MODEL_SYMMETRIZED_CROSS_CHECK_WITHIN_BOUNDARY_SEARCH_RESOLUTION"
            if inside else "RADIAL_LINEAR_MODEL_SYMMETRIZED_CROSS_CHECK_RESOLVABLY_DIFFERENT"
        )
        if inside:
            deviation_sign_classification = "SYMMETRIZED_DEVIATION_SIGN_UNRESOLVED_WITHIN_BOUNDARY_BRACKETS"
        elif interval_lower > stored_coefficient:
            deviation_sign_classification = "SYMMETRIZED_DEVIATION_POSITIVE_OVER_ALL_STORED_BOUNDARY_BRACKET_POSITIONS"
        else:
            deviation_sign_classification = "SYMMETRIZED_DEVIATION_NEGATIVE_OVER_ALL_STORED_BOUNDARY_BRACKET_POSITIONS"
        result = {
            "pair": pair, "positive_direction_deg": positive_angle, "opposite_direction_deg": opposite_angle,
            "positive_direction_effective_coupling": positive, "opposite_direction_effective_coupling": opposite,
            "symmetrized_estimate": estimate, "stored_coefficient": stored_coefficient,
            "topology_reconstructed_coefficient": reconstructed_coefficient,
            "absolute_difference": absolute_difference,
            "relative_difference": absolute_difference / abs(stored_coefficient),
            "directional_half_spread": half_spread,
            "directional_relative_half_spread": half_spread / abs(stored_coefficient),
            "symmetrized_interval_lower": interval_lower, "symmetrized_interval_upper": interval_upper,
            "symmetrized_interval_half_width": (interval_upper - interval_lower) / 2.0,
            "minimum_possible_absolute_difference_over_interval": minimum_difference,
            "maximum_possible_absolute_difference_over_interval": maximum_difference,
            "topology_coefficient_location": (
                "INSIDE_SYMMETRIZED_BOUNDARY_RESOLUTION_INTERVAL" if inside
                else "OUTSIDE_SYMMETRIZED_BOUNDARY_RESOLUTION_INTERVAL"
            ),
            "classification": resolution_classification,
            "deviation_sign_classification": deviation_sign_classification,
        }
        symmetrized.append(result)
        for angle in (positive_angle, opposite_angle):
            check_by_angle[angle].update({
                "opposite_direction_deg": opposite_angle if angle == positive_angle else positive_angle,
                "symmetrized_pair": pair,
                "symmetrized_estimate": estimate,
                "symmetrized_absolute_difference": absolute_difference,
                "symmetrized_relative_difference": result["relative_difference"],
                "directional_half_spread": half_spread,
                "directional_relative_half_spread": result["directional_relative_half_spread"],
                "symmetrized_interval_lower": interval_lower,
                "symmetrized_interval_upper": interval_upper,
                "symmetrized_interval_half_width": result["symmetrized_interval_half_width"],
                "symmetrized_minimum_possible_absolute_difference": minimum_difference,
                "symmetrized_maximum_possible_absolute_difference": maximum_difference,
                "topology_coefficient_location": result["topology_coefficient_location"],
                "symmetrized_resolution_classification": resolution_classification,
                "symmetrized_deviation_sign_classification": deviation_sign_classification,
                "diagnostic_family": "CARDINAL_DIRECTIONAL_AND_SYMMETRIZED_RESULTS_ARE_ONE_DIAGNOSTIC_FAMILY",
            })
    write_csv(output / "cardinal_directional_effective_coupling.csv", checks)
    cardinal_output = []
    for row in resolution["cardinal_boundaries"]:
        combined = row.copy()
        combined.update({
            key: value for key, value in check_by_angle[int(f(row["angle_deg"]))].items()
            if key not in {"timestamp", "angle_deg", "binding_mechanism", "binding_bus"}
        })
        cardinal_output.append(combined)
    write_csv(output / "cardinal_boundary_resolution.csv", cardinal_output)
    resolution["cardinal_boundaries"] = cardinal_output
    same_sign = all(row["symmetrized_estimate"] > row["stored_coefficient"] for row in symmetrized)
    if not same_sign:
        raise SystemExit("expected same-sign anchor point-estimate observation not found")
    availability = [{
        "bus": bus,
        "coefficient_13_pu_per_pu": f(stored[bus]["coefficient_13_pu_per_pu"]) if stored[bus].get("coefficient_13_pu_per_pu", "") != "" else None,
        "coefficient_30_pu_per_pu": f(stored[bus]["coefficient_30_pu_per_pu"]) if stored[bus].get("coefficient_30_pu_per_pu", "") != "" else None,
        "source_artifact": "results/dso_vpp_ac_map_pilot/ac_anchored_linear_corner_audit_corner_margins.csv",
    } for bus in (13, 30, 18, 33)]
    return {
        "classification": "CARDINAL_DIRECTION_SPECIFIC_EFFECTIVE_COUPLING_CHECK",
        "artifact_result": "STRICT_ARTIFACT_ONLY_RESULT",
        "stored_sensitivity_availability": availability,
        "symmetry_assumption_used": False,
        "method": "direction-specific equal-boundary effective coupling from the stored cardinal displacement, matching signed scale, orthogonal center coordinate, and the same active constraint bus",
        "checks": checks,
        "VMAX_side_comparison": [row for row in checks if row["binding_mechanism"] == "VMAX"],
        "VMIN_side_comparison": [row for row in checks if row["binding_mechanism"] == "VMIN"],
        "symmetrized_cross_checks": symmetrized,
        "symmetrized_classification": "PAIR_SPECIFIC_CARDINAL_BOUNDARY_RESOLUTION_CLASSIFICATION",
        "same_sign_point_estimate_observation": "SAME_SIGN_SYMMETRIZED_POINT_DEVIATION_AT_ANCHOR",
        "same_sign_point_estimate_interpretation": "Descriptive anchor-only observation; no systematic bias or physical mechanism is inferred.",
        "residual_and_backcalculation_relationship": "CARDINAL_RESIDUAL_AND_BACK_CALCULATION_ARE_ONE_DIAGNOSTIC_FAMILY",
        "diagnostic_family": "CARDINAL_DIRECTIONAL_AND_SYMMETRIZED_RESULTS_ARE_ONE_DIAGNOSTIC_FAMILY",
        "pooled_heterogeneous_active_constraint_estimate_retired": True,
        "first_order_binding_bus_sensitivity_mismatch_correction": {
            "classification": "FIRST_ORDER_BINDING_BUS_SENSITIVITY_MISMATCH_RULED_OUT_BY_TOPOLOGY",
            "basis": ["c18,13 = c13,13", "c18,30 = c13,30", "c33,13 = c30,13", "c33,30 = c30,30"],
            "interpretation": "The topology reconstruction rules out first-order LinDistFlow sensitivity mismatch between the opposite binding buses as the explanation for the directional spread. The remaining directional asymmetry is not causally identified.",
        },
        "remaining_directional_cardinal_asymmetry_cause": "CAUSALLY_UNRESOLVED",
        "candidate_facet_policy": {
            "role": "CANDIDATE_FACET_GENERATOR",
            "basis": ["SENSITIVITY_MATRIX_TOPOLOGY_CONSISTENT", "useful first-order analytical geometry", "one anchor symmetrized pair within boundary-search resolution", "one anchor pair resolvably different but numerically close in absolute terms"],
            "authority": "LINDISTFLOW_IS_NOT_DOE_FEASIBILITY_AUTHORITY",
            "validation_requirement": "EVERY_RETAINED_CANDIDATE_FACET_REQUIRES_NONLINEAR_AC_FALSIFICATION_OR_VALIDATION",
            "scope": "ANCHOR_SPECIFIC_CROSS_CHECK_NOT_GENERALIZED_TO_32_TIMESTAMPS",
        },
        "superseded_accuracy_wording": "the point-estimate percentages are descriptive differences only and must be interpreted through the propagated boundary-location brackets",
        "limitation": "cross-consistency check between computational pathways, not axis↔ray boundary certification; no Taylor-order mechanism is inferred",
    }


def anchor_metrics(production: Path, centers: dict[str, dict[str, float]], bounds: dict[str, dict[str, float]],
                   base: list[dict[str, str]], adaptive: list[dict[str, str]], asymmetry: list[dict[str, str]],
                   output: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    asym = {r["timestamp"]: r for r in asymmetry}
    runtime = {r["timestamp"]: r for r in read_csv(production / "timestamp_runtime_evaluation_summary.csv")}
    base_by: dict[str, list[dict[str, str]]] = defaultdict(list)
    adaptive_by: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in base: base_by[row["timestamp"]].append(row)
    for row in adaptive: adaptive_by[row["timestamp"]].append(row)
    metrics: dict[str, dict[str, float]] = defaultdict(dict)
    for timestamp in sorted(centers):
        b, c = bounds[timestamp], centers[timestamp]
        metrics["A13"][timestamp] = f(asym[timestamp]["a13"])
        metrics["A30"][timestamp] = f(asym[timestamp]["a30"])
        metrics["center_P13_kw"][timestamp] = c["p13"]
        metrics["center_P30_kw"][timestamp] = c["p30"]
        metrics["number_of_guard_limited_rays"][timestamp] = sum(r["status"] == "RAY_UNBOUNDED_WITHIN_GUARD" for r in base_by[timestamp] + adaptive_by[timestamp])
        metrics["number_of_adaptive_rays"][timestamp] = len(adaptive_by[timestamp])
        metrics["number_of_base_rays"][timestamp] = len(base_by[timestamp])
        metrics["P13_positive_kw"][timestamp] = b["p13_max"]
        metrics["P13_negative_magnitude_kw"][timestamp] = abs(b["p13_min"])
        metrics["P30_positive_kw"][timestamp] = b["p30_max"]
        metrics["P30_negative_magnitude_kw"][timestamp] = abs(b["p30_min"])
        metrics["P13_axis_width_kw"][timestamp] = b["p13_max"] - b["p13_min"]
        metrics["P30_axis_width_kw"][timestamp] = b["p30_max"] - b["p30_min"]
        metrics["total_axis_width_kw"][timestamp] = b["p13_max"] - b["p13_min"] + b["p30_max"] - b["p30_min"]
        br = [f(r["official_boundary_r"]) for r in base_by[timestamp] if r["status"] == "RAY_CERTIFIED_BOUNDARY"]
        ar = [f(r["official_boundary_r"]) for r in adaptive_by[timestamp] if r["status"] == "RAY_CERTIFIED_BOUNDARY"]
        metrics["median_base_ray_radius"][timestamp] = statistics.median(br)
        metrics["minimum_base_ray_radius"][timestamp] = min(br)
        metrics["maximum_base_ray_radius"][timestamp] = max(br)
        metrics["median_adaptive_ray_radius"][timestamp] = statistics.median(ar)
        metrics["retry_count"][timestamp] = f(runtime[timestamp]["retry_count"])
        metrics["actual_evaluations"][timestamp] = f(runtime[timestamp]["actual_evaluations"])
        metrics["runtime_seconds"][timestamp] = f(runtime[timestamp]["runtime_seconds"])
    classifier = {"total_axis_width_kw", "median_base_ray_radius"}
    low_cardinality = {"number_of_guard_limited_rays", "number_of_adaptive_rays"}
    rows = []
    for name in sorted(metrics):
        values, target = list(metrics[name].values()), metrics[name][ANCHOR]
        ordered = sorted(values)
        rank = ordered.index(target) + 1
        percentile = (rank - 1) / (len(ordered) - 1)
        frequencies = Counter(values)
        median = statistics.median(values)
        full_range = max(values) - min(values)
        rows.append({"metric": name, "metric_role": "HISTORICAL_CLASSIFIER_DIMENSION" if name in classifier else "ADDITIONAL_DESCRIPTIVE_DIMENSION",
                     "anchor_value": target, "rank_ascending": rank, "rank_descending": len(values) - rank + 1,
                     "percentile": percentile, "median_across_32": median,
                     "minimum_across_32": min(values), "maximum_across_32": max(values), "sample_count": len(values),
                     "anchor_minus_median_absolute": target - median,
                     "anchor_minus_median_percent": (target - median) / abs(median) * 100 if median != 0 else None,
                     "full_range_absolute": full_range,
                     "full_range_percent_of_median": full_range / abs(median) * 100 if median != 0 else None,
                     "number_of_unique_values": len(frequencies),
                     "unique_values": ";".join(fmt(value) for value in sorted(frequencies)),
                     "frequency_of_each_value": ";".join(f"{fmt(value)}:{frequencies[value]}" for value in sorted(frequencies)),
                     "cardinality_classification": "LOW_CARDINALITY_DESCRIPTIVE_METRIC" if name in low_cardinality else "CONTINUOUS_OR_HIGHER_CARDINALITY_METRIC"})
    write_csv(output / "anchor_metric_percentiles.csv", rows)
    dependence_residuals = []
    for timestamp in sorted(centers):
        b, c = bounds[timestamp], centers[timestamp]
        for interface, center_key, min_key, max_key, a_key in (
            ("P13", "p13", "p13_min", "p13_max", "a13"),
            ("P30", "p30", "p30_min", "p30_max", "a30"),
        ):
            signed_scale = (b[max_key] - b[min_key]) / 2
            expected = -c[center_key] / signed_scale
            dependence_residuals.append(abs(f(asym[timestamp][a_key]) - expected))
    required = {row["metric"]: row for row in rows}
    width = required["total_axis_width_kw"]
    summary = {
        "algebraic_relationship": "A_i = -c_i / s_i, where c_i is the Tier-1 midpoint center and s_i=(P_i^+ + |P_i^-|)/2",
        "maximum_absolute_identity_residual": max(dependence_residuals),
        "dependence_classification": "A_i_AND_NORMALIZED_CENTER_DISPLACEMENT_NOT_INDEPENDENT_METRICS",
        "total_axis_width_effect_size": {
            "anchor_minus_median_absolute": width["anchor_minus_median_absolute"],
            "anchor_minus_median_percent": width["anchor_minus_median_percent"],
            "full_range_absolute": width["full_range_absolute"],
            "full_range_percent_of_median": width["full_range_percent_of_median"],
            "rank_ascending": width["rank_ascending"], "rank_descending": width["rank_descending"],
            "interpretation": "RANK_EXTREMENESS_DISTINCT_FROM_EFFECT_SIZE",
        },
        "low_cardinality_metrics": {
            name: {"number_of_unique_values": required[name]["number_of_unique_values"],
                   "unique_values": required[name]["unique_values"],
                   "frequency_of_each_value": required[name]["frequency_of_each_value"],
                   "classification": "LOW_CARDINALITY_DESCRIPTIVE_METRIC"}
            for name in ("number_of_adaptive_rays", "number_of_guard_limited_rays")
        },
        "revised_interpretation": {
            "signed_axis_asymmetry": "GENUINELY_UPPER_TAIL_AND_BROAD_DISTRIBUTION",
            "total_axis_width": "LOW_RANK_WITH_SMALL_ABSOLUTE_EFFECT_SIZE",
            "median_base_ray_radius": "TYPICAL",
            "center_displacement": "ALGEBRAICALLY_LINKED_TO_SIGNED_AXIS_ASYMMETRY",
            "adaptive_and_guard_counts": "LOW_CARDINALITY_DESCRIPTIVE_METRICS",
            "scope": "ANCHOR_SPECIFIC_CLAIMS_ONLY",
            "multi_dimensionally_extreme_claim": False,
        },
    }
    return rows, summary


def sampled_skeleton_limitation(post: Path) -> dict[str, Any]:
    rows = read_csv(post / "sampling_geometry_timestamp_summary.csv")
    median_gaps = sorted(f(row["actual_median_angular_gap_deg"]) for row in rows)
    maximum_gaps = [f(row["actual_maximum_angular_gap_deg"]) for row in rows]
    anchor = next(row for row in rows if row["timestamp"] == ANCHOR)
    return {
        "MONOTONICITY_EVIDENCE_DOMAIN": "SAMPLED_RADIAL_AXIS_SKELETON",
        "angular_interior_classification": "ANGULAR_INTERIOR_BETWEEN_SAMPLED_DIRECTIONS_NOT_DIRECTLY_EVALUATED",
        "stored_converged_evaluations": 87086,
        "sampled_components": ["signed-axis search trajectories", "36 base radial directions per timestamp",
                               "adaptive radial directions", "coarse-sweep/bisection points along those trajectories"],
        "strict_2D_comparable_endpoint_pairs": 49830885,
        "median_of_timestamp_actual_median_angular_gaps_deg": statistics.median(median_gaps),
        "maximum_actual_angular_gap_observed_deg": max(maximum_gaps),
        "anchor_actual_median_angular_gap_deg": f(anchor["actual_median_angular_gap_deg"]),
        "anchor_actual_maximum_angular_gap_deg": f(anchor["actual_maximum_angular_gap_deg"]),
        "guard_limited_mixed_sign_sectors": 73,
        "future_geometry_caveat": "actual future box corners and arbitrary coupled-polytope interior points may not coincide with previously sampled trajectories",
        "strongest_allowed_wording": "Assumption (M) is strongly supported by the stored nonlinear-AC evaluations on the sampled radial/axis skeleton, including 49.83 million strictly two-dimensional comparable endpoint pairs with no observed scalar monotonicity counterexample. The angular interior between sampled directions is not directly covered by the existing AC campaign.",
        "carry_forward": "DOE_CONSTRUCTION_POLICY_MUST_RETAIN_SAMPLED_SKELETON_LIMITATION",
    }


def corner_result(post: Path, base: list[dict[str, str]], adaptive: list[dict[str, str]]) -> dict[str, Any]:
    prior = json.loads((post / "analytical_corner_geometric_audit.json").read_text(encoding="utf-8"))
    rays = [r for r in base + adaptive if r["timestamp"] == ANCHOR]
    exact = [r for r in rays if abs(f(r["angle_deg"]) - prior["normalized_angle_deg"]) <= 1e-12]
    lower, upper = prior["lower_neighbor"], prior["upper_neighbor"]
    upper_dominates = upper["safe_p13_abs_kw"] >= CORNER[0] and upper["safe_p30_abs_kw"] >= CORNER[1]
    return {
        "classification": "ANALYTICAL_CORNER_INSIDE_OUTSIDE_UNRESOLVED_FROM_STORED_DIRECTIONS",
        "corner_p13_kw": CORNER[0], "corner_p30_kw": CORNER[1],
        "normalized_radius": prior["normalized_radius"], "normalized_angle_deg": prior["normalized_angle_deg"],
        "exact_direction_sampled": bool(exact), "certified_radius_at_exact_direction": f(exact[0]["official_boundary_r"]) if exact else None,
        "lower_neighbor": lower, "upper_neighbor": upper,
        "upper_neighbor_componentwise_dominates_corner": upper_dominates,
        "reason": "The exact direction was not sampled. Componentwise dominance by a nearby converged-feasible point is suggestive but cannot certify the unsolved corner without a proven lower-closure theorem; no interpolation is promoted to certified evidence.",
    }


def solver_and_timing() -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    solver = {
        "BFS_STOPPING_TOLERANCE": {"primary_pu": PRIMARY_TOL_PU, "replay_pu": REPLAY_TOL_PU},
        "stopping_variable_norm": "maximum(abs(fixed_voltage - current_voltage)) over the complex bus-voltage vector (infinity norm of the undamped fixed-point update)",
        "criterion_type": "voltage fixed-point update, not current update, mismatch, residual, or proven solution error",
        "maximum_iterations": {"primary": PRIMARY_MAX_ITERATIONS, "replay": REPLAY_MAX_ITERATIONS},
        "retry_specific_tolerance_change": False, "retry_change": "initialization and maximum-iteration argument remains the same",
        "production_and_replay_same_criterion_form": True, "production_and_replay_same_tolerance_value": False,
        "final_update_magnitude_stored_per_solve": False,
        "stored_related_fields": "iterations, replay equation residual, primary-replay voltage difference; none is the final B/F update",
        "analytical_contraction_or_solution_error_bound_found": False,
        "REPLAY_VOLTAGE_MATCH_TOLERANCE_PU": REPLAY_VOLTAGE_MATCH_TOLERANCE_PU,
        "interpretation": "No inference from update <= epsilon to distance from the exact fixed point <= epsilon is made.",
    }
    scope_rows = [
        {"category": "module loading", "benchmark": "excluded (include occurs before run_scan)", "production": "top-level module loading excluded"},
        {"category": "first-call compilation", "benchmark": "included for first timed scan evaluation; no warmup in run_scan", "production": "included for calls first reached after run_production_probe timer starts"},
        {"category": "profile/network loading", "benchmark": "excluded (load_canonical_data before timer)", "production": "included"},
        {"category": "configuration/hashing", "benchmark": "validation before timer; git/hash after timer", "production": "preregistration hashes and locked-config validation included"},
        {"category": "probe setup", "benchmark": "data/path/output-policy setup excluded", "production": "included"},
        {"category": "AC evaluations", "benchmark": "included", "production": "included"},
        {"category": "independent replay", "benchmark": "included", "production": "included"},
        {"category": "checkpoint I/O", "benchmark": "none", "production": "included per direction/timestamp"},
        {"category": "serialization/artifact I/O", "benchmark": "excluded", "production": "final artifact serialization excluded; checkpoint serialization included"},
        {"category": "post-processing", "benchmark": "excluded", "production": "final validation/distributions excluded"},
    ]
    timing = {
        "classification": "AFFINE_FIXED_COST_HYPOTHESIS_CONSISTENT_WITH_TIMINGS",
        "benchmark": {"evaluations": 3691, "wall_seconds": 15.3498603},
        "production": {"logical_evaluations": 87229, "actual_attempts": 87372, "wall_seconds": 54.581000089645386},
        "two_point_affine_fit": {"slope_ms_per_logical_evaluation": 0.4696, "fixed_seconds": 13.62,
                                 "interpretation": "descriptive two-point fit, not measured marginal solve cost"},
        "first_call_compilation_inside_both_timers": True,
        "timers_started_before_equivalent_setup_work": False,
        "code_evidence_for_shared_fixed_cost": "both can include JIT for first timed evaluation, but scopes are not equivalent and other fixed work differs",
        "evaluation_mixes_sufficiently_similar_for_single_marginal_slope": False,
        "reason_not_upgraded": "benchmark is positive-axis VMAX scanning; production mixes signed axes, centers, base/adaptive rays, retries, and checkpoint I/O under materially different setup scopes",
    }
    return solver, timing, scope_rows


def fmt(value: Any) -> str:
    if isinstance(value, int): return f"{value:,}"
    if isinstance(value, float): return f"{value:.12g}"
    return str(value)


def build_report(path: Path, provenance: dict[str, Any], inputs: list[dict[str, Any]], pair_rows: list[dict[str, Any]],
                 separation: list[dict[str, Any]], boundary_inventory: dict[str, Any], boundary: dict[str, Any],
                 zero: dict[str, Any], percentile_rows: list[dict[str, Any]], cardinal: dict[str, Any],
                 sensitivity: dict[str, Any], topology: dict[str, Any], anchor: list[dict[str, Any]], anchor_summary: dict[str, Any],
                 skeleton: dict[str, Any], resolution: dict[str, Any], termination: dict[str, Any],
                 files: list[str], final_status: str) -> None:
    overall = pair_rows[0]
    anchor_required = {row["metric"]: row for row in anchor}
    pair13 = next(row for row in sensitivity["symmetrized_cross_checks"] if row["pair"] == "INTERFACE_13_ORIENTED")
    pair30 = next(row for row in sensitivity["symmetrized_cross_checks"] if row["pair"] == "INTERFACE_30_ORIENTED")
    lines = ["# DOE preconstruction artifact refinement — final code inspection and wording correction", "",
             "This is an artifact/code-inspection result. No AC power flow, backward/forward sweep, replay, production probing, multi-start test, or DOE construction was run.", "",
             "## A. Repository provenance", "", f"- branch: `{provenance['branch']}`", f"- HEAD: `{provenance['head']}`",
             f"- authoritative inputs hashed/schema-checked: {len(inputs)}", "- pre-analysis `git status --short`:", "", "```text", provenance["preanalysis_git_status_short"], "```", "",
             "## B. Ray bisection implementation", "",
             "- initial certified bracket: first adjacent converged-feasible/converged-infeasible pair in the retained full `r = 0:0.05:2` coarse sweep (`first_adjacent_bracket`, source lines 413–418 and `run_ray!`, lines 698–738)",
             "- initial normalized-r width: `0.05` for every certified physical ray",
             "- update: midpoint of the current coordinates; a converged-feasible midpoint replaces the safe endpoint, a converged-infeasible midpoint replaces the violating endpoint, and an unresolved midpoint aborts certification (`refine_boundary!`, lines 434–459)",
             "- stop: `(violating_r-safe_r)*hypot(vx,vy) <= 1.0 kW` **and** both endpoints are within `1e-5 p.u.` of the active VMIN or VMAX limit (`endpoint_voltage_close`, lines 421–431)",
             "- maximum bisection refinements: `60`; coordinate tolerance: none; normalized-r tolerance: none; relative tolerance: none; physical tolerance: `1.0 kW`; voltage-related tolerance: `1e-5 p.u.` at both endpoints",
             "- serialization: production Float64 values are written with `@sprintf(\"%.12g\")` after the in-memory inequalities have been evaluated; serialization does not control stopping", "",
             "## C. Why ray widths have three discrete levels", "",
             "All 1,561 certified physical rays start from `0.05`; exact halving therefore gives `0.05/2^7 = 0.000390625`, `0.05/2^8 = 0.0001953125`, and `0.05/2^9 = 0.00009765625`. Counts are 104, 771, and 686, respectively. Before the final halving, all 104 seven-step rays fail the physical-width condition; all 771 eight-step and all 686 nine-step rays already pass physical width but fail the endpoint-voltage conjunction.", "",
             "| candidate | classification | code-level finding |", "|---|---|---|"]
    for item in termination["ray"]["candidate_classifications"]:
        lines.append(f"| {item['candidate']} | `{item['classification']}` | {item['explanation']} |")
    lines += ["", "Anchor threshold crossings (the physical-width condition is already true in every preceding state; the active endpoint-voltage condition determines the 8-versus-9 split):", "",
              "| direction | scale (kW/r) | preceding step | preceding width (kW) | preceding safe/violating voltage distances (p.u.) | final step | final width (kW) | final safe/violating voltage distances (p.u.) |",
              "|---:|---:|---:|---:|---|---:|---:|---|"]
    for angle in (0, 90, 180, 270):
        crossing = termination["ray"]["anchor_threshold_crossings"][str(angle)]
        previous, final = crossing["preceding"], crossing["final"]
        lines.append(f"| {angle}° | {fmt(crossing['physical_scale_kw_per_r'])} | {previous['step']} | {fmt(previous['physical_width_kw'])} | {fmt(previous['safe_voltage_distance_pu'])} / {fmt(previous['violating_voltage_distance_pu'])} | {final['step']} | {fmt(final['physical_width_kw'])} | {fmt(final['safe_voltage_distance_pu'])} / {fmt(final['violating_voltage_distance_pu'])} |")
    lines += ["", "The equal 0°/180° scale of 1583.203125 kW/r and equal 90°/270° scale of 2268.4375 kW/r do not imply equal counts: the opposite directions cross the endpoint-voltage inequalities on different halvings.", "",
              "## D. Signed-axis bisection implementation", "",
              "- provisional transition scale: double from 100 kW until the first converged-infeasible point or the 20,000 kW guard (`run_axis!`, lines 486–499)",
              "- initial certified bracket: first adjacent converged-feasible/converged-infeasible pair in the retained coarse sweep with `delta = transition_scale/20` (`run_axis!`, lines 499–525)",
              "- initial bracket widths: 20, 40, 80, 160, or 320 kW in the completed certified searches",
              "- update and stop: the same `refine_boundary!` midpoint update and conjunction used by rays, with physical width per coordinate equal to 1.0; no axis-specific coordinate or relative tolerance exists",
              "- maximum refinements: 60; physical tolerance: 1.0 kW; both active-limit endpoint distances: at most 1e-5 p.u.; unresolved midpoint aborts", "",
              "## E. Why axis widths have three discrete levels", "",
              "The completed final widths are 0.15625, 0.3125, and 0.625 kW. They are dyadic descendants of the direction-specific coarse brackets, and every search stops on the first loop entry where both the physical-width and endpoint-voltage conditions are true.", "",
              "- P13+: 13 at 0.15625 kW; 19 at 0.3125 kW.",
              "- P13−: 27 at 0.15625 kW; 5 at 0.3125 kW.",
              "- P30+: 29 at 0.3125 kW; 3 at 0.625 kW; none at 0.15625 kW.",
              "- P30−: 16 at 0.15625 kW; 16 at 0.3125 kW.",
              termination["axis"]["p30_positive_explanation"],
              termination["axis"]["stored_binding_sides"],
              "There is no separate VMAX/VMIN refinement path. Axis initial-bracket geometry differs, and the shared voltage-distance conjunction determines whether additional halvings occur after width first reaches at most 1 kW.", "",
              "## F. VMAX-versus-VMIN bracket asymmetry", "",
              f"- `{termination['empirical_classification']}`", f"- `{termination['cause_classification']}`",
              "The ray and signed-axis families call the same refinement function. For opposite anchor rays with identical physical scale, the VMAX directions stop at 8 and the VMIN directions at 9 because of the stored endpoint-voltage threshold crossings. For axes, differing initial coarse brackets also contribute. This is a code/history reconciliation, not a physical causal explanation of directional asymmetry.", "",
              "## G. 0°/180° corrected cardinal interpretation", "",
              f"- symmetrized point estimate: {fmt(pair13['symmetrized_estimate'])}", f"- propagated interval: [{fmt(pair13['symmetrized_interval_lower'])}, {fmt(pair13['symmetrized_interval_upper'])}]", f"- topology coefficient: {fmt(pair13['stored_coefficient'])}", f"- `{pair13['classification']}`", f"- `{pair13['deviation_sign_classification']}`",
              "The coefficient lies inside the propagated interval; this is a resolution-aware cross-check, not a pass/fail accuracy test, and the deviation sign is unresolved.", "",
              "## H. 90°/270° corrected cardinal interpretation", "",
              f"- propagated interval: [{fmt(pair30['symmetrized_interval_lower'])}, {fmt(pair30['symmetrized_interval_upper'])}]", f"- topology coefficient: {fmt(pair30['stored_coefficient'])}", f"- `{pair30['classification']}`", f"- `{pair30['deviation_sign_classification']}`",
              "The complete propagated interval lies above the topology coefficient. This directional statement is anchor-specific and is not generalized across 32 timestamps.", "",
              "## I. Same-sign anchor observation", "", f"`{sensitivity['same_sign_point_estimate_observation']}`", "", sensitivity["same_sign_point_estimate_interpretation"], "",
              "## J. Certified-feasible inward endpoint semantics", "", f"`{resolution['endpoint_classification']}`", "", resolution["endpoint_semantics"], "", resolution["endpoint_limitation"], "", f"`{resolution['doe_policy']['distinction']}`", "",
              "## K. Candidate-facet implication", "", f"`{sensitivity['candidate_facet_policy']['role']}`", "",
              "The topology-consistent LinDistFlow structure may later generate candidate facets because its sensitivity matrix is exactly topology-consistent, its first-order geometry is useful, one anchor symmetrized pair agrees within search resolution, and the other is resolvably different but numerically close in absolute terms.", "", f"`{sensitivity['candidate_facet_policy']['authority']}`", "",
              "Every retained candidate facet requires nonlinear AC falsification/validation. No generic error percentage or 32-timestamp generalization is made.", "",
              "## L. Files updated/created", ""]
    lines += [f"- `{name}`" for name in files]
    lines += ["", "## M. Determinism/manifest verification", "", "`BYTE_IDENTICAL_DOUBLE_REGENERATION_VERIFIED`", "",
              "All authoritative inputs are manifest/hash checked. The output manifest hashes every generated file except the manifest itself; the finalized generator is run twice and the complete output directory is compared byte-for-byte.", "",
              "## N. Final git status", "", "```text", final_status, "```", "",
              "## Supporting evidence annex", "", "### Boundary-input reconciliation", ""]
    for key in ("purpose", "physical_ray_boundaries", "signed_axis_boundaries", "total_physical_boundaries",
                "distinct_physical_coordinates", "ray_axis_coordinate_overlap_clusters", "guard_truncations", "VMAX_total", "VMIN_total"):
        lines.append(f"- {key}: `{fmt(boundary_inventory[key])}`")
    lines += ["", "The signed-axis and centered-ray boundaries are distinct physical coordinates under the 1e-9 kW coordinate criterion. Future facet generation must deduplicate coordinates if this changes; search outcomes and physical coordinates are reported separately.", "",
              f"`{boundary['evidence_relationship']}`. This reconciliation serves `COMPLETE_DOE_FACET_INPUT_BOUNDARY_SET`; it is not a new falsification experiment or independent monotonicity evidence.", "",
              "### Zero-Delta Vmax decomposition", ""]
    z = zero["Vmax"]
    for key in ("zero_pairs_total", "both_endpoints_bus_1", "both_endpoints_value_exactly_1pu", "both_bus_1_and_value_exactly_1pu",
                "one_endpoint_bus_1_only", "neither_endpoint_bus_1", "same_non_slack_bus", "different_non_slack_buses",
                "Vmax_non_equality_pairs", "Vmax_slack_pinned_zero_pairs", "Vmax_non_slack_or_positive_response_pairs"):
        lines.append(f"- {key}: {fmt(z[key])}")
    lines += [f"- exact criterion: {z['stored_exact_equality_criterion']}", f"- classification: `{z['classification']}`", "",
              "These pairs remain consistent with nondecreasing monotonicity but are not responsive evidence that Vmax changes with injection.", "",
              "### Zero-Delta Vmin decomposition", ""]
    z = zero["Vmin"]
    for key in ("zero_pairs_total", "same_bus", "different_buses", "both_endpoints_bus_1", "both_endpoints_value_exactly_1pu",
                "both_bus_1_and_value_exactly_1pu", "same_non_slack_bus", "different_non_slack_buses",
                "unique_exact_stored_zero_pair_values", "Vmin_non_equality_pairs", "Vmin_slack_pinned_zero_pairs",
                "Vmin_non_slack_or_positive_response_pairs"):
        lines.append(f"- {key}: {fmt(z[key])}")
    lines += [f"- exact criterion: {z['stored_exact_equality_criterion']}", f"- classification: `{z['classification']}`",
              "", "All zero-Delta Vmin pairs have both endpoints pinned exactly at 1 p.u. on slack bus 1 in the stored representation. This structural origin was determined from the stored bus/value provenance rather than assumed from Vmax. Dominant combinations, including vmin_bus_a, vmin_bus_b, Vmin_a, and Vmin_b, are recorded in `zero_delta_voltage_decomposition.csv`.", "",
              "### Vmax percentile/minimum audit", "",
              "| statistic | positive N | exact minimum | count at minimum | requested label | probability | fractional index | ranks (1-based) | rank values | reported value | classification |",
              "|---|---:|---:|---:|---|---:|---:|---|---|---:|---|"]
    for row in percentile_rows:
        lines.append(f"| {row['voltage_statistic']} | {row['positive_population_size']:,} | {fmt(row['exact_minimum_positive'])} | {row['count_at_exact_minimum_positive']:,} | {row['requested_percentile_label']} | {fmt(row['quantile_probability_actually_used'])} | {fmt(row['zero_based_fractional_index'])} | {row['one_based_lower_rank']}/{row['one_based_upper_rank']} | {fmt(row['lower_rank_value'])}/{fmt(row['upper_rank_value'])} | {fmt(row['reported_quantile_value'])} | `{row['classification']}` |")
    lines += ["", "The implementation is label-consistent: 0.001% uses probability 0.00001; probability 0.001 would be 0.1%. Type-7 linear interpolation is used.", "",
              "### Cardinal direction-specific reinterpretation", "", f"- geometry classification: `{cardinal['classification']}`", f"- residual classification: `{cardinal['residual_classification']}`", f"- `{cardinal['axis_ray_cross_certification']}`", "",
              "| direction | active constraint | bus | effective coupling | matching stored coefficient | relative difference |",
              "|---:|---|---:|---:|---:|---:|"]
    for row in sensitivity["checks"]:
        lines.append(f"| {row['angle_deg']} deg | {row['binding_mechanism']} | {row['binding_bus']} | {fmt(row['directional_effective_coupling'])} | {fmt(row['corresponding_stored_coefficient'])} | {fmt(row['relative_difference'])} |")
    lines += ["", "VMAX-side and VMIN-side quantities are kept separate. No VMAX/VMIN pooling, sensitivity symmetry, or causal label is used.", "",
              "### Stored sensitivity availability", "", "| bus | coefficient wrt P13 | coefficient wrt P30 |", "|---:|---:|---:|"]
    for row in sensitivity["stored_sensitivity_availability"]:
        lines.append(f"| {row['bus']} | {fmt(row['coefficient_13_pu_per_pu'])} | {fmt(row['coefficient_30_pu_per_pu'])} |")
    lines += ["", "All four direction-matched comparisons have corresponding stored coefficients. No unstored coefficient or symmetry assumption is introduced.", "",
              "### Sensitivity convention reconstructed from code", "",
              f"- historical convention source: `{topology['historical_convention_source']}`",
              f"- independent historical reconstruction source: `{topology['historical_independent_reconstruction_source']}`",
              f"- quantity: {topology['quantity']}",
              f"- formula: `{topology['convention']}`",
              f"- base: {fmt(topology['base_mva'])} MVA, {fmt(topology['base_kv'])} kV; Zbase = {fmt(topology['zbase_ohm'])} ohm",
              "", "The factor of 2 and the ohm-to-per-unit conversion were taken from the historical implementation and verified against its independent raw-case reconstruction; they were not supplied from memory.", "",
              "### Root-path/topology reconstruction", ""]
    for row in topology["root_paths"]:
        lines.append(f"- bus {row['bus']}: branch IDs `{row['branch_ids']}`; path `{row['branches']}`")
    lines += ["", "### Stored-vs-topology sensitivity comparison", "",
              "| coefficient | shared root-path branches | resistance sum (ohm) | resistance sum (p.u.) | topology coefficient | stored coefficient | absolute difference | relative difference |",
              "|---|---|---:|---:|---:|---:|---:|---:|"]
    for row in topology["coefficient_comparisons"]:
        lines.append(f"| {row['coefficient']} | {row['shared_root_path_branches']} | {fmt(row['shared_resistance_sum_ohm'])} | {fmt(row['shared_resistance_sum_pu'])} | {fmt(row['topology_reconstructed_coefficient_pu_per_pu'])} | {fmt(row['stored_coefficient_pu_per_pu'])} | {fmt(row['absolute_difference'])} | {fmt(row['relative_difference'])} |")
    lines += ["", f"Classification: `{topology['classification']}`. This direct check is limited to the stored LinDistFlow sensitivity construction.", "",
              "### Opposite-direction symmetrized cardinal cross-check", "",
              "| pair | directions | estimate | interval lower | interval upper | half-width | stored/topology coefficient | point discrepancy | minimum discrepancy | maximum discrepancy | location | classification |",
              "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---|---|"]
    for row in sensitivity["symmetrized_cross_checks"]:
        lines.append(f"| {row['pair']} | {row['positive_direction_deg']}°/{row['opposite_direction_deg']}° | {fmt(row['symmetrized_estimate'])} | {fmt(row['symmetrized_interval_lower'])} | {fmt(row['symmetrized_interval_upper'])} | {fmt(row['symmetrized_interval_half_width'])} | {fmt(row['stored_coefficient'])} | {fmt(row['absolute_difference'])} | {fmt(row['minimum_possible_absolute_difference_over_interval'])} | {fmt(row['maximum_possible_absolute_difference_over_interval'])} | `{row['topology_coefficient_location']}` | `{row['classification']}` |")
    lines += ["", f"Classification: `{sensitivity['symmetrized_classification']}`.", "",
              "### Anchor cardinal boundary-location brackets", "",
              "| direction | search ID | feasible r | violating r | width r | steps | feasible P13/P30 (kW) | violating P13/P30 (kW) | binding | bus | physical components P13/P30 (kW) | physical length (kW) |",
              "|---:|---|---:|---:|---:|---:|---|---|---|---:|---|---:|"]
    for row in resolution["cardinal_boundaries"]:
        lines.append(f"| {row['angle_deg']}° | `{row['search_id']}` | {row['final_feasible_r']} | {row['final_violating_r']} | {fmt(row['normalized_r_bracket_width'])} | {row['bisection_steps']} | {row['final_feasible_p13_kw']} / {row['final_feasible_p30_kw']} | {row['final_violating_p13_kw']} / {row['final_violating_p30_kw']} | {row['binding_mechanism']} | {row['binding_bus']} | {fmt(row['delta_p13_bracket_component_kw'])} / {fmt(row['delta_p30_bracket_component_kw'])} | {fmt(row['physical_bracket_length_kw'])} |")
    lines += ["", "These are conservative boundary-location brackets between the stored converged-feasible endpoint and converged-infeasible endpoint. They are neither random noise nor a proven solver-error bound.", "",
              "### Direction-specific effective-coupling resolution", "",
              "| direction | feasible coupling | violating-coordinate mapped coupling | lower | upper | width | relative width (vs feasible) |",
              "|---:|---:|---:|---:|---:|---:|---:|"]
    for row in sensitivity["checks"]:
        lines.append(f"| {row['angle_deg']}° | {fmt(row['effective_coupling_at_feasible_endpoint'])} | {fmt(row['effective_coupling_at_violating_endpoint'])} | {fmt(row['effective_coupling_interval_lower'])} | {fmt(row['effective_coupling_interval_upper'])} | {fmt(row['effective_coupling_bracket_width'])} | {fmt(row['relative_effective_coupling_bracket_width'])} |")
    lines += ["", "The violating-coordinate value is an algebraic endpoint of the monotone linear map from the allowed r interval; it is not a claim that the violating endpoint itself is feasible or a direct coupling measurement.", "",
              "### Whole-production ray-boundary resolution", "",
              "| group | quantity | N | min | Q01 | Q05 | Q25 | median | Q75 | Q95 | Q99 | max | unit |",
              "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|"]
    for row in resolution["ray_distributions"]:
        lines.append(f"| {row['group']} | {row['quantity']} | {row['count']} | {fmt(row['min'])} | {fmt(row['Q01'])} | {fmt(row['Q05'])} | {fmt(row['Q25'])} | {fmt(row['median'])} | {fmt(row['Q75'])} | {fmt(row['Q95'])} | {fmt(row['Q99'])} | {fmt(row['max'])} | {row['unit']} |")
    lines += ["", f"The {resolution['ray_population']['guard_truncations']} guard-limited rays are reported separately as `{resolution['ray_population']['guard_classification']}` and are excluded from these physical-boundary statistics.", "",
              "### Signed-axis boundary resolution", "",
              "| group | N | min | Q01 | Q05 | Q25 | median | Q75 | Q95 | Q99 | max | unit |",
              "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|"]
    for row in resolution["axis_distributions"]:
        lines.append(f"| {row['group']} | {row['count']} | {fmt(row['min'])} | {fmt(row['Q01'])} | {fmt(row['Q05'])} | {fmt(row['Q25'])} | {fmt(row['median'])} | {fmt(row['Q75'])} | {fmt(row['Q95'])} | {fmt(row['Q99'])} | {fmt(row['max'])} | {row['unit']} |")
    correction = sensitivity["first_order_binding_bus_sensitivity_mismatch_correction"]
    lines += ["", "### Resolution interpretation and sensitivity correction", "",
              f"`{correction['classification']}`", "", correction["interpretation"], "",
              "No curvature, Taylor-order, odd/even, or other causal error mechanism is assigned to the remaining directional asymmetry.", "",
              f"`{resolution['doe_policy']['distinction']}`", "", resolution["doe_policy"]["statement"], "",
              "Bracket statistics can guide numerical tolerances, numerical indistinguishability, and the avoidance of meaningless sub-bracket refinement. They do not establish a mandatory DOE contraction distance and cannot substitute for AC validation of candidate facet interiors.", "",
              "### Directional spread versus symmetrized agreement", "",
              "Individual direction-specific estimates have several-percent signed spread around the corresponding stored linear coefficient. The opposite-direction point-estimate differences are descriptive only: the 0°/180° coefficient lies inside its propagated boundary-resolution interval, while the 90°/270° coefficient remains outside its interval.", "",
              "This is a cross-consistency check between computational pathways, not axis↔ray boundary certification.", "",
              f"`{cardinal['axis_ray_cross_certification']}`", "",
              "### Cardinal diagnostic-family consolidation", "",
              f"`{sensitivity['residual_and_backcalculation_relationship']}`.", f"`{sensitivity['diagnostic_family']}`.",
              "The cardinal antisymmetry residual, direction-specific effective couplings, and symmetrized cross-checks are deterministic transforms of the same four stored cardinal displacement observations. They are one diagnostic family and are not double-counted as independent scientific findings.", "",
              f"Superseded wording: `{sensitivity['superseded_accuracy_wording']}`. The earlier pooled heterogeneous-active-constraint estimate and its approximate 8% headline are retired.", "",
              "### Anchor dependence and effect-size correction", "", f"- verified identity: `{anchor_summary['algebraic_relationship']}`", f"- maximum absolute identity residual: {fmt(anchor_summary['maximum_absolute_identity_residual'])}", f"- `{anchor_summary['dependence_classification']}`", ""]
    width = anchor_summary["total_axis_width_effect_size"]
    lines += [f"- total-axis-width rank: {width['rank_ascending']} ascending / {width['rank_descending']} descending",
              f"- anchor minus median: {fmt(width['anchor_minus_median_absolute'])} kW ({fmt(width['anchor_minus_median_percent'])}%)",
              f"- full range: {fmt(width['full_range_absolute'])} kW ({fmt(width['full_range_percent_of_median'])}% of median)",
              "- `RANK_EXTREMENESS` is distinct from `EFFECT_SIZE`.", ""]
    for name in ("number_of_adaptive_rays", "number_of_guard_limited_rays"):
        item = anchor_summary["low_cardinality_metrics"][name]
        lines.append(f"- {name}: {item['number_of_unique_values']} unique values [{item['unique_values']}], frequencies [{item['frequency_of_each_value']}]; `{item['classification']}`")
    lines += ["", "Revised interpretation: signed-axis asymmetry is genuinely upper-tail and broad-distribution; total axis width has a low rank but small absolute effect size; median base-ray radius is typical; center displacement is algebraically linked to asymmetry; adaptive/guard counts are low-cardinality descriptors. The anchor is not described as multi-dimensionally extreme. `ANCHOR_SPECIFIC_CLAIMS_ONLY` is retained for claims tied to the locked anchor geometry, not because multiple independent extremeness dimensions were found.", "",
              "### Sampled-skeleton limitation", "", f"- `MONOTONICITY_EVIDENCE_DOMAIN = {skeleton['MONOTONICITY_EVIDENCE_DOMAIN']}`", f"- `{skeleton['angular_interior_classification']}`",
              f"- median of the 32 timestamp-specific median actual angular gaps: {fmt(skeleton['median_of_timestamp_actual_median_angular_gaps_deg'])} deg",
              f"- maximum actual angular gap observed: {fmt(skeleton['maximum_actual_angular_gap_observed_deg'])} deg",
              f"- anchor median/maximum actual angular gaps: {fmt(skeleton['anchor_actual_median_angular_gap_deg'])}/{fmt(skeleton['anchor_actual_maximum_angular_gap_deg'])} deg",
              f"- guard-limited mixed-sign sectors: {skeleton['guard_limited_mixed_sign_sectors']}", "", skeleton["strongest_allowed_wording"], "",
              "The 87,086 converged evaluations lie on signed-axis trajectories, 36 base radial directions per timestamp, adaptive radial directions, and coarse-sweep/bisection points. The 49.83 million count is a count of comparable endpoint pairs on that finite skeleton, not sampled interior points. Future box corners and arbitrary coupled-polytope interior points may not coincide with sampled trajectories. This limitation must carry forward into DOE Construction Policy.", "",
              "### Corrected scientific interpretation", "",
              f"Stored attempts: 87,372; converged usable evaluations: 87,086; cross-trajectory comparable pairs: {overall['cross_trajectory_pairs_total']:,}; equality-only: {overall['equality_only_pairs']:,}; non-equality principal pairs: {overall['principal_non_equality_monotonicity_evidence_pairs']:,}; strict-2D pairs: {overall['strict_2D_pairs']:,}. No raw negative Delta Vmin/Delta Vmax and no logical VMIN/VMAX contradictions were observed.", "",
              "Finite skeleton evidence is not a theorem; comparable pairs are not sampled interior points; slack-pinned plateaus are not responsive Vmax evidence; rank extremeness is not effect size; algebraically linked metrics are not independent dimensions; all directional and symmetrized cardinal results are one diagnostic family; different active constraints do not share one pooled coefficient; and boundary reconciliation is not a new falsification experiment.", "",
              "Current classification: `NO_MONOTONICITY_COUNTEREXAMPLE_OBSERVED_IN_STORED_EVALUATIONS`. Authoritative project classification: `POSTPRODUCTION_RESULT_AUDIT_COMPLETE_WITH_DOCUMENTED_LIMITATIONS`.", ""]
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output-directory", type=Path, default=Path("results/dso_vpp_ac_map_pilot/doe_preconstruction_artifact_refinement"))
    args = parser.parse_args()
    root = args.repository_root.resolve()
    output = args.output_directory if args.output_directory.is_absolute() else root / args.output_directory
    branch, head = git(root, "branch", "--show-current"), git(root, "rev-parse", "HEAD")
    raw_status = git(root, "status", "--short")
    # Exclude this script and its regenerated output so repeated artifact-only
    # runs preserve the authoritative pre-analysis status in the report.
    pre_status = "\n".join(line for line in raw_status.splitlines()
                           if "doe_preconstruction_artifact_refinement" not in line
                           and "prepare_dso_vpp_doe_preconstruction_artifact_refinement.py" not in line)
    if branch != EXPECTED_BRANCH or head != EXPECTED_HEAD:
        raise SystemExit(f"repository mismatch branch={branch} head={head}")
    output.mkdir(parents=True, exist_ok=True)
    temp = output / ".temporary_pair_storage"
    if temp.exists():
        shutil.rmtree(temp)
    temp.mkdir()
    started = time.perf_counter()
    production = root / "results/dso_vpp_ac_map_pilot/production_probe"
    post = root / "results/dso_vpp_ac_map_pilot/postproduction_result_audit"
    mono = root / "results/dso_vpp_ac_map_pilot/monotonicity_falsification_screen"
    production_required = ["evaluation_attempts.csv", "signed_axis_results.csv", "center_results.csv",
                           "base_ray_results.csv", "adaptive_ray_results.csv", "boundary_endpoints.csv",
                           "timestamp_runtime_evaluation_summary.csv"]
    post_required = ["cardinal_ray_invariant_audit.csv", "axis_asymmetry.csv", "analytical_corner_geometric_audit.json",
                     "sampling_geometry_timestamp_summary.csv"]
    mono_required = ["monotonicity_falsification_summary.json", "region_summary.csv"]
    inputs = verify_manifest(production, production_required) + verify_manifest(post, post_required) + verify_manifest(mono, mono_required)
    sensitivity_source = root / "results/dso_vpp_ac_map_pilot/ac_anchored_linear_corner_audit_corner_margins.csv"
    inputs.append({"path": sensitivity_source.as_posix(), "bytes": sensitivity_source.stat().st_size,
                   "sha256": sha256(sensitivity_source), "schema": list(read_csv(sensitivity_source)[0])})
    for source in (root / "src/benchmark/dso_vpp_ac_map_stage0.jl", root / "src/validation/s1b_independent_replay.jl",
                   root / "src/benchmark/dso_vpp_production_probe.jl", root / "src/benchmark/dso_vpp_export_side_axis_scan.jl",
                   root / "src/benchmark/dso_vpp_operating_point_provenance.jl", root / "data_raw/case33bw.m"):
        inputs.append({"path": source.as_posix(), "bytes": source.stat().st_size, "sha256": sha256(source), "schema": None})
    by_time, centers, bounds, excluded = load_population(production)
    duplicate, _ = audit_duplicates(by_time, output)
    counts, record_count, zero = enumerate_pairs(by_time, temp)
    pair_rows = write_pair_summary(counts, output)
    write_zero_delta_decomposition(zero, output)
    separation = separation_scales(temp, record_count, output)
    percentile_rows = percentile_audit(separation, output)
    base, adaptive = read_csv(production / "base_ray_results.csv"), read_csv(production / "adaptive_ray_results.csv")
    axes = read_csv(production / "signed_axis_results.csv")
    endpoints = read_csv(production / "boundary_endpoints.csv")
    boundary_inventory = boundary_input_reconciliation(axes, base, adaptive, output)
    boundary = boundary_order_screen(base, adaptive, output)
    resolution = boundary_resolution_analysis(base, adaptive, axes, centers, bounds, endpoints, output)
    termination = boundary_bisection_termination_audit(production, base, adaptive, axes, output)
    asymmetry = read_csv(post / "axis_asymmetry.csv")
    cardinal, cardinal_rows, regressions = cardinal_analysis(read_csv(post / "cardinal_ray_invariant_audit.csv"), centers, bounds, asymmetry, base + adaptive, output)
    topology = reconstruct_sensitivity_topology(root, output)
    sensitivity = sensitivity_backcalculation(cardinal_rows, centers, bounds, root, output, topology, resolution)
    anchor, anchor_summary = anchor_metrics(production, centers, bounds, base, adaptive, asymmetry, output)
    skeleton = sampled_skeleton_limitation(post)
    corner = corner_result(post, base, adaptive)
    solver, timing, timing_rows = solver_and_timing()
    write_csv(output / "timing_scope_comparison.csv", timing_rows)
    provenance = {"branch": branch, "head": head, "preanalysis_git_status_short": pre_status}
    summary = {
        "classification": "POSTPRODUCTION_RESULT_AUDIT_COMPLETE_WITH_DOCUMENTED_LIMITATIONS",
        "repository": provenance, "artifact_inputs": inputs,
        "population": {"total_stored_attempts": 87372, "converged_usable": 87086, "excluded": excluded},
        "pair_class_decomposition": pair_rows, "empirical_separation_scale": separation,
        "solver_stopping_criterion": solver, "duplicate_coordinate_reproducibility": duplicate,
        "boundary_input_reconciliation": boundary_inventory, "boundary_order_closure": boundary,
        "zero_delta_voltage_decomposition": zero, "percentile_audit": percentile_rows,
        "cardinal_antisymmetry": cardinal,
        "exploratory_residual_scaling": regressions, "cardinal_sensitivity_backcalculation": sensitivity,
        "sensitivity_topology_reconstruction": topology,
        "boundary_location_resolution": resolution,
        "boundary_bisection_termination_audit": termination,
        "radial_linear_model_symmetrized_cross_check": sensitivity["symmetrized_cross_checks"],
        "anchor_representativeness": anchor, "anchor_interpretation_correction": anchor_summary,
        "sampled_skeleton_limitation": skeleton, "analytical_corner": corner, "timing_scope": timing,
    }
    write_json(output / "doe_preconstruction_artifact_refinement_summary.json", summary)
    shutil.rmtree(temp)
    elapsed = time.perf_counter() - started
    report_name = "doe_preconstruction_artifact_refinement_report.md"
    manifest_name = "artifact_manifest.csv"
    created_names = sorted(path.relative_to(root).as_posix() for path in output.iterdir()
                           if path.is_file() and path.name not in {report_name, manifest_name})
    final_status = git(root, "status", "--short")
    build_report(output / report_name, provenance, inputs, pair_rows, separation, boundary_inventory, boundary,
                 zero, percentile_rows, cardinal, sensitivity, topology, anchor, anchor_summary, skeleton,
                  resolution, termination,
                 sorted(created_names + [
                     (output / report_name).relative_to(root).as_posix(),
                     (output / manifest_name).relative_to(root).as_posix(),
                     "scripts/prepare_dso_vpp_doe_preconstruction_artifact_refinement.py",
                 ]), final_status)
    manifest_rows = [{"artifact": path.name, "bytes": path.stat().st_size, "sha256": sha256(path)}
                     for path in sorted(output.iterdir()) if path.is_file() and path.name != manifest_name]
    write_csv(output / manifest_name, manifest_rows)
    print(json.dumps({"classification": summary["classification"], "output": str(output),
                      "principal_pairs": pair_rows[0]["principal_non_equality_monotonicity_evidence_pairs"],
                      "runtime_seconds": elapsed}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
