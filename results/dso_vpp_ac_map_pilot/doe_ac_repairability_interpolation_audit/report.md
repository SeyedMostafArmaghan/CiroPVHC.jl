# Integrated Repairability & Interpolation Audit

Source commit: `5538146bc22386abe52601a2ab0129064335f855`

This audit is deterministic and artifact-only. It performed **zero** new AC
solves, replays, probes, or repairs. Every scientific input was read directly
from the source commit through Git object bytes, so working-tree line endings
cannot affect the result.

## Decision status

Overall status: `NO_AUDIT_BLOCKER_DETECTED`

Locked campaign classification (unchanged):

`MAIN_COUPLED_DOE_GEOMETRIC_CANDIDATE_FALSIFIED_BY_AC_COUNTEREXAMPLE`

Secondary diagnostic label: `PATTERN_CONSISTENT_WITH_CHORD_INTERPOLATION_ERROR`. This label, when present,
is diagnostic-only and never replaces the locked falsification classification.

## 1. Edge-to-cell repairability

- outer edges: 1689
- ownership inconsistencies: 0
- non-convex owner occurrences: 0
- nonpositive/undefined geometric caps: 0

For an edge with owner cell `C`, `cap_e` is the maximum inward support distance
from the edge facet to any vertex of `C`. Moving only that facet in parallel by
`0 <= d < cap_e` preserves convexity of the clipped cell; at `d = cap_e` the
remaining support becomes degenerate. This is a geometry-only limit. It is not
an AC retreat estimate.

Cap distribution (kW): min 872.060598912349, Q1 1569.21654987395,
median 2115.03047676857, Q3 3174.38627003284,
max 7148.88474391187. Counts below 0.5/1/2/5 kW are
0/0/
0/0.
These thresholds are descriptive only. `cap_e < 5 kW` is not a blocker; the
future real blocker is `d_e* > cap_e` after AC calibration.

## 2. Sampling density and deterministic holdout geometry

- zero-sample edges: 8
- low-sample edges (`n_e < 3`): 36
- median `n_e`: 11
- median/max `g_e`: 0.102674441638566 / 1

Gap accounting always includes synthetic endpoints `t=0` and `t=1`. H1 is
the interlaced angular mesh `0.25 + 0.5k` degrees intersected with each stored
edge; H2 is one sample at the midpoint of the current largest `t` gap. The
capability table reports exact new-sample counts and gap reductions. It makes
no probability or statistical-power claim.

## 3. Exact vertex/BOTH mapping

- outer vertices: 1689
- angular-hit outer vertices: 1554
- missed outer vertices: 135
- BOTH points: 1554
- BOTH non-outer-vertex coincidences: 0
- missed vertices with prior production AC evidence: 135

At the locked `1e-08 kW` tolerance, the hypothesis
`BOTH = outer vertices hit by the angular mesh` is
`CONFIRMED`. Downstream
statistics use the independently reconstructed true sets.

## 4. Signed boundary margins

Margins use `1.05 - Vmax` for VMAX and `Vmin - 0.90` for VMIN. CLASS_TRANSITION
points contribute to both channels. Selected medians (p.u.): VMAX13
-3.94373999990094e-06, VMAX30 -1.72999999992207e-06,
VMIN18 2.06476069999906e-05, VMIN33
1.76385599999773e-05. The complete min/Q1/median/Q3/max and
fractions below `1e-5`, `1e-4`, and `1e-3` are in the margin table. VMAX/VMIN
asymmetry is interpreted only in light of these stored-margin distributions;
no physical mechanism is claimed.

## 5-6. Within-edge interpolation and between-edge scaling

For each sufficiently sampled edge/channel, the stored endpoint margins are
used in the chord baseline and are never set to zero:

`r(t) = (1-t) r_a + t r_b + s_e t(1-t)`.

- sufficient fits: 1776
- fraction improving on the endpoint chord: 0.991448118586089
- median SSE improvement: 0.999989977263678
- median `|s_e|`: 6.47133096434308e-05 p.u.

Scaling tables compare signed and absolute `s_e` with edge length squared,
angular span, local turn-angle curvature proxies, and topology-derived
LinDistFlow normal sensitivity. The coefficient reconstruction is artifact-only
and diagnostic. It does not determine authoritative facet retreat. Association
is not mechanism proof.

## 7. Guard anomaly decomposition

- crossing: 0/
  1371 failures
- adjacent: 576 failures
- non-guard: 6484 failures

Edge length, angular span, `n_e`, `g_e`, fitted amplitude, and violation
statistics are reported side by side. **Association observed; causal mechanism
not established.**

## 8. Reflex/convex association

Endpoint-status combinations and boundary-point failure rates are reported as
an associational, falsifiable diagnostic. Convex-convex edges have
0 failures among
16253 mapped boundary
points. This is not a theorem.

## 9. Numerical/replay diagnostics and headroom concepts

The numerical table gives actual distributions of primary-vs-replay voltage
difference, maximum residual, primary/replay iterations, and runtime for all
validation attempts, angular-boundary validation points, all production
attempts, and production official SAFE endpoints.

`h_design` means conservative design headroom used later to construct a repair.
Assessment may later validate the original AC limits and/or a headroom claim,
depending on preregistration. This audit sets no `h`, and it infers no mandatory
headroom floor from replay-match tolerance.

## 10. Runtime attribution and checkpoint redesign

- end-to-end wall: 393.033326 s
- attributable measured components: 218.9383157 s
- unattributed operational resume/uninstrumented residual: 174.0950103 s
- retained substantive AC: 7.70709970000016 s
- checkpoint/I/O: 193.0670898 s
- checkpoint/I/O to substantive-AC ratio: 25.0505504424701x

The last-process `final_resume_wall_seconds` is non-additive and cannot be
subtracted again. Committed source establishes 500 operationally reexecuted AC
calls, multiple resume-compatible script hashes, and timers around evaluation
and checkpoint serialization, but it does not separately time process startup,
resume orchestration, lost pre-checkpoint work, or all work between those
scopes. The 174.0950103 s residual therefore cannot be apportioned
further without guessing.

Deterministic future recommendation: write immutable append-only result shards
with stable IDs; checkpoint only a compact cursor and solver state; seal one
shard per completed timestamp; if within-timestamp recovery is required, use
fixed 2,000-row chunks rather than serializing the accumulated campaign every
250 points; concatenate and hash once in final postprocessing. AC compute is
cheap here, while repeated growing-state I/O is measured as expensive.

## 11-12. Holdout capability and cap distribution

The edge-level H1/H2 capability table resolves geometric information gain
without stochastic claims. The cap summary is stratified by boundary class,
guard relation, and normal-sign category. Neither table preregisters repair or
changes official validation classification.

## Locked evidence and policy

Validation commit `4612cac` remains locked at 65,494 points: 56,074 feasible,
9,420 converged-infeasible, zero unresolved, and 128/128 controls passing. All
9,420 failures are VMAX. Interpretation commit `5538146` remains locked at
7,060 direct 0.5-degree angular failures plus 2,360 cell-edge points coincident
with the outer boundary, zero strict-interior failures, 9,156 infeasible points
inside the residual fallback, and 1,554 BOTH points reproducing prior feasible
production RAY points.

Independent policy conclusion:

`SAFE_BOX_EXTRACTION_STRICTLY_AFTER_FINAL_REPAIRED_COUPLED_DOE_FREEZE`

Future paper metrics should include repair area loss and hosting-capacity loss.
Neither is computed here.
