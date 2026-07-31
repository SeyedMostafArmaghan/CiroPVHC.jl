# Preregistration: fixed radial normalization for a future AC-versus-linear probe

## Immutable Phase-B provenance

- Phase-B commit: `24138a3423875d1c58f814b8f448cebdd8287383`.
- Axis-capacity source: `results/dso_vpp_ac_map_pilot/export_side_axis_capacity_bounds.csv`.
- Committed axis-capacity CSV SHA-256: `79ae1cd38ca705399babfa104e4f14c75f18d9bed4ecd4cd5b4b99d044a6af92`.
- Scale derivation rule: read the committed CSV and set `s13 = min_t P_axis,13,t` and `s30 = min_t P_axis,30,t`, using only rows with `axis_status = VALID_REFINED_BOUND`.
- Resolved fixed scales: `s13 = 681.370544434 kW` and `s30 = 1739.59228516 kW`.
- Source timestamp for `s13`: `2012-10-15 13:00:00`.
- Source timestamp for `s30`: `2012-10-15 13:00:00`.
- Both global minima occur at the same timestamp.
- Status of LinDistFlow implementation: **NOT YET STARTED**.

These values are provenance-locked to the committed Phase-B CSV. They were not copied from a chat result and must not be recalculated from a later, uncommitted artifact.

## Fixed normalization and future rays

For every timestamp, define the normalized coordinates

\[
u=\frac{P_{13}}{s_{13}},
\qquad
w=\frac{P_{30}}{s_{30}}.
\]

The future radial parameterization for `0 <= theta <= pi/2` is

\[
P_{13}=s_{13}r\cos\theta,
\qquad
P_{30}=s_{30}r\sin\theta,
\qquad r\ge 0.
\]

The coordinate rays are `theta = 0` for the bus-13 axis and `theta = pi/2` for the bus-30 axis. The scales remain fixed across every timestamp.

> A common \(\theta\) must represent the same physical injection ratio at every timestamp. Per-timestamp normalization is prohibited for cross-time aggregation.

## No clipping at the reference scale

> \(r=1\) is only the reference scale defined by the limiting one-axis capacities. It is not a physical upper bound. Future AC or linear radial searches must not stop or clip at \(r=1\). Values \(r>1\) are expected in nonlimiting intervals.

The future search guard must therefore be independent of `r = 1` and large enough to locate a terminal status on nonlimiting timestamps.

## Star-shapedness limitation and ray classification

> Phase B established one-transition behavior only on the coordinate rays \(\theta=0\) and \(\theta=\pi/2\). It does not establish star-shapedness for intermediate directions.

For every future `(t, theta)` pair, the procedure is preregistered as follows:

1. Perform a coarse radial scan from `r = 0` using nonnegative radial commands and without clipping at `r = 1`.
2. Count the ordered status transitions along the complete sampled ray.
3. Apply bisection only after observing exactly one safe-to-terminal transition with a valid ordered bracket.
4. Classify multiple transitions explicitly as `MULTIPLE_STATUS_TRANSITIONS`; do not select one transition post hoc.
5. Classify a nonconvergent point as unresolved rather than physically infeasible. If nonconvergence prevents a trustworthy one-transition bracket, classify the ray as `UNRESOLVED_NONCONVERGENT_RAY` and exclude it from quantitative metrics.

Any future claim of star-shapedness requires evidence over the intermediate directions actually scanned; the coordinate-axis result alone is insufficient.

## Future primary metrics

For each approximation method, timestamp, and resolved direction, the primary radial-boundary error will be

\[
g_r(t,\theta)=
\frac{r_{\mathrm{approx}}(t,\theta)-r_{AC}(t,\theta)}
{r_{AC}(t,\theta)}.
\]

The second primary metric is the buswise voltage error at the approximation boundary, evaluated at the same physical injections:

\[
\Delta V_i(t,\theta)=
V_i^{\mathrm{approx}}\!\left(t,r_{\mathrm{approx}},\theta\right)-
V_i^{AC}\!\left(t,r_{\mathrm{approx}},\theta\right).
\]

Future reporting must retain every buswise `Delta V_i` and may additionally summarize its maximum absolute value and corresponding bus. Unresolved nonconvergent rays are excluded from both primary quantitative metrics and reported separately by status.

Area is a secondary descriptive metric and is not part of the primary go/no-go gate. No numerical conclusion, acceptance threshold, LinDistFlow result, intermediate-direction result, or radial-probe result is preregistered here.
