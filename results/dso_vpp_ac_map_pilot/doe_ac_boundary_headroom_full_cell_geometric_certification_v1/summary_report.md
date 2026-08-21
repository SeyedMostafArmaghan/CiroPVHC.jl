# Full-cell geometric certification v1

## Scope and result

This is a deterministic `IMMUTABLE_COMMITTED_INPUTS_ZERO_AC_FULL_CELL_LINE_CERTIFICATION` artifact over all `24004` locked probe memberships.
It reads only immutable committed geometry/provenance objects. It performs no AC power flow, optimization, DOE construction, cell-partition modification, direction change, or candidate-geometry freeze.

Geometrically certified memberships: `23640`. Every certification restricts only movement length along the registered inward direction.

## Classification counts

- `INPUT_PROVENANCE_MISMATCH`: `0`
- `CELL_GEOMETRY_INVALID`: `0`
- `REGISTERED_FACET_OWNERSHIP_MISMATCH`: `0`
- `SOURCE_POINT_OUTSIDE_OWNER_CELL`: `0`
- `FULL_CELL_TOLERANCE_AMBIGUITY`: `0`
- `NO_POSITIVE_FULL_CELL_MOVEMENT`: `357`
- `FULL_CELL_CAP_BELOW_GRID`: `7`
- `GEOMETRICALLY_CERTIFIED`: `23640`

## Method

For every owner-cell facet, the generator records `s_j`, `q_j`, and the finite limit `-s_j/q_j` only when `q_j < 0`. The raw cap is the minimum finite limit, the guarded cap subtracts the fixed 1e-7 kW geometry guard, and the accepted grid cap is snapped downward to 0.25 kW.

Source and snapped endpoint membership are checked independently by normalized CCW halfspaces and an even/odd polygon ray-crossing test with a Euclidean boundary calculation. No coordinate outside its owner cell under either check can receive `GEOMETRICALLY_CERTIFIED`.

## Provenance and determinism

Registered memberships/policies are read from `fc15fbf7bf93ca89c2ab4a45145f937abbc70f63`. Owner cells and polygon facets are read from `ba88f54f52f7bcd03df2466ce69dff2b9b1c538b`. `source_manifest.json` records exact byte sizes and SHA-256 hashes.

`hashes.sha256` and `manifest.json` cover the generated payloads. Byte identity must be checked by two clean-location generations; it demonstrates determinism, not AC feasibility.

## Claim boundary

`GEOMETRICALLY_CERTIFIED` means only that the registered line segment from `x0` through the downward-snapped cap stays in the immutable owner cell under both geometric checks. It is not an AC, headroom, feasibility, repair, or freeze decision.
