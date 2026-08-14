# DOE construction policy preregistration (artifact only)

## Scope and locked provenance

- Starting branch: `codex/dso-vpp-ac-map-pilot`
- Starting HEAD: `c18021d9b981f2629e54f60e8c2fc5f33b00c1a2`
- Initial working tree: clean
- Generation performs no AC solve, production probing, annual TVPP optimization, HC optimization, historical-result regeneration, or validation-driven tuning.
- Coordinate authority: absolute physical `P_PCC=[P13,P30]` kW, positive export, with `Q_PCC=0`.

This package preregisters a deterministic candidate generator and diagnostics. `LINDISTFLOW_IS_NOT_DOE_FEASIBILITY_AUTHORITY`; topology normals are candidate-facet generators. Stored fitted normals are diagnostic/falsification evidence only. Finite future AC meshes are empirical falsification/validation, never proof of continuous feasibility.

## Coordinate contract

The previous `(156.8947,1610.2757)` versus `(934.6080,1610.2757)` discrepancy is resolved by source: the former is command space and the latter is absolute physical PCC space, with `P_PCC_13_abs=777.7133428167988+P_command_13` for that historical Phase-B timestamp. Production data do not apply that translation: the production evaluator passes stored absolute `P_PCC` directly with `reference_pv_capacity_kw=0`. Rays use the exact timestamp-specific production transform `P=c_t+r[cos(theta)s13_sign,sin(theta)s30_sign]`. See `coordinate_contract.csv`.

## Locked boundary reconciliation

The input contains 1,561 physical ray boundaries plus 128 signed-axis boundaries = 1,689 paired physical brackets, and 73 separate guard-limited trajectories. VMAX=851 and VMIN=838. The four primary reported classes are VMAX/13 (429), VMAX/30 (422), VMIN/18 (435), and VMIN/33 (403). No fifth primary reported bus exists. `CO_BINDING_STATUS_NOT_RESOLVABLE_FROM_STORED_ARTIFACTS` is preserved; the historical source spells this `CO_BINDING_NOT_RESOLVABLE_FROM_STORED_ARTIFACTS`.

Guard truncations are certified-feasible endpoints, not physical boundaries and not evidence of unboundedness. They never enter classwise offset or fitted-normal calculations.

## Per-timestamp candidate physical facets

All 32 timestamps produced all four required classes (128 facets total); every certified production center is strictly inside all four oriented facets. Normals are the preregistered topology rows, negated for VMIN and positively unit-normalized without changing geometry. Each offset is the same-timestamp, same-class maximum support over certified inward endpoints. No fitted quantity changes a normal or offset. These are candidates, not certified inner facets.

The topology identities `c18,.=c13,.` and `c33,.=c30,.` are retained. Point counts, offsets, center slacks, and paired local radial bracket lengths are in `candidate_facets.csv`.

## Fitted-normal falsification diagnostic

The deterministic fit is unweighted orthogonal total least squares (2D PCA) per timestamp/class after removing exact duplicate coordinates. Inward endpoints alone are fitted; bracket lengths are reported, not converted to facet contraction. Across 128 fits the maximum raw orientation deviation is 3.08557529538 degrees at `2012-08-04 03:30:00` / `VMAX_BUS_30`. No materiality threshold was preregistered, so no success/failure label is invented. Raw results are in `fitted_normal_diagnostic.csv`.

## Candidate vertices and guard geometry

Each four-facet physical candidate yielded four actual offset-dependent intersections. Every vertex was transformed back to the exact centered/sign-normalized production-ray convention before angle/radius comparison. Guard caps were created only for the 73 stored guard trajectories as `cos(theta)z13+sin(theta)z30<=2`, then converted to unit-normal physical halfspaces. They are explicitly artificial guard caps.

For the longest-normalized-radius physical vertex or tied vertices, the nearest stored guard-direction deviations range from 0.16096506384 to 3.79209664732 degrees. Physical-candidate maximum/minimum edge-length ratios range from 1.35217295803 to 1.39244012378 across timestamps. Alignment remains a raw observation because no angular materiality threshold was preregistered. Pre-cap and post-cap vertices are in `candidate_vertex_guard_diagnostic.csv`; timestamp-dependent edge ratios, diagonal directions, and active guard caps are in `candidate_geometry_timestamp_summary.csv`; caps are in `guard_caps.csv`.

## Stored infeasible-endpoint exclusion screen

The screen evaluated all 1,689 paired converged-infeasible outward endpoints against the same-timestamp physical facets plus guard caps, without AC solves. At zero tolerance, 1552 endpoints are strictly inside and 32/32 timestamps contain at least one such point. The largest strict-inside margin is 195.335413607 kW at `2013-04-17 05:30:00`. Every uncontracted (`alpha=1`) timestamp candidate is therefore `CONDITIONAL_FAIL`: all 32 fail for any future `tau_membership_kw < 134.884426495` kW, and each row records its exact (larger or equal) failure bound. This is an artifact-level falsification of the uncontracted candidates, not a contradiction of the locked topology-normal policy. The dependent final-Coupled/Box construction stops at the predeclared contraction gate; no alpha is selected here.

The authoritative screen status remains `PENDING_PREREGISTERED_MEMBERSHIP_TOLERANCE`, as required. Excluding endpoints would still be only a necessary falsification screen, never certification. Details are in `infeasible_endpoint_exclusion_screen.csv` and its timestamp summary.

As a construction sanity check, 0 of 1,689 stored inward endpoints fall outside the full pre-contraction candidate (physical facets plus stored guard caps) beyond the generator's fixed 1e-8 kW enumeration tolerance. This check is not an AC-interior certification; rows are in `stored_inward_endpoint_containment_check.csv`.

## Contraction and future AC validation

The only allowed family is `P'=c_t+alpha(P-c_t)`, `0<alpha<=1`, under a predeclared descending schedule. There is no validation-driven alpha bisection and no manual facet tuning. Each selected level must first rerun the stored-outward-endpoint screen and then the full mandatory AC protocol. Mesh density, alpha levels, AC tolerance, and runtime/checkpoint/parallel settings remain unresolved until a limited benchmark conducted before substantive validation.

Mandatory future domains are all candidate vertices, deterministic physical-facet samples, guard-cap samples, deterministic interior samples, between-ray points, largest-gap oversampling, guard-sector oversampling, and later all four Main Safe Box corners.

## Main Safe Box policy

Only after the final Coupled DOE is fixed, solve continuously in absolute physical PCC coordinates:

`maximize (U13-L13)(U30-L30)`

subject to, for every final halfspace, `a13+ U13 + a13- L13 + a30+ U30 + a30- L30 <= b`. The implementation form maximizes the equivalent sum of log widths; no grid is allowed. Equal-area solutions use the complete hierarchy: minimize `L13`, then `L30`, then `U13`, then `U30`. Fixed optimization tolerances are 1e-8 kW absolute halfspace feasibility, 1e-10 relative primary objective, and 1e-8 kW lexicographic coordinate tolerance.

The Main Box is objective-independent and need contain neither the production center nor a no-control point. All four corners require later independent AC checks. The final timestamp-specific no-control absolute PCC point is derived later from the final accounting contract and tested afterward; zero command is not presumed to mean `(0,0)` PCC.

## Conditional monotonicity diagnostic

`m_conditional_box_candidates.csv` selects, per timestamp, the maximum-area componentwise-ordered pair of a stored certified VMIN inward point (lower diagonal) and VMAX inward point (upper diagonal), with the Main Box lexicographic hierarchy. This is `M_CONDITIONAL_BOX_CANDIDATE_DIAGNOSTIC_ONLY_NOT_AC_AUTHORITY`; Assumption (M) remains empirical on the sampled radial/axis skeleton and cannot enlarge the authoritative Coupled DOE.

## Unresolved execution parameters

See `unresolved_execution_parameters.csv`. In particular, membership tolerance and any fitted-normal materiality threshold are unresolved, so the raw diagnostics are not silently thresholded.

## Sources inspected

- `config/dso_vpp_production_probe_preregistration.toml`
- `src/benchmark/dso_vpp_production_probe.jl`
- `src/benchmark/dso_vpp_ac_map_stage0.jl`
- `results/dso_vpp_ac_map_pilot/absolute_pcc_coordinate_resolution/absolute_pcc_coordinate_resolution_report.md`
- `results/dso_vpp_ac_map_pilot/production_probe/run_manifest.toml`
- `results/dso_vpp_ac_map_pilot/production_probe/center_results.csv`
- `results/dso_vpp_ac_map_pilot/production_probe/signed_axis_results.csv`
- `results/dso_vpp_ac_map_pilot/production_probe/base_ray_results.csv`
- `results/dso_vpp_ac_map_pilot/production_probe/adaptive_ray_results.csv`
- `results/dso_vpp_ac_map_pilot/production_probe/boundary_endpoints.csv`
- `results/dso_vpp_ac_map_pilot/production_probe/evaluation_attempts.csv`
- `results/dso_vpp_ac_map_pilot/production_probe/unresolved_guard_cases.csv`
- `results/dso_vpp_ac_map_pilot/postproduction_result_audit/primary_binding_bus_audit.csv`
- `results/dso_vpp_ac_map_pilot/postproduction_result_audit/primary_binding_bus_summary.json`
- `results/dso_vpp_ac_map_pilot/postproduction_result_audit/ray_guard_truncation_audit.csv`
- `results/dso_vpp_ac_map_pilot/postproduction_result_audit/postproduction_result_audit_summary.json`
- `results/dso_vpp_ac_map_pilot/doe_preconstruction_artifact_refinement/sensitivity_topology_reconstruction.csv`
- `results/dso_vpp_ac_map_pilot/doe_preconstruction_artifact_refinement/boundary_input_reconciliation.csv`
- `results/dso_vpp_ac_map_pilot/doe_preconstruction_artifact_refinement/doe_preconstruction_artifact_refinement_summary.json`
- `results/dso_vpp_ac_map_pilot/monotonicity_falsification_screen/monotonicity_falsification_summary.json`
