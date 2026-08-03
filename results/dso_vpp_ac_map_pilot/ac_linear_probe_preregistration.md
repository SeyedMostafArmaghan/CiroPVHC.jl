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

## Pre-execution Amendment 1 — Analytically Identified Linear-Corner Directions

**Amendment date:** 2026-07-31. This section is an additive amendment. It does not delete, replace, or reinterpret the original preregistration above.

### Locked provenance and analytical method

- Original preregistration commit: `79d92dce83a41cc0407897b78afa43d6252cd70f`.
- Phase-B commit: `24138a3423875d1c58f814b8f448cebdd8287383`.
- Capacity source: the Git blob `24138a3423875d1c58f814b8f448cebdd8287383:results/dso_vpp_ac_map_pilot/export_side_axis_capacity_bounds.csv`.
- Committed capacity CSV SHA-256: `79ae1cd38ca705399babfa104e4f14c75f18d9bed4ecd4cd5b4b99d044a6af92`.
- Fixed scales remain `s13 = 681.370544434 kW` and `s30 = 1739.59228516 kW`.
- Limiting timestamp: `2012-10-15 13:00:00`.
- Exact linear-model variant: **`AC_ANCHORED_LINDISTFLOW`**. For every voltage-constrained bus `j`, the audit used the squared-voltage headroom `Delta v_j = 1.05^2 - abs2(V_j^AC(0))` from the corrected AC fixed-injection solution at `P13_VPP=P30_VPP=0`, with the committed timestamp-dependent load and PV factors, `H=850 kW` reference PV at bus 13, and zero reactive commands. It then constructed `c_jk = 2 sum r_e` over the common root paths for `k in {13,30}`, ranked `Delta v_j/c_jk` over all 33 buses, solved the bus-13/bus-30 equality system, and evaluated every bus constraint at that intersection.
- Coefficients at or below `1e-14` were non-controlling; axis ties used `1e-6 kW`; corner near-binding used `1e-10` in squared-voltage margin; the intersection condition-number threshold was `1e10`.

### Analytical result fixed before probe execution

- Axis 13 all-bus argmin: `{13}`, classified `LINEAR_AXIS_13_SELF_BINDS`.
- Axis 30 all-bus argmin: `{30}`, classified `LINEAR_AXIS_30_SELF_BINDS`.
- Full-envelope candidate classification: **`EXPOSED_LINEAR_CORNER_13_30`**.
- Candidate coordinates: `P13* = 156.894700536220 kW`, `P30* = 1610.27566755161 kW`.
- Full-envelope active/near-binding set: `{13,30}`; no third bus was active within the declared tolerance and no all-bus constraint was violated.
- Fixed normalized corner direction:

\[
\theta^*=
\operatorname{atan2}\!\left(
\frac{1610.27566755161}{1739.59228516},
\frac{156.894700536220}{681.370544434}
\right)
=1.32698958614415\ \mathrm{rad}
=76.0309027438716^\circ.
\]

The corner direction `theta*` is added as a required corner-focused direction for the later normalized radial-probe design. The reason is prospective and structural: the complete analytical all-bus envelope identified a unique exposed intersection of the bus-13 and bus-30 upper-voltage constraints, which the coordinate rays alone cannot interrogate.

No numerical base direction grid or compatible numerical perturbation spacing was specified in the original preregistration. Therefore this amendment does **not** invent a value of `delta`; the adjacent directions `theta*-delta` and `theta*+delta` remain unresolved for the later probe-design commit. Any later resolution must preserve the original grid and use the preregistered deterministic half-smallest-positive-spacing rule, physical clipping to `[0,pi/2]`, and angular deduplication tolerance `1e-12 rad`.

**Pre-execution declaration:** no AC radial scan, LinDistFlow radial scan, intermediate-direction probe, or direction probe had been executed before this amendment. This amendment was informed only by the analytical AC-anchored linear diagnostic and not by any AC radial-probe result. It does not preregister or assert an AC result at the candidate corner.
