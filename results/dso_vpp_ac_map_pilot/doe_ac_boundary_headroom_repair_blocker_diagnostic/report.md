# Zero-AC root-cause diagnostic audit

## Scope and provenance

This audit reads committed objects from calibration commit `82ccd0f20693c90c39904f6016d85cf62433f4f0` and locked preregistration `fc15fbf7bf93ca89c2ab4a45145f937abbc70f63`. It uses Python standard-library CSV/JSON processing only and executes no Julia process, solver, replay, calibration, or AC power-flow call.

The authoritative artifact paths, commits, record counts, byte sizes, and SHA-256 hashes are in `source_artifact_inventory.csv`. The primary outcome source has 1,689 edge rows; the trajectory source has 51,773 attempt rows; the consolidated point source has 13,465 rows.

A blocked edge is keyed by `(timestamp, edge_id)`. Edge IDs repeat across timestamps, so `edge_id` alone is not a unique campaign key.

## Result

All 15 blockers receive the preliminary classification `POSSIBLE_TRUE_OPERATOR_LIMITATION`, where *operator* means the preregistered positive scalar parallel-retreat operator along the original inward normal. It does not mean that the physical grid has been proved infeasible.

| candidate explanation | artifact-only assessment |
|---|---|
| Algorithmic | No solver or replay failure is present. Two blocking searches stop after the locked verify-escalation allowance; 13 stop when the next doubling step would exceed the geometry cap. Those mechanics leave untested intervals, but every observed binding margin worsens with retreat, so the artifacts do not identify the call ceilings as the primary mechanism. |
| Grid resolution | Not supported by the observed sequences. No blocker has a PASS/FAIL bracket, no blocking trajectory reaches the 0.25 kW bisection stage, and no joint design-limit pass is observed. |
| Cap-limited | Not supported as the primary mechanism. No cap is reached; `d_max/cap` ranges from 0.0115788301204009 to 0.844341294675652 (median 0.66424475325427). The margin moves away from feasibility rather than toward it. |
| Scalar operator/direction limitation | Best-supported preliminary explanation: 4 VMIN-bound and 11 VMAX-bound trajectories move the binding channel monotonically in the wrong direction while improving the opposite channel. |
| Unresolved evidence | No unresolved solver status or retry occurs in the 15 blocking trajectories. Global behavior between or beyond sampled points remains unproved. |

## Trajectory mechanism

Violation magnitude decreases monotonically in 0 of 15 blocking trajectories. In all 15 trajectories the binding-channel margin worsens monotonically and the opposite voltage-channel margin improves monotonically. There is no joint headroom pass and no `last_pass_retreat_kw` for any blocker.

All 13 anchor blockers are observed from `d=0` as original-limit passes but design-headroom failures. The two verify-escalation blockers are first observed after a common retreat selected from another membership (4.75 kW for the VMIN case and 2.75 kW for the VMAX case); both already fail the corresponding original limit, and their blocking memberships have no calibration-attempt observation at `d=0`. In every case, further positive retreat worsens the binding voltage channel. This is consistent with fundamental inadequacy of the registered one-sided scalar retreat for these observed points. It is strong directional evidence, not a global monotonicity proof and not proof that another operator would work.

Blocking search phases: `13` anchor searches and `2` verify-escalation searches.

## Crossing control associations

The crossing control contains exactly 64 rows: 15 blocked and 49 successful. Successful crossing retreats have min/median/max `d_e` of 0/2.75/1440.5 kW.

| characteristic | blocked | successful crossing controls | campaign denominator |
|---|---:|---:|---:|
| mixed-sign | 15/15 | 49/49 | 65/1689 |
| transition | 15/15 | 49/49 | 128/1689 |
| crossing | 15/15 | 49/49 | 64/1689 |

Thus all blockers are mixed-sign, transition, crossing edges, and the crossing-edge blocker rate is 23.438%. However, all 49 successful crossing controls share the same mixed-sign and transition flags. These are associations and do not establish causality or distinguish blockers within the crossing subset.

## Timestamp clustering

The 15 blockers occur at 14 timestamps. The maximum timestamp cluster is 2, at `2012-10-15 13:00:00`; every other blocked timestamp contributes one edge. The artifacts therefore show no broad same-timestamp pile-up.

## Minimum next scientific action

The minimum discriminating next action is a separately preregistered targeted study of the 15 exact `(timestamp, edge_id, calibration_id)` blocking trajectories that tests whether any admissible scalar retreat has a joint VMIN/VMAX pass and explicitly covers the currently untested interval before each cap. That action would distinguish a one-sided operator limitation from a search-coverage miss. It is not performed or designed here, and this audit proposes no repair-policy or geometry change.

## Output guide

- `blocked_edge_root_cause.csv`: one row per blocker and preliminary classification.
- `blocked_edge_trajectory_summary.csv`: observed blocking-search trajectory summaries.
- `blocked_edge_cap_analysis.csv`: tested retreat relative to the locked cap.
- `crossing_control_comparison.csv`: 15 blocked and 49 successful crossing-edge controls.
- `blocked_edge_timestamp_cluster.csv`: deterministic timestamp aggregation.
- `h_design_retreat_diagnostic.md`: safety-headroom versus geometric-difficulty interpretation.
- `source_artifact_inventory.csv`: exact committed source inventory.
- `audit_validation_checks.csv`: source and invariant checks.
