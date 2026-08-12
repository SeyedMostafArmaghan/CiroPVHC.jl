# Pre-execution Amendment 4 - DOE boundary-extraction design

This amendment is additive and does not alter the numerical content of S0, S1, Phase B, the analytical LinDistFlow audit, operating-point provenance, architecture, or coordinate-resolution artifacts.

## Locked model semantics

- Coordinates: absolute physical interface active power `P_PCC_abs`, export positive and import negative.
- Interface reactive policy: `UNITY_POWER_FACTOR_INTERFACE_POLICY`, hence `Q_PCC=0`.
- Passive case33bw loads are DSO background and are excluded from `P_PCC_abs`.
- The 850 kW reference PV is TVPP-owned; at 2012-10-15 13:00:00, its fixed contribution is `777.7133428167988 kW`.
- `A_t^AC` is network acceptance only. PV/EV/BESS capability and optimized `H` belong only to `F_TVPP(H)`. The coordination relation remains `P_PCC_abs in F_TVPP(H) intersection E_DOE`, with `E_DOE subset A_t^AC`.
- Non-unity-PF operation and reactive flexibility are outside the main model and are limitations/future sensitivity topics. No `kappa != 0` is introduced.

## Selected production architecture

`CENTERED_RADIAL` is selected, conditional on the targeted signed-axis prepass. For each timestamp, obtain true positive/negative half-axis intervals for P13 and P30 using only network acceptance. Let `c0` be the componentwise midpoint of those intervals. Evaluate `c0`. If it is not accepted, test `c_j=2^(-j)c0`, `j=1,...,20`, toward the accepted physical origin and select the first accepted point. Failure to obtain a non-origin interior center stops the timestamp for method revision; optimized resource capacity never enters center selection.

Directions are uniform in coordinates normalized by the two signed-axis half-widths, not by `theta_star_command` or `Lambda_lin_command`. Dense cases use 24 base directed rays at 15-degree spacing over the full 0-360 degrees. Sparse cases use eight cardinal/diagonal rays at 45-degree spacing. No quadrant symmetry is assumed.

Dense adaptive refinement inserts an angular midpoint when adjacent normalized radii differ by more than 10%, their binding-bus sets differ, or the evaluated midpoint differs by more than 2% from secant interpolation. Recursion stops at 3.75 degrees or 48 directed rays. The command-space `theta_star_command=76.03090274387165 deg` remains a diagnostic and is not a grid center or privileged absolute-PCC angle.

Each ray must show exactly one accepted interval from the verified center followed by one accepted-to-infeasible transition. Coarse samples are retained. Reverse transitions, multiple feasible intervals, or unresolved points stop that timestamp and trigger a preregistered method revision; the outermost point is never selected post hoc.

## Selected temporal architecture

`HIERARCHICAL_CRITICAL_TIMESTAMP_PROBE` is selected with 32 unique timestamps: eight dense and 24 sparse. Partition the full profile into DJF/MAM/JJA/SON and two network-background stress modes: export stress `pv_profile/max(load_multiplier,0.05)` and import stress `load_multiplier` subject to `pv_profile<=1e-4`. Within each of the eight season-mode strata, rank by score descending and timestamp ascending, enforce at least 24 hours between selected timestamps, and take four. The first is dense and the next three are sparse. Deduplicate across strata and fill from the next eligible rank under the same rule. `2012-10-15 13:00:00` must be the dense spring-export case if it remains the stratum leader.

The old 96 timestamps are `USE_ONLY_FOR_EXPORT_PILOT`; they are not substituted for this balanced set. Dense DOE reconstruction over all 52,608 intervals is not planned. The final optimized TVPP schedules will instead receive a separate full 52,608-interval AC replay.

## Search budget and stopping rules

- Four signed true-axis searches at every selected timestamp.
- Eight dense timestamps: 24 base plus expected 12 adaptive directions, hard cap 48.
- Twenty-four sparse timestamps: eight directions.
- Calibration: 20 fixed-injection AC evaluations per search (observed mean 19.224).
- Nominal budget: 12192 AC evaluations; hard adaptive budget: 14112.
- Boundary stopping: bracket width <=1.0 kW and both endpoint voltage distances <=1e-5 p.u.; replay voltage agreement <=2e-5 p.u.; residual <=1e-5; maximum 60 refinements.
- Nonconvergence or replay failure is `UNRESOLVED`, never physical infeasibility. Retry deterministically from flat and nearest accepted neighbor starts, then checkpoint an unresolved ray without interpolation.
- Eight single-thread worker processes on the 12-CPU/32-GB VM; serial search within a ray, parallel rays/timestamps, deterministic merge order.
- Atomic checkpoints after every direction and timestamp; retain raw evaluations, transition inventory, bounds, unresolved queue, resume index, and manifest.

At the observed orchestration rate (4.1587 ms/evaluation), the nominal raw evaluator time is about 50.7 seconds. The operational budget is 2-5 minutes including Julia/process startup, validation, checkpoints, and output. Expected RAM is below 8 GB with eight workers; the 31-core/126-GB cluster is not materially necessary for this fixed-evaluator design.

No production probe, support-function OPF, DOE construction, EV/BESS model, centralized optimization, or full-period optimization is authorized by this amendment.
