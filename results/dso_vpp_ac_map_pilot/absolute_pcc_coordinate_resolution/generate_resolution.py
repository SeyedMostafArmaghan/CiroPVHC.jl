"""Deterministically generate the absolute-PCC coordinate-resolution artifacts."""

from __future__ import annotations

import csv
import hashlib
import re
from pathlib import Path


OUTPUT_DIR = Path(__file__).resolve().parent
REPOSITORY_ROOT = OUTPUT_DIR.parents[2]
PILOT_DIR = REPOSITORY_ROOT / "results" / "dso_vpp_ac_map_pilot"
PRIMARY_CLASSIFICATION = "ABSOLUTE_PCC_COORDINATES_IMPLEMENTED_PROBE_REDESIGN_REQUIRED"
TIMESTAMP = "2012-10-15 13:00:00"
PV_FACTOR = 0.9149568739021162
REFERENCE_PV_CAPACITY_KW = 850.0
PCC_BASE_13_KW = 777.7133428167988
LOAD_MULTIPLIER = 0.15594037439888725
PHASE_B_CAPACITY_SHA256 = "79ae1cd38ca705399babfa104e4f14c75f18d9bed4ecd4cd5b4b99d044a6af92"


def read_key_value_csv(path: Path) -> dict[str, str]:
    with path.open("r", encoding="utf-8", newline="") as stream:
        return {row["key"]: row["value"] for row in csv.DictReader(stream)}


def sha256_canonical_lf(path: Path) -> str:
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def write_csv(name: str, header: tuple[str, ...], rows: list[tuple[object, ...]]) -> None:
    if not rows:
        raise RuntimeError(f"refusing to write empty artifact {name}")
    with (OUTPUT_DIR / name).open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream, lineterminator="\n")
        writer.writerow(header)
        writer.writerows(rows)


def number(value: float) -> str:
    return repr(float(value))


def main() -> None:
    phase_b_capacity = PILOT_DIR / "export_side_axis_capacity_bounds.csv"
    if sha256_canonical_lf(phase_b_capacity) != PHASE_B_CAPACITY_SHA256:
        raise RuntimeError("locked Phase-B capacity artifact SHA-256 mismatch")
    analytical = read_key_value_csv(PILOT_DIR / "ac_anchored_linear_corner_audit_summary.csv")
    provenance = read_key_value_csv(PILOT_DIR / "operating_point_provenance_summary.csv")

    expected = {
        "reference_pv_factor": PV_FACTOR,
        "reference_pv_injection_kw": PCC_BASE_13_KW,
        "load_multiplier": LOAD_MULTIPLIER,
        "axis_13_ac_limit_kw": 681.370544434,
        "axis_30_ac_limit_kw": 1739.59228516,
        "axis_13_linear_limit_kw": 640.523683713952,
        "axis_30_linear_limit_kw": 1677.65719938575,
        "intersection_p13_kw": 156.894700536220,
        "intersection_p30_kw": 1610.27566755161,
        "normalized_angle_deg": 76.03090274387165,
    }
    for key, expected_value in expected.items():
        actual = float(analytical[key])
        if abs(actual - expected_value) > 5e-12:
            raise RuntimeError(f"locked analytical value mismatch for {key}: {actual}")
    if provenance["primary_classification"] != "ADJACENT_TIMESTAMP_HISTORICAL_TEXT_ERROR":
        raise RuntimeError("operating-point provenance classification changed")
    if abs(float(provenance["Lambda_lin"]) - 0.20478347541993824) > 1e-15:
        raise RuntimeError("locked command-space Lambda_lin changed")

    mapping_header = (
        "item", "interface_id", "bus_id", "quantity_kind", "implemented_equation_or_value",
        "units", "positive_meaning", "ownership", "coordinate_system", "evidence",
    )
    mapping_rows = [
        ("audited operating point", "ALL", "13;30", "InterfaceOperatingPoint", TIMESTAMP, "timezone-naive timestamp", "not applicable", "fixed pilot anchor", "ABSOLUTE_PCC_TRANSLATION", "data_processed/ausgrid/ausgrid_halfhour_normalized.csv; operating_point_provenance_summary.csv"),
        ("bus-13 command", "PCC_13", 13, "P_command", "externally supplied incremental command", "kW", "incremental TVPP export", "experimental command; not resource-derived P_agg", "COMMAND_COORDINATES", "src/benchmark/dso_vpp_ac_map_stage0.jl:89-116"),
        ("bus-30 command", "PCC_30", 30, "P_command", "externally supplied incremental command", "kW", "incremental TVPP export", "experimental command; not resource-derived P_agg", "COMMAND_COORDINATES", "src/benchmark/dso_vpp_ac_map_stage0.jl:89-116"),
        ("bus-13 absolute interface", "PCC_13", 13, "P_PCC_abs", f"P_PCC_13_abs={number(PCC_BASE_13_KW)}+P_command_13", "kW", "TVPP export", "reference PV plus experimental command", "ABSOLUTE_PCC_COORDINATES", "src/data/interface_coordinates.jl:command_to_absolute"),
        ("bus-30 absolute interface", "PCC_30", 30, "P_PCC_abs", "P_PCC_30_abs=P_command_30", "kW", "TVPP export", "experimental command", "ABSOLUTE_PCC_COORDINATES", "src/data/interface_coordinates.jl:command_to_absolute"),
        ("audited baseline vector", "PCC_13;PCC_30", "13;30", "P_PCC_base", f"[{number(PCC_BASE_13_KW)},0]", "kW", "TVPP export", "850 kW reference PV is TVPP-owned", "ABSOLUTE_PCC_COORDINATES", "850*0.9149568739021162"),
        ("future aggregate resource power", "ALL", "data-driven", "P_agg", "resource-derived PV+EV+BESS aggregate; no pilot computation", "kW", "export positive; import negative", "TVPP resource model", "NOT_YET_MAPPED_TO_PCC", "src/data/interface_coordinates.jl:AggregateResourcePower"),
        ("network active demand", "ALL", "data-driven", "p_net", "passive_DSO_load-sum(P_PCC_abs)-other_nonload_DSO_injections", "kW", "network consumption", "DSO network model", "NETWORK_COORDINATES", "src/data/interface_coordinates.jl:assemble_bus_net_active_demand_kw"),
        ("bus-13 passive load", "PCC_13", 13, "passive_DSO_load", "60*load_multiplier", "kW", "network consumption", "BUS_13_CASE_LOAD_IS_DSO_BACKGROUND", "NETWORK_COORDINATES", "src/data/ieee33.jl:17"),
        ("bus-30 passive load", "PCC_30", 30, "passive_DSO_load", "200*load_multiplier", "kW", "network consumption", "BUS_30_CASE_LOAD_IS_DSO_BACKGROUND", "NETWORK_COORDINATES", "src/data/ieee33.jl:34"),
        ("interface reactive policy", "PCC_13;PCC_30", "13;30", "Q_PCC", "Q_PCC=kappa(P_PCC)=0", "kvar", "reactive export", "UNITY_POWER_FACTOR", "ABSOLUTE_PCC_COORDINATES", "src/data/interface_coordinates.jl:UnityPowerFactor"),
        ("reference capacity accounting", "PCC_13", 13, "planning H_13", "total-versus-expansion accounting not selected", "kW nameplate", "not applicable", "REFERENCE_PV_CAPACITY_ACCOUNTING_REQUIRES_FINAL_HC_FORMULATION_DECISION", "UNRESOLVED_PLANNING_CHOICE", "absolute_pcc_coordinate_resolution_report.md"),
    ]
    write_csv("absolute_pcc_coordinate_mapping.csv", mapping_header, mapping_rows)

    l13 = float(provenance["linear_axis_13_intercept_kw"])
    l30 = float(provenance["linear_axis_30_intercept_kw"])
    c13 = float(provenance["linear_corner_p13_kw"])
    c30 = float(provenance["linear_corner_p30_kw"])
    ac13 = float(analytical["axis_13_ac_limit_kw"])
    ac30 = float(analytical["axis_30_ac_limit_kw"])
    vertex_header = (
        "source_coordinate_system", "source_point_type", "source_p13_kw", "source_p30_kw",
        "baseline_p13_kw", "baseline_p30_kw", "absolute_pcc_13_kw", "absolute_pcc_30_kw",
        "true_absolute_pcc_axis_intercept", "scientific_interpretation", "provenance_artifact",
    )
    vertex_rows = [
        ("COMMAND_COORDINATES", "COMMAND_ORIGIN_O", "0", "0", number(PCC_BASE_13_KW), "0", number(PCC_BASE_13_KW), "0", "NO_BASELINE_OPERATING_POINT_NOT_BOUNDARY_INTERCEPT", "Zero incremental command; translated audited operating point", "operating_point_provenance_report.md"),
        ("COMMAND_COORDINATES", "LINEAR_COMMAND_AXIS_13_VERTEX_A", provenance["linear_axis_13_intercept_kw"], "0", number(PCC_BASE_13_KW), "0", number(PCC_BASE_13_KW + l13), "0", "YES_LINEAR_MODEL_PCC13_AXIS_ONLY", "Translated linear command-axis vertex; not an AC intercept claim", "operating_point_provenance_summary.csv"),
        ("COMMAND_COORDINATES", "LINEAR_COMMAND_CORNER_C", provenance["linear_corner_p13_kw"], provenance["linear_corner_p30_kw"], number(PCC_BASE_13_KW), "0", number(PCC_BASE_13_KW + c13), number(c30), "NO", "Translation of the locked command-space linear corner", "operating_point_provenance_summary.csv"),
        ("COMMAND_COORDINATES", "LINEAR_COMMAND_AXIS_30_VERTEX_B", "0", provenance["linear_axis_30_intercept_kw"], number(PCC_BASE_13_KW), "0", number(PCC_BASE_13_KW), number(l30), "NO_TRANSLATED_COMMAND_AXIS_POINT", "Not on the absolute P_PCC_30 axis because P_PCC_13_abs is nonzero", "operating_point_provenance_summary.csv"),
        ("COMMAND_COORDINATES", "AC_COMMAND_AXIS_13_BOUND", analytical["axis_13_ac_limit_kw"], "0", number(PCC_BASE_13_KW), "0", number(PCC_BASE_13_KW + ac13), "0", "YES_AC_PCC13_AXIS_BOUNDARY_POINT", "Existing AC boundary point lies on P_PCC_30_abs=0; connectivity from absolute origin remains unevaluated", "export_side_axis_capacity_bounds.csv"),
        ("COMMAND_COORDINATES", "AC_COMMAND_AXIS_30_BOUND", "0", analytical["axis_30_ac_limit_kw"], number(PCC_BASE_13_KW), "0", number(PCC_BASE_13_KW), number(ac30), "NO_TRANSLATED_COMMAND_AXIS_POINT", "Existing AC command-axis point is not a true absolute P_PCC_30 axis intercept", "export_side_axis_capacity_bounds.csv"),
    ]
    write_csv("absolute_pcc_translated_vertices.csv", vertex_header, vertex_rows)

    coverage_header = (
        "region_id", "absolute_pcc_13_domain_kw", "absolute_pcc_30_domain_kw",
        "equivalent_command_domain_kw", "existing_evidence", "coverage_classification",
        "feasibility_status", "required_next_evidence",
    )
    coverage_rows = [
        ("TRANSLATED_NONNEGATIVE_COMMAND_QUADRANT", f">={number(PCC_BASE_13_KW)}", ">=0", "P_command_13>=0; P_command_30>=0", "AC evaluated only on the two command axes; analytical linear quadrilateral translated exactly", "PARTIAL_AXES_AND_LINEAR_MODEL_ONLY", "NO_COMPLETE_AC_SET_EVIDENCE", "new absolute-coordinate design after origin and true-axis checks"),
        ("BETWEEN_ABSOLUTE_ORIGIN_AND_REFERENCE_BASE", f"0<=P13<{number(PCC_BASE_13_KW)}", "P30=0 or mixed", f"-{number(PCC_BASE_13_KW)}<=P_command_13<0", "not covered by Phase B", "UNEVALUATED", "UNRESOLVED", "origin evaluation and P13 absolute-axis continuation"),
        ("NEGATIVE_PCC13_IMPORT", "P13<0", "any planned P30", f"P_command_13<-{number(PCC_BASE_13_KW)}", "not covered by Phase B", "UNEVALUATED_IMPORT_DOMAIN", "UNRESOLVED", "negative P13 axis and mixed-quadrant AC solves"),
        ("NEGATIVE_PCC30_IMPORT", "any planned P13", "P30<0", "P_command_30<0", "not covered by Phase B", "UNEVALUATED_IMPORT_DOMAIN", "UNRESOLVED", "negative P30 axis and mixed-quadrant AC solves"),
        ("MIXED_EXPORT_IMPORT", "P13>0;P30<0 or P13<0;P30>0", "mixed signs", "one or both commands may be negative after baseline translation", "not covered by Phase B", "UNEVALUATED_MIXED_QUADRANTS", "UNRESOLVED", "deterministic mixed-quadrant design after true intercepts"),
        ("TRUE_ABSOLUTE_PCC30_AXIS", "P13=0", "P30 variable", f"P_command_13=-{number(PCC_BASE_13_KW)};P_command_30=P30", "no locked Phase-B boundary solve", "TRUE_AXIS_UNAVAILABLE", "UNRESOLVED", "positive and negative P30 half-axis scans"),
        ("ABSOLUTE_ORIGIN", "P13=0", "P30=0", f"P_command=(-{number(PCC_BASE_13_KW)},0)", "exact point absent from locked evidence", "ORIGIN_NOT_EVALUATED", "UNRESOLVED", "single audited-timestamp AC solve and replay before any radial design"),
        ("FULL_FINAL_TVPP_DOMAIN", "export and import", "export and import", "not representable by nonnegative Phase-B command quadrant", "PV/EV/BESS operational bounds and DOE are not constructed", "FINAL_DOMAIN_NOT_DEFINED", "UNRESOLVED", "declare finite absolute domain independently of optimized H"),
    ]
    write_csv("absolute_pcc_domain_coverage.csv", coverage_header, coverage_rows)

    evaluation_header = (
        "priority", "evaluation_id", "absolute_pcc_path", "equivalent_command_path",
        "purpose", "required_method", "decision_enabled", "production_probe_gate",
    )
    evaluation_rows = [
        ("P0", "ABS_ORIGIN_EXACT", "P_abs=(0,0)", f"P_command=(-{number(PCC_BASE_13_KW)},0)", "establish physical-origin AC convergence/replay/0.90-1.05 feasibility", "one exact AC evaluation plus replay; no optimization", "whether origin can anchor any radial representation", "BLOCKING"),
        ("P0", "PCC13_POSITIVE_HALF_AXIS", "P_abs=(lambda,0), lambda>=0", f"P_command=(lambda-{number(PCC_BASE_13_KW)},0)", "connect origin through the fixed-reference point to the known positive boundary and test ordered transitions", "coarse scan plus bracket/refinement with explicit multiple-transition handling", "true positive P13 absolute-axis boundary and connectivity", "BLOCKING"),
        ("P0", "PCC13_NEGATIVE_HALF_AXIS", "P_abs=(-lambda,0), lambda>=0", f"P_command=(-lambda-{number(PCC_BASE_13_KW)},0)", "find or classify import-side terminal behavior", "guarded coarse scan plus bracket/refinement; nonconvergence unresolved", "negative P13 domain extent", "BLOCKING_IF_IMPORT_INCLUDED"),
        ("P0", "PCC30_POSITIVE_HALF_AXIS", "P_abs=(0,lambda), lambda>=0", f"P_command=(-{number(PCC_BASE_13_KW)},lambda)", "obtain true positive P30 absolute-axis intercept", "guarded coarse scan plus bracket/refinement", "positive P30 normalization based on a true axis", "BLOCKING"),
        ("P0", "PCC30_NEGATIVE_HALF_AXIS", "P_abs=(0,-lambda), lambda>=0", f"P_command=(-{number(PCC_BASE_13_KW)},-lambda)", "find or classify P30 import-side terminal behavior", "guarded coarse scan plus bracket/refinement; nonconvergence unresolved", "negative P30 domain extent", "BLOCKING_IF_IMPORT_INCLUDED"),
        ("P1", "EXPORT_EXPORT_INTERIOR", "P13>0;P30>0 from the selected absolute reference", "subtract fixed baseline componentwise", "test intermediate-direction transitions without reusing theta_star_command", "directions preregistered only after true intercept/domain selection", "star-shapedness evidence in export-export quadrant", "BLOCKING_FOR_RADIAL_REPRESENTATION"),
        ("P1", "EXPORT_IMPORT_INTERIOR", "P13>0;P30<0", "subtract fixed baseline componentwise", "cover EV/BESS mixed export/import behavior", "deterministic directions after positive/negative axis scales exist", "mixed-quadrant connectivity and transitions", "BLOCKING_IF_DOMAIN_INCLUDED"),
        ("P1", "IMPORT_EXPORT_INTERIOR", "P13<0;P30>0", "subtract fixed baseline componentwise", "cover EV/BESS mixed import/export behavior", "deterministic directions after positive/negative axis scales exist", "mixed-quadrant connectivity and transitions", "BLOCKING_IF_DOMAIN_INCLUDED"),
        ("P1", "IMPORT_IMPORT_INTERIOR", "P13<0;P30<0", "subtract fixed baseline componentwise", "cover simultaneous charging/import behavior", "deterministic directions after negative axis scales exist", "import-import connectivity and transitions", "BLOCKING_IF_DOMAIN_INCLUDED"),
        ("P2", "NONRADIAL_FALLBACK", "finite declared absolute domain", "componentwise translation only", "avoid invalid radial construction if origin is infeasible or rays have multiple transitions", "adaptive cells/support directions/half-space or disconnected-component representation", "choice of nonradial boundary representation", "CONDITIONAL"),
    ]
    write_csv("absolute_pcc_required_ac_evaluations.csv", evaluation_header, evaluation_rows)

    label_header = (
        "artifact_path", "line_or_field", "quantity", "coordinate_label", "interpretation",
        "additive_label_action", "historical_bytes_modified",
    )
    label_rows = [
        ("results/dso_vpp_ac_map_pilot/export_side_axis_capacity_bounds.csv", "axis; axis_bus; axis_capacity_kW", "AC axis bounds", "COMMAND_COORDINATES", "safe endpoints of incremental command axes", "sidecar label; retain raw schema", "no"),
        ("results/dso_vpp_ac_map_pilot/export_side_axis_report.md", "axis summaries", "AC axis bounds", "COMMAND_COORDINATES", "command-axis results with fixed reference PV", "sidecar label", "no"),
        ("results/dso_vpp_ac_map_pilot/ac_anchored_linear_corner_audit_summary.csv", "axis_*_limit; intersection_*; normalization_scale_*; normalized_angle_*", "linear limits/corner/theta_star", "COMMAND_COORDINATES", "all capacity and normalized-angle fields use command coordinates and command-axis denominators", "sidecar aliases P_command_axis_bound and theta_star_command", "no"),
        ("results/dso_vpp_ac_map_pilot/ac_anchored_linear_corner_audit_report.md", "axis comparison; candidate intersection; normalized direction", "linear and mixed AC/linear quantities", "COMMAND_COORDINATES", "the report's P13/P30 variables are incremental commands", "sidecar label", "no"),
        ("results/dso_vpp_ac_map_pilot/ac_anchored_linear_corner_audit_axis_13_ranking.csv", "linear_axis_limit_kw", "linear axis limits", "COMMAND_COORDINATES", "bus-13 incremental-command axis", "sidecar label", "no"),
        ("results/dso_vpp_ac_map_pilot/ac_anchored_linear_corner_audit_axis_30_ranking.csv", "linear_axis_limit_kw", "linear axis limits", "COMMAND_COORDINATES", "bus-30 incremental-command axis", "sidecar label", "no"),
        ("results/dso_vpp_ac_map_pilot/ac_anchored_linear_corner_audit_corner_margins.csv", "contribution_13_v2; contribution_30_v2", "corner contributions", "COMMAND_COORDINATES", "evaluated at the command-space linear corner", "sidecar label", "no"),
        ("results/dso_vpp_ac_map_pilot/operating_point_provenance_summary.csv", "g13;g30;theta_star_degrees;linear_*;Lambda_lin", "g13/g30/theta_star/Lambda_lin", "COMMAND_COORDINATES", "g values and theta use command-axis AC scales; Lambda uses command-space areas", "sidecar aliases g13_command/g30_command/theta_star_command/Lambda_lin_command", "no"),
        ("results/dso_vpp_ac_map_pilot/operating_point_provenance_report.md", "Scientific result", "quadrilateral/theta_star/Lambda_lin", "COMMAND_COORDINATES", "locked incremental-command geometry", "sidecar label", "no"),
        ("results/dso_vpp_ac_map_pilot/operating_point_provenance_phaseb_audit_comparison.csv", "command/boundary comparison fields", "aligned operating-point quantities", "COMMAND_COORDINATES", "compares Phase-B and analytical command paths", "sidecar label", "no"),
        ("results/dso_vpp_ac_map_pilot/ac_linear_probe_preregistration.md", "P13/P30;s13/s30;theta_star;g_r;epsilon_v;Lambda_*", "prior radial design and metrics", "COMMAND_COORDINATES", "all prior rays/scales/normalized areas are based on incremental commands", "superseded for production grid by absolute-PCC amendment", "no"),
        ("scripts/run_dso_vpp_ac_anchored_linear_corner_audit.jl", "Normalized angle console label", "theta_star", "COMMAND_COORDINATES", "diagnostic command-space angle", "future console alias theta_star_command; do not change locked artifacts", "no"),
        ("src/benchmark/dso_vpp_operating_point_provenance.jl", "g13;g30;theta_star;Lambda_lin writers", "normalized provenance quantities", "COMMAND_COORDINATES", "writer generated the locked command-space artifacts", "sidecar metadata preserves hashes", "no"),
        ("repository search", "m_star", "m_star", "NOT_PRESENT", "no material pilot occurrence found", "no action", "no"),
    ]
    write_csv("absolute_pcc_artifact_label_inventory.csv", label_header, label_rows)

    git_provenance = f"""# Absolute-PCC coordinate resolution: Git provenance

Observed before tracked modifications on 2026-08-06:

- Working tree: clean.
- Branch: `codex/dso-vpp-ac-map-pilot`.
- Local HEAD: `461892dcae37b16c1e640d430ab0df92957fc5cd` (`docs: clarify multi-interface TVPP architecture`).
- Tracking state: `origin/codex/dso-vpp-ac-map-pilot`, locally ahead by three commits, behind by zero.
- Raw origin fetch/push URL: `https://github.com/SeyedMostafArmaghan/CiroPVHC.jl.git`.
- Live remote query: `refs/heads/codex/dso-vpp-ac-map-pilot` was `d8e1bb0a7909711b4124f95673fb3a4802ae783a`.

## Commit presence and push status

| Commit | Present locally | Present on live tracked remote | Interpretation |
|---|---:|---:|---|
| `4c478232428dcb8f28be2d85ed12cf1c84fc7925` | yes | no | local provenance-test commit |
| `5fc6ac12fe115acf2de282b5c10c821d400e0cc7` | yes | no | local provenance documentation commit |
| `461892dcae37b16c1e640d430ab0df92957fc5cd` | yes | no | local TVPP architecture-audit commit |

Commit `461892d` adds nine files under `results/dso_vpp_ac_map_pilot/tvpp_interface_architecture_audit/`: eight audit artifacts and one deterministic Python generator, 737 inserted lines. It changes no `src/`, `scripts/`, `test/`, configuration, canonical data, Phase-B artifact, analytical artifact, or provenance artifact. It is therefore not literally documentation-only because it contains `generate_audit.py`, but it is an audit-artifact commit with no production scientific behavior.

History is linear (`d8e1bb0 -> 4c478232 -> 5fc6ac12 -> 461892d`). No divergence, merge, simultaneous dirty work, or evidence of overlapping/unexplained sessions was found. Classification: `LINEAR_LOCAL_UNPUSHED_HISTORY_NO_OVERLAP_EVIDENCE`.

No push was performed. Final post-commit state is reported by the task handoff because embedding the containing commit hash would create a circular self-reference.
"""
    (OUTPUT_DIR / "absolute_pcc_git_provenance.md").write_text(
        git_provenance.rstrip() + "\n", encoding="utf-8", newline="\n"
    )

    amendment = f"""# Pre-execution Amendment 3 — Absolute-PCC coordinate correction and probe redesign

**Amendment date:** 2026-08-06. This is additive. It does not delete, regenerate, or numerically reinterpret the locked Phase-B, analytical, or operating-point provenance artifacts.

1. Final DOE coordinates are absolute physical interface powers `P_PCC_abs`, with export positive and import negative.
2. The 850 kW reference PV at bus 13 is TVPP-owned. At the audited timestamp it contributes `{number(PCC_BASE_13_KW)} kW` to `P_PCC_13_abs`.
3. Passive case loads at buses 13 and 30 remain DSO background. They are excluded from `P_PCC_abs` and enter only the DSO equation `p_net=passive_DSO_load-sum(P_PCC_abs)-other_nonload_DSO_injections`.
4. All existing Phase-B and analytical results are `COMMAND_COORDINATES` results. Their numerical scientific content remains valid and immutable.
5. At a fixed timestamp/background state, `P_PCC_abs=P_command+P_PCC_base`, with audited baseline `[{number(PCC_BASE_13_KW)},0] kW`; equivalently `A_cmd_t=A_abs_t-P_PCC_base_t`.
6. A translated command-axis point is classified `TRANSLATED_COMMAND_AXIS_POINT`; it is not automatically a `TRUE_ABSOLUTE_PCC_AXIS_INTERCEPT`. In particular `(0,s30)` commands translate to `({number(PCC_BASE_13_KW)},s30)` absolute kW.
7. The locked `theta_star_command=76.03090274387165 degrees` and its command-axis scales will not determine the next production probe grid.
8. A new absolute-coordinate design requires origin feasibility, true positive/negative absolute-axis information, a finite domain independent of optimized `H`, and mixed-quadrant coverage before directions are fixed.
9. EV and BESS require import/export and mixed-sign quadrants that remain unscanned by the nonnegative command pilot.
10. No final absolute-PCC DOE, `theta_star_abs`, absolute-domain normalization, radial boundary, or star-shapedness claim is made here.

The present pilot policy is `UNITY_POWER_FACTOR`: `Q_PCC=kappa(P_PCC)=0`. Future fixed `Q(P)` policies must implement the interface-policy abstraction and must never absorb passive-load Q into `Q_PCC`.

`REFERENCE_PV_850_KW_IS_TVPP_OWNED` is selected. Whether final `H_13` means total installed capacity, expansion above the fixed 850 kW, or a replacement variable remains `REFERENCE_PV_CAPACITY_ACCOUNTING_REQUIRES_FINAL_HC_FORMULATION_DECISION`.

**The existing command-space pilot results are scientifically valid.**

**The final absolute-PCC DOE has not yet been constructed or validated.**

No production radial/direction probe, AC map, DOE construction, EV/BESS/centralized optimization, constraint generation, or full-period campaign was executed for this amendment.
"""
    (OUTPUT_DIR / "absolute_pcc_probe_preregistration_amendment.md").write_text(
        amendment.rstrip() + "\n", encoding="utf-8", newline="\n"
    )

    report = f"""# Absolute-PCC coordinate resolution report

Primary readiness classification: `{PRIMARY_CLASSIFICATION}`.

## Fixed scientific interpretation

`REFERENCE_PV_850_KW_IS_TVPP_OWNED` is selected. At `{TIMESTAMP}`, `850*{PV_FACTOR}={number(PCC_BASE_13_KW)} kW`. `BUS_13_CASE_LOAD_IS_DSO_BACKGROUND` and `BUS_30_CASE_LOAD_IS_DSO_BACKGROUND` are selected; their nominal 60/35 and 200/600 kW/kvar loads remain outside TVPP interface power.

The implemented equations are:

```text
P_PCC_13_abs = {number(PCC_BASE_13_KW)} + P_command_13
P_PCC_30_abs = P_command_30
p_net_i = passive_DSO_load_i - sum(P_PCC_abs at bus i) - other_nonload_DSO_injections_i
```

Positive `P_PCC_abs` is export and negative is import. `P_command` remains an externally supplied experiment and is not resource-derived `P_agg`. The separate `AggregateResourcePower` type reserves that future semantic distinction.

The present interface policy is `UNITY_POWER_FACTOR`, so `Q_PCC=0`; passive load Q stays in DSO background demand. The abstract `InterfaceReactivePolicy` dispatch permits a future `Q_PCC=kappa(P_PCC)` without creating an independent Q coordinate.

## Fixed-state set translation and DOE separation

For this timestamp and fixed DSO background, `A_cmd_t=A_abs_t-P_PCC_base_t`, where `P_PCC_base_t=[{number(PCC_BASE_13_KW)},0] kW`. This is a translation, not a new AC evaluation. It cannot be reused as a moving origin tied to an optimized capacity `H`.

The final coordination statement is `P_PCC_abs in F_TVPP(H) intersection E_abs`, with `E_abs subset A_abs`. The DSO admissible set depends on passive/background injections, topology, documented limits, and fixed interface Q policy; the TVPP deliverability set contains resource capacities and schedules. Whether the fixed 850 kW is included in total `H_13` or treated as an existing installation plus expansion remains `REFERENCE_PV_CAPACITY_ACCOUNTING_REQUIRES_FINAL_HC_FORMULATION_DECISION`.

## Translated locked geometry

| Point | Command kW | Absolute-PCC kW | Interpretation |
|---|---:|---:|---|
| command origin | `(0,0)` | `({number(PCC_BASE_13_KW)},0)` | audited fixed-reference operating point |
| linear A | `({provenance['linear_axis_13_intercept_kw']},0)` | `({number(PCC_BASE_13_KW + l13)},0)` | linear-model point on absolute P13 axis |
| linear C | `({provenance['linear_corner_p13_kw']},{provenance['linear_corner_p30_kw']})` | `({number(PCC_BASE_13_KW + c13)},{number(c30)})` | translated command-space corner |
| linear B | `(0,{provenance['linear_axis_30_intercept_kw']})` | `({number(PCC_BASE_13_KW)},{number(l30)})` | `TRANSLATED_COMMAND_AXIS_POINT`, not absolute P30 intercept |
| AC P13 command bound | `({analytical['axis_13_ac_limit_kw']},0)` | `({number(PCC_BASE_13_KW + ac13)},0)` | existing AC point on absolute P13 axis |
| AC P30 command bound | `(0,{analytical['axis_30_ac_limit_kw']})` | `({number(PCC_BASE_13_KW)},{number(ac30)})` | `TRANSLATED_COMMAND_AXIS_POINT`, not absolute P30 intercept |

The locked linear command-space quadrilateral, command-axis bounds, active set, `g13`, `g30`, `theta_star_command=76.03090274387165 degrees`, and `Lambda_lin_command=0.20478347541993824` remain scientifically valid in `COMMAND_COORDINATES`. Translation preserves shape and area, but not the meaning of axes or a radial origin. No translated command-axis point is silently promoted to a physical-axis normalization.

## Absolute-domain coverage gap

The nonnegative command quadrant maps to `P_PCC_13_abs>={number(PCC_BASE_13_KW)}` and `P_PCC_30_abs>=0`. Phase B evaluated only its command axes; it did not map the full AC quadrant. The regions `0<=P_PCC_13_abs<{number(PCC_BASE_13_KW)}`, negative P13, negative P30, both mixed-sign quadrants, import-import operation, and the true absolute P30 axis are not covered.

The physical origin `(0,0)` corresponds to command `(-{number(PCC_BASE_13_KW)},0)` and has no locked exact AC evaluation. Its feasibility is `UNRESOLVED`. Existing data therefore neither prove nor disprove a connected feasible segment from the origin to the translated baseline.

Star-shapedness around the absolute origin is `UNRESOLVED_NOT_JUSTIFIED`. A radial representation is blocked until the origin passes AC/replay/voltage gates and selected rays show trustworthy ordered transitions. If the origin is infeasible or any required ray has multiple feasible components/transitions, use a different declared feasible reference point or a nonradial adaptive/half-space/component representation.

## Required AC evidence before production probing

1. Evaluate exactly `P_abs=(0,0)`, i.e. command `(-{number(PCC_BASE_13_KW)},0)`.
2. Scan/refine both positive and negative absolute P13 half-axes using command `(P13_abs-{number(PCC_BASE_13_KW)},0)`.
3. Scan/refine both positive and negative absolute P30 half-axes using command `(-{number(PCC_BASE_13_KW)},P30_abs)`.
4. Declare finite import/export bounds independently of optimized `H`; derive any positive/negative normalization only from true absolute-axis evidence.
5. Preregister deterministic export-export, export-import, import-export, and import-import directions after those scales/domain are known. Do not reuse `theta_star_command` as `theta_star_abs`.
6. Count all status transitions and retain nonconvergence as unresolved. If radial assumptions fail, execute the preregistered nonradial fallback rather than selecting a boundary post hoc.

These are required future evaluations, not results of this task.

## Classifications

| Topic | Classification |
|---|---|
| reference PV ownership | `REFERENCE_PV_850_KW_IS_TVPP_OWNED` |
| passive-load ownership | `BUS_13_AND_30_CASE_LOADS_ARE_DSO_BACKGROUND` |
| command-to-PCC mapping | `DETERMINISTIC_FIXED_BASELINE_TRANSLATION_IMPLEMENTED` |
| absolute-domain coverage | `RESTRICTED_TRANSLATED_EXPORT_SUBSET_ONLY` |
| true absolute-axis intercept availability | `PCC13_POSITIVE_POINT_AVAILABLE_PCC30_AND_IMPORT_INTERCEPTS_MISSING` |
| absolute-origin feasibility evidence | `UNRESOLVED_NO_LOCKED_AC_EVALUATION` |
| star-shaped radial suitability | `UNRESOLVED_NOT_JUSTIFIED` |
| reactive-policy readiness | `UNITY_POWER_FACTOR_IMPLEMENTED_FUTURE_KAPPA_DISPATCH_READY` |
| artifact coordinate labeling | `ADDITIVE_COMMAND_COORDINATE_SIDECAR_COMPLETE` |
| Git provenance | `LINEAR_LOCAL_UNPUSHED_HISTORY_NO_OVERLAP_EVIDENCE` |
| readiness for production radial probe | `NOT_READY_TARGETED_ABSOLUTE_AC_EVIDENCE_AND_GRID_REDESIGN_REQUIRED` |

## Implementation and preservation

`src/data/interface_coordinates.jl` adds arbitrary-length interface definitions, operating points, command/absolute/aggregate quantity types, strict layout validation, round-trip transforms, reactive-policy dispatch, and active/reactive bus-demand assembly. The locked Stage-0/Phase-B positional APIs and schemas are unchanged.

Raw Phase-B, analytical, and provenance artifacts remain byte-identical. `absolute_pcc_artifact_label_inventory.csv` supplies additive coordinate labels without invalidating their manifests. The new artifacts are deterministic and repository-relative.

**The existing command-space pilot results are scientifically valid.**

**The final absolute-PCC DOE has not yet been constructed or validated.**

No production radial/direction probe or prohibited downstream computation was executed.
"""
    (OUTPUT_DIR / "absolute_pcc_coordinate_resolution_report.md").write_text(
        report.rstrip() + "\n", encoding="utf-8", newline="\n"
    )

    required = {
        "absolute_pcc_coordinate_resolution_report.md",
        "absolute_pcc_coordinate_mapping.csv",
        "absolute_pcc_translated_vertices.csv",
        "absolute_pcc_domain_coverage.csv",
        "absolute_pcc_required_ac_evaluations.csv",
        "absolute_pcc_artifact_label_inventory.csv",
        "absolute_pcc_git_provenance.md",
        "absolute_pcc_probe_preregistration_amendment.md",
    }
    missing = sorted(name for name in required if not (OUTPUT_DIR / name).is_file())
    if missing:
        raise RuntimeError(f"missing required artifacts: {missing}")
    for name in sorted(required):
        text = (OUTPUT_DIR / name).read_text(encoding="utf-8")
        if not text.strip():
            raise RuntimeError(f"empty artifact: {name}")
        if re.search(r"(?<![A-Za-z])[A-Za-z]:[\\/]", text):
            raise RuntimeError(f"absolute path found in artifact: {name}")

    written_report = (OUTPUT_DIR / "absolute_pcc_coordinate_resolution_report.md").read_text(
        encoding="utf-8"
    )
    if written_report.count(f"Primary readiness classification: `{PRIMARY_CLASSIFICATION}`") != 1:
        raise RuntimeError("primary readiness classification missing or duplicated")
    with (OUTPUT_DIR / "absolute_pcc_translated_vertices.csv").open(
        "r", encoding="utf-8", newline=""
    ) as stream:
        written_vertices = list(csv.DictReader(stream))
    if len(written_vertices) != 6:
        raise RuntimeError("translated-vertex row-count mismatch")
    if not any(
        row["true_absolute_pcc_axis_intercept"] == "NO_TRANSLATED_COMMAND_AXIS_POINT"
        for row in written_vertices
    ):
        raise RuntimeError("translated command-axis warning is absent")


if __name__ == "__main__":
    main()
