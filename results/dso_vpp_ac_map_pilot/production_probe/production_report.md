# DSO-VPP production AC boundary probe

Primary classification: `PRODUCTION_PROBE_COMPLETE_WITH_PREREGISTERED_UNRESOLVED_CASES`

- Coordinate system: absolute physical `P_PCC` kW; `Q_PCC = 0`.
- Git commit: `972e934b44e9e8c7004517618c8f5bee727b0760`.
- Run mode: FRESH; 1 Julia process, 1 Julia thread(s).
- Wall time: 54.581 s; actual AC evaluations: 87372; retries: 143.
- Timestamps: 32/32; base directions: 1152; adaptive directions: 482.
- Axis status distribution: AXIS_CERTIFIED_BOUNDARY=128.
- Center-tier distribution: CENTER_TIER_1_AXIS_MIDPOINT=32.
- Binding distribution: BINDING_VMAX=851, BINDING_VMIN=838, RAY_UNBOUNDED_WITHIN_GUARD=73.
- Binding buses: 13=429, 18=435, 30=422, 33=403.
- Unresolved: 0; guard-limited: 73; axis re-entry: 0; ray re-entry: 0.
- Anchor `2012-10-15 13:00:00`: NEAR_EXTREME. Criterion: EXTREME if either total-axis-width or median-base-radius empirical tail rank <=5%; NEAR_EXTREME if <=15%; otherwise PLATEAU_REGION if at least 8/32 timestamps lie within 1% of the anchor on both metrics; otherwise TYPICAL.
- Independent post-run validation: PASS.

Historical command-space anchor values are retained only as provenance and were not used as absolute-axis intercepts.
