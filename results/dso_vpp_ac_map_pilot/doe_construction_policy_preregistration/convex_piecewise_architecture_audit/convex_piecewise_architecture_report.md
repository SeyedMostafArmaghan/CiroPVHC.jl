# Convex / piecewise architecture artifact audit

## Safety gate recorded before execution

- Branch: `codex/dso-vpp-ac-map-pilot`.
- Authoritative committed HEAD: `c18021d9b981f2629e54f60e8c2fc5f33b00c1a2`.
- Initial status: only the expected untracked DOE-policy preregistration/audit package and its three predecessor scripts; no tracked modification.
- This generator neither stages, commits, pushes, resets, nor cleans repository content.

## Scope and evidence boundary

This deterministic audit uses only frozen committed/uncommitted artifacts in the established absolute physical PCC coordinate system (`P13`, `P30`, kW; `reference_pv_capacity_kw = 0`; `Q_PCC = 0`). It performs no AC feasibility work. The unresolved risk remains `INTER_RAY_EDGE_AND_ANGULAR_INTERIOR_AC_FEASIBILITY`.

The polygon kernel is reported only as a conservative single-convex diagnostic baseline. It is not the maximum convex subset, an optimal convex inner DOE, or the selected architecture. A true maximum-area convex subset is a distinct later optimization problem; no ad hoc comparator was introduced here.

## Kernel baseline

- Kernel/polygon area ratio across 32 timestamps: min/Q1/median/Q3/max = 0.713432776403/0.938795606893/0.942898929807/0.949519077665/0.959730966558.
- Per-timestamp inward-boundary retention fraction: min/Q1/median/Q3/max = 0.274509803922/0.471698113208/0.509433962264/0.509433962264/0.519230769231; aggregate 819/1689 = 0.484902309059.
- Circular angular coverage (degrees): min/Q1/median/Q3/max = 84.9999999999/165/175/175/175.
- The kernel retains 61/128 signed-axis inward endpoints (one or two per timestamp); all four are retained at 0/32 timestamps.
- The kernel excludes 1689/1689 stored outward endpoints. This is `KERNEL_OUTWARD_EXCLUSION_IS_INHERITED_FROM_POLYGON_SUBSET_RELATION`, not independent safety evidence.

## Exact fan and minimum convex-cell partition

- Raw triangle count: min/Q1/median/Q3/max = 51/53/53/53/54; total 1689.
- Every raw triangle is nondegenerate, contains the certified production center as a vertex, and the exact fan partition verifies at all timestamps: `true`.
- Exact minimum merged convex-cell count: min/Q1/median/Q3/max = 21/22/23/24.25/28; total 749.
- Every merged partition is convex, gap-free, has no positive-area overlap above the recorded tolerance, and has area ratio 1 within numerical tolerance: `true`.
- Greedy merge order is not used. Cyclic interval dynamic programming minimizes cell count exactly; the deterministic tie-break is minimum start index then lexicographic block order. Multiple minimum paths/partitions were detected for 30/32 timestamps and are explicitly recorded.
- Separate-cell complexity totals 3173 per-cell irredundant halfspaces, 2452 unique geometric facets after shared radial-boundary deduplication, and 749 conceptual cell-selection alternatives across timestamps. No binaries or MILP were implemented.

These cells are geometric only and are not AC-certified interiors.

## Nonconvexity localization

- VMAX: 717/851 points concave; 731 positive hull deficits; local-depth median/max 1.17450150597952/9.02245431931105 kW; perpendicular deficit median/max 46.0678914711216/69.5784528982857 kW.
- VMIN: 2/838 points concave; 2 positive hull deficits; local-depth median/max 0.0472335242085255/0.0757787373499487 kW; perpendicular deficit median/max 0.0472335242085255/0.0757787373499487 kW.

By primary class:

- `VMAX_BUS_13`: 363/429 concave; local-depth median/max 1.18845270514527/7.28586141087993 kW; positive hull deficits 368; perpendicular median/max 46.8538551254755/69.5784528982857 kW.
- `VMAX_BUS_30`: 354/422 concave; local-depth median/max 1.12844987102204/9.02245431931105 kW; positive hull deficits 363; perpendicular median/max 45.289002652215/66.6267402677561 kW.
- `VMIN_BUS_18`: 1/435 concave; local-depth median/max 0.0186883110671024/0.0186883110671024 kW; positive hull deficits 1; perpendicular median/max 0.0186883110671024/0.0186883110671024 kW.
- `VMIN_BUS_33`: 1/403 concave; local-depth median/max 0.0757787373499487/0.0757787373499487 kW; positive hull deficits 1; perpendicular median/max 0.0757787373499487/0.0757787373499487 kW.

Convex-hull-minus-polygon pocket area reconciles exactly: total 9187500.68012 kW^2, with 9187485.41389 kW^2 VMAX-only, 15.2662365015 kW^2 VMIN-only, and 0 kW^2 mixed-family pockets. This attribution is by the classes of all inward polygon vertices strictly inside each hull chord; class-mixed pockets are not forced into a class.

Concave-vertex angular localization counts: `WITHIN_VMAX_RUN`=717, `WITHIN_VMIN_RUN`=2. Class-transition/run count per timestamp has min/Q1/median/Q3/max = 4/4/4/4/4. Exact per-run extents and transition contexts are in `binding_class_angular_runs.csv` and `concavity_angular_localization.csv`. Artificial guard adjacency is not applicable because the angular inward polygon contains no guard vertices.

## VMAX-only piecewise hypothesis and fitted-normal context

The raw VMAX/VMIN counts, depths, bracket ratios, pocket areas, and minimum-partition radial-cut contexts are in `vmax_only_piecewise_hypothesis.csv`. VMIN has two trace concavities: 0.0186883 and 0.0757787 kW, respectively 0.118324 and 0.342032 of their paired bracket spacing. Thus nonconvexity is overwhelmingly VMAX by count, depth, hull deficit, and pocket area; VMIN is not mathematically zero, but no resolvably large VMIN effect appears relative to its own stored bracket. No post-hoc severity threshold is introduced.

Existing fitted-normal diagnostics were read without refitting. Their small angular deviations can coexist with the positional curvature/nonconvexity above; they do not prove convexity and the preregistered topology normals remain unchanged.

- `VMAX_BUS_13`: angular-deviation median/max 1.7335616336/2.05738991257 degrees; TLS RMS residual median/max 20.5596055362/23.7879267415 kW.
- `VMAX_BUS_30`: angular-deviation median/max 2.7294971294/3.08557529538 degrees; TLS RMS residual median/max 19.9703827568/22.7073685227 kW.
- `VMIN_BUS_18`: angular-deviation median/max 1.66407222863/1.96630949893 degrees; TLS RMS residual median/max 18.3821018714/20.8126912366 kW.
- `VMIN_BUS_33`: angular-deviation median/max 2.38509629482/2.68375457083 degrees; TLS RMS residual median/max 16.6956815135/19.3478034266 kW.

## Reproducibility contract

The three frozen predecessor manifests verified before generation:

- `results/dso_vpp_ac_map_pilot/doe_construction_policy_preregistration/artifact_manifest.csv`: 14 entries; manifest SHA-256 `2be51c9e7c0a6406f75ec790eb28ffb9dda7a8fcac98d7d70c658afd76299b40`.
- `results/dso_vpp_ac_map_pilot/doe_construction_policy_preregistration/geometric_contraction_threshold_audit/artifact_manifest.csv`: 19 entries; manifest SHA-256 `53f9e985dd15794881376e8e4f15afc73f47d1469e8b87bb0e151da735ea846f`.
- `results/dso_vpp_ac_map_pilot/doe_construction_policy_preregistration/nonconvexity_resolvability_audit/artifact_manifest.csv`: 14 entries; manifest SHA-256 `ca4f09d8c3fded8010f6a3c16cdfbbf8cfb076e1622d6b1b378afec2dffdeb62`.

`artifact_manifest.csv` records canonical byte sizes and SHA-256 hashes for every output other than itself plus this generator. Two clean-location byte-identical reconstructions are required and performed during handoff.

## Quantitative decision evidence

The kernel preserves a median 94.289893% of polygon area but only a median 50.943396% of stored inward-boundary points (aggregate 48.490231%), only 61/128 signed-axis endpoints, and a median 175 degrees of circular angular coverage. It therefore loses substantial measured boundary evidence despite retaining high area. The exact star-shaped partition needs 21--28 convex cells per timestamp (median 23), so its complexity is tens of cells rather than a single-digit decomposition. Whether that count is operationally modest is left to the later architecture policy decision.

Resolvable nonconvexity is predominantly VMAX: 717 versus 2 concave vertices, 731 versus 2 positive hull deficits, and 99.999834% of hull-minus-polygon pocket area is VMAX-only. The two VMIN traces are below their own paired bracket spacing and are not materially comparable to the VMAX depth/deficit distributions. This evidence informs, but does not select, single-convex, piecewise-convex, or VMAX-only hybrid architecture.
