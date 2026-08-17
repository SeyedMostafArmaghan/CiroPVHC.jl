# AC Interior Validation Interpretation Audit

Source validation commit: `4612cac821f63c9bdcc838f4cc097387dfd617ad`

This audit is deterministic and artifact-only. It performs no AC solve,
replay, probing, or repair.

## A. Pocket fallback semantic closure

`inside_pocket_fallback=true` denotes the residual region obtained by
excluding the strict interiors of the convex-hulled VMAX pockets from the
already-admissible Main validation domain, using the locked coordinate
tolerance of `1e-08 kW`.

The stored membership was independently reconstructed from pocket halfspaces
with zero mismatches.

- inside residual fallback: 64923
- AC-feasible inside: 55767
- AC-infeasible inside: 9156
- strict pocket-interior / outside fallback: 571
- AC-infeasible outside: 264

Therefore the compact pocket fallback is itself falsified by observed AC
counterexamples and must not be described as AC-safe or AC-certified.

## B. BOTH provenance closure

All 1554 `BOTH` points are deduplicated overlaps between angular-boundary
and cell-barycentric provenance. All are `CELL_VERTEX`, all lie on the outer
polygon boundary, and all reconverged feasible in the validation campaign.

Every one of the 1554 points has exactly one coordinate-matched committed
production `RAY` evaluation within `1e-08 kW`; all were
`CONVERGED_FEASIBLE`. Phase split:

- bisection: 1552
- coarse sweep: 2

Locked interpretation:

`PRODUCTION_BOUNDARY_POINT_REPRODUCTION_1554_OF_1554_FEASIBLE`

## C. Failure localization

All 9420 converged AC counterexamples lie on the outer polygon
boundary within the locked numerical tolerance.

- direct angular-boundary failures: 7060
- cell-mesh edge failures: 2360
- strict cell-interior failures: 0
- maximum cell-edge failure distance to outer boundary:
  9.71340767287e-13 kW

The wording must remain precise: the first 7,060 are direct 0.5-degree angular
samples; the other 2,360 are cell-mesh edge points geometrically coincident
with the same outer polygon boundary.

This is numerical/tolerance-level boundary coincidence, not an analytic
continuous proof.

## D. Guard provenance closure

Polygon edge relations:

- crossing edges: 64
- adjacent edges: 128
- touching edges: 0

All crossing edges are class transitions. The adjacent-edge class split is
32 each for VMAX13, VMAX30, VMIN18, and VMIN33.

For boundary-only validation points:

- crossing-labelled points: 1371
- crossing failures: 0
- adjacent failures: 576
- non-guard failures: 6484

Adjacent failures are 288 VMAX13 and 288 VMAX30.

Violation magnitude among angular-boundary-provenance failures:

- guard-adjacent median: 4.61135857205e-05 p.u.
- guard-adjacent maximum: 0.000142248109239 p.u.
- non-guard median: 5.08027073676e-06 p.u.
- non-guard maximum: 4.33223324872e-05 p.u.

This establishes a guard-adjacent VMAX association only. It does not establish
a causal guard mechanism.

## Scientific caveats

- The finite mesh is not a proof of continuous AC safety.
- The pocket fallback is falsified and is not AC-certified.
- VMAX concentration does not establish a physical loss-induced mechanism.
- Boundary coincidence is asserted only at the locked numerical tolerance.
- Guard adjacency is an observed association, not a causal explanation.
- Raw-byte checkpoint compatibility across LF/CRLF working trees is not claimed.
