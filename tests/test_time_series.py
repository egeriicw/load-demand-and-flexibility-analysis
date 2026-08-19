from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from load_profile.data_ingestion import load_demand_data
from load_profile.time_series import (
    apply_smoothing,
    assess_quality,
    regularize,
    segment_days,
)


def _regular_df(n=96, freq="15min", tz="America/Chicago", start="2024-01-15", value=100.0):
    idx = pd.date_range(start, periods=n, freq=freq, tz=tz)
    return pd.DataFrame(
        {
            "demand_kw": np.full(n, value, dtype=float),
            "demand_kw_raw": np.full(n, value, dtype=float),
        },
        index=idx,
    )


# ---------------------------------------------------------------------------
# regularize
# ---------------------------------------------------------------------------

class TestRegularize:
    def test_fully_observed_data_unchanged_in_length(self, cfg):
        df = _regular_df()
        out = regularize(df, 15, cfg)
        assert len(out) == len(df)
        assert out["is_observed"].all()
        assert not out["is_interpolated"].any()
        assert not out["is_missing"].any()

    def test_fills_short_gap_via_interpolation(self, cfg):
        df = _regular_df(n=20)
        # Remove 2 consecutive rows (30-min gap at 15-min resolution)
        gap_idx = df.index[[8, 9]]
        df = df.drop(gap_idx)
        out = regularize(df, 15, cfg)
        assert len(out) == 20
        assert out.loc[gap_idx, "is_interpolated"].all()
        assert not out.loc[gap_idx, "is_missing"].any()

    def test_long_gap_remains_missing(self, cfg):
        cfg["data_quality"]["max_interpolation_gap_minutes"] = 60
        df = _regular_df(n=40)
        # Drop 10 consecutive rows -> gap of 150 min, exceeds max
        gap_idx = df.index[10:20]
        df = df.drop(gap_idx)
        out = regularize(df, 15, cfg)
        assert out.loc[gap_idx, "is_missing"].all()
        assert not out.loc[gap_idx, "is_interpolated"].any()

    def test_negative_demand_treated_as_missing_then_interpolated(self, cfg):
        df = _regular_df(n=10)
        df.iloc[5, df.columns.get_loc("demand_kw")] = -5.0
        out = regularize(df, 15, cfg)
        ts = df.index[5]
        # Negative demand was NaN'd out then interpolated (bracketed by valid data)
        assert out.loc[ts, "demand_kw"] >= 0 or np.isnan(out.loc[ts, "demand_kw"])

    def test_interpolated_values_are_linear(self, cfg):
        idx = pd.date_range("2024-01-15", periods=5, freq="15min", tz="UTC")
        df = pd.DataFrame(
            {"demand_kw": [0.0, np.nan, np.nan, np.nan, 40.0]}, index=idx
        )
        out = regularize(df, 15, cfg)
        # Linear interpolation from 0 to 40 over 4 steps -> 10, 20, 30
        assert out["demand_kw"].iloc[1] == pytest.approx(10.0)
        assert out["demand_kw"].iloc[2] == pytest.approx(20.0)
        assert out["demand_kw"].iloc[3] == pytest.approx(30.0)

    def test_edge_gap_not_interpolated(self, cfg):
        idx = pd.date_range("2024-01-15", periods=5, freq="15min", tz="UTC")
        df = pd.DataFrame(
            {"demand_kw": [np.nan, 10.0, 20.0, 30.0, 40.0]}, index=idx
        )
        out = regularize(df, 15, cfg)
        assert np.isnan(out["demand_kw"].iloc[0])
        assert out["is_missing"].iloc[0]


# ---------------------------------------------------------------------------
# assess_quality
# ---------------------------------------------------------------------------

class TestAssessQuality:
    def test_fully_observed_day_is_good(self, cfg):
        df = _regular_df()
        reg = regularize(df, 15, cfg)
        q = assess_quality(reg, 15, cfg)
        assert q["completeness_fraction"] == 1.0
        assert q["quality_status"] == "GOOD"
        assert q["longest_missing_gap_minutes"] == 0.0

    def test_poor_quality_when_mostly_missing(self, cfg):
        idx = pd.date_range("2024-01-15", periods=96, freq="15min", tz="UTC")
        vals = np.full(96, np.nan)
        vals[:20] = 100.0
        df = pd.DataFrame({"demand_kw": vals}, index=idx)
        reg = regularize(df, 15, cfg)
        q = assess_quality(reg, 15, cfg)
        assert q["completeness_fraction"] < 0.5
        assert q["quality_status"] in ("POOR", "UNUSABLE")

    def test_unusable_when_almost_no_data(self, cfg):
        idx = pd.date_range("2024-01-15", periods=96, freq="15min", tz="UTC")
        vals = np.full(96, np.nan)
        vals[:5] = 100.0
        df = pd.DataFrame({"demand_kw": vals}, index=idx)
        reg = regularize(df, 15, cfg)
        q = assess_quality(reg, 15, cfg)
        assert q["quality_status"] == "UNUSABLE"

    def test_empty_day_handled(self, cfg):
        idx = pd.DatetimeIndex([], tz="UTC")
        df = pd.DataFrame(
            {"demand_kw": [], "is_observed": [], "is_interpolated": [], "is_missing": []},
            index=idx,
        )
        q = assess_quality(df, 15, cfg)
        assert q["expected_intervals"] == 0
        assert q["completeness_fraction"] == 0.0


# ---------------------------------------------------------------------------
# segment_days
# ---------------------------------------------------------------------------

class TestSegmentDays:
    def test_splits_by_calendar_day(self, cfg):
        idx = pd.date_range("2024-01-15", periods=192, freq="15min", tz="America/Chicago")
        df = pd.DataFrame({"demand_kw": np.arange(192, dtype=float)}, index=idx)
        days = segment_days(df)
        assert set(days.keys()) == {"2024-01-15", "2024-01-16"}
        assert len(days["2024-01-15"]) == 96
        assert len(days["2024-01-16"]) == 96

    def test_single_day(self, cfg):
        idx = pd.date_range("2024-01-15", periods=96, freq="15min", tz="UTC")
        df = pd.DataFrame({"demand_kw": np.arange(96, dtype=float)}, index=idx)
        days = segment_days(df)
        assert list(days.keys()) == ["2024-01-15"]


# ---------------------------------------------------------------------------
# apply_smoothing
# ---------------------------------------------------------------------------

class TestApplySmoothing:
    def test_none_method_returns_unchanged(self, cfg):
        cfg["smoothing"]["method"] = "none"
        s = pd.Series([1.0, 5.0, 2.0, 8.0, 3.0])
        out = apply_smoothing(s, cfg, 15)
        assert list(out) == list(s)
        assert out.name == "analysis_demand_kw"

    def test_rolling_median_smooths_spike(self, cfg):
        cfg["smoothing"]["method"] = "rolling_median"
        cfg["smoothing"]["window_minutes"] = 60
        idx = pd.date_range("2024-01-15", periods=20, freq="15min")
        vals = np.full(20, 100.0)
        vals[10] = 1000.0  # spike
        s = pd.Series(vals, index=idx)
        out = apply_smoothing(s, cfg, 15)
        assert out.iloc[10] < 1000.0

    def test_rolling_mean_method(self, cfg):
        cfg["smoothing"]["method"] = "rolling_mean"
        cfg["smoothing"]["window_minutes"] = 30
        idx = pd.date_range("2024-01-15", periods=10, freq="15min")
        s = pd.Series(np.full(10, 50.0), index=idx)
        out = apply_smoothing(s, cfg, 15)
        assert (out == 50.0).all()

    def test_output_named_correctly(self, cfg):
        idx = pd.date_range("2024-01-15", periods=10, freq="15min")
        s = pd.Series(np.full(10, 50.0), index=idx)
        out = apply_smoothing(s, cfg, 15)
        assert out.name == "analysis_demand_kw"


# ---------------------------------------------------------------------------
# DST handling (full-day, naive-local input, as real ingestion would see it)
# ---------------------------------------------------------------------------

def _tz_aware_full_day_df(day_start, day_end, tz, freq="15min", value=100.0, **kwargs):
    """Build a genuinely DST-correct full local calendar day (already tz-aware)."""
    idx = pd.date_range(day_start, day_end, freq=freq, tz=tz, inclusive="left", **kwargs)
    return pd.DataFrame({"datetime": idx, "demand_kw": np.full(len(idx), value, dtype=float)})


class TestDstHandling:
    def test_spring_forward_day_has_fewer_intervals(self, cfg):
        # 2024-03-10: US Central springs forward at 02:00 -> 03:00 (23-hour day).
        df_raw = _tz_aware_full_day_df("2024-03-10 00:00", "2024-03-11 00:00", "America/Chicago")
        assert len(df_raw) == 92
        df = load_demand_data(df_raw, cfg)
        reg = regularize(df, 15, cfg)
        days = segment_days(reg)
        day = next(iter(days.values()))
        q = assess_quality(day, 15, cfg)
        assert q["expected_intervals"] == 92

    def test_fall_back_day_has_more_intervals(self, cfg):
        # 2024-11-03: US Central falls back at 02:00 -> 01:00 (25-hour day).
        df_raw = _tz_aware_full_day_df(
            "2024-11-03 00:00", "2024-11-04 00:00", "America/Chicago", ambiguous="infer"
        )
        assert len(df_raw) == 100
        df = load_demand_data(df_raw, cfg)
        reg = regularize(df, 15, cfg)
        days = segment_days(reg)
        day = next(iter(days.values()))
        q = assess_quality(day, 15, cfg)
        assert q["expected_intervals"] == 100
