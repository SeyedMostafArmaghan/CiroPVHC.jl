# Absolute-PCC coordinate resolution report

Primary readiness classification: `ABSOLUTE_PCC_COORDINATES_IMPLEMENTED_PROBE_REDESIGN_REQUIRED`.

## Fixed scientific interpretation

`REFERENCE_PV_850_KW_IS_TVPP_OWNED` is selected. At `2012-10-15 13:00:00`, `850*0.9149568739021162=777.7133428167988 kW`. `BUS_13_CASE_LOAD_IS_DSO_BACKGROUND` and `BUS_30_CASE_LOAD_IS_DSO_BACKGROUND` are selected; their nominal 60/35 and 200/600 kW/kvar loads remain outside TVPP interface power.

The implemented equations are:

```text
P_PCC_13_abs = 777.7133428167988 + P_command_13
P_PCC_30_abs = P_command_30
p_net_i = passive_DSO_load_i - sum(P_PCC_abs at bus i) - other_nonload_DSO_injections_i
```

Positive `P_PCC_abs` is export and negative is import. `P_command` remains an externally supplied experiment and is not resource-derived `P_agg`. The separate `AggregateResourcePower` type reserves that future semantic distinction.

The present interface policy is `UNITY_POWER_FACTOR`, so `Q_PCC=0`; passive load Q stays in DSO background demand. The abstract `InterfaceReactivePolicy` dispatch permits a future `Q_PCC=kappa(P_PCC)` without creating an independent Q coordinate.

## Fixed-state set translation and DOE separation

For this timestamp and fixed DSO background, `A_cmd_t=A_abs_t-P_PCC_base_t`, where `P_PCC_base_t=[777.7133428167988,0] kW`. This is a translation, not a new AC evaluation. It cannot be reused as a moving origin tied to an optimized capacity `H`.

The final coordination statement is `P_PCC_abs in F_TVPP(H) intersection E_abs`, with `E_abs subset A_abs`. The DSO admissible set depends on passive/background injections, topology, documented limits, and fixed interface Q policy; the TVPP deliverability set contains resource capacities and schedules. Whether the fixed 850 kW is included in total `H_13` or treated as an existing installation plus expansion remains `REFERENCE_PV_CAPACITY_ACCOUNTING_REQUIRES_FINAL_HC_FORMULATION_DECISION`.

## Translated locked geometry

| Point | Command kW | Absolute-PCC kW | Interpretation |
|---|---:|---:|---|
| command origin | `(0,0)` | `(777.7133428167988,0)` | audited fixed-reference operating point |
| linear A | `(640.52368371395187,0)` | `(1418.2370265307507,0)` | linear-model point on absolute P13 axis |
| linear C | `(156.89470053621986,1610.2756675516089)` | `(934.6080433530186,1610.2756675516089)` | translated command-space corner |
| linear B | `(0,1677.6571993857481)` | `(777.7133428167988,1677.657199385748)` | `TRANSLATED_COMMAND_AXIS_POINT`, not absolute P30 intercept |
| AC P13 command bound | `(681.370544434,0)` | `(1459.0838872507989,0)` | existing AC point on absolute P13 axis |
| AC P30 command bound | `(0,1739.59228516)` | `(777.7133428167988,1739.59228516)` | `TRANSLATED_COMMAND_AXIS_POINT`, not absolute P30 intercept |

The locked linear command-space quadrilateral, command-axis bounds, active set, `g13`, `g30`, `theta_star_command=76.03090274387165 degrees`, and `Lambda_lin_command=0.20478347541993824` remain scientifically valid in `COMMAND_COORDINATES`. Translation preserves shape and area, but not the meaning of axes or a radial origin. No translated command-axis point is silently promoted to a physical-axis normalization.

## Absolute-domain coverage gap

The nonnegative command quadrant maps to `P_PCC_13_abs>=777.7133428167988` and `P_PCC_30_abs>=0`. Phase B evaluated only its command axes; it did not map the full AC quadrant. The regions `0<=P_PCC_13_abs<777.7133428167988`, negative P13, negative P30, both mixed-sign quadrants, import-import operation, and the true absolute P30 axis are not covered.

The physical origin `(0,0)` corresponds to command `(-777.7133428167988,0)` and has no locked exact AC evaluation. Its feasibility is `UNRESOLVED`. Existing data therefore neither prove nor disprove a connected feasible segment from the origin to the translated baseline.

Star-shapedness around the absolute origin is `UNRESOLVED_NOT_JUSTIFIED`. A radial representation is blocked until the origin passes AC/replay/voltage gates and selected rays show trustworthy ordered transitions. If the origin is infeasible or any required ray has multiple feasible components/transitions, use a different declared feasible reference point or a nonradial adaptive/half-space/component representation.

## Required AC evidence before production probing

1. Evaluate exactly `P_abs=(0,0)`, i.e. command `(-777.7133428167988,0)`.
2. Scan/refine both positive and negative absolute P13 half-axes using command `(P13_abs-777.7133428167988,0)`.
3. Scan/refine both positive and negative absolute P30 half-axes using command `(-777.7133428167988,P30_abs)`.
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
