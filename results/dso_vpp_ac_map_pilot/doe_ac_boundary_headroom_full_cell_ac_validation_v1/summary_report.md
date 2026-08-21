# Full-cell AC validation v1

## Scientific conclusion

Full-cell repair candidates exist and satisfy headroom.

This conclusion concerns only the Phase 2 evidence status. Geometric membership is not treated as AC repair success, and impossibility is not claimed unless every certified grid was exhausted without unresolved, provenance, or budget issues.

## 1. Historical failed single-facet campaign

The historical status remains `MAIN_COUPLED_DOE_GEOMETRIC_CANDIDATE_FALSIFIED_BY_AC_COUNTEREXAMPLE`. Its artifacts were hash-inventoried before execution and were unchanged afterward. Historical coordinates and results were not reused as Phase 2 repair evidence.

## 2. Phase 1 geometric certification

Phase 1 supplied 24,004 memberships: 23,640 `GEOMETRICALLY_CERTIFIED`, 357 `NO_POSITIVE_FULL_CELL_MOVEMENT`, and 7 `FULL_CELL_CAP_BELOW_GRID`. Only certified rows entered the AC search. Phase 1 payload and source hashes were verified before the first AC call.

## 3. Phase 2 full-cell AC validation

The search used `d = 0, 0.25, ... d_max_grid` and rechecked normalized analytical halfspaces plus an independent even/odd polygon test before every AC call. It stopped per membership at the first design pass, cap exhaustion, unresolved AC, locked-budget exhaustion, or a detected pass-to-fail transition. No extrapolation beyond the Phase 1 cap was allowed.

Logical AC calls: `302303` / `302303`. Retry calls: `0` / `3024`. Unresolved calls: `0`.

### Membership classifications

- `GEOMETRY_ONLY_NO_POSITIVE_MOVEMENT`: `357`
- `GEOMETRY_GRID_LIMIT_TOO_SMALL`: `7`
- `AC_HEADROOM_ACHIEVED`: `20287`
- `AC_HEADROOM_FAILED_WITHIN_FULL_CELL`: `10`
- `ORIGINAL_LIMIT_FAILED_WITHIN_FULL_CELL`: `0`
- `AC_UNRESOLVED`: `0`
- `SEARCH_BUDGET_EXHAUSTED`: `3343`
- `PROVENANCE_FAILURE`: `0`

### Scope safeguards

- Q13 and Q30 remained zero through the locked production evaluator.
- Reference PV capacity remained zero through the locked production evaluator.
- The network, load profile, selected timestamps, solver/retry/replay settings, residual auditing, committed cells, directions, facet identities, and owner assignments were not modified.
- Blank substation-power fields mean that quantity is not exposed by the locked wrapper; the runner did not bypass the wrapper to obtain it.
