# Zero-AC Signed-Interpolation Addendum

Source commit: `07a31791134aec7e941e7674953e887edd697d3d`

This addendum is deterministic and artifact-only. It performs zero new AC
calibration, solve, replay, probing, or repair.

## Gate result

`NO_ADDENDUM_BLOCKER`

The locked campaign classification remains:

`MAIN_COUPLED_DOE_GEOMETRIC_CANDIDATE_FALSIFIED_BY_AC_COUNTEREXAMPLE`

## Signed interpolation population

The committed audit contains 1817 edge-by-margin-channel rows:

- sufficient fits (`n_interior >= 3`): 1776
- insufficient rows: 41
- exact unique insufficient edges: 41

The prompt expectation of 44 low-sample edges is not reproduced. Direct
reconstruction gives **41**, with one margin channel per edge. This is a
resolved input-count correction, not a blocker: the true set is complete and
the enrichment algorithm is defined over it.

Signed `s_e` is reported by guard relation × margin channel × endpoint
convex/reflex combination, including positive/negative counts and full
quantiles. Endpoint margins are retained as observed; they are never set to
zero. The predicted midpoint margin is

`r_hat(0.5) = 0.5*r_a + 0.5*r_b + 0.25*s_e`.

Across the 1776 sufficient fits, signed `s_e` has median
2.8540389522155e-06 p.u. and range
[-0.00137010050112312, 0.00626479516293093] p.u. These are diagnostic
associations, not mechanism proof.

## Failure-edge closure

All 9420 committed failures map to an outer edge within the locked
`1e-08 kW` tolerance. The exact number of unique edges carrying at
least one failure is **655**. All mapped failures remain
VMAX. Detailed direct-angular versus cell-edge counts are provided per edge.

`cap_e` is retained only as a geometry feasibility bound. It is not used as the
primary falsification path and it is not an AC retreat estimate.

## Deterministic low-sample enrichment

For each of the 41 true low-sample edges, start from its distinct
interior fractions and repeatedly add the midpoint of the largest current gap
in `{0, samples, 1}`; ties choose the smallest left endpoint. Stop only when:

- at least 3 interior calibration points exist; and
- `g_e <= 0.25`.

This creates 130 new coordinates. After enrichment, the
minimum interior count is 3
and the maximum gap is 0.25.
Coordinates are construction-only and have not been AC evaluated.

## Phase-2 gate

No scientific blocker was found. The exact corrected low-sample set and its
deterministic enrichment may therefore be consumed by the Repair
Preregistration. No calibration is authorized by this addendum.
