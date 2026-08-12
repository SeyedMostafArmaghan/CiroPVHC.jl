# Pre-production verification and amendment audit

Final classification: **`PRODUCTION_PROBE_VERIFIED_READY_FOR_REMOTE_BACKUP`**.

This was a read-only scientific evidence audit plus deterministic preregistration amendment. The production probe, DOE construction, optimizations, full campaigns, and push were not performed.

## Git provenance before audit

- Branch: `codex/dso-vpp-ac-map-pilot`
- HEAD: `a6c0e515676a13be5b6bda5d183d38811506e55b`
- Remote tip: `d8e1bb0a7909711b4124f95673fb3a4802ae783a`
- Divergence: 0 behind / 7 ahead
- Working tree: clean

## V1 - independent S0 spot check

The anchor, the selected maximum-load summer/evening import row, and a winter/morning export-oriented row were compared field-by-field against the canonical root-voltage-1.0 S0 CSV. All 21 comparisons pass. The anchor independently matches Vmin `0.98730595284058` at bus 18 and Vmax `1.0` at bus 1. Source and exact-row hashes are retained as secondary provenance, not substitutes for the comparisons.

## V2-V4 - production boundary contract

Only `AXIS_CERTIFIED_BOUNDARY` is finite-valid. Guard-limited, unresolved, and re-entry axes are finite-invalid. A Tier-1 center therefore requires four genuinely certified axes.

A voltage bracket requires a `CONVERGED_FEASIBLE` lower endpoint and a `CONVERGED_INFEASIBLE` upper endpoint with an actual Vmin < 0.90 or Vmax > 1.05 violation. A feasible-to-nonconverged transition becomes `AXIS_UNRESOLVED` or `RAY_UNRESOLVED`; it never enters bisection. Retry changes initialization from flat start to a nearest accepted neighbor. If no neighbor exists, an identical retry is forbidden and the point remains unresolved.

Both primary attempts retain the audited Stage-0 settings (2,000 iterations, damping 0.70, tolerance 1e-11); only initialization changes. A converged result still receives the independent flat-start replay (4,000 iterations, tolerance 1e-12). Retry never changes voltage limits or network/resource physics. The existing historical export-axis implementation already rejects unresolved endpoints and reports its safe side. No production radial executor existed to audit; the new pure contract is the mandatory implementation boundary for that future runner.

Both endpoints store coordinate/r, absolute P13/P30, voltage extrema and buses, and solver status. The 1 kW coordinate-width criterion remains explicit. The official boundary is the last converged-feasible endpoint. Binding labels require a converged violating endpoint, an actual registered violation, its non-null bus, and stored voltage. Sampled feasible rays do not certify interpolated edges/polygons; those require later independent conservative validation.

## V3 - anchor replacement

The anchor is in `SPRING/AFTERNOON` and explicitly replaces the EXPORT-ranked pick before other slot selection. It is naturally rank 87, proving the count is not accidental deduplication. The other 31 selections exclude the anchor and use only load, PV, season, daypart, and timestamp tie-breaking. Output remains exactly 32 unique timestamps.

## V5 - cost provenance

The 4.1587 ms/evaluation input is aggregate throughput from 3,691 evaluations in 15.3498603 s on one serial Julia process with one Julia thread (`x86_64-w64-mingw32`, NT). The committed evidence does not identify the benchmark host/CPU/RAM; the 12-CPU/32-GB VM is the future target, not proven to be the benchmark machine. Single-worker solve latency was not directly measured. The former 12,192/50.7 s pair was an extrapolated design count/runtime, not an executed benchmark. The original 66,304 base and 125,056 full-adaptive counts and 5-15 minute estimate are retained. The estimate does not require parallel speedup because the full-adaptive aggregate extrapolation is about 8.7 minutes; eight-worker scaling is uncertain. Easy/feasible cases may be overrepresented relative to near-boundary, retry-heavy, or nonconvergent points.

## V6 and near-axis decision

Every selection now has a scientific semantic category. A NIGHT export-ranked candidate with exactly zero PV is `LOW_LOAD_ZERO_PV`, never PV export stress. The ranking algorithm is unchanged. Mandatory refinement of the eight near-axis intervals was not added: all four axes are base-sampled and existing binding/radius/unresolved adaptive triggers remain available. It stays a candidate enhancement, not a blocker.

## Amendment consequence

The amendment closes underspecified pre-production semantics; it does not generate AC boundary data. Deterministic contract tests now reject nonconverged or nonviolating upper endpoints, invalid finite bounds, unsafe binding labels, and use of a violating endpoint as the official coordinate.

## Tests and reproducibility

- Python selector, audit, and policy tests: 15/15 passed.
- Julia interface, Stage-0, historical axis-state, and production-contract tests: 137/137 passed (33 + 10 + 19 + 53 + 22).
- Deterministic regeneration checks: 6/6 preregistration artifacts and 9/9 audit artifacts reproduced.
