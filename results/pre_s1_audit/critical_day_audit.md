# Pre-S1 critical-day audit

## Scope and sources

This audit reads the existing three-year processed profiles and ranking outputs; it does not rerun a network model or regenerate the Ausgrid pipeline. The implementation is in `scripts/prepare_ausgrid_profiles.py`, principally `PipelineConfig`, `aggregate_profiles`, `rank_days`, and `run_pipeline`. The persisted evidence is in `data_processed/ausgrid/ausgrid_halfhour_normalized.csv`, `ausgrid_daily_stress_ranking.csv`, `ausgrid_top_30_critical_days.csv`, and `ausgrid_pipeline_metadata.json`.

## Exact current method

For each accepted timestamp, general-consumption (GC) half-hour energy is converted from kWh to mean kW by division by 0.5 h, then averaged across accepted customers. The load factor is

\[
m_t = \frac{\overline{P}^{GC}_t}{\max_{\tau\in\text{three years}}\overline{P}^{GC}_{\tau}}.
\]

The global load normalizer is 2.7888628762541794 kW/customer, reached at `2011-02-05 18:00:00`.

When generator capacities exist, each customer's GG power is first divided by that customer's generator capacity, the resulting customer PV capacity factors are averaged at each timestamp, and that mean shape is divided by its fixed three-year maximum:

\[
\phi_t = \frac{\operatorname{mean}_c(P^{GG}_{c,t}/P^{rated}_{c})}
{\max_{\tau\in\text{three years}}\operatorname{mean}_c(P^{GG}_{c,\tau}/P^{rated}_{c})}.
\]

The global PV-shape normalizer is 0.823644701257353, reached at `2010-12-21 12:00:00`. The pipeline accepted 299 customers and requires at least 80% timestamp customer coverage after a 98% customer-completeness screen.

For each complete 48-interval day \(d\), the active-PV set is

\[
A_d=\{t\in d:\phi_t\ge 0.05\},
\]

and the current score is exactly

\[
S_d=\max_{t\in A_d}\frac{\phi_t}{\max(m_t,0.05)}.
\]

The critical interval is the half-hour attaining this maximum. Thus the ranking is an interval maximum, not a daily-energy ratio or another daily aggregate. Complete days are sorted first by descending \(S_d\), then by descending daily PV energy index; stable input order resolves any remaining tie. Yes: subject to the active-PV screen and denominator floor, the implemented criterion really is `max(phi_PV / m_load)`.

## Zero-load and small-denominator behavior

The `max(m_t, 0.05)` denominator makes the score finite at zero load and caps the possible ratio at 20 because `pv_profile <= 1`. The PV activity threshold excludes night and very small PV values.

In the persisted dataset there are 21,702 active-PV intervals, none has `load_multiplier < 0.05`, and the minimum is 0.14177029992684717. Consequently the floor does not alter any current interval ratio or selected score. The top-30 critical-interval load factors range well above the floor; the highest score uses load factor 0.15594037439888725 and PV factor 0.91495687390211622.

The formula is numerically finite and the current ranking is not inflated by denominator clipping. It is nevertheless structurally sensitive to a single half-hour outlier because it uses a maximum. A future dataset with load below the floor could also make several materially different load values indistinguishable at 0.05, while still permitting a score as high as 20.

No algorithm change is made in this audit. Before using this screen as the sole temporal reduction for S1, the proposed tests are:

1. a synthetic complete-day test proving the exact active-PV filter, floor, maximizing interval, and tie-break order;
2. zero-load and sub-floor-load cases proving finite scores and the expected `pv/0.05` result;
3. a persisted-data regression test reproducing all top-30 dates, scores, and critical timestamps;
4. a stability comparison against a predeclared robust companion score, either the 95th percentile of active-PV interval ratios or the maximum of a three-interval rolling-median ratio. Any day selected only by one isolated interval should be flagged, not silently removed.

## Current top 30

| Rank | Date | Stress score | Critical interval |
|---:|:---|---:|:---|
| 1 | 2012-10-15 | 5.867350757808 | 2012-10-15 13:00:00 |
| 2 | 2012-10-10 | 5.806024584358 | 2012-10-10 12:00:00 |
| 3 | 2012-12-06 | 5.682464696193 | 2012-12-06 13:00:00 |
| 4 | 2012-10-24 | 5.656689452050 | 2012-10-24 13:00:00 |
| 5 | 2012-10-23 | 5.651692211721 | 2012-10-23 13:00:00 |
| 6 | 2012-12-05 | 5.639888425497 | 2012-12-05 13:00:00 |
| 7 | 2012-09-10 | 5.634468085973 | 2012-09-10 11:30:00 |
| 8 | 2012-09-18 | 5.604165245940 | 2012-09-18 12:00:00 |
| 9 | 2011-09-22 | 5.591993608234 | 2011-09-22 11:00:00 |
| 10 | 2012-09-20 | 5.587388081956 | 2012-09-20 11:30:00 |
| 11 | 2012-09-05 | 5.559914557855 | 2012-09-05 11:00:00 |
| 12 | 2011-10-19 | 5.478603674743 | 2011-10-19 14:00:00 |
| 13 | 2012-11-12 | 5.458955235956 | 2012-11-12 11:00:00 |
| 14 | 2012-11-13 | 5.452494061651 | 2012-11-13 13:00:00 |
| 15 | 2010-10-20 | 5.452203539945 | 2010-10-20 14:00:00 |
| 16 | 2010-10-18 | 5.448374645571 | 2010-10-18 12:00:00 |
| 17 | 2012-09-24 | 5.418667275081 | 2012-09-24 11:30:00 |
| 18 | 2012-10-04 | 5.411784462051 | 2012-10-04 11:30:00 |
| 19 | 2011-09-21 | 5.401289868595 | 2011-09-21 11:30:00 |
| 20 | 2011-10-20 | 5.387766696466 | 2011-10-20 12:00:00 |
| 21 | 2010-12-21 | 5.385350239204 | 2010-12-21 12:30:00 |
| 22 | 2012-12-04 | 5.359641297747 | 2012-12-04 11:00:00 |
| 23 | 2012-10-03 | 5.333509950953 | 2012-10-03 11:00:00 |
| 24 | 2012-10-31 | 5.320758935995 | 2012-10-31 11:30:00 |
| 25 | 2013-02-06 | 5.319034798695 | 2013-02-06 13:30:00 |
| 26 | 2012-10-29 | 5.290522808900 | 2012-10-29 14:00:00 |
| 27 | 2012-10-25 | 5.286689903784 | 2012-10-25 11:30:00 |
| 28 | 2011-11-02 | 5.270883764113 | 2011-11-02 12:30:00 |
| 29 | 2011-09-07 | 5.269702150676 | 2011-09-07 11:30:00 |
| 30 | 2010-11-24 | 5.259528128312 | 2010-11-24 12:30:00 |

## Deduplicated candidate set

The union contains 32 unique days. The maximum-PV day `2010-12-21` is already rank 21. The maximum-load day `2011-02-05` and the minimum-active-PV-load day `2012-10-07` add two dates. The latter minimum occurs at 07:00 with PV factor 0.062137545466398623 and load factor 0.14177029992684717; its ratio-maximizing interval is separately reported as 14:00. Full per-day values and combined reasons are in `critical_day_candidates.csv`.
