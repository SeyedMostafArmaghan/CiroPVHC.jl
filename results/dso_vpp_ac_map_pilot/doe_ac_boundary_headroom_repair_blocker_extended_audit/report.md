# Final zero-AC structural and provenance blocker audit

## Scope

This deterministic audit is `ARTIFACT_ONLY_ZERO_AC_PYTHON_STANDARD_LIBRARY`. It reads immutable committed artifacts and does not execute Julia, a solver, calibration, replay, H1/H2, hosting-capacity analysis, or Safe-Box analysis.

The generator requires the expected branch and requires the audit base commit to be an ancestor of `HEAD`; it does not require exact `HEAD` equality. Scientific inputs are always read from fixed commits with `git show`, so a descendant audit commit can reproduce the same bytes.

## Hardening results

- Both escalation baselines have exactly one same-timestamp, componentwise coordinate match within `1e-8 kW` to committed historical validation points.
- Stop classification follows the executed source control: 13 anchor searches reach the strict cap precheck before their call budget; 2 escalation searches exhaust eight extra calls while their next candidate remains strictly below `cap_e`.
- The classifier supports anchor cap-precheck, anchor budget, escalation budget, unresolved stops, and explicit evidence gaps before bisection. No blocker was silently mapped from an unsupported path.
- The supported resolution statement is `NO_PASS_FAIL_BRACKET_OR_RESOLUTION_REFINEMENT_EVENT_OBSERVED`. An unsampled narrow pass is not ruled out.
- Original-limit evidence is reported as sampled pass/fail bounds. Every row sets `continuous_crossing_location_claim=false`.
- `generation_assertion_summary.csv` identifies generator assertions, provenance assertions, regression references, and the externally required determinism check. It is not presented as independent validation.

## Blocking-membership results

- Blocking memberships: `15` (not all memberships of the affected edges).
- Target status: `15 DESIGN_HEADROOM / 0 ORIGINAL_LIMIT`.
- Stop mechanism: `13 GEOMETRIC_CAP_PRECHECK_LIMITED / 2 SEARCH_BUDGET_LIMITED`.
- Observed pass/fail brackets: `0`; bisection or resolution-refinement events: `0`.
- Every membership has at least one sampled positive-`d` original-limit failure: `4 VMIN / 11 VMAX`.
- First sampled original-limit failure is at or before 2 kW for `13` memberships. This is a sample-location count, not a continuous crossing claim.

## Edge-ID concentration and topology

Blocking-membership concentration is `E0019=10, E0044=2, E0021=1, E0045=1, E0046=1`. This is descriptive only: edge numbers are not treated as independent samples, no effective sample size is computed, and no uniform-null significance test is used.

Committed endpoint geometry shows which unique edge IDs share a facet endpoint; `blocker_edge_geometric_relationships.csv` reports that separately. The only timestamp with two simultaneous blockers is tested directly rather than inferred from ID adjacency.

## Normal orientation and full-cell location

All `15/15` stored normals are orientation-consistent with `n_in·(x-a)>=0`, using the arithmetic mean of the committed CCW owner-cell vertices as a witness and independently verifying each witness is strict cell interior at the executed `1e-7 kW` geometry tolerance.

Positive sampled-point full-cell classifications are `{"OUTSIDE_CELL": 190}`. Original-limit-failing sampled-point classifications are `{"OUTSIDE_CELL": 183}`.

No sampled original-limit failure lies in the strict interior of any committed full cell, so this audit does not add a strict-cell-interior counterexample to the earlier audit's zero count. The earlier `9,420` failures were `7,060` direct angular-boundary points plus `2,360` cell-mesh edge points, not strict-interior counterexamples.

All positive blocker samples lie outside every committed full cell; their owner-cell diagnostics identify violation of another facet immediately after leaving the source vertex/edge neighborhood. With all stored normals oriented inward relative to the registered facet, this supports Case 3: the registered-normal path leaves the full cell through another facet. It does not support a stored-normal sign defect or a strict-interior geometry/AC mismatch.

Where a point belongs to more than one cell within tolerance, all containing cells are retained. Owner-cell slack, active facets, violated facets, and strict-interior cell IDs are reported per sample.

## Local directional fact and baseline slack

At all 15 blocking memberships, the sampled positive registered-normal direction is locally adverse to the already-binding design-margin channel. This is an observed local fact, not a global mechanism proof.

Binding original-limit slack at `d=0` has min/median/max `8.46521089892249e-08/2.51637899006951e-06/8.92762000015423e-06` p.u. Each baseline slack is below the requested `1.5e-4` p.u. design headroom, so these are boundary-like blocking memberships with insufficient initial slack for the requested design headroom, not independent physical failures at `d=0`.

## Limiting calibration ID audit

All `1689` edge rows are comparable through the executed anchor/escalation state transitions. There are `2` mismatches, both blocker escalation rows and both numeric offset `+20`. The repeated offset is suspicious provenance evidence, not proof of a deterministic indexing bug.

Committed `scripts/src/test` search finds schema declaration and producer-write references, but no downstream decision read. Thus the demonstrated code role is summary output; impact outside that search scope remains unresolved.

## Unsampled reverse-direction hypothesis

`reverse_direction_linear_hypothesis.csv` contains `15` first-order estimates using the `d=0` and first positive-`d` binding-margin samples. Every row is labeled `UNSAMPLED_REVERSE_DIRECTION_LINEAR_EXTRAPOLATION` and `ac_validated=false`. No negative-`d` AC call was made, and feasibility is not claimed.

## Validation and epistemic boundary

A clean byte-identical rerun is an external determinism check only; it does not establish scientific validity. Manifest, payload, generator, index, source-artifact, protected-file, and scope checks are performed separately from generation.

This audit does not claim `TRUE_DIRECTIONAL_LIMITATION`, global monotonicity, a continuous crossing location, negative-direction AC feasibility, full-edge feasibility from one membership, blocker independence, `n_eff=2`, statistical significance, resolution failure ruled out, or an indexing bug proved by two `+20` offsets.

## Output map

- `blocker_trajectory_audit.csv`: one row per blocking membership, including baseline slack and stop provenance.
- `trajectory_observations.csv`: every reconstructed/observed blocker trajectory sample.
- `original_limit_sample_bounds.csv`: last sampled pass, first sampled fail, and unsampled interval bounds.
- `blocker_edge_id_concentration.csv`: descriptive blocker distribution by edge ID.
- `blocker_edge_geometric_relationships.csv`: endpoint-grounded relationships among unique blocker edge IDs.
- `normal_orientation_audit.csv`: facet point, interior witness, signed orientation, convention, and tolerance.
- `failing_point_full_cell_membership.csv`: every positive sample located against all committed full cells.
- `limiting_calibration_id_global_audit.csv`: global recorded-vs-attempt-derived comparison.
- `limiting_calibration_id_offset_summary.csv`: mismatch/match aggregation by population, phase, status, and offset.
- `limiting_calibration_id_downstream_use.csv`: deterministic committed-code search results.
- `reverse_direction_linear_hypothesis.csv`: unvalidated first-order reverse-direction hypotheses.
- `generation_assertion_summary.csv`: epistemically labeled generation assertions and regression references.
- `implementation_semantics_checks.csv`: exact executed-source logic matched by the generator.
- `source_artifact_inventory.csv`, `hashes.sha256`, and `manifest.json`: immutable provenance and integrity metadata.
