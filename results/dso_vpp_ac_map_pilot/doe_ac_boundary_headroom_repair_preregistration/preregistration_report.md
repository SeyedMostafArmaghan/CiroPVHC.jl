# AC Boundary-Headroom Repair Study Preregistration

Source commit: `ba88f54f52f7bcd03df2466ce69dff2b9b1c538b`

Status: `PREREGISTERED_NOT_EXECUTED`

This package locks the future repair study. It performs no AC calibration,
solve, replay, probe, or repair.

## BOUNDARY_HEADROOM_POLICY

The evidence envelope is the maximum of:

- observed negative signed boundary margin: 0.000142248109999965 p.u.;
- diagnostic predicted-midpoint deficit: 0.000142436171381289 p.u.;
- maximum stored primary/replay voltage difference: 1.49313894582e-12 p.u.

The envelope is rounded upward on the committed production voltage-termination
quantum `1e-05` p.u., giving:

`h_design = 0.00015000 p.u.`

The symmetric design limits are `Vmin >= 0.90015000`
and `Vmax <= 1.04985000`. Original AC limits
`[0.90, 1.05]` remain a separate authoritative assessment track. Replay
tolerance is not treated as a mandatory headroom floor.

## Repair geometry

All 1689 outer facets are eligible for symmetric headroom calibration.
Each facet is tightened in its **original inward normal** using
`n_in · (x-a) >= d_e`. Componentwise projection is forbidden, including the
65 mixed-sign normals. Every edge has one committed convex
owner cell.

`cap_e` is only a single-facet geometry bound. It neither sets nor predicts
retreat. `d_i*` and `d_e*` remain `FUTURE_AC_ONLY`. Combined cells must be
rebuilt from all tightened halfspaces and remain convex and nondegenerate.

## Calibration population

- committed failure edges: 655
- corrected low-sample edges: 41 (not the unconfirmed prompt expectation 44)
- deterministic enrichment coordinates: 130
- locked interior memberships: 22315
- vertex combined-geometry verification memberships: 1689
- total calibration memberships: 24004

Low-sample enrichment occurs before any future AC calibration. Endpoint
vertices verify combined geometry; interior memberships drive per-edge
`d_i*`/`d_e*` search.

## Search, re-entry, and assessment

Anchor-search uses diagnostic predictions only to order calls. Every accepted
retreat is AC verified in the future. Bracketing, bisection, verify-escalate,
and a local re-entry stencil use the locked 0.25 kW
resolution. A detected pass-to-fail transition blocks repair freeze. This is a
local diagnostic and not a global monotonicity theorem.

## Independent holdout

H1 is the post-repair interlaced `0.25 + 0.5k` degree mesh. H2 is targeted to
the largest remaining gap on H1-redundant edges. Pre-repair capability implies
23040 H1 candidates and 120 H2-target edges; final
counts are generated only from frozen repaired geometry.

Any holdout coordinate within componentwise `1e-08 kW` of a
calibration coordinate is rejected before AC evaluation and replaced by the
next deterministic eligible gap midpoint. Required calibration/holdout overlap
is exactly zero. Holdout outcomes never tune repair.

## Calls and checkpoints

Hard cap: 302303 primary logical AC calls and 3024
retry calls. Wall time is not a budget. Results use append-only immutable
2000-row shards, compact cursor/state checkpoints, and one
final concatenate/hash pass.

## Locked policy

`SAFE_BOX_EXTRACTION_STRICTLY_AFTER_FINAL_REPAIRED_COUPLED_DOE_FREEZE`

Future paper metrics must report repair area loss and hosting-capacity loss;
neither is computed by this preregistration.
