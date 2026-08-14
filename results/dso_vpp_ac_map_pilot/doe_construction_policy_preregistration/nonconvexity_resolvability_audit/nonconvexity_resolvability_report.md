# Nonconvexity resolvability audit (artifact only)

## Safety, frozen inputs, and coordinate contract

- Starting branch: `codex/dso-vpp-ac-map-pilot`
- Starting HEAD: `c18021d9b981f2629e54f60e8c2fc5f33b00c1a2`
- Initial status: only `results/dso_vpp_ac_map_pilot/doe_construction_policy_preregistration/`, `scripts/prepare_dso_vpp_doe_construction_policy_preregistration.py`, and `scripts/audit_dso_vpp_doe_geometric_contraction_threshold.py` were untracked; there were no tracked modifications.
- The frozen preregistration manifest passed all 14 size/SHA-256 checks (manifest SHA-256 `2be51c9e7c0a6406f75ec790eb28ffb9dda7a8fcac98d7d70c658afd76299b40`); the frozen geometric-contraction manifest passed all 19 checks (manifest SHA-256 `53f9e985dd15794881376e8e4f15afc73f47d1469e8b87bb0e151da735ea846f`).
- Geometry uses absolute physical PCC `(P13,P30)` in kW, `reference_pv_capacity_kw=0`, `Q_PCC=0`, and the timestamp-specific certified center plus sign-specific production scales. Angles are `atan2(normalized P30, normalized P13)` modulo 360 degrees. The historical `P13_command+777.7133428167988 kW` mapping is not applied.
- No AC solve, replay, probing, benchmark, HC/TVPP optimization, monotonicity analysis, mesh/alpha choice, or DOE-policy tuning is performed by this generator.

## A. Polygon kernel and star-shapedness

All 32 polygon kernels are nonempty. The certified production center is in the polygon kernel for 32/32 timestamps. The all-boundary visibility predicate is true for 32/32 timestamps. Thus every angular polygon is star-shaped with respect to its production center. This is a geometric statement, not AC-feasibility proof for edges or angular interiors.

Kernel computation uses deterministic intersection of normalized left halfplanes of the CCW polygon edges at 1e-09 kW tolerance. Kernel vertices, areas, center locations, and signed/nearest boundary distances are reported in the kernel CSVs.

- kernel area: n=32; min 11272616.9362 kW^2; Q1 15192422.6812 kW^2; median 15244950.7595 kW^2; Q3 15333110.4717 kW^2; max 15465273.783 kW^2; mean 15147923.872 kW^2.
- production-center distance to nearest kernel boundary: n=32; min 834.388441153 kW; Q1 1126.58849336 kW; median 1365.29798379 kW; Q3 1419.42351474 kW; max 1480.91968466 kW; mean 1290.50201966 kW.

## Existing 0/1689 outward screen

The direct screen reconstructs 0 inside, 0 on boundary, and 1689 outside. Same-production-ray pairing holds for 1561/1689 pairs; the strict structural implication from a selected inward radial vertex and `r_out>r_in` is verified for 1561/1689 endpoints. Those rows are classified `EXPECTED_FROM_RADIAL_POLYGON_CONSTRUCTION_ON_SAMPLED_RAYS`.

The remaining 128 rows are retained as direct geometric checks rather than mislabeled as same-ray implications; this includes signed-axis searches whose endpoints are not generally collinear with the certified center. Consequently, the radial subset of the prior screen is structurally expected and is not independent safety evidence. The unresolved risk remains `INTER_RAY_EDGE_AND_ANGULAR_INTERIOR_AC_FEASIBILITY`.

## B. Local concavity

Across 1689 polygon vertices, the robust CCW orientation classification gives 719 concave, 970 convex, and 0 numerically collinear vertices. The tolerance is `1e-12*max(1, ||incoming||*||outgoing||)` in kW^2. Every timestamp has at least one concave vertex; per-timestamp counts range from 20 to 27.

- local neighbor-chord segment depth: n=719; min 0.0186883110671 kW; Q1 0.746122748273 kW; median 1.17354010671 kW; Q3 1.5759268555 kW; max 9.02245431931 kW; mean 1.52548475394 kW.
- local depth / paired physical bracket: n=719; min 0.070601810553; Q1 2.08107302478; median 3.53673056479; Q3 5.38545021365; max 19.8514718306; mean 4.12410069041.
- VMAX local depth: n=717, median/max 1.17450150598/9.02245431931 kW; VMIN local depth: n=2, median/max 0.0472335242085/0.0757787373499 kW.

The local metric is diagnostic only; the global hull deficits below determine convexification severity.

## C. Convex-hull deficits of inward points

There are 733/1689 inward points with a nonzero hull deficit above the 1e-08 kW reporting tolerance.

- perpendicular hull deficit, positive-deficit points: n=733; min 0.0138099310546 kW; Q1 34.3003043212 kW; median 46.0192645878 kW; Q3 55.6922103596 kW; max 69.5784528983 kW; mean 43.3527134848 kW.
- physical production-ray hull deficit, positive-deficit points: n=733; min 0.0183224454467 kW; Q1 39.4490120893 kW; median 56.7594540878 kW; Q3 73.9755205925 kW; max 135.575716115 kW; mean 56.5067956875 kW.
- perpendicular deficit / physical bracket: n=733; min 0.03462277148; Q1 84.7783808185; median 128.190013087; Q3 167.219200634; max 435.847393342; mean 135.449140863.
- radial deficit / signed radial bracket where same-ray denominator is valid: n=669; min 0.0459360616148; Q1 104.494221598; median 153.57729027; Q3 206.309148006; max 520.132433927; mean 161.807341467.
- Axis positive-deficit ratio: n=64, median/max 158.379559049/409.425278192; production-ray positive-deficit ratio: n=669, median/max 119.068996446/435.847393342.
- Per-timestamp median perpendicular-deficit/bracket ratio ranges from 94.1220939816 at `2011-02-06 00:00:00` to 142.030677578 at `2013-04-17 05:30:00`.

No ambiguous nondegenerate ray/hull intersection occurred. The all-point, positive-deficit, timestamp, VMAX/VMIN, primary-class, and ray/axis distributions are in the summary CSV.

## D. Severity of convex-hull outward violations

Exactly 730 stored outward converged-infeasible endpoints lie strictly inside the inward convex hull, reconciling the frozen comparator.

- perpendicular penetration: n=730; min 0.576452584804 kW; Q1 34.1552439886 kW; median 45.7908795918 kW; Q3 55.5145270479 kW; max 69.3152117638 kW; mean 43.2403803466 kW.
- physical production-ray penetration: n=730; min 0.576471589939 kW; Q1 39.3229408115 kW; median 56.4694907025 kW; Q3 73.4915358136 kW; max 134.794461347 kW; mean 56.3641760092 kW.
- perpendicular penetration / own physical bracket: n=730; min 1.42650192465; Q1 84.1237847866; median 127.506279166; Q3 166.401316456; max 435.009438689; mean 135.186566869.
- radial penetration / own signed radial bracket where valid: n=666; min 1.42654895308; Q1 104.404097706; median 152.769169101; Q3 206.62436549; max 519.132433928; mean 161.535422949.
- VMAX perpendicular penetration: n=730, median/max 45.7908795918/69.3152117638 kW; VMIN perpendicular penetration: n=0.
- Axis violation ratio: n=64, median/max 157.4825702/408.478144569; production-ray violation ratio: n=666, median/max 118.273264094/435.009438689.
- Per-timestamp median perpendicular-penetration/bracket ratio ranges from 93.2974959717 at `2011-02-06 00:00:00` to 141.170045523 at `2013-04-17 05:30:00`.

Physical scale context is timestamp-specific in `physical_scale_context.csv`: signed-axis spans, angular-polygon diameter/area, convex-hull area, and median physical/normalized radii. Dimensionless diameter ratios are secondary; bracket ratios remain primary.

- timestamp P13 axis span: n=32; min 3164.375 kW; Q1 3168.5546875 kW; median 3175.625 kW; Q3 3197.65625 kW; max 3227.03125 kW; mean 3182.84179688 kW.
- timestamp P30 axis span: n=32; min 4532.34375 kW; Q1 4541.6015625 kW; median 4557.421875 kW; Q3 4606.328125 kW; max 4672.1875 kW; mean 4573.46679688 kW.
- angular-polygon diameter: n=32; min 7037.48423313 kW; Q1 7488.38989447 kW; median 7503.21847144 kW; Q3 7524.35181793 kW; max 7669.54179742 kW; mean 7485.72158691 kW.

## Optional uniform convex-hull erosion diagnostic

For each timestamp with an inside outward endpoint, the supremum erosion distance is the maximum inward distance of such endpoints from a hull edge. Strictly greater erosion excludes every stored violation; equality leaves the deepest endpoint on the eroded boundary.

- required erosion-distance supremum across timestamps: n=32; min 45.6984761925 kW; Q1 58.1907907196 kW; median 62.3104915954 kW; Q3 66.1621670336 kW; max 69.3152117638 kW; mean 61.0512458789 kW.
- inward-point retained fraction at erosion supremum: n=32; min 0.0185185185185; Q1 0.0188679245283; median 0.019419306184; Q3 0.0377358490566; max 0.0384615384615; mean 0.0272377597225.
- hull-area retained fraction at erosion supremum: n=32; min 0.928430424879; Q1 0.931742602519; median 0.935600379589; Q3 0.939893732662; max 0.953200148984; mean 0.936932990785.

This is a morphological diagnostic, not an adopted DOE policy.

## Interpretation boundary

The report supplies raw physical distances and bracket ratios without inventing a threshold for `COMPARABLE_TO_BOUNDARY_SEARCH_RESOLUTION` versus `RESOLVABLY_LARGER`. The distributions show how many bracket widths convexification adds and how deeply known infeasible endpoints penetrate; they do not choose convex versus piecewise-convex architecture. Kernel/star-shapedness does not resolve inter-ray AC feasibility.

## Outputs and reproducibility contract

`artifact_manifest.csv` records deterministic sizes and SHA-256 hashes for every generated file other than itself plus the generator. The generator accepts `--output`; two clean-location byte comparisons are performed externally during handoff. The frozen 14-entry preregistration and 19-entry geometric-audit manifests are verified before every build and are never rewritten.
