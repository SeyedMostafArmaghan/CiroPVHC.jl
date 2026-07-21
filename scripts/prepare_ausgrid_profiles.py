#!/usr/bin/env python3
"""Prepare reproducible half-hour Ausgrid load/PV profiles for CiroPVHC.jl.

Supported inputs
----------------
1. Original Ausgrid yearly files (daily wide format):
   - first metadata row is skipped automatically when needed;
   - columns include Customer, Consumption Category, date and 48 period columns;
   - GC = general consumption, GG = gross PV generation;
   - values are half-hour energy (kWh) and are converted to mean kW by ×2.
2. Already reshaped time-series CSV files with columns datetime (or unnamed index),
   GC and GG. These values are interpreted as kW unless --timeseries-values-are-kwh
   is supplied.

The script aggregates customers using the timestamp-wise mean, normalizes the
aggregate load and PV profiles using one fixed global maximum over the complete
input dataset, ranks complete days by max(phi_PV / max(m_load, epsilon)), and
exports the top-N critical days.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Iterable, Sequence

import numpy as np
import pandas as pd

TIME_LABEL_RE = re.compile(r"^(?:[01]?\d|2[0-4])[:.]?(?:00|30)$")
REQUIRED_CHANNELS = ("GC", "GG")


@dataclass(frozen=True)
class PipelineConfig:
    dt_hours: float = 0.5
    top_n_days: int = 30
    load_floor: float = 0.05
    pv_activity_threshold: float = 0.05
    min_customer_completeness: float = 0.98
    min_timestamp_customer_fraction: float = 0.80
    timeseries_values_are_kwh: bool = False


def _canonical_name(value: object) -> str:
    return str(value).strip().lower().replace("_", " ")


def _find_column(columns: Sequence[object], candidates: Iterable[str]) -> object | None:
    lookup = {_canonical_name(c): c for c in columns}
    for candidate in candidates:
        found = lookup.get(_canonical_name(candidate))
        if found is not None:
            return found
    return None


def _read_csv_with_header_detection(path: Path) -> pd.DataFrame:
    """Read a standard CSV or an original Ausgrid file with a leading notes row.

    Reading the notes row directly with pandas can trigger a field-count parser
    error, so the first few physical lines are inspected with the stdlib CSV
    parser before pandas is invoked.
    """
    with path.open("r", encoding="utf-8-sig", errors="replace", newline="") as handle:
        candidate_lines = [handle.readline() for _ in range(4)]
    header_row = 0
    for row_number, line in enumerate(candidate_lines):
        if not line:
            break
        fields = next(csv.reader([line]))
        normalized = {_canonical_name(field) for field in fields}
        if "customer" in normalized and ("consumption category" in normalized or "channel" in normalized):
            header_row = row_number
            break
        if "gc" in normalized and "gg" in normalized:
            header_row = row_number
            break
    return pd.read_csv(path, skiprows=header_row, encoding_errors="replace")


def _period_columns(columns: Sequence[object]) -> list[object]:
    result: list[object] = []
    for col in columns:
        text = str(col).strip()
        if TIME_LABEL_RE.match(text):
            result.append(col)
    if len(result) == 48:
        return result

    # Fallback compatible with the original dataset layout used by Haessig:
    # metadata columns 0:5, then 48 intervals, then Row Quality.
    if len(columns) >= 54:
        middle = list(columns[5:-1])
        if len(middle) == 48:
            return middle
    raise ValueError(f"Expected 48 half-hour period columns; found {len(result)}")


def _interval_start(base_date: pd.Timestamp, slot: int) -> pd.Timestamp:
    return base_date.normalize() + timedelta(minutes=30 * slot)


def _parse_ausgrid_dates(values: pd.Series) -> pd.Series:
    """Parse the two date conventions used across the three source years."""
    text = values.astype("string").str.strip()
    parsed = pd.Series(pd.NaT, index=values.index, dtype="datetime64[ns]")
    for date_format in ("%d/%m/%Y", "%d-%b-%y"):
        missing = parsed.isna()
        parsed.loc[missing] = pd.to_datetime(
            text.loc[missing], format=date_format, errors="coerce"
        )
    return parsed


def parse_original_ausgrid(path: Path, config: PipelineConfig) -> tuple[pd.DataFrame, dict]:
    raw = _read_csv_with_header_detection(path)
    customer_col = _find_column(raw.columns, ["Customer"])
    channel_col = _find_column(raw.columns, ["Consumption Category", "Channel"])
    date_col = _find_column(raw.columns, ["date", "Date"])
    capacity_col = _find_column(raw.columns, ["Generator Capacity", "PV Capacity", "Capacity"])
    if customer_col is None or channel_col is None or date_col is None:
        raise ValueError(f"{path} does not look like an original Ausgrid yearly CSV")

    periods = _period_columns(raw.columns)
    raw[date_col] = _parse_ausgrid_dates(raw[date_col])
    raw[channel_col] = raw[channel_col].astype(str).str.strip().str.upper()
    raw = raw[raw[channel_col].isin(REQUIRED_CHANNELS) & raw[date_col].notna()].copy()

    capacity_values = (
        pd.to_numeric(raw[capacity_col], errors="coerce")
        if capacity_col is not None
        else pd.Series(np.nan, index=raw.index)
    )
    records: list[pd.DataFrame] = []
    missing_power_observations = 0
    negative_power_observations = 0
    for slot, period_col in enumerate(periods):
        values = pd.to_numeric(raw[period_col], errors="coerce")
        missing_power_observations += int(values.isna().sum())
        negative_power_observations += int((values < 0).sum())
        piece = pd.DataFrame(
            {
                "datetime": raw[date_col].map(lambda d: _interval_start(d, slot)),
                "customer": raw[customer_col].astype(str).str.strip(),
                "channel": raw[channel_col],
                "power_kw": values * (1.0 / config.dt_hours),
                "generator_capacity_kw": capacity_values,
            }
        )
        records.append(piece)
    long = pd.concat(records, ignore_index=True)
    long = long.sort_values(["customer", "channel", "datetime"], kind="stable")
    metadata = {
        "source_file": str(path),
        "input_format": "original_ausgrid_daily_wide",
        "raw_rows": int(len(raw)),
        "customers": int(raw[customer_col].nunique()),
        "channels": sorted(raw[channel_col].unique().tolist()),
        "channel_row_counts": {str(k): int(v) for k, v in raw[channel_col].value_counts().items()},
        "date_start": str(raw[date_col].min().date()),
        "date_end": str(raw[date_col].max().date()),
        "period_columns": [str(c) for c in periods],
        "unit_conversion": f"kWh per interval divided by dt={config.dt_hours} h",
        "missing_power_observations": missing_power_observations,
        "negative_power_observations": negative_power_observations,
    }
    return long, metadata


def parse_timeseries(path: Path, config: PipelineConfig) -> tuple[pd.DataFrame, dict]:
    raw = _read_csv_with_header_detection(path)
    gc_col = _find_column(raw.columns, ["GC"])
    gg_col = _find_column(raw.columns, ["GG"])
    if gc_col is None or gg_col is None:
        raise ValueError(f"{path} has neither original Ausgrid structure nor GC/GG columns")

    dt_col = _find_column(raw.columns, ["datetime", "timestamp", "date"])
    if dt_col is None:
        dt_col = raw.columns[0]
    timestamps = pd.to_datetime(raw[dt_col], errors="coerce")
    factor = 1.0 / config.dt_hours if config.timeseries_values_are_kwh else 1.0
    pieces = []
    for channel, col in (("GC", gc_col), ("GG", gg_col)):
        pieces.append(
            pd.DataFrame(
                {
                    "datetime": timestamps,
                    "customer": path.stem,
                    "channel": channel,
                    "power_kw": pd.to_numeric(raw[col], errors="coerce") * factor,
                    "generator_capacity_kw": np.nan,
                }
            )
        )
    long = pd.concat(pieces, ignore_index=True).dropna(subset=["datetime"])
    metadata = {
        "source_file": str(path),
        "input_format": "reshaped_timeseries",
        "raw_rows": int(len(raw)),
        "unit_conversion": "kWh to kW" if config.timeseries_values_are_kwh else "none; input assumed kW",
    }
    return long, metadata


def parse_input(path: Path, config: PipelineConfig) -> tuple[pd.DataFrame, dict]:
    raw = _read_csv_with_header_detection(path)
    if _find_column(raw.columns, ["Customer"]) is not None:
        return parse_original_ausgrid(path, config)
    return parse_timeseries(path, config)


def validate_halfhour_grid(long: pd.DataFrame, dt_hours: float) -> None:
    if long.empty:
        raise ValueError("No usable GC/GG observations found")
    expected = timedelta(hours=dt_hours)
    for (_, _), group in long.groupby(["customer", "channel"], sort=False):
        times = group["datetime"].drop_duplicates().sort_values()
        if len(times) < 2:
            continue
        deltas = times.diff().dropna()
        bad = deltas[(deltas != expected) & (deltas < timedelta(days=1))]
        if not bad.empty:
            raise ValueError(f"Non-{expected} interval detected: {bad.iloc[0]}")


def filter_customers(long: pd.DataFrame, config: PipelineConfig) -> tuple[pd.DataFrame, pd.DataFrame]:
    pivot = long.pivot_table(index="datetime", columns=["customer", "channel"], values="power_kw", aggfunc="mean")
    all_timestamps = pivot.index
    rows = []
    keep: list[str] = []
    customers = sorted(set(pivot.columns.get_level_values("customer")))
    for customer in customers:
        channel_stats = {}
        present_channels = set()
        for channel in REQUIRED_CHANNELS:
            if (customer, channel) in pivot.columns:
                present_channels.add(channel)
                completeness = float(pivot[(customer, channel)].notna().sum() / len(all_timestamps))
            else:
                completeness = 0.0
            channel_stats[channel] = completeness
        reasons = []
        missing_channels = sorted(set(REQUIRED_CHANNELS) - present_channels)
        if missing_channels:
            reasons.append(f"missing {'/'.join(missing_channels)} channel")
        for channel in REQUIRED_CHANNELS:
            if channel in present_channels and channel_stats[channel] < config.min_customer_completeness:
                reasons.append(
                    f"{channel} completeness {channel_stats[channel]:.6f} below "
                    f"{config.min_customer_completeness:.6f}"
                )
        accepted = not reasons
        rows.append(
            {
                "customer": customer,
                "gc_completeness": channel_stats["GC"],
                "gg_completeness": channel_stats["GG"],
                "accepted": accepted,
                "rejection_reason": "" if accepted else "; ".join(reasons),
            }
        )
        if accepted:
            keep.append(customer)
    report = pd.DataFrame(rows)
    if not keep:
        raise ValueError("No customer has both GC and GG at the required completeness threshold")
    return long[long["customer"].isin(keep)].copy(), report


def aggregate_profiles(long: pd.DataFrame, config: PipelineConfig) -> pd.DataFrame:
    by_channel = long.pivot_table(index="datetime", columns=["customer", "channel"], values="power_kw", aggfunc="mean")
    customers = sorted(set(by_channel.columns.get_level_values("customer")))
    minimum_count = max(1, math.ceil(config.min_timestamp_customer_fraction * len(customers)))

    output = pd.DataFrame(index=by_channel.index.sort_values())

    gc_columns = [c for c in by_channel.columns if c[1] == "GC"]
    gc_values = by_channel[gc_columns]
    gc_counts = gc_values.notna().sum(axis=1)
    output["load_kw_mean"] = gc_values.mean(axis=1, skipna=True).where(gc_counts >= minimum_count)
    output["gc_customer_count"] = gc_counts

    gg_long = long[long["channel"] == "GG"].copy()
    has_capacity = gg_long["generator_capacity_kw"].notna() & (gg_long["generator_capacity_kw"] > 0)
    if has_capacity.any():
        gg_long = gg_long[has_capacity].copy()
        gg_long["pv_shape_value"] = gg_long["power_kw"] / gg_long["generator_capacity_kw"]
        pv_basis = "customer PV capacity factor (GG kW / generator capacity kW)"
    else:
        gg_long["pv_shape_value"] = gg_long["power_kw"]
        pv_basis = "GG power; generator capacities unavailable"
    pv_wide = gg_long.pivot_table(
        index="datetime", columns="customer", values="pv_shape_value", aggfunc="mean"
    ).reindex(output.index)
    pv_counts = pv_wide.notna().sum(axis=1)
    pv_minimum_count = max(1, math.ceil(config.min_timestamp_customer_fraction * max(1, len(pv_wide.columns))))
    output["pv_shape_mean"] = pv_wide.mean(axis=1, skipna=True).where(pv_counts >= pv_minimum_count)
    output["gg_customer_count"] = pv_counts
    output.attrs["pv_basis"] = pv_basis

    output = output.dropna(subset=["load_kw_mean", "pv_shape_mean"]).reset_index()
    output["load_kw_mean"] = output["load_kw_mean"].clip(lower=0.0)
    output["pv_shape_mean"] = output["pv_shape_mean"].clip(lower=0.0)
    if output.empty:
        raise ValueError("Aggregation produced no timestamps after completeness filtering")

    load_peak = float(output["load_kw_mean"].max())
    pv_peak = float(output["pv_shape_mean"].max())
    if load_peak <= 0 or pv_peak <= 0:
        raise ValueError(f"Nonpositive global peak(s): load={load_peak}, PV={pv_peak}")
    output["load_multiplier"] = output["load_kw_mean"] / load_peak
    output["pv_profile"] = output["pv_shape_mean"] / pv_peak
    output["date"] = output["datetime"].dt.date.astype(str)
    output["slot"] = output["datetime"].dt.hour * 2 + output["datetime"].dt.minute // 30
    return output.sort_values("datetime", kind="stable").reset_index(drop=True)


def rank_days(profiles: pd.DataFrame, config: PipelineConfig) -> pd.DataFrame:
    rows = []
    for date, day in profiles.groupby("date", sort=True):
        day = day.sort_values("slot")
        complete = len(day) == 48 and set(day["slot"].astype(int)) == set(range(48))
        active = day["pv_profile"] >= config.pv_activity_threshold
        if active.any():
            ratios = day.loc[active, "pv_profile"] / day.loc[active, "load_multiplier"].clip(lower=config.load_floor)
            idx = ratios.idxmax()
            score = float(ratios.loc[idx])
            critical_slot = int(day.loc[idx, "slot"])
            critical_time = str(day.loc[idx, "datetime"])
        else:
            score = 0.0
            critical_slot = -1
            critical_time = ""
        rows.append(
            {
                "date": date,
                "complete_48_intervals": complete,
                "stress_index": score,
                "critical_slot": critical_slot,
                "critical_time": critical_time,
                "daily_pv_energy_index": float(day["pv_profile"].sum() * config.dt_hours),
                "daily_load_energy_index": float(day["load_multiplier"].sum() * config.dt_hours),
                "max_pv_profile": float(day["pv_profile"].max()),
                "min_load_multiplier_during_active_pv": float(day.loc[active, "load_multiplier"].min()) if active.any() else np.nan,
            }
        )
    ranking = pd.DataFrame(rows)
    ranking = ranking[ranking["complete_48_intervals"]].sort_values(
        ["stress_index", "daily_pv_energy_index"], ascending=[False, False], kind="stable"
    )
    ranking.insert(0, "rank", range(1, len(ranking) + 1))
    return ranking.reset_index(drop=True)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run_pipeline(inputs: Sequence[Path], output_dir: Path, config: PipelineConfig) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    parsed = []
    input_metadata = []
    for path in inputs:
        frame, metadata = parse_input(path, config)
        metadata["filename"] = path.name
        metadata["size_bytes"] = path.stat().st_size
        metadata["sha256"] = _sha256(path)
        frame["source_file"] = path.name
        parsed.append(frame)
        input_metadata.append(metadata)
    long = pd.concat(parsed, ignore_index=True)
    long = long.drop_duplicates(subset=["datetime", "customer", "channel"], keep="last")
    validate_halfhour_grid(long, config.dt_hours)
    clean, customer_report = filter_customers(long, config)
    profiles = aggregate_profiles(clean, config)
    ranking = rank_days(profiles, config)
    if ranking.empty:
        raise ValueError("No complete 48-interval days available for ranking")

    top_dates = set(ranking.head(config.top_n_days)["date"])
    top_profiles = profiles[profiles["date"].isin(top_dates)].merge(
        ranking[["rank", "date", "stress_index"]], on="date", how="left"
    ).sort_values(["rank", "slot"], kind="stable")

    profiles.to_csv(output_dir / "ausgrid_halfhour_normalized.csv", index=False)
    ranking.to_csv(output_dir / "ausgrid_daily_stress_ranking.csv", index=False)
    top_profiles.to_csv(output_dir / f"ausgrid_top_{config.top_n_days}_critical_days.csv", index=False)
    customer_report.to_csv(output_dir / "ausgrid_customer_quality.csv", index=False)

    metadata = {
        "created_utc": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "citation": {
            "authors": "Ratnam, Weller, Kellett, Murray",
            "title": "Residential load and rooftop PV generation: an Australian distribution network dataset",
            "journal": "International Journal of Sustainable Energy",
            "doi": "10.1080/14786451.2015.1100196",
        },
        "config": asdict(config),
        "input_files": input_metadata,
        "accepted_customers": int(customer_report["accepted"].sum()),
        "rejected_customers": int((~customer_report["accepted"]).sum()),
        "rejection_reasons": {
            str(reason): int(count)
            for reason, count in customer_report.loc[
                ~customer_report["accepted"], "rejection_reason"
            ].value_counts().items()
        },
        "pv_shape_basis": (
            "customer PV capacity factor"
            if (clean.loc[clean["channel"] == "GG", "generator_capacity_kw"].fillna(0) > 0).any()
            else "GG power normalized by global maximum (capacity unavailable)"
        ),
        "normalized_rows": int(len(profiles)),
        "complete_ranked_days": int(len(ranking)),
        "top_day": ranking.iloc[0].to_dict(),
        "normalization": {
            "load": "aggregate timestamp-wise customer mean divided by its global maximum over all input years",
            "pv": "mean customer PV capacity factor when generator capacities exist; otherwise mean GG power; then divided by its global maximum over all input years",
            "day_stress": "max over active-PV slots of pv_profile / max(load_multiplier, load_floor)",
        },
        "important_scope_note": "Ausgrid supplies temporal shapes only; absolute bus loads remain from case33bw.",
    }
    with (output_dir / "ausgrid_pipeline_metadata.json").open("w", encoding="utf-8") as handle:
        json.dump(metadata, handle, indent=2, ensure_ascii=False, default=str)
    return metadata


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("inputs", nargs="+", type=Path, help="Original yearly Ausgrid CSVs or reshaped GC/GG CSVs")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--top-n-days", type=int, default=30)
    parser.add_argument("--load-floor", type=float, default=0.05)
    parser.add_argument("--pv-activity-threshold", type=float, default=0.05)
    parser.add_argument("--min-customer-completeness", type=float, default=0.98)
    parser.add_argument("--min-timestamp-customer-fraction", type=float, default=0.80)
    parser.add_argument("--timeseries-values-are-kwh", action="store_true")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    config = PipelineConfig(
        top_n_days=args.top_n_days,
        load_floor=args.load_floor,
        pv_activity_threshold=args.pv_activity_threshold,
        min_customer_completeness=args.min_customer_completeness,
        min_timestamp_customer_fraction=args.min_timestamp_customer_fraction,
        timeseries_values_are_kwh=args.timeseries_values_are_kwh,
    )
    metadata = run_pipeline(args.inputs, args.output_dir, config)
    print(json.dumps(metadata, indent=2, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
