# Execution and Checkpoint Policy

This preregistration performs no AC calls and does not authorize execution.

## Anchor-search + verify-escalate

- Reuse committed `d=0` evidence as descriptive anchors.
- For each edge, select the most adverse artifact-predicted interior anchor; prediction only sets order.
- Verify the anchor by AC in the future. Start retreat bracketing at 0.5 kW and double outward, always below `cap_e`, for at most 16 logical calls.
- Refine the first AC fail/pass bracket to width <= 0.25 kW with at most 16 calls.
- Screen every remaining interior membership at the accepted anchor retreat, then allow at most 8 additional calls per membership.
- Rebuild the combined multi-facet geometry and verify all interior and vertex memberships at final common edge retreats.
- The local re-entry stencil is `d-Δ, d, d+Δ`, `Δ=0.25 kW`, where geometrically valid. It detects local re-entry only; it does not assert global monotonicity between tested locations.

## Checkpoints

- Attempt rows are immutable and append-only.
- Seal a shard at 2000 rows or timestamp completion, whichever comes first.
- Each shard records first/last attempt ID, row count, and SHA-256.
- Checkpoint state contains only the compact cursor, sealed-shard manifest, active solver state, call counters, and deterministic pending queue.
- Serializing the accumulated campaign history is forbidden.
- Concatenate and hash final tables once after phase completion.

## Budget

The hard budget is 302303 primary logical AC calls plus 3024 retry calls across calibration and holdout. At most one retry is permitted per nonconverged logical call. Wall time is not a budget or stopping criterion. Exceeding either call cap stops the study as inconclusive before repair freeze.
