# S1-B DST / timestamp audit of the Ausgrid half-hour profile

Scope: an audit of how daylight-saving-time (DST) transitions appear in the
processed profile `data_processed/ausgrid/ausgrid_halfhour_normalized.csv`
(52,608 half-hour intervals, 1,096 complete days). Read-only: **no data was
changed, padded, interpolated, deduplicated, or timezone-converted by this
audit.** It records what the data already contains so that later
curtailment-ratio work rests on a documented denominator.

## Findings

### 1. Timestamps are local wall-clock and timezone-naive

The `datetime` column has dtype `datetime64[ns]` with `tz = None`. Timestamps
are constructed in `scripts/prepare_ausgrid_profiles.py` (`_interval_start`) as
`base_date.normalize() + timedelta(minutes=30 * slot)`, i.e. a plain local wall
clock with no UTC offset and no timezone attached. The source Ausgrid files store
each day as a fixed grid of 48 half-hour slot columns, so every calendar day —
including DST-transition days — carries exactly 48 intervals.

### 2. The pipeline introduces no new padding or interpolation

The preprocessing pipeline performs no timezone conversion, no reindexing onto a
regular grid, no `fillna`, and no interpolation. The only two loosely related
operations are:

- `drop_duplicates(subset=["datetime", "customer", "channel"], keep="last")` —
  inert here, because the source contains no duplicate (datetime, customer,
  channel) rows;
- `validate_halfhour_grid`, which excludes gaps `>= 1 day` from its spacing check.

Across the whole series there are **0 duplicated timestamps** and **0 missing
timestamps** relative to a regular 30-minute grid.

### 3. The DST behaviour is inherited from the 48-slot dataset format

Because each source day is a 48-slot row, the dataset absorbs both DST
transitions into that fixed grid rather than adding or removing intervals:

**DST start (first Sunday of October; local 02:00–03:00 does not exist).**
The two affected slots are recorded as exactly zero for **all** customers in the
raw files, so the processed profile shows load = 0 and PV = 0 there. These are
data-native zeros, not padding:

| global_index | timestamp (local)      | load | PV |
|-------------:|------------------------|------|----|
| 4517, 4518   | 2010-10-03 02:00, 02:30 | 0    | 0  |
| 21989, 21990 | 2011-10-02 02:00, 02:30 | 0    | 0  |
| 39797, 39798 | 2012-10-07 02:00, 02:30 | 0    | 0  |

These are the only six intervals in the entire series with load = 0 **and**
PV = 0 simultaneously.

**DST end (first Sunday of April; local 02:00–03:00 occurs twice).**
The 48-slot format has no room for the extra hour, and the source has folded the
repeated hour into slots 4 and 5. The processed load at those two intervals is
therefore roughly double the same-slot median on all three DST-end days:

| timestamp (local)      | load_kW | same-slot median | ratio |
|------------------------|---------|------------------|-------|
| 2011-04-03 02:00       | 0.7202  | 0.3802           | 1.89× |
| 2011-04-03 02:30       | 0.6950  | 0.3733           | 1.86× |
| 2012-04-01 02:00       | 0.7353  | 0.3802           | 1.93× |
| 2012-04-01 02:30       | 0.7272  | 0.3733           | 1.95× |
| 2013-04-07 02:00       | 0.7407  | 0.3802           | 1.95× |
| 2013-04-07 02:30       | 0.7239  | 0.3733           | 1.94× |

The energy is (approximately) conserved — two hours of consumption attributed to
one nominal hour — but the instantaneous power at those two intervals is about 2×
the physical level.

### 4. Effect on annual energy is negligible, especially for PV

Over the three-year record:

- excess load energy from the DST-end folding: **1.04 kWh**, i.e. **0.00597%** of
  the 17,425.4 kWh three-year load energy;
- excess PV energy: **1.9e-4 kWh**, i.e. **0.00001%** of the 3,780.0 kWh three-year
  PV energy.

All twelve DST-affected intervals sit between 02:00 and 03:00 local (night), where
PV availability is ~0 regardless (max `pv_profile` among them is 2.6e-4). Their
share of each dataset year's available PV energy — the denominator of any
curtailment ratio — is **0.0000131% / 0.0000127% / 0.0000094%** for
2010-2011 / 2011-2012 / 2012-2013. The PV curtailment denominator is therefore
effectively unaffected.

Per dataset year (1 July – 30 June), available PV and load energy:

| dataset year | intervals | Σ pv_profile · 0.5 | Σ load_mult · 0.5 |
|--------------|-----------|--------------------|-------------------|
| 2010–2011    | 17,520    | 1520.4549          | 2185.7682         |
| 2011–2012    | 17,568    | 1493.7262          | 2057.4049         |
| 2012–2013    | 17,520    | 1575.1776          | 2005.0538         |

### Baseline voltage cross-check of the six doubled DST-end intervals

Under the zero-PV baseline power flow, the six doubled-load DST-end intervals
have minimum bus voltage ~0.978–0.979 p.u. (all at bus 18), so **none** of them
fall within the 336 intervals that dip below 0.95 p.u. The doubling occurs at
night, far from the load peak, so it does not create undervoltage.

## Decision

The data is **left unchanged for now.** This audit only documents the DST
behaviour and quantifies its (negligible) effect on the annual energy
denominator. Any correction — deciding whether to keep, drop, or re-attribute the
DST-transition intervals — is deferred and must be made explicitly, not silently.

## Reproduction

The audit scripts are kept in the session scratchpad (outside the repository):
`dst_audit.py` (processed profile), `dst_raw_audit.py` (raw Ausgrid files at the
DST slots), and `dst_quantify.py` (energy quantification). They read
`data_processed/ausgrid/ausgrid_halfhour_normalized.csv`, the three raw
`Solar home *.csv` files, and `results/baseline_voltage_band/`.
