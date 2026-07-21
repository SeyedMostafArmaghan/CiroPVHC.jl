from pathlib import Path
import sys

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from prepare_ausgrid_profiles import PipelineConfig, filter_customers, parse_timeseries, run_pipeline


def make_leap_year_sample(path: Path) -> Path:
    timestamps = pd.date_range("2011-07-01", periods=366 * 48, freq="30min")
    hours = timestamps.hour + timestamps.minute / 60
    frame = pd.DataFrame(
        {
            "datetime": timestamps,
            "GC": 0.75 + abs(hours - 13.0) / 24.0,
            "GG": ((hours >= 6.0) & (hours <= 18.0)) * (1.0 - abs(hours - 12.0) / 6.5),
        }
    )
    frame.to_csv(path, index=False)
    return path


def test_sample_is_full_leap_year_halfhour_series(tmp_path):
    sample = make_leap_year_sample(tmp_path / "data_2011-2012_customer12.csv")
    frame, metadata = parse_timeseries(sample, PipelineConfig())
    assert metadata["input_format"] == "reshaped_timeseries"
    assert frame["datetime"].nunique() == 366 * 48
    assert set(frame["channel"]) == {"GC", "GG"}


def test_pipeline_normalizes_and_ranks_complete_days(tmp_path):
    sample = make_leap_year_sample(tmp_path / "data_2011-2012_customer12.csv")
    metadata = run_pipeline([sample], tmp_path, PipelineConfig(top_n_days=30))
    profiles = pd.read_csv(tmp_path / "ausgrid_halfhour_normalized.csv")
    ranking = pd.read_csv(tmp_path / "ausgrid_daily_stress_ranking.csv")
    top = pd.read_csv(tmp_path / "ausgrid_top_30_critical_days.csv")

    assert len(profiles) == 366 * 48
    assert profiles.groupby("date").size().eq(48).all()
    assert 0 <= profiles["load_multiplier"].min() <= profiles["load_multiplier"].max() <= 1.0 + 1e-12
    assert 0 <= profiles["pv_profile"].min() <= profiles["pv_profile"].max() <= 1.0 + 1e-12
    assert abs(profiles["load_multiplier"].max() - 1.0) < 1e-12
    assert abs(profiles["pv_profile"].max() - 1.0) < 1e-12
    assert len(ranking) == 366
    assert ranking["stress_index"].is_monotonic_decreasing
    assert len(top) == 30 * 48
    assert metadata["complete_ranked_days"] == 366


def test_original_daily_wide_parser_converts_kwh_to_kw(tmp_path):
    source = tmp_path / "original.csv"
    periods = [f"{h}:{m:02d}" for h in range(24) for m in (30, 0)]
    # Use unique labels in chronological period-ending order: 0:30, 1:00, ... 24:00.
    periods = []
    for slot in range(1, 49):
        minutes = slot * 30
        periods.append(f"{minutes // 60}:{minutes % 60:02d}")
    header = ["Customer", "Generator Capacity", "Postcode", "Consumption Category", "date", *periods, "Row Quality"]
    rows = ["Ausgrid test fixture", ",".join(header)]
    for channel, value in (("GC", "0.5"), ("GG", "0.25")):
        rows.append(",".join(["1", "2.0", "2000", channel, "1-Jul-10", *([value] * 48), ""] ))
    source.write_text("\n".join(rows), encoding="utf-8")

    from prepare_ausgrid_profiles import parse_original_ausgrid
    frame, metadata = parse_original_ausgrid(source, PipelineConfig(min_customer_completeness=1.0))
    assert metadata["input_format"] == "original_ausgrid_daily_wide"
    assert len(frame) == 96
    assert frame.loc[frame["channel"] == "GC", "power_kw"].eq(1.0).all()
    assert frame.loc[frame["channel"] == "GG", "power_kw"].eq(0.5).all()
    assert frame["datetime"].nunique() == 48


def test_original_pipeline_uses_capacity_factor_for_pv_shape(tmp_path):
    source = tmp_path / "original_two_customers.csv"
    periods = []
    for slot in range(1, 49):
        minutes = slot * 30
        periods.append(f"{minutes // 60}:{minutes % 60:02d}")
    header = ["Customer", "Generator Capacity", "Postcode", "Consumption Category", "date", *periods, "Row Quality"]
    rows = ["Ausgrid test fixture", ",".join(header)]
    # Both systems operate at 0.5 per-unit despite different capacities.
    for customer, capacity, gg_energy in (("1", "2.0", "0.5"), ("2", "4.0", "1.0")):
        rows.append(",".join([customer, capacity, "2000", "GC", "01/07/2011", *(["0.5"] * 48), ""]))
        rows.append(",".join([customer, capacity, "2000", "GG", "01/07/2011", *([gg_energy] * 48), ""]))
    source.write_text("\n".join(rows), encoding="utf-8")

    run_pipeline([source], tmp_path / "out", PipelineConfig(top_n_days=1, min_customer_completeness=1.0))
    profiles = pd.read_csv(tmp_path / "out" / "ausgrid_halfhour_normalized.csv")
    # Raw energy 0.5/1.0 kWh -> 1/2 kW; divided by 2/4 kW => both 0.5 p.u.
    assert profiles["pv_shape_mean"].eq(0.5).all()
    assert profiles["pv_profile"].eq(1.0).all()


def test_customer_quality_records_explicit_rejection_reason():
    long = pd.DataFrame(
        {
            "datetime": pd.to_datetime(["2011-07-01 00:00"] * 3),
            "customer": ["complete", "complete", "missing-pv"],
            "channel": ["GC", "GG", "GC"],
            "power_kw": [1.0, 0.5, 1.0],
            "generator_capacity_kw": [2.0, 2.0, 2.0],
        }
    )

    _, report = filter_customers(long, PipelineConfig(min_customer_completeness=1.0))

    rejected = report.loc[report["customer"] == "missing-pv"].iloc[0]
    assert not bool(rejected["accepted"])
    assert rejected["rejection_reason"] == "missing GG channel"
