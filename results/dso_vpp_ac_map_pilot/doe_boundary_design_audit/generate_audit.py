#!/usr/bin/env python3
"""Deterministically generate the DOE boundary-design audit sidecars.

This script reads committed evidence only.  It does not call an AC evaluator,
an optimizer, or any production-probe runner.
"""

from __future__ import annotations

import argparse
import csv
import io
import math
import subprocess
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
RESULTS = ROOT / "results" / "dso_vpp_ac_map_pilot"
REFERENCE_PV_KW = 777.7133428167988
AUDITED_TIMESTAMP = "2012-10-15 13:00:00"
AUDIT_BASE_HEAD = "8ce89e4de76a14ecbe8de29611f112d5695854da"
REMOTE_TIP = "d8e1bb0a7909711b4124f95673fb3a4802ae783a"
LOCAL_COMMITS = [
    ("4c478232428dcb8f28be2d85ed12cf1c84fc7925", "test: verify Phase-B operating-point provenance"),
    ("5fc6ac12fe115acf2de282b5c10c821d400e0cc7", "docs: amend probe metrics after provenance audit"),
    ("461892dcae37b16c1e640d430ab0df92957fc5cd", "docs: clarify multi-interface TVPP architecture"),
    ("a89d9ad254a19ac9098b326e78e2ecd8b8ed092b", "refactor: distinguish command and absolute PCC coordinates"),
    ("8ce89e4de76a14ecbe8de29611f112d5695854da", "docs: preregister absolute-PCC probe redesign"),
]


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def csv_text(fieldnames: list[str], rows: list[dict[str, object]]) -> str:
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=fieldnames, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue()


def git(*args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=ROOT, check=True, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    return result.stdout.strip()


def lower_quantile(values: list[float], probability: float) -> float:
    ordered = sorted(values)
    return ordered[math.floor((len(ordered) - 1) * probability)]


def evidence() -> dict[str, object]:
    # The audit may be regenerated after an additive audit commit, but the
    # original five-commit provenance chain must remain an ancestor.
    subprocess.run(
        ["git", "merge-base", "--is-ancestor", AUDIT_BASE_HEAD, "HEAD"],
        cwd=ROOT, check=True,
    )

    s0_path = ROOT / "results" / "s0_full_period_baseline" / "s0_interval_metrics.csv"
    s0_matches = []
    with s0_path.open(newline="", encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle):
            if row["timestamp"] == AUDITED_TIMESTAMP:
                s0_matches.append(row)
    s0 = next(row for row in s0_matches if float(row["root_voltage_pu"]) == 1.0)
    assert s0["numerical_validation_passed"] == "true"
    assert s0["operational_voltage_feasible"] == "true"

    scan_rows = read_csv(RESULTS / "export_side_axis_scan_points.csv")
    bounds = read_csv(RESULTS / "export_side_axis_capacity_bounds.csv")
    audited_scan = [row for row in scan_rows if row["timestamp"] == AUDITED_TIMESTAMP]
    p13_scan = sorted(
        (row for row in audited_scan if row["axis"] == "P13_VPP"),
        key=lambda row: float(row["axis_injection_kW"]),
    )
    p30_scan = sorted(
        (row for row in audited_scan if row["axis"] == "P30_VPP"),
        key=lambda row: float(row["axis_injection_kW"]),
    )
    p13_bound = next(row for row in bounds if row["timestamp"] == AUDITED_TIMESTAMP and row["axis"] == "P13_VPP")
    p30_bound = next(row for row in bounds if row["timestamp"] == AUDITED_TIMESTAMP and row["axis"] == "P30_VPP")

    eval_times = sorted(float(row["total_evaluation_ms"]) for row in scan_rows)
    groups: dict[tuple[str, str], int] = {}
    refinement_counts: dict[tuple[str, str], int] = {}
    for row in scan_rows:
        key = (row["timestamp"], row["axis"])
        groups[key] = groups.get(key, 0) + 1
        if row["search_phase"] == "refinement":
            refinement_counts[key] = refinement_counts.get(key, 0) + 1
    timing = read_csv(RESULTS / "export_side_axis_timing.csv")[0]

    profile = read_csv(ROOT / "data_processed" / "ausgrid" / "ausgrid_halfhour_normalized.csv")
    pilot = [row for row in profile if row["date"] in {"2012-10-15", "2012-10-16"}]
    loads = [float(row["load_multiplier"]) for row in profile]
    pvs = [float(row["pv_profile"]) for row in profile]
    pilot_loads = [float(row["load_multiplier"]) for row in pilot]
    pilot_pvs = [float(row["pv_profile"]) for row in pilot]
    load_p90 = lower_quantile(loads, 0.90)
    pv_p90 = lower_quantile(pvs, 0.90)
    pv_p10 = lower_quantile(pvs, 0.10)
    ranking = read_csv(ROOT / "data_processed" / "ausgrid" / "ausgrid_daily_stress_ranking.csv")
    ranks = {row["date"]: row for row in ranking}

    return {
        "s0": s0,
        "scan_rows": scan_rows,
        "p13_scan": p13_scan,
        "p30_scan": p30_scan,
        "p13_bound": p13_bound,
        "p30_bound": p30_bound,
        "eval_count": len(scan_rows),
        "eval_median_ms": eval_times[len(eval_times) // 2],
        "eval_mean_ms": sum(eval_times) / len(eval_times),
        "eval_max_ms": max(eval_times),
        "wall_seconds": float(timing["wall_seconds"]),
        "wall_ms_per_eval": 1000.0 * float(timing["wall_seconds"]) / len(scan_rows),
        "bound_group_count": len(groups),
        "mean_evals_per_bound": sum(groups.values()) / len(groups),
        "mean_refinements": sum(refinement_counts.values()) / len(refinement_counts),
        "nonconverged": sum(row["power_flow_status"] != "CONVERGED" for row in scan_rows),
        "replay_failures": sum(row["replay_status"] != "PASSED" for row in scan_rows),
        "pilot": pilot,
        "pilot_load_min": min(pilot_loads),
        "pilot_load_median": lower_quantile(pilot_loads, 0.50),
        "pilot_load_max": max(pilot_loads),
        "pilot_load_max_percentile": 100.0 * sum(x <= max(pilot_loads) for x in loads) / len(loads),
        "full_load_p90": load_p90,
        "pilot_pv_min": min(pilot_pvs),
        "pilot_pv_median": lower_quantile(pilot_pvs, 0.50),
        "pilot_pv_max": max(pilot_pvs),
        "pilot_pv_max_percentile": 100.0 * sum(x <= max(pilot_pvs) for x in pvs) / len(pvs),
        "full_pv_p90": pv_p90,
        "pilot_night_count": sum(x <= 1e-4 for x in pilot_pvs),
        "pilot_high_load_count": sum(x >= load_p90 for x in pilot_loads),
        "pilot_high_pv_count": sum(x >= pv_p90 for x in pilot_pvs),
        "pilot_import_stress_count": sum(
            float(row["load_multiplier"]) >= load_p90 and float(row["pv_profile"]) <= pv_p10
            for row in pilot
        ),
        "rank_2012_10_15": int(ranks["2012-10-15"]["rank"]),
        "rank_2012_10_16": int(ranks["2012-10-16"]["rank"]),
    }


def build_artifacts(ev: dict[str, object]) -> dict[str, str]:
    s0 = ev["s0"]
    p13_bound = ev["p13_bound"]
    p30_bound = ev["p30_bound"]
    p13_safe_abs = REFERENCE_PV_KW + float(p13_bound["safe_lower_kW"])
    p13_violating_abs = REFERENCE_PV_KW + float(p13_bound["violating_upper_kW"])
    p13_max_evaluated_abs = REFERENCE_PV_KW + max(float(row["axis_injection_kW"]) for row in ev["p13_scan"])
    p30_max_translated = max(float(row["axis_injection_kW"]) for row in ev["p30_scan"])
    origin_vmin = float(s0["minimum_voltage_pu"])
    origin_margin_090 = origin_vmin - 0.90
    origin_margin_095 = origin_vmin - 0.95
    nominal_evaluations = 12_192
    capped_evaluations = 14_112
    nominal_serial_seconds = nominal_evaluations * float(ev["wall_ms_per_eval"]) / 1000.0

    method_fields = [
        "method", "implementation_reuse", "required_assumption", "import_export_coverage",
        "geometry_quality", "fixed_ac_evaluations_per_boundary_estimate", "software_cost",
        "coupled_polytope_implication", "safe_box_implication", "suitability", "decision",
    ]
    method_rows = [
        {
            "method": "ABSOLUTE_ORIGIN_RADIAL",
            "implementation_reuse": "high; reuse fixed-injection evaluator, doubling, warm starts, replay, and bisection",
            "required_assumption": "origin feasible plus one connected feasible interval and one feasible-to-infeasible transition on every directed ray; star-shapedness is not proven",
            "import_export_coverage": "possible with a full 0-360 degree grid, but origin is geometrically off-center and creates strong quadrant anisotropy",
            "geometry_quality": "good only for an origin-star-shaped component; can miss disconnected pockets, re-entry, or narrow boundary structure",
            "fixed_ac_evaluations_per_boundary_estimate": "about 20 from Phase-B mean 19.224",
            "software_cost": "low; roughly 100-200 LOC adaptation",
            "coupled_polytope_implication": "ordered points are easy to connect, but chords are not certified feasible without convexity or edge validation",
            "safe_box_implication": "poorly balanced scales; requires separate corner validation",
            "suitability": "NOT_RECOMMENDED_AS_PRIMARY",
            "decision": "reject as production anchor despite proven origin feasibility",
        },
        {
            "method": "CENTERED_RADIAL",
            "implementation_reuse": "high; same evaluator and one-dimensional bracket/refinement on translated rays",
            "required_assumption": "verified interior center and exactly one outward transition per directed ray; violations trigger a method-revision gate",
            "import_export_coverage": "full 0-360 degree directed grid in per-axis normalized coordinates; no symmetry assumption",
            "geometry_quality": "reduces anisotropy and gives balanced access to all four quadrants; still empirical if non-star-shaped about the center",
            "fixed_ac_evaluations_per_boundary_estimate": "about 20 plus a one-time signed-axis prepass and center check",
            "software_cost": "low-to-moderate; roughly 180-300 LOC adaptation and checkpointing",
            "coupled_polytope_implication": "natural angular ordering; sampled hull/support values are diagnostics only unless every DOE construction is independently validated",
            "safe_box_implication": "best candidate; derive and shrink a center-aligned box, then AC-check all corners and adaptive edge points",
            "suitability": "RECOMMENDED_CONDITIONAL_ON_TARGETED_AXIS_EVIDENCE",
            "decision": "selected production architecture",
        },
        {
            "method": "SUPPORT_FUNCTION_OPF",
            "implementation_reuse": "partial; nonlinear branch-flow equations and Ipopt scaffolding exist, but current model has four nonnegative PV-capacity variables shared over 48 intervals",
            "required_assumption": "local NLP solutions from multistart are not global support certificates; signed two-interface variables and fixed Q policy require a new model",
            "import_export_coverage": "excellent in principle if signed bounds and global support solutions exist",
            "geometry_quality": "excellent for a convex hull; can hide nonconvexity and disconnected components",
            "fixed_ac_evaluations_per_boundary_estimate": "5-13 NLP starts plus replay per support direction; not comparable to one PF call",
            "software_cost": "high; estimated 300-600 LOC plus 2-5 engineering days and new validation",
            "coupled_polytope_implication": "direct halfspaces, but only locally supported without a global certificate",
            "safe_box_implication": "good only after independent fixed-injection validation",
            "suitability": "NOT_READY_REQUIRES_NEW_OPF_ARCHITECTURE",
            "decision": "do not select",
        },
        {
            "method": "SUPPORT_LINE_SEARCH",
            "implementation_reuse": "medium; fixed evaluator reusable, but every parallel line needs a tangential search",
            "required_assumption": "finite domain and a global-enough one-dimensional tangential search on every support line",
            "import_export_coverage": "possible in all quadrants",
            "geometry_quality": "support-oriented but can miss feasible islands along a line",
            "fixed_ac_evaluations_per_boundary_estimate": "120-300 per support direction (10-15 line bisections times 12-20 tangential samples), about 6-15x radial",
            "software_cost": "moderate-to-high; estimated 250-450 LOC plus search validation",
            "coupled_polytope_implication": "direct approximate halfspaces",
            "safe_box_implication": "requires the same independent validation as other sampled representations",
            "suitability": "NOT_COST_EFFECTIVE_WITH_CURRENT_EVALUATOR",
            "decision": "do not select",
        },
        {
            "method": "SAMPLED_SUPPORT_POSTPROCESSING",
            "implementation_reuse": "high; compute max(d dot P) over already sampled boundary points with no new AC calls",
            "required_assumption": "none for describing the sample convex hull; not equivalent to the true AC support function",
            "import_export_coverage": "inherits sampled coverage",
            "geometry_quality": "useful representation diagnostic, but convexifies and can include infeasible points",
            "fixed_ac_evaluations_per_boundary_estimate": "0 incremental",
            "software_cost": "low; under 100 LOC",
            "coupled_polytope_implication": "must not be asserted as E_DOE subset A_t_AC without independent validation",
            "safe_box_implication": "screening only",
            "suitability": "POSTPROCESSING_DIAGNOSTIC_ONLY",
            "decision": "retain as non-authoritative postprocessing",
        },
    ]

    temporal_fields = [
        "scope", "timestamps", "selection", "directions", "estimated_ac_evaluations",
        "estimated_serial_runtime", "coverage", "paper_use", "decision",
    ]
    temporal_rows = [
        {
            "scope": "T1_SINGLE_TIMESTAMP",
            "timestamps": 1,
            "selection": AUDITED_TIMESTAMP,
            "directions": "24 base plus expected 12 adaptive; cap 48; four signed-axis prepass searches",
            "estimated_ac_evaluations": 801,
            "estimated_serial_runtime": "about 3.3 s raw evaluator time; budget under 1 min including startup/checkpointing",
            "coverage": "method proof and detailed export-stress geometry only",
            "paper_use": "method demonstration; insufficient for a time-dependent DOE claim",
            "decision": "retain as mandatory dense validation case, not sole scope",
        },
        {
            "scope": "T2_EXISTING_96_DENSE",
            "timestamps": 96,
            "selection": "two literal consecutive dates 2012-10-15 and 2012-10-16",
            "directions": "24 base plus expected 12 adaptive per timestamp; cap 48; signed-axis prepass",
            "estimated_ac_evaluations": 76_896,
            "estimated_serial_runtime": "about 5.3 min raw evaluator time; under 30 min with overhead",
            "coverage": "excellent within two spring days but no seasonal or top-decile-load coverage",
            "paper_use": "export-side pilot only; density does not repair temporal bias",
            "decision": "reject as final temporal design",
        },
        {
            "scope": "T3_HIERARCHICAL_BALANCED_CRITICAL",
            "timestamps": 32,
            "selection": "four seasons x two stress modes (export ratio and night import load) x four non-adjacent ranks; first in each stratum dense",
            "directions": "8 dense timestamps: 24 base plus expected 12 adaptive (cap 48); 24 sparse timestamps: 8 fixed cardinal/diagonal directions; four signed-axis prepass searches at all timestamps",
            "estimated_ac_evaluations": nominal_evaluations,
            "estimated_serial_runtime": f"{nominal_serial_seconds:.1f} s raw observed-rate estimate; budget 2-5 min serial or process-parallel",
            "coverage": "balanced seasonal export/import stress with detailed geometry at eight cases",
            "paper_use": "boundary characterization; separate 52,608-interval AC replay validates final schedules",
            "decision": "SELECTED",
        },
    ]

    reuse_fields = ["existing_result", "classification", "permitted_use", "prohibited_use"]
    reuse_rows = [
        {"existing_result": "Phase-B P13 command-axis bound", "classification": "REUSABLE_AFTER_COORDINATE_TRANSLATION", "permitted_use": f"true physical-axis positive safe point ({p13_safe_abs:.13f},0) and runtime/bracketing calibration", "prohibited_use": "does not cover 0<P13_abs<reference PV or import"},
        {"existing_result": "Phase-B P30 command-axis bound", "classification": "REUSABLE_AFTER_COORDINATE_TRANSLATION", "permitted_use": f"point ({REFERENCE_PV_KW:.13f},{float(p30_bound['safe_lower_kW']):.11f}) and evaluator calibration", "prohibited_use": "must not be called a true P13_abs=0 intercept"},
        {"existing_result": "command-space linear quadrilateral", "classification": "REUSABLE_AFTER_COORDINATE_TRANSLATION", "permitted_use": "translated linear diagnostic and candidate refinement cues", "prohibited_use": "not a certified AC DOE"},
        {"existing_result": "linear translated corner", "classification": "REUSABLE_AFTER_COORDINATE_TRANSLATION", "permitted_use": "diagnostic active-set-change cue at (934.6080433530186,1610.2756675516089)", "prohibited_use": "not a verified AC boundary point"},
        {"existing_result": "theta_star_command", "classification": "COMMAND_SPACE_DIAGNOSTIC_ONLY", "permitted_use": "historical command-coordinate comparison", "prohibited_use": "must not center or seed absolute-PCC direction grids"},
        {"existing_result": "Lambda_lin_command", "classification": "COMMAND_SPACE_DIAGNOSTIC_ONLY", "permitted_use": "historical command-space analytical comparison", "prohibited_use": "must not normalize absolute-PCC geometry"},
        {"existing_result": "LinDistFlow coefficient matrix", "classification": "DIRECTLY_REUSABLE", "permitted_use": "local sensitivity and active-set diagnostic at the audited network state", "prohibited_use": "does not prove AC convexity or boundary"},
        {"existing_result": "linear active set {13,30}", "classification": "DIRECTLY_REUSABLE", "permitted_use": "adaptive-refinement diagnostic", "prohibited_use": "does not fix AC binding buses in other quadrants/timestamps"},
        {"existing_result": "operating-point provenance", "classification": "DIRECTLY_REUSABLE", "permitted_use": "timestamp, load, PV, coordinate, and ownership provenance", "prohibited_use": "none within its stated scope"},
        {"existing_result": "S0 full-period baseline", "classification": "DIRECTLY_REUSABLE", "permitted_use": f"zero-TVPP origin evidence; audited Vmin={origin_vmin:.14f} p.u. at bus {s0['minimum_voltage_bus']}", "prohibited_use": "global minimum 0.913090479358158 must not be substituted for the audited timestamp"},
        {"existing_result": "existing 96-timestamp list", "classification": "DIRECTLY_REUSABLE", "permitted_use": "export-pilot regression and runtime comparison only", "prohibited_use": "not the final temporally balanced DOE set"},
        {"existing_result": "PV/EV/BESS capability or optimized H", "classification": "NOT_RELEVANT_TO_FINAL_DOE", "permitted_use": "F_TVPP(H) only", "prohibited_use": "must not bound A_t_AC"},
    ]

    p13_evaluated_abs = ";".join(
        f"{REFERENCE_PV_KW + float(row['axis_injection_kW']):.13f}"
        for row in ev["p13_scan"]
    )
    axis_fields = [
        "axis_half", "absolute_path", "command_path", "existing_coverage", "evaluated_absolute_points_kw", "known_safe_extent",
        "known_violating_or_terminal_evidence", "untested_portion", "minimum_new_evidence", "classification",
    ]
    axis_rows = [
        {
            "axis_half": "P13_abs_positive",
            "absolute_path": "(lambda,0), lambda>=0",
            "command_path": f"(lambda-{REFERENCE_PV_KW},0)",
            "existing_coverage": f"S0 at lambda=0; Phase-B fixed evaluations on physical P30_abs=0 from lambda={REFERENCE_PV_KW} through {p13_max_evaluated_abs:.13f}",
            "evaluated_absolute_points_kw": "0 (S0);" + p13_evaluated_abs,
            "known_safe_extent": f"origin safe; ordered Phase-B evidence supports [{REFERENCE_PV_KW:.13f},{p13_safe_abs:.13f}]",
            "known_violating_or_terminal_evidence": f"first refined violating point {p13_violating_abs:.13f}; maximum evaluated {p13_max_evaluated_abs:.13f} violates upper voltage",
            "untested_portion": f"continuous connection 0<lambda<{REFERENCE_PV_KW:.13f} except endpoints; no exhaustive off-grid guarantee",
            "minimum_new_evidence": "deterministic coarse connection scan from origin to translated baseline; reuse upper refined bracket if ordered single-transition checks pass",
            "classification": "REQUIRES_TARGETED_NEW_AC_EVIDENCE",
        },
        {
            "axis_half": "P13_abs_negative",
            "absolute_path": "(-lambda,0), lambda>=0",
            "command_path": f"(-lambda-{REFERENCE_PV_KW},0)",
            "existing_coverage": "origin endpoint only from S0",
            "evaluated_absolute_points_kw": "0 (S0)",
            "known_safe_extent": "lambda=0 only",
            "known_violating_or_terminal_evidence": "none",
            "untested_portion": "all lambda>0",
            "minimum_new_evidence": "guarded coarse import scan, transition inventory, and bracket refinement; nonconvergence remains unresolved",
            "classification": "REQUIRES_TARGETED_NEW_AC_EVIDENCE",
        },
        {
            "axis_half": "P30_abs_positive",
            "absolute_path": "(0,lambda), lambda>=0",
            "command_path": f"(-{REFERENCE_PV_KW},lambda)",
            "existing_coverage": "origin endpoint only; translated P30 command-axis points lie at P13_abs=reference PV and are not intercepts",
            "evaluated_absolute_points_kw": "0 (S0)",
            "known_safe_extent": "lambda=0 only",
            "known_violating_or_terminal_evidence": f"none on true axis; translated line reaches {p30_max_translated:.6f} kW",
            "untested_portion": "all lambda>0 on true P13_abs=0 axis",
            "minimum_new_evidence": "guarded coarse export scan, transition inventory, and bracket refinement",
            "classification": "REQUIRES_TARGETED_NEW_AC_EVIDENCE",
        },
        {
            "axis_half": "P30_abs_negative",
            "absolute_path": "(0,-lambda), lambda>=0",
            "command_path": f"(-{REFERENCE_PV_KW},-lambda)",
            "existing_coverage": "origin endpoint only from S0",
            "evaluated_absolute_points_kw": "0 (S0)",
            "known_safe_extent": "lambda=0 only",
            "known_violating_or_terminal_evidence": "none",
            "untested_portion": "all lambda>0",
            "minimum_new_evidence": "guarded coarse import scan, transition inventory, and bracket refinement; nonconvergence remains unresolved",
            "classification": "REQUIRES_TARGETED_NEW_AC_EVIDENCE",
        },
    ]

    timestamp_fields = ["audit_item", "source", "evidence", "classification", "recommendation"]
    timestamp_rows = [
        {"audit_item": "selection_logic", "source": "src/benchmark/dso_vpp_ac_map_stage0.jl:8,46-67", "evidence": "literal dates 2012-10-15 and 2012-10-16; 48 contiguous half-hours per day; no ranking or clustering at runtime", "classification": "EXPORT_PILOT_WINDOW_NOT_BALANCED_SELECTION", "recommendation": "USE_ONLY_FOR_EXPORT_PILOT"},
        {"audit_item": "provenance_of_first_day", "source": "data_processed/ausgrid/ausgrid_daily_stress_ranking.csv", "evidence": f"2012-10-15 is export-stress rank {ev['rank_2012_10_15']} using max pv_profile/load_multiplier during active PV", "classification": "INTENTIONALLY_EXPORT_STRESSING", "recommendation": "retain audited timestamp as one dense case"},
        {"audit_item": "provenance_of_second_day", "source": "same ranking plus literal source selection", "evidence": f"2012-10-16 is rank {ev['rank_2012_10_16']} and is included as the adjacent calendar day", "classification": "ADJACENCY_NOT_INDEPENDENT_CRITICAL_SELECTION", "recommendation": "retain only for regression continuity"},
        {"audit_item": "load_coverage", "source": "data_processed/ausgrid/ausgrid_halfhour_normalized.csv", "evidence": f"pilot load range {ev['pilot_load_min']:.12f}-{ev['pilot_load_max']:.12f}; maximum is full-series percentile {ev['pilot_load_max_percentile']:.3f}; top-decile threshold {ev['full_load_p90']:.12f}; top-decile pilot count {ev['pilot_high_load_count']}", "classification": "HIGH_LOAD_NOT_REPRESENTED", "recommendation": "add balanced night high-load/import strata"},
        {"audit_item": "pv_coverage", "source": "same canonical profile", "evidence": f"pilot PV range {ev['pilot_pv_min']:.12f}-{ev['pilot_pv_max']:.12f}; maximum is percentile {ev['pilot_pv_max_percentile']:.3f}; top-decile PV intervals {ev['pilot_high_pv_count']}", "classification": "HIGH_PV_WELL_REPRESENTED", "recommendation": "reuse audited export-stress case"},
        {"audit_item": "night_and_import_stress", "source": "same canonical profile", "evidence": f"{ev['pilot_night_count']} intervals have pv<=1e-4, but {ev['pilot_import_stress_count']} combine top-decile load with bottom-decile PV", "classification": "NIGHT_PRESENT_IMPORT_STRESS_ABSENT", "recommendation": "select seasonal high-load low-PV timestamps"},
        {"audit_item": "seasonal_coverage", "source": "literal dates", "evidence": "two consecutive Southern Hemisphere spring days only", "classification": "SEASONAL_COVERAGE_ABSENT", "recommendation": "four-season deterministic strata"},
        {"audit_item": "overall_suitability", "source": "combined audit", "evidence": "dense intraday export-stress coverage cannot substitute for seasonal and import-stress coverage", "classification": "USE_ONLY_FOR_EXPORT_PILOT", "recommendation": "HIERARCHICAL_CRITICAL_TIMESTAMP_PROBE with a new balanced 32-timestamp set"},
    ]

    cost_fields = [
        "design", "timestamp_count", "axis_prepass_searches", "directed_boundary_searches",
        "average_evaluations_per_search", "estimated_ac_evaluations", "preregistered_cap",
        "observed_rate_basis", "estimated_wall_runtime", "cpu_ram", "artifact_size", "verdict",
    ]
    cost_rows = [
        {"design": "single_timestamp_centered_radial", "timestamp_count": 1, "axis_prepass_searches": 4, "directed_boundary_searches": 36, "average_evaluations_per_search": 20, "estimated_ac_evaluations": 801, "preregistered_cap": 1041, "observed_rate_basis": f"{ev['wall_ms_per_eval']:.4f} ms/eval orchestration wall; {ev['mean_evals_per_bound']:.3f} eval/bound", "estimated_wall_runtime": "3.3 s raw; under 1 min end-to-end budget", "cpu_ram": "1 core serial; under 1 GB observed process RSS", "artifact_size": "under 2 MB", "verdict": "SAFE_METHOD_DEMONSTRATION_ONLY"},
        {"design": "dense_96_centered_radial", "timestamp_count": 96, "axis_prepass_searches": 384, "directed_boundary_searches": 3456, "average_evaluations_per_search": 20, "estimated_ac_evaluations": 76896, "preregistered_cap": 99936, "observed_rate_basis": f"{ev['wall_ms_per_eval']:.4f} ms/eval", "estimated_wall_runtime": "5.3 min raw; budget under 30 min", "cpu_ram": "8 workers recommended; under 8 GB expected", "artifact_size": "30-45 MB", "verdict": "COMPUTATIONALLY_SAFE_BUT_TEMPORALLY_BIASED"},
        {"design": "recommended_hierarchical_centered_radial", "timestamp_count": 32, "axis_prepass_searches": 128, "directed_boundary_searches": 480, "average_evaluations_per_search": 20, "estimated_ac_evaluations": nominal_evaluations, "preregistered_cap": capped_evaluations, "observed_rate_basis": f"{ev['wall_ms_per_eval']:.4f} ms/eval; row median {ev['eval_median_ms']:.4f} ms; row mean {ev['eval_mean_ms']:.4f} ms", "estimated_wall_runtime": f"{nominal_serial_seconds:.1f} s raw; 2-5 min budget including process startup, checks, and checkpoints", "cpu_ram": "8 single-thread workers on 12-CPU/32-GB VM; expected under 8 GB; cluster not materially necessary", "artifact_size": "about 5 MB raw rows; budget under 15 MB with summaries/checkpoints", "verdict": "SAFE_ON_12_CPU_32_GB_VM"},
        {"design": "support_line_hierarchical", "timestamp_count": 32, "axis_prepass_searches": 128, "directed_boundary_searches": 480, "average_evaluations_per_search": "120-300", "estimated_ac_evaluations": "60192-146592", "preregistered_cap": "not established", "observed_rate_basis": f"{ev['wall_ms_per_eval']:.4f} ms/eval", "estimated_wall_runtime": "4.2-10.2 min raw plus tangential-search overhead", "cpu_ram": "parallelizable but search branches are sequential", "artifact_size": "25-60 MB", "verdict": "FEASIBLE_BUT_NOT_COST_EFFECTIVE_AND_NO_GLOBAL_LINE_GUARANTEE"},
        {"design": "support_function_opf_hierarchical", "timestamp_count": 32, "axis_prepass_searches": 0, "directed_boundary_searches": 480, "average_evaluations_per_search": "5-13 local NLP starts plus one fixed-injection replay", "estimated_ac_evaluations": "2400-6240 NLP solves plus 480 replays", "preregistered_cap": "requires a new benchmark", "observed_rate_basis": "existing 48-interval/four-capacity NLP averaged 0.802 s/start; single-timestamp cost is unmeasured", "estimated_wall_runtime": "rough 2.4-100 min solve range; 2-5 engineering days dominate", "cpu_ram": "cluster may help multistarts; local-optimum/global-support issue remains", "artifact_size": "moderate", "verdict": "SUPPORT_FUNCTION_REQUIRES_NEW_OPF_ARCHITECTURE"},
    ]

    design_fields = [
        "coordinate_system", "reactive_policy", "boundary_method", "reference_point",
        "timestamp_strategy", "dense_timestamp_count", "sparse_timestamp_count",
        "directions_per_dense_timestamp", "directions_per_sparse_timestamp",
        "adaptive_refinement_rule", "axis_scans_required", "estimated_AC_evaluations",
        "estimated_runtime", "parallelization_plan", "checkpoint_plan", "stopping_tolerances",
        "failure_handling",
    ]
    design_rows = [{
        "coordinate_system": "ABSOLUTE_PHYSICAL_INTERFACE_POWER_P_PCC_ABS_KW",
        "reactive_policy": "UNITY_POWER_FACTOR_INTERFACE_POLICY; Q_PCC=0",
        "boundary_method": "CENTERED_RADIAL",
        "reference_point": "per timestamp: midpoint c0 of confirmed signed true-axis intervals; AC-check c0; if rejected/unresolved use first AC-accepted c_j=2^(-j)c0 toward the AC-accepted origin, j=1..20; scales are signed-axis half-widths; network evidence only",
        "timestamp_strategy": "HIERARCHICAL_CRITICAL_TIMESTAMP_PROBE; four seasons x export/import stress x four non-adjacent ranks; first rank in each stratum dense",
        "dense_timestamp_count": 8,
        "sparse_timestamp_count": 24,
        "directions_per_dense_timestamp": "24 base directed rays at 15-degree spacing in signed-axis-normalized coordinates; expected 12 adaptive; hard cap 48",
        "directions_per_sparse_timestamp": "8 directed cardinal/diagonal rays at 45-degree spacing in signed-axis-normalized coordinates",
        "adaptive_refinement_rule": "insert angular midpoint when adjacent normalized radii differ by >10%, binding sets differ, or a newly sampled midpoint deviates >2% from secant interpolation; recurse to 3.75-degree minimum gap or 48-ray cap; no symmetry",
        "axis_scans_required": "four signed true absolute half-axis searches at every selected timestamp; audited P13 positive upper bracket may be reused only after 0-to-reference connectivity and one-transition checks",
        "estimated_AC_evaluations": "12192 nominal (20/search; 12 adaptive dense rays); 14112 preregistered cap (24 adaptive dense rays)",
        "estimated_runtime": f"{nominal_serial_seconds:.1f} s raw observed-rate estimate; budget 2-5 min including startup/checkpoints on the 12-CPU VM",
        "parallelization_plan": "8 single-thread worker processes; parallel across timestamps and rays; serial within each bracket; deterministic merge order; leave 4 CPUs and >20 GB RAM headroom",
        "checkpoint_plan": "atomic checkpoint after every completed direction and timestamp; separate raw points, bounds, transition inventory, unresolved queue, manifest, and resume index",
        "stopping_tolerances": "capacity bracket <=1.0 kW and safe/violating voltage distances <=1e-5 p.u.; replay voltage match <=2e-5 p.u.; residual <=1e-5; max 60 refinements",
        "failure_handling": "nonconvergence or replay failure is UNRESOLVED, never infeasible; deterministic flat/nearest-neighbor restarts; retain all coarse transitions; multiple feasible intervals or reverse transitions stop that timestamp and trigger preregistered method revision, with no outermost-boundary selection or interpolation across unresolved rays",
    }]

    git_lines = [
        "# DOE boundary-design audit: Git state",
        "",
        "## Initial state captured before any audit file change",
        "",
        "```text",
        "git status --short",
        "<empty>",
        "",
        "git status -sb",
        "## codex/dso-vpp-ac-map-pilot...origin/codex/dso-vpp-ac-map-pilot [ahead 5]",
        "",
        "git branch --show-current",
        "codex/dso-vpp-ac-map-pilot",
        "",
        "git rev-parse HEAD",
        AUDIT_BASE_HEAD,
        "",
        "git log --oneline --decorate -10",
        "8ce89e4 (HEAD -> codex/dso-vpp-ac-map-pilot) docs: preregister absolute-PCC probe redesign",
        "a89d9ad refactor: distinguish command and absolute PCC coordinates",
        "461892d docs: clarify multi-interface TVPP architecture",
        "5fc6ac1 docs: amend probe metrics after provenance audit",
        "4c47823 test: verify Phase-B operating-point provenance",
        "d8e1bb0 (origin/codex/dso-vpp-ac-map-pilot) docs: preregister analytically identified corner directions",
        "beb7df9 feat: audit AC-anchored linear corner structure",
        "79d92dc docs: preregister fixed radial normalization",
        "24138a3 feat: make export-side AC axis scan reproducible",
        "ae24e08 Repair Stage 0 reference PV propagation",
        "",
        "git remote -v",
        "origin https://github.com/SeyedMostafArmaghan/CiroPVHC.jl.git (fetch)",
        "origin https://github.com/SeyedMostafArmaghan/CiroPVHC.jl.git (push)",
        "",
        "git branch -vv",
        "* codex/dso-vpp-ac-map-pilot 8ce89e4 [origin/codex/dso-vpp-ac-map-pilot: ahead 5] docs: preregister absolute-PCC probe redesign",
        "  main                       282663d [origin/main] Lock S1 and S2 baseline before protection proxy",
        "",
        "git ls-remote --heads origin codex/dso-vpp-ac-map-pilot",
        f"{REMOTE_TIP} refs/heads/codex/dso-vpp-ac-map-pilot",
        "```",
        "",
        "The remote query was executed successfully at audit start. All five requested commits are local objects, ancestors of the initial HEAD, and absent from the remote branch tip:",
        "",
        "| commit | local status | remote status | subject |",
        "|---|---|---|---|",
    ]
    for commit, subject in LOCAL_COMMITS:
        git_lines.append(f"| `{commit}` | present; ancestor of initial HEAD | absent; remote tip predates it | {subject} |")
    git_lines.extend([
        "",
        "**`LOCAL_SCIENTIFIC_PROVENANCE_NOT_YET_BACKED_UP_TO_REMOTE`**",
        "",
        "## Audit working-tree state after deterministic generation",
        "",
        "```text",
        "git diff --name-only",
        "<empty: no tracked scientific artifact changed>",
        "",
        "git status --short",
        "?? results/dso_vpp_ac_map_pilot/doe_boundary_design_audit/",
        "```",
        "",
        "No push, rebase, amend, merge, or history rewrite was performed by this audit.",
        "",
    ])

    prereg = f"""# Pre-execution Amendment 4 - DOE boundary-extraction design

This amendment is additive and does not alter the numerical content of S0, S1, Phase B, the analytical LinDistFlow audit, operating-point provenance, architecture, or coordinate-resolution artifacts.

## Locked model semantics

- Coordinates: absolute physical interface active power `P_PCC_abs`, export positive and import negative.
- Interface reactive policy: `UNITY_POWER_FACTOR_INTERFACE_POLICY`, hence `Q_PCC=0`.
- Passive case33bw loads are DSO background and are excluded from `P_PCC_abs`.
- The 850 kW reference PV is TVPP-owned; at {AUDITED_TIMESTAMP}, its fixed contribution is `{REFERENCE_PV_KW} kW`.
- `A_t^AC` is network acceptance only. PV/EV/BESS capability and optimized `H` belong only to `F_TVPP(H)`. The coordination relation remains `P_PCC_abs in F_TVPP(H) intersection E_DOE`, with `E_DOE subset A_t^AC`.
- Non-unity-PF operation and reactive flexibility are outside the main model and are limitations/future sensitivity topics. No `kappa != 0` is introduced.

## Selected production architecture

`CENTERED_RADIAL` is selected, conditional on the targeted signed-axis prepass. For each timestamp, obtain true positive/negative half-axis intervals for P13 and P30 using only network acceptance. Let `c0` be the componentwise midpoint of those intervals. Evaluate `c0`. If it is not accepted, test `c_j=2^(-j)c0`, `j=1,...,20`, toward the accepted physical origin and select the first accepted point. Failure to obtain a non-origin interior center stops the timestamp for method revision; optimized resource capacity never enters center selection.

Directions are uniform in coordinates normalized by the two signed-axis half-widths, not by `theta_star_command` or `Lambda_lin_command`. Dense cases use 24 base directed rays at 15-degree spacing over the full 0-360 degrees. Sparse cases use eight cardinal/diagonal rays at 45-degree spacing. No quadrant symmetry is assumed.

Dense adaptive refinement inserts an angular midpoint when adjacent normalized radii differ by more than 10%, their binding-bus sets differ, or the evaluated midpoint differs by more than 2% from secant interpolation. Recursion stops at 3.75 degrees or 48 directed rays. The command-space `theta_star_command=76.03090274387165 deg` remains a diagnostic and is not a grid center or privileged absolute-PCC angle.

Each ray must show exactly one accepted interval from the verified center followed by one accepted-to-infeasible transition. Coarse samples are retained. Reverse transitions, multiple feasible intervals, or unresolved points stop that timestamp and trigger a preregistered method revision; the outermost point is never selected post hoc.

## Selected temporal architecture

`HIERARCHICAL_CRITICAL_TIMESTAMP_PROBE` is selected with 32 unique timestamps: eight dense and 24 sparse. Partition the full profile into DJF/MAM/JJA/SON and two network-background stress modes: export stress `pv_profile/max(load_multiplier,0.05)` and import stress `load_multiplier` subject to `pv_profile<=1e-4`. Within each of the eight season-mode strata, rank by score descending and timestamp ascending, enforce at least 24 hours between selected timestamps, and take four. The first is dense and the next three are sparse. Deduplicate across strata and fill from the next eligible rank under the same rule. `{AUDITED_TIMESTAMP}` must be the dense spring-export case if it remains the stratum leader.

The old 96 timestamps are `USE_ONLY_FOR_EXPORT_PILOT`; they are not substituted for this balanced set. Dense DOE reconstruction over all 52,608 intervals is not planned. The final optimized TVPP schedules will instead receive a separate full 52,608-interval AC replay.

## Search budget and stopping rules

- Four signed true-axis searches at every selected timestamp.
- Eight dense timestamps: 24 base plus expected 12 adaptive directions, hard cap 48.
- Twenty-four sparse timestamps: eight directions.
- Calibration: 20 fixed-injection AC evaluations per search (observed mean {ev['mean_evals_per_bound']:.3f}).
- Nominal budget: {nominal_evaluations} AC evaluations; hard adaptive budget: {capped_evaluations}.
- Boundary stopping: bracket width <=1.0 kW and both endpoint voltage distances <=1e-5 p.u.; replay voltage agreement <=2e-5 p.u.; residual <=1e-5; maximum 60 refinements.
- Nonconvergence or replay failure is `UNRESOLVED`, never physical infeasibility. Retry deterministically from flat and nearest accepted neighbor starts, then checkpoint an unresolved ray without interpolation.
- Eight single-thread worker processes on the 12-CPU/32-GB VM; serial search within a ray, parallel rays/timestamps, deterministic merge order.
- Atomic checkpoints after every direction and timestamp; retain raw evaluations, transition inventory, bounds, unresolved queue, resume index, and manifest.

At the observed orchestration rate ({ev['wall_ms_per_eval']:.4f} ms/evaluation), the nominal raw evaluator time is about {nominal_serial_seconds:.1f} seconds. The operational budget is 2-5 minutes including Julia/process startup, validation, checkpoints, and output. Expected RAM is below 8 GB with eight workers; the 31-core/126-GB cluster is not materially necessary for this fixed-evaluator design.

No production probe, support-function OPF, DOE construction, EV/BESS model, centralized optimization, or full-period optimization is authorized by this amendment.
"""

    report = f"""# DOE boundary-extraction design audit

Primary classification: **`CENTERED_RADIAL_RECOMMENDED_WITH_TARGETED_AXIS_EVIDENCE`**.

## Executive decision

The next production architecture should be `CENTERED_RADIAL` with a deterministic signed-axis midpoint center, per-timestamp AC verification/backtracking, transition auditing, normalized full-circle directions, and hierarchical balanced timestamps. The production probe is not yet ready to run: the true signed absolute axes remain incomplete and must be the first preregistered stage. Support-function OPF is not selected because the current fast evaluator is a fixed-injection power flow and the existing AC-OPF model is not a signed two-interface support solver.

The temporal strategy should be `HIERARCHICAL_CRITICAL_TIMESTAMP_PROBE`: eight dense and 24 sparse balanced critical timestamps, not a dense replay of the existing export-biased 96-window and not all 52,608 intervals.

## Scientific locks

- Final coordinates are `P_PCC_abs`; at the audited point `P13_abs={REFERENCE_PV_KW}+P13_command` and `P30_abs=P30_command`.
- `REFERENCE_PV_850_KW_IS_TVPP_OWNED` remains fixed.
- `UNITY_POWER_FACTOR_INTERFACE_POLICY` is final for the main paper: `Q_PCC=0`. Non-unity-PF interface operation and reactive flexibility are outside the main model and belong to limitations/future sensitivity analysis. No nonzero `kappa` is introduced and no Phase-B/analytical result is regenerated.
- `A_t^AC` depends only on network background, topology/limits, and the fixed interface policy. PV, EV, BESS, and optimized `H` belong to `F_TVPP(H)` and must not define the network boundary. The final relation is `P_PCC_abs in F_TVPP(H) intersection E_DOE`, with `E_DOE subset A_t^AC`.

## Absolute-origin correction

The previous unresolved classification is corrected additively to **`ABSOLUTE_ORIGIN_FEASIBLE_FROM_EXISTING_S0_EVIDENCE`**. At `P_PCC_abs=(0,0)`, command is `(-{REFERENCE_PV_KW},0)`, so the TVPP-owned reference PV is removed and the state is exactly the zero-DER/zero-TVPP S0 network with passive DSO loads retained.

The committed `results/s0_full_period_baseline/s0_interval_metrics.csv` explicitly contains `{AUDITED_TIMESTAMP}` at root voltage 1.00 p.u.: solver `{s0['operational_solver_status']}`, numerical validation `{s0['numerical_validation_passed']}`, operational voltage feasible `{s0['operational_voltage_feasible']}`, `Vmin={origin_vmin:.14f}` p.u. at bus {s0['minimum_voltage_bus']}, and `Vmax={float(s0['maximum_voltage_pu']):.1f}` p.u. This gives a {origin_margin_090:.14f} p.u. lower-voltage margin to the pilot 0.90 limit (and {origin_margin_095:.14f} p.u. to the S0 0.95 operational limit), plus 0.05 p.u. upper margin to 1.05.

The three-year global S0 minimum `0.913090479358158` p.u. is **not** used as the audited 13:00 voltage; it occurs at `2011-02-05 18:00:00`.

## Existing absolute-axis coverage

The Phase-B P13 command scan is already on the true physical segment `P30_abs=0`. At the audited timestamp it includes 17 fixed AC evaluations from command 0 through 928.75 kW, translating to `P13_abs={REFERENCE_PV_KW:.13f}` through `{p13_max_evaluated_abs:.13f}` kW. Ordered Phase-B evidence supports the safe interval from the translated baseline through `{p13_safe_abs:.13f}` kW; the refined violating endpoint is `{p13_violating_abs:.13f}` kW. The origin is separately feasible from S0, but the open connection `0<P13_abs<{REFERENCE_PV_KW:.13f}` has not been explicitly scanned.

The P30 command scan lies on `P13_abs={REFERENCE_PV_KW:.13f}`, not on the true P30 axis. Its safe point `({REFERENCE_PV_KW:.13f},{float(p30_bound['safe_lower_kW']):.11f})` is a translated command-axis point, not a `P13_abs=0` intercept.

Minimum targeted new evidence is therefore: (1) connect the positive P13 half-axis from origin to the translated baseline and reuse its upper bracket only if the ordered-transition audit passes; (2) scan/refine the negative P13 half-axis; (3) scan/refine the true positive P30 half-axis using command `(-{REFERENCE_PV_KW},P30_abs)`; and (4) scan/refine the true negative P30 half-axis. These are preregistered future evaluations and were not run here.

## Method assessment

### Absolute-origin radial

Implementation is cheapest because the current doubling/bisection evaluator can be generalized. Origin feasibility is now established, but origin-star-shapedness is not. The origin is also far from the center of the already observed export-side extent and provides poor angular resolution across import/export quadrants. A ray can have two or more feasible intervals, reverse transitions, a nonconvergent gap, or a narrow component; selecting the outermost feasible point would be scientifically invalid. Origin radial is therefore not the primary architecture.

### Centered radial

Centered radial retains the cheap fixed-injection evaluator while reducing anisotropy. The chosen center is network-only: midpoint of true signed axis intervals, followed by an exact fixed-injection acceptance check and deterministic dyadic backtracking toward the accepted origin. An approximate Chebyshev center is rejected because no certified halfspace description exists yet and adding an optimization layer would not improve the underlying AC information.

Center candidates were resolved as follows:

| candidate | assessment |
|---|---|
| absolute origin as a simple axis center | now proven feasible, but geometrically off-center and retained only as the deterministic backtracking endpoint |
| midpoint of confirmed positive/negative true-axis intervals | selected `c0`; deterministic, cheap, network-only, and balanced in both coordinates |
| approximate Chebyshev center | rejected for this stage; it needs a trustworthy halfspace/cell model that the repository does not yet have |
| midpoint with dyadic backtracking | selected feasibility safeguard; test `2^(-j)c0` toward the accepted origin without resource information |

A full directed 0-360 degree grid represents both intersections of any geometric line as two opposite rays. Each ray still requires a one-transition audit. Dense directions are uniform in signed-axis-normalized coordinates, not around `theta_star_command`. This is safer and cheaper than origin radial and far cheaper to implement than support optimization.

### Support functions

The repository contains JuMP/Ipopt nonlinear branch-flow code, but its current AC-OPF model uses four nonnegative PV-capacity variables shared over 48 intervals and maximizes total capacity. A true support solver needs two signed absolute-interface variables, one timestamp, fixed `Q_PCC=0`, finite network-derived bounds, objective `d'P`, multistart policy, replay, and direction-specific diagnostics. Estimated work is 300-600 LOC and 2-5 engineering days. Existing evidence shows 13/13 accepted local starts in a different 48-interval problem at mean 0.802 s/start, but that does not certify global support values or predict a single-timestamp solve.

Parallel support-line search with the fixed evaluator needs roughly 120-300 AC evaluations per direction versus about 20 for radial search, and its tangential search can still miss islands. Reconstructing support values from radial samples costs no new AC calls but returns only the sampled convex hull; it can contain infeasible points if `A_t^AC` is nonconvex. It is allowed only as diagnostic postprocessing, never as an unvalidated `E_DOE`.

## Information and geometry classifications

| property | classification | evidence |
|---|---|---|
| AC-region convexity | `NOT_TESTED` | the translated linear quadrilateral is convex, but it is not an AC proof |
| star-convexity about absolute origin | `NOT_PROVEN` | origin is feasible; no absolute mixed-quadrant rays exist |
| star-convexity about selected center | `NOT_TESTED` | center and signed axes do not yet exist |
| monotonicity on existing positive command axes | `SUPPORTED_BY_EXISTING_EVIDENCE` | all 192 Phase-B axis rows report monotonic checks true |
| monotonicity on absolute mixed-quadrant rays | `NOT_TESTED` | no such ray campaign exists |
| single feasible-to-infeasible transition on existing positive command axes | `SUPPORTED_BY_EXISTING_EVIDENCE` | 192 valid refined bounds, 0 nonconvergence, ordered status checks true |
| single transition on production rays | `NOT_TESTED` | explicit production gate |
| multiple feasible intervals | `NOT_TESTED` | existing algorithm searched only one positive-axis transition |
| solver nonconvergence regions in tested Phase-B domain | `CONTRADICTED` | {ev['nonconverged']} of {ev['eval_count']} evaluations nonconverged |
| absence of nonconvergence outside tested domain | `NOT_PROVEN` | import/mixed quadrants are untested |

Radial and support representations can encode similar sampled boundary information only if the relevant component is convex or approximately convex. No such AC conclusion is made. A more elegant halfspace representation does not create more information than the AC evaluations behind it.

## Timestamp-selection audit

`select_pilot_indices` selects two literal consecutive dates, not 96 independently selected critical timestamps. The first day is export-stress rank {ev['rank_2012_10_15']}; the adjacent day is rank {ev['rank_2012_10_16']}. The 96 intervals cover load multipliers `{ev['pilot_load_min']:.6f}-{ev['pilot_load_max']:.6f}`; the maximum is only the {ev['pilot_load_max_percentile']:.2f}th full-series percentile, with {ev['pilot_high_load_count']} top-decile-load intervals. PV reaches `{ev['pilot_pv_max']:.6f}` (the {ev['pilot_pv_max_percentile']:.2f}th percentile) and {ev['pilot_high_pv_count']} intervals are top-decile PV. Although {ev['pilot_night_count']} night intervals are present, there are {ev['pilot_import_stress_count']} high-load/low-PV import-stress intervals. Both days are spring and provide no seasonal coverage.

Classification: **`USE_ONLY_FOR_EXPORT_PILOT`**. Dense probing of all 96 would be computationally safe but would reproduce temporal bias at greater density.

## Recommended temporal and directional architecture

Select 32 balanced critical timestamps by four seasons and two deterministic stress modes; use eight dense cases and 24 sparse cases. Dense cases use 24 base full-circle directions plus deterministic adaptive refinement (12 expected, 24 cap). Sparse cases use eight cardinal/diagonal full-circle directions. All directions use signed-axis normalization and no symmetry. Detailed selection and refinement rules are in the preregistration amendment.

Direction-count audit:

| count | role and decision |
|---:|---|
| 8 | selected for sparse timestamps: four axes plus four diagonals provide all-quadrant screening |
| 12 | acceptable only as a 30-degree method smoke grid; too coarse for the dense paper geometry |
| 16 | a viable 22.5-degree intermediate grid, but it does not materially reduce cost relative to 24 at the observed evaluator rate |
| 24 | selected dense base grid: deterministic 15-degree full-circle coverage |
| 36 | nominal dense outcome after about 12 data-driven midpoint insertions; it is an expected adaptive count, not a hand-picked grid |
| 48 | preregistered dense cap; permits one complete 7.5-degree refinement layer and localized further refinement to 3.75 degrees |
| 72 | a uniform 5-degree grid would be computationally feasible but is not justified before curvature/active-set evidence; use only after a method amendment |

Quadrants receive equal base angular coverage. Additional density follows only the preregistered normalized-radius, active-set, and secant-error rules; no post-hoc angle selection and no symmetry reduction are allowed.

The nominal budget is `{nominal_evaluations}` fixed AC evaluations: 2,560 signed-axis-prepass evaluations, 32 center checks, and 9,600 centered-ray evaluations. The hard adaptive budget is `{capped_evaluations}`. At the observed Phase-B orchestration wall rate `{ev['wall_ms_per_eval']:.4f} ms/evaluation`, nominal raw evaluator time is `{nominal_serial_seconds:.1f} s`; allow 2-5 minutes end-to-end. Use eight one-thread workers, serial within each ray and parallel across rays/timestamps. Observed peak evaluator-process RSS is about 743 MiB, so expected eight-worker RAM is below 8 GB and safe on the 12-CPU/32-GB VM. The 31-core/126-GB cluster would shorten an already small compute kernel but is not materially needed. Raw output should be about 5 MB and remain below a 15 MB checkpoint/summary budget.

Checkpoint atomically after every direction and timestamp. Store raw evaluations separately from bounds, transition inventories, unresolved cases, manifests, and resume indices. Never interpolate across unresolved rays.

## Coupled DOE and safe-box use

Angular boundary points can be ordered into a polygonal diagnostic, and sampled support values can be computed afterward. Because AC convexity is unproven, neither chords nor the sampled convex hull are automatically certified subsets of `A_t^AC`. Any final coupled `E_DOE` and any safe box must be constructed inward and separately checked at all vertices plus deterministic adaptive edge/interior points for every applicable timestamp. A failure shrinks or splits the candidate; it is never overwritten by a convexity assumption.

## Reuse summary

Phase-B P13 evidence is useful after translation and targeted connection; the translated P30 bound is not a true intercept. The linear quadrilateral/corner translate exactly but remain diagnostics. `theta_star_command` and `Lambda_lin_command` are command-space diagnostics only. The coefficient matrix and active set are local refinement cues, not AC boundary proof. Operating-point provenance and S0 are directly reusable. The old 96 timestamps remain directly reusable for regression/export-pilot comparison but not as the final temporal set. Resource capabilities are outside `A_t^AC`.

## Lightweight validation

- Deterministic generator check: `generate_audit.py --check` verified all 10 generated artifacts.
- The generator's S0 parser asserted the exact audited timestamp, 1.00-p.u. root case, numerical-validation flag, and operational-feasibility flag while regenerating the origin evidence.
- Focused Julia coordinate tests: 33/33 command/absolute-PCC semantic assertions and 10/10 locked command-path assertions passed through `run_coordinate_tests.jl`.
- `git diff --check` exited 0. It emitted only existing checkout CRLF-conversion warnings for untouched coordinate-resolution files.
- `git diff --name-only` was empty; all tracked locked scientific artifacts remain unmodified. `git status --short` contains only the new additive audit directory.
- Cost estimates are regenerated from the committed Phase-B scan/timing files and rechecked by the deterministic generator.

## Final classifications

| topic | classification |
|---|---|
| primary design readiness | `CENTERED_RADIAL_RECOMMENDED_WITH_TARGETED_AXIS_EVIDENCE` |
| absolute-origin feasibility | `ABSOLUTE_ORIGIN_FEASIBLE_FROM_EXISTING_S0_EVIDENCE` |
| unity-PF policy | `LOCKED_Q_PCC_EQUALS_ZERO` |
| network/resource domain separation | `LOCKED_A_AC_SEPARATE_FROM_F_TVPP_H` |
| origin-radial suitability | `NOT_RECOMMENDED_STAR_SHAPEDNESS_NOT_PROVEN` |
| centered-radial suitability | `RECOMMENDED_CONDITIONAL_ON_SIGNED_AXIS_AND_TRANSITION_GATES` |
| support-function suitability | `SUPPORT_FUNCTION_REQUIRES_NEW_OPF_ARCHITECTURE` |
| absolute-axis evidence completeness | `INCOMPLETE_TARGETED_FOUR_HALF_AXIS_PREPASS_REQUIRED` |
| 96-timestamp suitability | `USE_ONLY_FOR_EXPORT_PILOT` |
| temporal-coverage adequacy | `INADEQUATE_UNTIL_BALANCED_32_TIMESTAMP_SET_IS_SELECTED` |
| computational feasibility | `SAFE_ON_12_CPU_32_GB_VM` |
| remote-backup status | `LOCAL_SCIENTIFIC_PROVENANCE_NOT_YET_BACKED_UP_TO_REMOTE` |
| production-probe readiness | `NOT_READY_TARGETED_AXIS_PREPASS_AND_BALANCED_TIMESTAMP_LIST_REQUIRED` |

No production radial/directional probe, new AC scan, support-function OPF, DOE solver, EV model, BESS model, centralized model, full-period optimization, or 96-timestamp campaign was executed.
"""

    return {
        "doe_boundary_method_comparison.csv": csv_text(method_fields, method_rows),
        "doe_temporal_scope_comparison.csv": csv_text(temporal_fields, temporal_rows),
        "doe_existing_evidence_reuse.csv": csv_text(reuse_fields, reuse_rows),
        "doe_axis_coverage_inventory.csv": csv_text(axis_fields, axis_rows),
        "doe_timestamp_selection_audit.csv": csv_text(timestamp_fields, timestamp_rows),
        "doe_computational_cost_estimate.csv": csv_text(cost_fields, cost_rows),
        "doe_recommended_probe_design.csv": csv_text(design_fields, design_rows),
        "doe_git_state.md": "\n".join(git_lines),
        "doe_probe_preregistration_amendment.md": prereg,
        "doe_boundary_design_audit_report.md": report,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="verify generated files without writing")
    args = parser.parse_args()
    artifacts = build_artifacts(evidence())
    if args.check:
        mismatches = []
        for name, expected in artifacts.items():
            path = HERE / name
            actual = path.read_text(encoding="utf-8") if path.exists() else None
            if actual != expected:
                mismatches.append(name)
        if mismatches:
            raise SystemExit("non-deterministic or stale audit artifacts: " + ", ".join(mismatches))
        print(f"verified {len(artifacts)} deterministic audit artifacts")
        return 0
    HERE.mkdir(parents=True, exist_ok=True)
    for name, content in artifacts.items():
        (HERE / name).write_text(content, encoding="utf-8", newline="")
    print(f"generated {len(artifacts)} audit artifacts from committed evidence only")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
