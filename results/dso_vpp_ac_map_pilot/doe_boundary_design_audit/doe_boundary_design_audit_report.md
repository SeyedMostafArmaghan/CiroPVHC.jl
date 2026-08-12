# DOE boundary-extraction design audit

Primary classification: **`CENTERED_RADIAL_RECOMMENDED_WITH_TARGETED_AXIS_EVIDENCE`**.

## Executive decision

The next production architecture should be `CENTERED_RADIAL` with a deterministic signed-axis midpoint center, per-timestamp AC verification/backtracking, transition auditing, normalized full-circle directions, and hierarchical balanced timestamps. The production probe is not yet ready to run: the true signed absolute axes remain incomplete and must be the first preregistered stage. Support-function OPF is not selected because the current fast evaluator is a fixed-injection power flow and the existing AC-OPF model is not a signed two-interface support solver.

The temporal strategy should be `HIERARCHICAL_CRITICAL_TIMESTAMP_PROBE`: eight dense and 24 sparse balanced critical timestamps, not a dense replay of the existing export-biased 96-window and not all 52,608 intervals.

## Scientific locks

- Final coordinates are `P_PCC_abs`; at the audited point `P13_abs=777.7133428167988+P13_command` and `P30_abs=P30_command`.
- `REFERENCE_PV_850_KW_IS_TVPP_OWNED` remains fixed.
- `UNITY_POWER_FACTOR_INTERFACE_POLICY` is final for the main paper: `Q_PCC=0`. Non-unity-PF interface operation and reactive flexibility are outside the main model and belong to limitations/future sensitivity analysis. No nonzero `kappa` is introduced and no Phase-B/analytical result is regenerated.
- `A_t^AC` depends only on network background, topology/limits, and the fixed interface policy. PV, EV, BESS, and optimized `H` belong to `F_TVPP(H)` and must not define the network boundary. The final relation is `P_PCC_abs in F_TVPP(H) intersection E_DOE`, with `E_DOE subset A_t^AC`.

## Absolute-origin correction

The previous unresolved classification is corrected additively to **`ABSOLUTE_ORIGIN_FEASIBLE_FROM_EXISTING_S0_EVIDENCE`**. At `P_PCC_abs=(0,0)`, command is `(-777.7133428167988,0)`, so the TVPP-owned reference PV is removed and the state is exactly the zero-DER/zero-TVPP S0 network with passive DSO loads retained.

The committed `results/s0_full_period_baseline/s0_interval_metrics.csv` explicitly contains `2012-10-15 13:00:00` at root voltage 1.00 p.u.: solver `ALMOST_OPTIMAL`, numerical validation `true`, operational voltage feasible `true`, `Vmin=0.98730595284058` p.u. at bus 18, and `Vmax=1.0` p.u. This gives a 0.08730595284058 p.u. lower-voltage margin to the pilot 0.90 limit (and 0.03730595284058 p.u. to the S0 0.95 operational limit), plus 0.05 p.u. upper margin to 1.05.

The three-year global S0 minimum `0.913090479358158` p.u. is **not** used as the audited 13:00 voltage; it occurs at `2011-02-05 18:00:00`.

## Existing absolute-axis coverage

The Phase-B P13 command scan is already on the true physical segment `P30_abs=0`. At the audited timestamp it includes 17 fixed AC evaluations from command 0 through 928.75 kW, translating to `P13_abs=777.7133428167988` through `1706.4633428167988` kW. Ordered Phase-B evidence supports the safe interval from the translated baseline through `1459.0838872507989` kW; the refined violating endpoint is `1459.3106328557988` kW. The origin is separately feasible from S0, but the open connection `0<P13_abs<777.7133428167988` has not been explicitly scanned.

The P30 command scan lies on `P13_abs=777.7133428167988`, not on the true P30 axis. Its safe point `(777.7133428167988,1739.59228516000)` is a translated command-axis point, not a `P13_abs=0` intercept.

Minimum targeted new evidence is therefore: (1) connect the positive P13 half-axis from origin to the translated baseline and reuse its upper bracket only if the ordered-transition audit passes; (2) scan/refine the negative P13 half-axis; (3) scan/refine the true positive P30 half-axis using command `(-777.7133428167988,P30_abs)`; and (4) scan/refine the true negative P30 half-axis. These are preregistered future evaluations and were not run here.

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
| solver nonconvergence regions in tested Phase-B domain | `CONTRADICTED` | 0 of 3691 evaluations nonconverged |
| absence of nonconvergence outside tested domain | `NOT_PROVEN` | import/mixed quadrants are untested |

Radial and support representations can encode similar sampled boundary information only if the relevant component is convex or approximately convex. No such AC conclusion is made. A more elegant halfspace representation does not create more information than the AC evaluations behind it.

## Timestamp-selection audit

`select_pilot_indices` selects two literal consecutive dates, not 96 independently selected critical timestamps. The first day is export-stress rank 1; the adjacent day is rank 52. The 96 intervals cover load multipliers `0.114754-0.307561`; the maximum is only the 81.84th full-series percentile, with 0 top-decile-load intervals. PV reaches `0.928221` (the 99.69th percentile) and 23 intervals are top-decile PV. Although 23 night intervals are present, there are 0 high-load/low-PV import-stress intervals. Both days are spring and provide no seasonal coverage.

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

The nominal budget is `12192` fixed AC evaluations: 2,560 signed-axis-prepass evaluations, 32 center checks, and 9,600 centered-ray evaluations. The hard adaptive budget is `14112`. At the observed Phase-B orchestration wall rate `4.1587 ms/evaluation`, nominal raw evaluator time is `50.7 s`; allow 2-5 minutes end-to-end. Use eight one-thread workers, serial within each ray and parallel across rays/timestamps. Observed peak evaluator-process RSS is about 743 MiB, so expected eight-worker RAM is below 8 GB and safe on the 12-CPU/32-GB VM. The 31-core/126-GB cluster would shorten an already small compute kernel but is not materially needed. Raw output should be about 5 MB and remain below a 15 MB checkpoint/summary budget.

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
