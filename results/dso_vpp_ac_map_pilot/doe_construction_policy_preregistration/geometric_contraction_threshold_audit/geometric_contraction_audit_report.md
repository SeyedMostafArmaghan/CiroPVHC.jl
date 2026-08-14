# Geometric contraction threshold audit (artifact only)

## Safety and scope

- Starting branch: `codex/dso-vpp-ac-map-pilot`
- Starting HEAD: `c18021d9b981f2629e54f60e8c2fc5f33b00c1a2`
- Initial status: only the frozen untracked preregistration directory and its generator were present.
- This separate audit reads frozen artifacts and changes no topology normal, offset, guard cap, DOE policy, or historical production result.
- No AC solve, replay, production probe, HC/TVPP optimization, substantive mesh, runtime benchmark, alpha-policy selection, monotonicity rerun, or deferred 1,561-boundary slope study was performed.
- Production DOE geometry is stored directly in absolute physical PCC coordinates with `reference_pv_capacity_kw=0` and `Q_PCC=0`. The resolved historical Phase-B relation remains `P_PCC_13_abs=P_command_13+777.7133428167988 kW`; it is not applied to production DOE rows.

## Margin semantics and normals

The previously reported "inside margin" is exactly `min_j(b_j-a_j^T P)` over the full alpha=1 candidate. It is raw halfspace slack: positive inside, zero on the boundary, negative outside. Here `a_j` was stored after positive Euclidean unit normalization, so the raw slack (kW) is numerically equal to the signed perpendicular distance `(b_j-a_j^T P)/||a_j||_2` (kW). That equivalence would not hold for arbitrarily scaled normals. The prior timestamp-summary range 134.884426495 to 195.335413607 kW is therefore both raw unit-normal slack and signed perpendicular distance in this specific representation, not an invariant distance under arbitrary normal scaling.

The raw topology norm for VMAX/13 and VMIN/18 is `0.933265670732189`; the raw norm for VMAX/30 and VMIN/33 is `0.68028089621282`. Every stored physical/guard candidate normal has norm 1 within maximum error `6.66e-16`. The prior margins were reconstructed with maximum error `7.28e-12` kW. Full point-constraint values and grouped distributions are in the distance CSVs.

## Homothetic gauge and outward threshold

For every actual physical facet and guard cap, `D_jt=b_jt-a_jt^T c_t` was checked: all 201 values are positive, ranging from 1076.62121206 to 3876.13113593 kW. The audit uses exactly `rho_t(P)=max_j[(a_jt^T P-a_jt^T c_t)/D_jt]`. Direct contracted-halfspace membership and `rho<=alpha` were compared for all 3,378 endpoints at alpha 0.25, 0.5, 0.75, 1, and the timestamp threshold: 0 mismatches at 1e-09 kW halfspace and 1e-12 gauge comparison tolerances; maximum algebraic identity error was 1.82e-12 kW.

`alpha_outward_exclusion_sup,t=min rho_t(P_out)`. Exact alpha strictly below it excludes every stored outward point; equality leaves at least one limiter on the boundary and is not relabeled as a final alpha.

- alpha outward-exclusion supremum: min 0.871353212216; Q1 0.894102203855; median 0.899653273533; Q3 0.910254519008; max 0.921013182665.
- alpha-squared area consequence: min 75.9256420438%; Q1 79.9418750957%; median 80.9378394989%; Q3 82.8563360839%; max 84.8265282643%.

| timestamp | alpha supremum | alpha^2 | inward strictly below / total | limiter type |
|---|---:|---:|---:|---|
| 2010-07-01 07:30:00 | 0.921013182665 | 0.848265282643 | 1/51 | PHYSICAL_CANDIDATE_FACET |
| 2010-07-02 17:30:00 | 0.902865045733 | 0.815165290806 | 1/53 | PHYSICAL_CANDIDATE_FACET |
| 2010-07-02 18:00:00 | 0.89810976762 | 0.806601154694 | 1/53 | PHYSICAL_CANDIDATE_FACET |
| 2010-07-03 00:00:00 | 0.901196779446 | 0.812155635283 | 1/53 | PHYSICAL_CANDIDATE_FACET |
| 2010-11-26 18:00:00 | 0.905515366889 | 0.819958079672 | 1/53 | PHYSICAL_CANDIDATE_FACET |
| 2010-12-21 11:30:00 | 0.894256341428 | 0.799694404184 | 1/53 | PHYSICAL_CANDIDATE_FACET |
| 2010-12-21 12:00:00 | 0.894707981884 | 0.800502372846 | 1/53 | PHYSICAL_CANDIDATE_FACET |
| 2011-01-21 18:00:00 | 0.912447598893 | 0.832560620725 | 1/53 | PHYSICAL_CANDIDATE_FACET |
| 2011-02-05 11:30:00 | 0.906783206321 | 0.822255783266 | 1/53 | PHYSICAL_CANDIDATE_FACET |
| 2011-02-05 17:30:00 | 0.871353212216 | 0.759256420438 | 2/54 | PHYSICAL_CANDIDATE_FACET |
| 2011-02-05 18:00:00 | 0.877482551401 | 0.769975628012 | 1/54 | PHYSICAL_CANDIDATE_FACET |
| 2011-02-06 00:00:00 | 0.920774509862 | 0.847825698011 | 1/51 | PHYSICAL_CANDIDATE_FACET |
| 2011-03-04 18:00:00 | 0.905639630545 | 0.820183140414 | 1/53 | PHYSICAL_CANDIDATE_FACET |
| 2011-03-08 11:30:00 | 0.894094729197 | 0.799405384778 | 1/53 | PHYSICAL_CANDIDATE_FACET |
| 2011-03-08 12:30:00 | 0.895521667262 | 0.801959056536 | 1/53 | PHYSICAL_CANDIDATE_FACET |
| 2011-05-11 17:30:00 | 0.884039843865 | 0.781526445541 | 1/53 | PHYSICAL_CANDIDATE_FACET |
| 2011-05-11 18:00:00 | 0.884876026095 | 0.783005581558 | 1/53 | PHYSICAL_CANDIDATE_FACET |
| 2011-05-16 07:30:00 | 0.913734936899 | 0.83491153491 | 1/53 | PHYSICAL_CANDIDATE_FACET |
| 2011-09-11 00:00:00 | 0.896999457875 | 0.804608027427 | 1/53 | PHYSICAL_CANDIDATE_FACET |
| 2011-09-30 05:30:00 | 0.910100176128 | 0.828282330588 | 1/52 | PHYSICAL_CANDIDATE_FACET |
| 2011-09-30 11:30:00 | 0.896168437947 | 0.803117869172 | 1/53 | PHYSICAL_CANDIDATE_FACET |
| 2011-11-14 17:30:00 | 0.884189384416 | 0.781790867514 | 1/53 | PHYSICAL_CANDIDATE_FACET |
| 2011-11-14 19:30:00 | 0.887926923732 | 0.788414221888 | 1/53 | PHYSICAL_CANDIDATE_FACET |
| 2011-12-15 05:30:00 | 0.910717547647 | 0.829406451591 | 1/52 | PHYSICAL_CANDIDATE_FACET |
| 2012-08-04 03:30:00 | 0.911038221285 | 0.829990640642 | 1/52 | PHYSICAL_CANDIDATE_FACET |
| 2012-08-05 23:30:00 | 0.896667841195 | 0.804013217433 | 1/53 | PHYSICAL_CANDIDATE_FACET |
| 2012-08-24 12:00:00 | 0.894104695408 | 0.79942320635 | 1/53 | PHYSICAL_CANDIDATE_FACET |
| 2012-08-31 11:30:00 | 0.893117348027 | 0.797658597347 | 1/53 | PHYSICAL_CANDIDATE_FACET |
| 2012-09-03 07:00:00 | 0.909509076578 | 0.827206760378 | 1/53 | PHYSICAL_CANDIDATE_FACET |
| 2012-10-15 13:00:00 | 0.910749034607 | 0.829463804037 | 1/52 | PHYSICAL_CANDIDATE_FACET |
| 2013-04-07 02:00:00 | 0.901525234076 | 0.812747747676 | 1/53 | PHYSICAL_CANDIDATE_FACET |
| 2013-04-17 05:30:00 | 0.912196032795 | 0.832101602247 | 1/52 | PHYSICAL_CANDIDATE_FACET |

Limiter counts: 32 physical-candidate-facet-limited and 0 guard-cap-limited. The limiter constraint matches the outward endpoint's primary class in 32/32 timestamps; mismatches are retained as observations.

## Certified inward evidence retained

At the supremum with comparison tolerance, 33/1689 inward points (1.95381882771%) are retained. Under the strict `< alpha_sup` interpretation before any epsilon, 33/1689 (1.95381882771%) are retained.

- per-timestamp retained fraction at supremum: min 1.85185185185%; Q1 1.88679245283%; median 1.88679245283%; Q3 1.89586357039%; max 3.7037037037%.
- per-timestamp fraction strictly below supremum: min 1.85185185185%; Q1 1.88679245283%; median 1.88679245283%; Q3 1.89586357039%; max 3.7037037037%.

Gauge distributions show the paired clouds directly:

- inward rho: min 0.871064780168; Q1 0.926085828625; median 0.955138751383; Q3 0.994047177359; max 1.
- outward rho: min 0.871353212216; Q1 0.92624988674; median 0.955247451025; Q3 0.994145636861; max 1.00023736055.
- paired delta rho = rho_out-rho_in: min 4.86423170851e-05; Q1 9.33101686872e-05; median 0.000114462018594; Q3 0.00017289347875; max 0.000393143010348.
- physical inward/outward bracket spacing (kW): min 0.1545105; Q1 0.197616350481; median 0.314297532165; Q3 0.404620595588; max 0.854157002871.

There are 0 pairwise gauge-ordering violations at tolerance 1e-12; none were sign-corrected. Full global/timestamp/VMAX-VMIN/class/ray-axis summaries are provided.

The two-dimensional area consequence is exactly `alpha_sup^2`; this is not an accepted operational factor. Independent polygon calculations at four deterministic alpha values have maximum relative identity error 4.15e-16.

## Neutral architecture diagnostics

The retained class count, exact normalized angular coverage, largest gap, and signed-axis survival are reported per timestamp in `architecture_viability_diagnostics.csv`; no viability threshold or post-hoc category is introduced.

- retained angular coverage (degrees): min 0; Q1 0; median 0; Q3 0; max 9.99999999994.
- largest retained angular gap (degrees): min 350; Q1 360; median 360; Q3 360; max 360.
- primary classes represented among retained points: min 1; Q1 1; median 1; Q3 1; max 1.
- signed-axis inward endpoints retained strictly: min 0; Q1 0; median 0; Q3 0; max 0.

## Angular inward polygon and convex hull comparators

All 32 angular constructions are simple: 32/32; all contain the production center: 32/32; convex: 0/32. Duplicate-angle groups are handled deterministically by selecting maximum normalized radius, then endpoint ID, while all nonselected inward rows remain in the containment check. All-input inward containment passes in 32/32 timestamps.

Against the angular polygons, stored outward endpoints are: 0 inside, 0 on boundary, and 1689 outside at 1e-08 kW. This result is measured, not inferred from paired directions.

The optional artifact-only convex hull comparator was also produced. Stored outward endpoints are: 730 inside, 0 on boundary, and 959 outside. Hull vertex fractions and areas relative to the alpha=1 candidate and angular polygon are reported per timestamp. It remains diagnostic only.

## Outputs and reproducibility contract

`artifact_manifest.csv` lists every generated audit artifact other than itself plus this generator, with deterministic byte size and SHA-256. The generator accepts `--output` so clean-location reconstructions can be compared byte-for-byte without embedding temporary paths. The external two-pass reconstruction result is reported with the task handoff.

## Quantitative consequence

Global homothetic contraction to the stored-outward exclusion supremum retains 1.95381882771% of measured certified-feasible inward boundary points using the supremum comparison tolerance, and 1.95381882771% under strict comparison before any epsilon. Per timestamp, the strict retained fraction ranges from 1.85185185185% to 3.7037037037% (median 1.88679245283%), while the geometric candidate-area consequence ranges from 75.9256420438% to 84.8265282643% (median 80.9378394989%). These percentages state the evidence loss without assigning an unpreregistered viability label.
