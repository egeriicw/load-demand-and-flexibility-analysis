from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from load_profile.der.patterns import (
    build_daily_summary,
    find_outlier_days,
    find_recurring_peak_timing,
    find_recurring_shape,
)


def _day(date, peak_hour=8, peak_value=100.0, base_value=10.0, complete=True):
    idx = pd.date_range(date, periods=24, freq="60min", tz="UTC")
    vals = np.full(24, base_value)
    vals[peak_hour] = peak_value
    df = pd.DataFrame({"demand_kw": vals}, index=idx)
    if not complete:
        df = df.iloc[:20]  # drop the tail -> incomplete day
    return df


class TestBuildDailySummary:
    def test_complete_day_flagged(self):
        summary = build_daily_summary(_day("2024-01-15"))
        assert summary["is_complete_day"].iloc[0] == True  # noqa: E712

    def test_incomplete_day_flagged(self):
        summary = build_daily_summary(_day("2024-01-15", complete=False))
        assert summary["is_complete_day"].iloc[0] == False  # noqa: E712

    def test_peak_time_minutes_matches_peak_hour(self):
        summary = build_daily_summary(_day("2024-01-15", peak_hour=14))
        assert summary["peak_time_minutes"].iloc[0] == 14 * 60

    def test_daily_energy_matches_expected(self):
        # 23 hours at 10kW + 1 hour at 100kW, 60-min resolution -> energy = 23*10 + 100
        summary = build_daily_summary(_day("2024-01-15", base_value=10.0, peak_value=100.0))
        assert summary["maximum_demand_kw"].iloc[0] == 100.0
        assert summary["daily_energy_kwh"].iloc[0] == pytest.approx(23 * 10 + 100)


class TestFindRecurringPeakTiming:
    def test_recurring_bucket_reported(self, cfg):
        cfg["der"]["patterns"]["min_occurrences"] = 3
        days = pd.concat([
            build_daily_summary(_day(f"2024-01-{d}", peak_hour=8)) for d in range(15, 20)
        ], ignore_index=True)
        out = find_recurring_peak_timing(days, cfg)
        assert len(out) == 1
        assert out.iloc[0]["n_days"] == 5
        assert out.iloc[0]["statistical_support"] == pytest.approx(1.0)

    def test_below_min_occurrences_not_reported(self, cfg):
        cfg["der"]["patterns"]["min_occurrences"] = 3
        days = pd.concat([
            build_daily_summary(_day("2024-01-15", peak_hour=8)),
            build_daily_summary(_day("2024-01-16", peak_hour=14)),
        ], ignore_index=True)
        out = find_recurring_peak_timing(days, cfg)
        assert len(out) == 0

    def test_incomplete_days_excluded(self, cfg):
        cfg["der"]["patterns"]["min_occurrences"] = 1
        days = pd.concat([
            build_daily_summary(_day("2024-01-15", complete=False)),
        ], ignore_index=True)
        out = find_recurring_peak_timing(days, cfg)
        assert len(out) == 0


class TestFindRecurringShape:
    def test_excludes_insufficient_data(self, cfg):
        cfg["der"]["patterns"]["min_occurrences"] = 1
        days = pd.concat([
            build_daily_summary(_day(d)) for d in ("2024-01-15", "2024-01-16")
        ], ignore_index=True)
        days["der_primary_shape"] = ["insufficient_data", "flat"]
        out = find_recurring_shape(days, cfg)
        assert "insufficient_data" not in out["primary_shape"].tolist()

    def test_missing_shape_column_returns_empty(self, cfg):
        days = build_daily_summary(_day("2024-01-15"))
        out = find_recurring_shape(days, cfg)
        assert len(out) == 0


class TestFindOutlierDays:
    def test_fewer_than_min_days_returns_empty(self, cfg):
        cfg["der"]["patterns"]["min_days_for_outliers"] = 5
        days = pd.concat([build_daily_summary(_day(f"2024-01-{d}")) for d in (15, 16, 17)],
                          ignore_index=True)
        out = find_outlier_days(days, cfg)
        assert len(out) == 0

    def test_outlier_energy_day_flagged(self, cfg):
        cfg["der"]["patterns"]["min_days_for_outliers"] = 5
        cfg["der"]["patterns"]["outlier_z_threshold"] = 1.5
        frames = [build_daily_summary(_day(f"2024-01-{d}", peak_value=100.0)) for d in range(15, 20)]
        # inject one very high-energy day
        spike = build_daily_summary(_day("2024-01-25", peak_value=100.0, base_value=500.0))
        days = pd.concat(frames + [spike], ignore_index=True)
        out = find_outlier_days(days, cfg)
        assert (out["metric"] == "daily_energy_kwh").any()
