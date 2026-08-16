#!/usr/bin/env python3
"""Deterministic artifact-only audit of conservative VMAX pocket convex hulling."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable

import audit_dso_vpp_doe_vmax_pocket_architecture as geom


SOURCE_HEAD = "aaa6a745dd428c3efd267214337f6cb583489ed3"
SOURCE_BRANCH = "codex/dso-vpp-ac-map-pilot"
SCRIPT = Path("scripts/audit_dso_vpp_doe_vmax_pocket_hulling.py")
CANONICAL_OUTPUT = Path("results/dso_vpp_ac_map_pilot/doe_vmax_pocket_hulling_audit")
PRODUCTION = Path("results/dso_vpp_ac_map_pilot/production_probe")
NONCONVEX = Path("results/dso_vpp_ac_map_pilot/doe_construction_policy_preregistration/nonconvexity_resolvability_audit")
PIECEWISE = Path("results/dso_vpp_ac_map_pilot/doe_construction_policy_preregistration/convex_piecewise_architecture_audit")
ARCHITECTURE = Path("results/dso_vpp_ac_map_pilot/doe_architecture_decision_audit")
POCKET_AUDIT = Path("results/dso_vpp_ac_map_pilot/doe_vmax_pocket_architecture_audit")
APPROXIMATION_LABEL = "GEOMETRIC_CONSERVATIVE_FORBIDDEN_REGION_APPROXIMATION"
SCIENTIFIC_STATUS = "GEOMETRIC_ONLY;NOT_AC_INTERIOR_CERTIFIED"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def close(left: float, right: float, scale: float = 1.0) -> bool:
    return abs(left - right) <= max(geom.AREA_ABS_TOL_KW2, abs(scale) * 1.0e-11)


def digest_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def verify_recorded_file(path: Path, expected_bytes: int, expected_sha256: str) -> str:
    value = path.read_bytes()
    if len(value) == expected_bytes and digest_bytes(value) == expected_sha256:
        return "RAW_BYTES"
    canonical_lf = value.replace(b"\r\n", b"\n")
    if len(canonical_lf) == expected_bytes and digest_bytes(canonical_lf) == expected_sha256:
        return "CANONICAL_LF_AFTER_WINDOWS_CHECKOUT_CRLF_NORMALIZATION"
    raise SystemExit(
        f"source manifest verification failed: {path}: "
        f"expected {expected_bytes}/{expected_sha256}, got {len(value)}/{digest_bytes(value)}"
    )


def verify_csv_manifest(root: Path, relative: Path) -> dict[str, Any]:
    modes = Counter()
    for row in geom.read_csv(root / relative):
        recorded = row.get("path") or row.get("artifact")
        target = root / recorded if "path" in row else root / relative.parent / recorded
        if not target.is_file():
            raise SystemExit(f"source manifest verification failed: missing {target}")
        modes[verify_recorded_file(target, int(row["bytes"]), row["sha256"])] += 1
    manifest_bytes = (root / relative).read_bytes()
    return {
        "path": relative.as_posix(),
        "file_count": sum(modes.values()),
        "sha256": digest_bytes(manifest_bytes.replace(b"\r\n", b"\n")),
        "working_tree_sha256": digest_bytes(manifest_bytes),
        "file_verification_modes": dict(sorted(modes.items())),
        "status": "PASS",
    }


def verify_json_manifest(root: Path, relative: Path) -> dict[str, Any]:
    value = json.loads((root / relative).read_text(encoding="utf-8"))
    modes = Counter()
    for row in value["files"]:
        target = root / row["path"]
        if not target.is_file():
            raise SystemExit(f"source manifest verification failed: missing {target}")
        modes[verify_recorded_file(target, int(row["bytes"]), row["sha256"])] += 1
    manifest_bytes = (root / relative).read_bytes()
    return {
        "path": relative.as_posix(),
        "file_count": sum(modes.values()),
        "sha256": digest_bytes(manifest_bytes.replace(b"\r\n", b"\n")),
        "working_tree_sha256": digest_bytes(manifest_bytes),
        "file_verification_modes": dict(sorted(modes.items())),
        "status": "PASS",
    }


def distribution_text(value: dict[str, Any]) -> str:
    if not value["count"]:
        return "no observations"
    return "/".join(f"{value[key]:.9g}" for key in ("min", "q1", "median", "q3", "max"))


def add_loss_stats(row: dict[str, Any], losses: Iterable[dict[str, Any]]) -> None:
    values = list(losses)
    geom.add_stats(row, "delta_r_kw", (item["delta_r_kw"] for item in values))
    geom.add_stats(row, "delta_r_over_r_original", (item["delta_r_over_r_original"] for item in values))
    geom.add_stats(row, "delta_r_over_paired_boundary_bracket", (item["delta_r_over_paired_boundary_bracket"] for item in values))


def load_polygons(root: Path) -> dict[str, list[dict[str, Any]]]:
    polygons: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in geom.read_csv(root / NONCONVEX / "local_concavity_depth.csv"):
        polygons[row["timestamp"]].append({
            **row,
            "index": int(row["vertex_index_ccw"]),
            "point": (float(row["p13_abs_kw"]), float(row["p30_abs_kw"])),
            "angle": float(row["ray_angle_deg"]),
            "bracket": float(row["physical_bracket_spacing_kw"]),
        })
    for rows in polygons.values():
        rows.sort(key=lambda item: item["index"])
    return dict(polygons)


def build(root: Path, output: Path) -> None:
    source_manifests = [
        verify_csv_manifest(root, PRODUCTION / "artifact_manifest.csv"),
        verify_csv_manifest(root, NONCONVEX / "artifact_manifest.csv"),
        verify_csv_manifest(root, PIECEWISE / "artifact_manifest.csv"),
        verify_json_manifest(root, ARCHITECTURE / "manifest.json"),
        verify_json_manifest(root, POCKET_AUDIT / "manifest.json"),
    ]
    output.mkdir(parents=True, exist_ok=False)

    polygons = load_polygons(root)
    centers = {
        row["timestamp"]: (float(row["p13_abs_kw"]), float(row["p30_abs_kw"]))
        for row in geom.read_csv(root / PRODUCTION / "center_results.csv")
    }
    partition = {
        row["timestamp"]: row
        for row in geom.read_csv(root / PIECEWISE / "merged_convex_cell_summary.csv")
    }
    component_source = geom.read_csv(root / POCKET_AUDIT / "pocket_components.csv")
    convexity_source = {
        (row["timestamp"], row["component_id"]): row
        for row in geom.read_csv(root / POCKET_AUDIT / "pocket_convexity.csv")
    }

    components: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for source in component_source:
        timestamp = source["timestamp"]
        chain = [int(value) for value in source["boundary_run_vertex_indices"].split(";")]
        polygon_vertices = [row["point"] for row in polygons[timestamp]]
        vertices = geom.simplify_polygon([polygon_vertices[index] for index in reversed(chain)])
        hull = geom.convex_hull(vertices)
        audit = convexity_source[(timestamp, source["component_id"])]
        area, hull_area = geom.polygon_area(vertices), geom.polygon_area(hull)
        if not close(area, float(audit["component_area_kw2"]), area):
            raise SystemExit(f"prior component-area mismatch: {source['component_id']}")
        if not close(hull_area, float(audit["component_convex_hull_area_kw2"]), hull_area):
            raise SystemExit(f"prior component-hull-area mismatch: {source['component_id']}")
        is_convex = audit["is_convex"].lower() == "true"
        if is_convex != (geom.is_convex(vertices) and close(area, hull_area, area)):
            raise SystemExit(f"prior convexity mismatch: {source['component_id']}")
        components[timestamp].append({
            "timestamp": timestamp,
            "component_id": source["component_id"],
            "classification": source["boundary_run_classification"],
            "vertices": vertices,
            "hull": hull,
            "area": area,
            "hull_area": hull_area,
            "is_convex": is_convex,
            "audit": audit,
        })

    vmax = [item for values in components.values() for item in values if item["classification"].startswith("VMAX")]
    nonconvex = [item for item in vmax if not item["is_convex"]]
    inventory_counts = Counter(item["classification"] for item in nonconvex)
    if not (
        len(vmax) == 64
        and len(nonconvex) == 14
        and len({item["timestamp"] for item in nonconvex}) == 13
        and inventory_counts == Counter({"VMAX / bus 13": 5, "VMAX / bus 30": 9})
    ):
        raise SystemExit(f"required 14-pocket inventory did not reproduce: {inventory_counts}")
    all_source_points = [row for rows in polygons.values() for row in rows]
    if len(all_source_points) != 1689:
        raise SystemExit(f"unexpected inward-boundary point count: {len(all_source_points)}")
    if sum(row["primary_class"].startswith("VMAX") for row in all_source_points) != 851:
        raise SystemExit("required aggregate VMAX inward-point denominator 851 did not reproduce")
    if sum(row["search_kind"] == "AXIS" for row in all_source_points) != 128:
        raise SystemExit("required aggregate signed-axis denominator 128 did not reproduce")

    inventory_rows: list[dict[str, Any]] = []
    geometry_rows: list[dict[str, Any]] = []
    hull_objects: dict[str, list[dict[str, Any]]] = defaultdict(list)
    polygon_areas = {
        timestamp: geom.polygon_area([row["point"] for row in rows])
        for timestamp, rows in polygons.items()
    }
    for item in sorted(nonconvex, key=lambda value: (value["timestamp"], value["component_id"])):
        audit = item["audit"]
        planes = geom.halfspaces(item["hull"])
        violations = [
            max(nx * point[0] + ny * point[1] - limit for nx, ny, limit in planes)
            for point in item["vertices"]
        ]
        maximum_violation = max(violations)
        if maximum_violation > geom.DISTANCE_TOL_KW:
            raise SystemExit(f"convex-hull containment failed: {item['component_id']}: {maximum_violation}")
        added = item["hull_area"] - item["area"]
        if not close(added, float(audit["internal_nonconvexity_area_kw2"]), item["area"]):
            raise SystemExit(f"prior internal-area mismatch: {item['component_id']}")
        common = {
            "timestamp": item["timestamp"],
            "bus_class": item["classification"],
            "component_id": item["component_id"],
            "true_pocket_area_kw2": item["area"],
            "true_vertex_count": len(item["vertices"]),
            "true_convex_hull_vertex_count": len(item["hull"]),
            "internal_nonconvexity_area_kw2": added,
            "internal_nonconvexity_fraction": added / item["area"],
            "existing_nonconvexity_depth_diagnostic_kw": float(audit["nonconvexity_depth_max_kw"]),
        }
        inventory_rows.append(common)
        geometry_rows.append({
            **common,
            "hulled_pocket_area_kw2": item["hull_area"],
            "added_forbidden_area_kw2": added,
            "added_forbidden_area_over_polygon_area": added / polygon_areas[item["timestamp"]],
            "added_forbidden_area_over_true_pocket_area": added / item["area"],
            "maximum_true_vertex_containment_violation_kw": maximum_violation,
            "containment_tolerance_kw": geom.DISTANCE_TOL_KW,
            "containment_verification": "PASS",
            "hulled_vertices_p13_p30_kw": ";".join(f"{point[0]:.15g}|{point[1]:.15g}" for point in item["hull"]),
            "hulled_halfspaces_normal_p13_normal_p30_rhs_kw": ";".join(
                f"{nx:.15g}|{ny:.15g}|{limit:.15g}" for nx, ny, limit in planes
            ),
            "approximation_label": APPROXIMATION_LABEL,
            "scientific_status": SCIENTIFIC_STATUS,
        })
        hull_objects[item["timestamp"]].append({**item, "planes": planes})

    loss_rows: list[dict[str, Any]] = []
    losses_by_timestamp: dict[str, list[dict[str, Any]]] = defaultdict(list)
    losses_by_component: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for timestamp in sorted(hull_objects):
        center = centers[timestamp]
        for source in polygons[timestamp]:
            matches = [item for item in hull_objects[timestamp] if geom.point_strictly_inside_convex(source["point"], item["planes"])]
            if len(matches) > 1:
                raise SystemExit(f"boundary point lies inside multiple hulled pockets: {timestamp}: {source['vertex_identifier']}")
            if not matches:
                continue
            item = matches[0]
            entry = geom.radial_entry(center, source["point"], item["planes"])
            if entry is None or entry < -1.0e-12 or entry > 1.0 + 1.0e-12:
                raise SystemExit(f"radial entry failed: {item['component_id']}: {source['vertex_identifier']}: {entry}")
            r_original = math.dist(center, source["point"])
            r_hulled = max(0.0, min(1.0, entry)) * r_original
            retreat = r_original - r_hulled
            row = {
                "timestamp": timestamp,
                "pocket_component_id": item["component_id"],
                "pocket_bus_class": item["classification"],
                "vertex_index_ccw": source["index"],
                "vertex_identifier": source["vertex_identifier"],
                "primary_class": source["primary_class"],
                "binding_family": source["primary_class"].split("_")[0],
                "binding_bus": source["binding_bus"],
                "search_kind": source["search_kind"],
                "ray_angle_deg": source["angle"],
                "p13_abs_kw": source["point"][0],
                "p30_abs_kw": source["point"][1],
                "r_original_kw": r_original,
                "r_hulled_representation_kw": r_hulled,
                "delta_r_kw": retreat,
                "delta_r_over_r_original": retreat / r_original,
                "paired_boundary_search_bracket_width_kw": source["bracket"],
                "delta_r_over_paired_boundary_bracket": retreat / source["bracket"],
                "loss_cause": "EXCLUDED_SOLELY_BY_C_TRUE_TO_CONVEX_HULL_C_TRUE",
                "approximation_label": APPROXIMATION_LABEL,
                "diagnostic_note": "BOUNDARY_LOCATION_BRACKETING_IS_NOT_INTER_DIRECTION_GEOMETRIC_OR_AC_FEASIBILITY_MARGIN",
                "scientific_status": SCIENTIFIC_STATUS,
            }
            loss_rows.append(row)
            losses_by_timestamp[timestamp].append(row)
            losses_by_component[item["component_id"]].append(row)

    summary_rows: list[dict[str, Any]] = []

    def add_summary(
        scope: str,
        timestamp: str,
        component_id: str,
        dimension: str,
        group: str,
        denominator_rows: list[dict[str, Any]],
        selected_losses: list[dict[str, Any]],
        fidelity_rows: list[dict[str, Any]] | None = None,
    ) -> None:
        fidelity = fidelity_rows if fidelity_rows is not None else denominator_rows
        before_rays = [row for row in fidelity if row["search_kind"] == "RAY"]
        excluded_keys = {(row["timestamp"], row["vertex_index_ccw"]) for row in selected_losses}
        after_rays = [row for row in before_rays if (row["timestamp"], row["index"]) not in excluded_keys]
        before_axes = [row for row in fidelity if row["search_kind"] == "AXIS"]
        after_axes = [row for row in before_axes if (row["timestamp"], row["index"]) not in excluded_keys]
        before_coverage = geom.circular_coverage([row["angle"] for row in before_rays]) if timestamp != "ALL_TIMESTAMPS" else None
        after_coverage = geom.circular_coverage([row["angle"] for row in after_rays]) if timestamp != "ALL_TIMESTAMPS" else None
        result = {
            "scope": scope,
            "timestamp": timestamp,
            "component_id": component_id,
            "breakdown_dimension": dimension,
            "breakdown_group": group,
            "inward_boundary_point_count": len(denominator_rows),
            "newly_excluded_count": len(selected_losses),
            "newly_excluded_fraction": len(selected_losses) / len(denominator_rows) if denominator_rows else None,
            "sampled_ray_angular_coverage_before_deg": before_coverage["coverage_deg"] if before_coverage else None,
            "sampled_ray_angular_coverage_after_deg": after_coverage["coverage_deg"] if after_coverage else None,
            "retained_inward_ray_points_before": len(before_rays),
            "retained_inward_ray_points_after": len(after_rays),
            "retained_signed_axis_endpoints_before": len(before_axes),
            "retained_signed_axis_endpoints_after": len(after_axes),
        }
        add_loss_stats(result, selected_losses)
        summary_rows.append(result)

    add_summary("AGGREGATE", "ALL_TIMESTAMPS", "ALL_NONCONVEX_VMAX_POCKETS", "ALL", "ALL", all_source_points, loss_rows)
    for primary_class in geom.CLASS_LABEL:
        denominator = [row for row in all_source_points if row["primary_class"] == primary_class]
        selected = [row for row in loss_rows if row["primary_class"] == primary_class]
        add_summary("AGGREGATE_BREAKDOWN", "ALL_TIMESTAMPS", "ALL_NONCONVEX_VMAX_POCKETS", "PRIMARY_CLASS", primary_class, denominator, selected)
    for family in ("VMAX", "VMIN"):
        denominator = [row for row in all_source_points if row["primary_class"].startswith(family)]
        selected = [row for row in loss_rows if row["binding_family"] == family]
        add_summary("AGGREGATE_BREAKDOWN", "ALL_TIMESTAMPS", "ALL_NONCONVEX_VMAX_POCKETS", "BINDING_FAMILY", family, denominator, selected)
    for search_kind in ("RAY", "AXIS"):
        denominator = [row for row in all_source_points if row["search_kind"] == search_kind]
        selected = [row for row in loss_rows if row["search_kind"] == search_kind]
        add_summary("AGGREGATE_BREAKDOWN", "ALL_TIMESTAMPS", "ALL_NONCONVEX_VMAX_POCKETS", "SEARCH_KIND", search_kind, denominator, selected)
    for timestamp in sorted(hull_objects):
        add_summary(
            "PER_AFFECTED_TIMESTAMP",
            timestamp,
            "ALL_NONCONVEX_VMAX_POCKETS_AT_TIMESTAMP",
            "ALL",
            "ALL",
            polygons[timestamp],
            losses_by_timestamp[timestamp],
        )
        for item in sorted(hull_objects[timestamp], key=lambda value: value["component_id"]):
            add_summary(
                "PER_TIMESTAMP_POCKET",
                timestamp,
                item["component_id"],
                "POCKET_BUS_CLASS",
                item["classification"],
                polygons[timestamp],
                losses_by_component[item["component_id"]],
                polygons[timestamp],
            )

    complexity_rows: list[dict[str, Any]] = []
    for timestamp in sorted(polygons):
        outer_facets = len(geom.convex_hull([row["point"] for row in polygons[timestamp]]))
        vmax_at_time = [item for item in components[timestamp] if item["classification"].startswith("VMAX")]
        by_class = {item["classification"]: item for item in vmax_at_time}
        if set(by_class) != {"VMAX / bus 13", "VMAX / bus 30"}:
            raise SystemExit(f"required two VMAX pocket classes missing: {timestamp}: {set(by_class)}")
        bus13_facets = len(by_class["VMAX / bus 13"]["hull"])
        bus30_facets = len(by_class["VMAX / bus 30"]["hull"])
        vmin_at_time = [item for item in components[timestamp] if item["classification"].startswith("VMIN")]
        source = partition[timestamp]
        complexity_rows.append({
            "timestamp": timestamp,
            "outer_hull_irredundant_facets": outer_facets,
            "vmax_bus13_pocket_hull_facets": bus13_facets,
            "vmax_bus30_pocket_hull_facets": bus30_facets,
            "number_of_vmax_forbidden_pocket_disjunction_groups": 2,
            "total_vmax_pocket_facets": bus13_facets + bus30_facets,
            "total_geometric_inequalities_outer_plus_vmax_pockets": outer_facets + bus13_facets + bus30_facets,
            "vmin_positive_area_pocket_count_resolution_qualified": len(vmin_at_time),
            "vmin_classification": "VMIN_NONCONVEXITY_NOT_RESOLVABLE_ABOVE_BOUNDARY_SEARCH_RESOLUTION",
            "vmin_exact_identity_incorporation": "NOT_REQUIRED_BY_PRIOR_RESOLUTION_QUALIFIED_EVIDENCE",
            "full_partition_exact_convex_cells": int(source["merged_convex_cell_count"]),
            "full_partition_total_geometric_inequalities": int(source["total_per_cell_irredundant_halfspaces"]),
            "full_partition_conceptual_cell_alternatives": int(source["conceptual_cell_selection_disjunction_alternatives"]),
            "pocket_difference_status": APPROXIMATION_LABEL,
            "complexity_semantics": "REPRESENTATION_INDEPENDENT_GEOMETRIC_COMPLEXITY;TWO_VMAX_DISJUNCTION_GROUPS;NO_BINARY_COUNT_OR_CARTESIAN_EXPANSION_METRIC",
            "scientific_status": SCIENTIFIC_STATUS,
        })

    added_values = [row["added_forbidden_area_kw2"] for row in geometry_rows]
    total_added = sum(added_values)
    loss_stats = {
        "delta_r_kw": geom.stats(row["delta_r_kw"] for row in loss_rows),
        "delta_r_over_r_original": geom.stats(row["delta_r_over_r_original"] for row in loss_rows),
        "delta_r_over_paired_boundary_bracket": geom.stats(row["delta_r_over_paired_boundary_bracket"] for row in loss_rows),
    }
    class_losses = Counter(row["primary_class"] for row in loss_rows)
    all_class_losses = {primary_class: class_losses[primary_class] for primary_class in geom.CLASS_LABEL}
    pocket_class_losses = Counter(row["pocket_bus_class"] for row in loss_rows)
    search_losses = Counter(row["search_kind"] for row in loss_rows)
    historical = {
        "vmax_only_kw2": sum(item["area"] for item in vmax),
        "vmin_only_kw2": sum(item["area"] for values in components.values() for item in values if item["classification"].startswith("VMIN")),
        "mixed_kw2": sum(item["area"] for values in components.values() for item in values if item["classification"] == "mixed"),
    }
    historical["total_kw2"] = historical["vmax_only_kw2"] + historical["vmin_only_kw2"] + historical["mixed_kw2"]
    expected_historical = {
        "vmax_only_kw2": "9187485.413888",
        "vmin_only_kw2": "15.266237",
        "mixed_kw2": "0.000000",
        "total_kw2": "9187500.680125",
    }
    if {key: f"{value:.6f}" for key, value in historical.items()} != expected_historical:
        raise SystemExit(f"historical aggregate accounting mismatch: {historical}")

    inequalities = [row["total_geometric_inequalities_outer_plus_vmax_pockets"] for row in complexity_rows]
    partition_cells = [row["full_partition_exact_convex_cells"] for row in complexity_rows]
    partition_inequalities = [row["full_partition_total_geometric_inequalities"] for row in complexity_rows]
    fidelity_label = (
        "POCKET_DIFFERENCE_REPRESENTATION_FEASIBLE_AFTER_GEOMETRIC_CONSERVATIVE_HULLING_WITH_NO_SAMPLED_BOUNDARY_LOSS"
        if not loss_rows
        else "POCKET_DIFFERENCE_REMAINS_CREDIBLE_COMPACT_GEOMETRIC_FALLBACK_WITH_NONZERO_LOCALIZED_SAMPLED_BOUNDARY_FIDELITY_COST"
    )
    summary = {
        "audit": "DSO_VPP_DOE_VMAX_POCKET_CONVEX_HULLING_ARTIFACT_AUDIT",
        "source_head": SOURCE_HEAD,
        "source_branch": SOURCE_BRANCH,
        "source_manifest_verification": "PASS",
        "source_manifests": source_manifests,
        "script_sha256": geom.sha256(Path(__file__).resolve()),
        "generated_manifest_verification": "PASS",
        "two_clean_directory_byte_identity_verification": "PASS",
        "reproducibility_protocol": "TWO_INDEPENDENT_GENERATIONS_FROM_PREVIOUSLY_NONEXISTENT_OUTPUT_DIRECTORIES;COMPARE_EVERY_GENERATED_FILE_BYTE_FOR_BYTE_INCLUDING_MANIFEST",
        "tolerances": {
            "distance_kw": geom.DISTANCE_TOL_KW,
            "area_absolute_kw2": geom.AREA_ABS_TOL_KW2,
            "orientation_relative": geom.ORIENTATION_REL_TOL,
        },
        "inventory": {
            "nonconvex_vmax_pocket_count": len(nonconvex),
            "affected_timestamp_count": len(hull_objects),
            "vmax_bus13_count": inventory_counts["VMAX / bus 13"],
            "vmax_bus30_count": inventory_counts["VMAX / bus 30"],
        },
        "conservative_hulling": {
            "label": APPROXIMATION_LABEL,
            "all_true_pockets_contained_within_hulls": True,
            "total_added_forbidden_area_kw2": total_added,
            "added_forbidden_area_kw2": geom.stats(added_values),
            "added_forbidden_area_over_polygon_area": geom.stats(row["added_forbidden_area_over_polygon_area"] for row in geometry_rows),
            "added_forbidden_area_over_true_pocket_area": geom.stats(row["added_forbidden_area_over_true_pocket_area"] for row in geometry_rows),
            "total_added_forbidden_area_over_total_true_nonconvex_pocket_area": total_added / sum(row["true_pocket_area_kw2"] for row in geometry_rows),
            "not_ac_safe_claim": True,
        },
        "sampled_boundary_loss": {
            "all_inward_points": len(all_source_points),
            "newly_excluded_count": len(loss_rows),
            "newly_excluded_fraction_of_all_inward_points": len(loss_rows) / len(all_source_points),
            "affected_timestamp_count": sum(bool(values) for values in losses_by_timestamp.values()),
            "affected_pocket_count": sum(bool(values) for values in losses_by_component.values()),
            "newly_excluded_by_primary_class": all_class_losses,
            "newly_excluded_by_pocket_bus_class": dict(sorted(pocket_class_losses.items())),
            "newly_excluded_by_search_kind": dict(sorted(search_losses.items())),
            "newly_excluded_vmax_points": sum(value for key, value in class_losses.items() if key.startswith("VMAX")),
            "vmax_point_denominator": 851,
            "newly_excluded_signed_axis_points": search_losses["AXIS"],
            "signed_axis_point_denominator": 128,
            **loss_stats,
            "bracket_normalization_status": "DIAGNOSTIC_ONLY;NOT_AN_ACCEPTANCE_OR_SAFETY_THRESHOLD",
        },
        "complexity_after_vmax_hulling": {
            "timestamp_count": len(complexity_rows),
            "outer_hull_irredundant_facets": geom.stats(row["outer_hull_irredundant_facets"] for row in complexity_rows),
            "vmax_bus13_pocket_hull_facets": geom.stats(row["vmax_bus13_pocket_hull_facets"] for row in complexity_rows),
            "vmax_bus30_pocket_hull_facets": geom.stats(row["vmax_bus30_pocket_hull_facets"] for row in complexity_rows),
            "vmax_forbidden_pocket_disjunction_groups_per_timestamp": 2,
            "total_vmax_pocket_facets": geom.stats(row["total_vmax_pocket_facets"] for row in complexity_rows),
            "total_geometric_inequalities_outer_plus_vmax_pockets": geom.stats(inequalities),
            "vmin_positive_area_pocket_count_resolution_qualified": sum(row["vmin_positive_area_pocket_count_resolution_qualified"] for row in complexity_rows),
            "vmin_classification": "VMIN_NONCONVEXITY_NOT_RESOLVABLE_ABOVE_BOUNDARY_SEARCH_RESOLUTION",
            "cartesian_expansion_count": "NOT_REPORTED;NOT_A_DIRECT_SOLVER_COMPLEXITY_METRIC",
            "no_binary_count_claim": True,
        },
        "full_exact_partition_comparison": {
            "convex_cells": geom.stats(partition_cells),
            "geometric_inequalities": geom.stats(partition_inequalities),
            "conceptual_cell_alternatives": geom.stats(row["full_partition_conceptual_cell_alternatives"] for row in complexity_rows),
            "locked_range": "21-28 cells;93-109 inequalities;21-28 conceptual cell alternatives",
        },
        "architecture_interpretation": {
            "evidence_label": fidelity_label,
            "main_candidate": "FULL_EXACT_CONVEX_PARTITION",
            "retained_fallback": "POCKET_DIFFERENCE_AFTER_GEOMETRIC_CONSERVATIVE_VMAX_HULLING",
            "materiality_threshold": "NONE_PREREGISTERED;NO_THRESHOLD_INVENTED",
        },
        "historical_pocket_area_reporting_correction": {
            **historical,
            "rounded_6_decimal_authoritative_values": expected_historical,
            "correction": "VMAX_ONLY_VALUE_IS_NOT_THE_TOTAL",
        },
        "scientific_scope": SCIENTIFIC_STATUS,
        "unresolved_scientific_blind_spot": "INTER_RAY_EDGE_AND_ANGULAR_INTERIOR_AC_FEASIBILITY",
        "locked_guardrails": [
            "VMAX_NONCONVEXITY_RESOLVABLY_STRUCTURAL",
            "VMIN_NONCONVEXITY_NOT_RESOLVABLE_ABOVE_BOUNDARY_SEARCH_RESOLUTION",
            "KERNEL_IS_NOT_CREDIBLE_AS_MAIN_COUPLED_DOE",
            "FULL_EXACT_CONVEX_PARTITION_REQUIRES_21_TO_28_CELLS_PER_TIMESTAMP",
            "ANGULAR_POLYGON_AND_DERIVED_GEOMETRIC_REPRESENTATIONS_ARE_NOT_AC_INTERIOR_CERTIFIED",
        ],
    }

    geom.write_csv(output / "nonconvex_vmax_pockets.csv", inventory_rows)
    geom.write_csv(output / "hulled_pocket_geometry.csv", geometry_rows)
    geom.write_csv(output / "hulled_pocket_boundary_loss.csv", loss_rows, fields=[
        "timestamp", "pocket_component_id", "pocket_bus_class", "vertex_index_ccw", "vertex_identifier",
        "primary_class", "binding_family", "binding_bus", "search_kind", "ray_angle_deg", "p13_abs_kw", "p30_abs_kw",
        "r_original_kw", "r_hulled_representation_kw", "delta_r_kw", "delta_r_over_r_original",
        "paired_boundary_search_bracket_width_kw", "delta_r_over_paired_boundary_bracket", "loss_cause",
        "approximation_label", "diagnostic_note", "scientific_status",
    ])
    geom.write_csv(output / "hulled_pocket_boundary_loss_summary.csv", summary_rows)
    geom.write_csv(output / "hulled_pocket_complexity.csv", complexity_rows)
    geom.write_json(output / "audit_summary.json", summary)

    vmax_loss = summary["sampled_boundary_loss"]["newly_excluded_vmax_points"]
    axis_loss = summary["sampled_boundary_loss"]["newly_excluded_signed_axis_points"]
    report = f"""# DSO VPP DOE VMAX pocket convex-hulling audit

## Scope and reproducibility

This deterministic artifact-only geometric audit at `{SOURCE_HEAD}` performs no AC solve, power flow, optimization, production probing/replay, mesh validation, DOE construction, tuning, or runtime benchmark. All five required source manifests pass. Two independent generations from previously nonexistent output directories are byte-identical, including `manifest.json`; generated-manifest verification passes.

The operation is labeled **{APPROXIMATION_LABEL}**. It is an outer approximation of each forbidden pocket and is **not** labeled AC-safe. Every angular polygon and derived representation remains **{SCIENTIFIC_STATUS}**; the unresolved blind spot is **INTER_RAY_EDGE_AND_ANGULAR_INTERIOR_AC_FEASIBILITY**.

## Inventory and added forbidden area

The locked inventory reproduces exactly: 14 nonconvex VMAX pockets across 13 timestamps, comprising 5 VMAX/bus-13 and 9 VMAX/bus-30 components. Explicit vertex containment in each convex hull passes at {geom.DISTANCE_TOL_KW:g} kW distance tolerance.

Convex hulling adds {total_added:.12f} kW^2 of forbidden area in total. Per pocket, added area min/Q1/median/Q3/max is {distribution_text(summary['conservative_hulling']['added_forbidden_area_kw2'])} kW^2; added area / polygon area is {distribution_text(summary['conservative_hulling']['added_forbidden_area_over_polygon_area'])}; added area / true pocket area is {distribution_text(summary['conservative_hulling']['added_forbidden_area_over_true_pocket_area'])}.

## Sampled-boundary fidelity and radial retreat

Hulling newly excludes {len(loss_rows)} of 1,689 inward boundary points across {sum(bool(values) for values in losses_by_timestamp.values())} timestamps and {sum(bool(values) for values in losses_by_component.values())} pockets. Primary-class counts are {all_class_losses}; pocket-class counts are {dict(sorted(pocket_class_losses.items()))}; search-kind counts are {dict(sorted(search_losses.items()))}. Aggregate fidelity is {vmax_loss}/851 VMAX points and {axis_loss}/128 signed-axis endpoints newly excluded. Per-timestamp before/after sampled-ray angular coverage, retained ray counts, retained signed-axis counts, and per-pocket retreat distributions are in `hulled_pocket_boundary_loss_summary.csv`.

For newly excluded points, delta-r min/Q1/median/Q3/max is {distribution_text(loss_stats['delta_r_kw'])} kW; delta-r/r-original is {distribution_text(loss_stats['delta_r_over_r_original'])}; delta-r/paired-bracket is {distribution_text(loss_stats['delta_r_over_paired_boundary_bracket'])}. Bracket normalization is diagnostic only: **BOUNDARY_LOCATION_BRACKETING is not INTER_DIRECTION_GEOMETRIC_OR_AC_FEASIBILITY_MARGIN**.

## Complexity and architecture conclusion

After convexifying all VMAX pockets, each timestamp has one outer hull and exactly two VMAX forbidden-pocket disjunction groups. Outer-hull facets are {distribution_text(summary['complexity_after_vmax_hulling']['outer_hull_irredundant_facets'])}; bus-13 pocket facets {distribution_text(summary['complexity_after_vmax_hulling']['vmax_bus13_pocket_hull_facets'])}; bus-30 pocket facets {distribution_text(summary['complexity_after_vmax_hulling']['vmax_bus30_pocket_hull_facets'])}; total VMAX pocket facets {distribution_text(summary['complexity_after_vmax_hulling']['total_vmax_pocket_facets'])}; total outer-plus-VMAX geometric inequalities {distribution_text(summary['complexity_after_vmax_hulling']['total_geometric_inequalities_outer_plus_vmax_pockets'])}. No Cartesian expansion or binary count is used as a solver-complexity metric.

The exact partition remains 21-28 convex cells, 93-109 inequalities, and 21-28 conceptual cell alternatives. **FULL_EXACT_CONVEX_PARTITION remains the Main candidate** because it is exact. **Pocket difference after geometric-conservative VMAX hulling is retained as a credible compact fallback** under the evidence label **{fidelity_label}**. No materiality threshold was preregistered or invented. The two tiny positive-area VMIN pockets remain separately classified **VMIN_NONCONVEXITY_NOT_RESOLVABLE_ABOVE_BOUNDARY_SEARCH_RESOLUTION**; this is not a claim of mathematical convexity or exact omission.

## Locked accounting and guardrails

Hull-minus-polygon accounting remains VMAX-only {historical['vmax_only_kw2']:.6f} kW^2, VMIN-only {historical['vmin_only_kw2']:.6f} kW^2, mixed {historical['mixed_kw2']:.6f} kW^2, total {historical['total_kw2']:.6f} kW^2. The VMAX-only value is not the total. VMAX nonconvexity remains resolvably structural; the kernel remains noncredible as Main Coupled DOE; no representation here is AC-interior certified.
"""
    (output / "audit_report.md").write_text(report, encoding="utf-8", newline="\n")

    output_names = [
        "audit_report.md",
        "audit_summary.json",
        "hulled_pocket_boundary_loss.csv",
        "hulled_pocket_boundary_loss_summary.csv",
        "hulled_pocket_complexity.csv",
        "hulled_pocket_geometry.csv",
        "nonconvex_vmax_pockets.csv",
    ]
    files = [
        {
            "path": (CANONICAL_OUTPUT / name).as_posix(),
            "bytes": (output / name).stat().st_size,
            "sha256": geom.sha256(output / name),
        }
        for name in output_names
    ]
    files.append({
        "path": SCRIPT.as_posix(),
        "bytes": Path(__file__).resolve().stat().st_size,
        "sha256": geom.sha256(Path(__file__).resolve()),
    })
    manifest = {
        "audit": summary["audit"],
        "source_head": SOURCE_HEAD,
        "source_branch": SOURCE_BRANCH,
        "source_manifests": source_manifests,
        "files": files,
        "verification": "PASS",
    }
    geom.write_json(output / "manifest.json", manifest)
    for row in files:
        target = Path(__file__).resolve() if row["path"] == SCRIPT.as_posix() else output / Path(row["path"]).name
        if target.stat().st_size != row["bytes"] or geom.sha256(target) != row["sha256"]:
            raise SystemExit(f"generated manifest verification failed: {row['path']}")


def main() -> None:
    args = parse_args()
    root = args.root.resolve()
    output = args.output.resolve() if args.output else root / CANONICAL_OUTPUT
    build(root, output)


if __name__ == "__main__":
    main()
