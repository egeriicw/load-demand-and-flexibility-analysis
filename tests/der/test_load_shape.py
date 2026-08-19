from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from load_profile.der.calendar_features import add_time_of_day_segments
from load_profile.der.load_shape import classify_load_shape


def _flat_day_frame(date="2024-01-15", value=100.0, tz="UTC"):
    idx = pd.date_range(date, periods=24, freq="60min", tz=tz)
    return pd.DataFrame({"demand_kw": np.full(24, value)}, index=idx)


def _morning_peak_day_frame(date="2024-01-15", tz="UTC"):
    idx = pd.date_range(date, periods=24, freq="60min", tz=tz)
    vals = np.full(24, 10.0)
    vals[7] = 100.0  # sharp morning spike at 7am
    return pd.DataFrame({"demand_kw": vals}, index=idx)


class TestClassifyLoadShape:
    def test_flat_day_is_flat(self, cfg):
        df = _flat_day_frame()
        tod = add_time_of_day_segments(df, cfg)
        out = classify_load_shape(df, tod, cfg)
        assert out.iloc[0]["is_flat"] == True  # noqa: E712
        assert out.iloc[0]["der_primary_shape"] == "flat"

    def test_sharp_morning_spike_is_morning_peak(self, cfg):
        df = _morning_peak_day_frame()
        tod = add_time_of_day_segments(df, cfg)
        out = classify_load_shape(df, tod, cfg)
        row = out.iloc[0]
        assert row["is_highly_peaked"] == True  # noqa: E712
        assert row["has_morning_peak"] == True  # noqa: E712
        assert row["der_primary_shape"] == "morning_peak"

    def test_insufficient_data_day_flagged_unusual(self, cfg):
        idx = pd.date_range("2024-01-15", periods=4, freq="60min", tz="UTC")
        df = pd.DataFrame({"demand_kw": [10.0, 20.0, 30.0, 40.0]}, index=idx)
        tod = add_time_of_day_segments(df, cfg)
        out = classify_load_shape(df, tod, cfg)
        assert out.iloc[0]["is_unusual"] == True  # noqa: E712
        assert out.iloc[0]["der_primary_shape"] == "insufficient_data"

    def test_peak_valley_pattern_requires_both(self, cfg):
        idx = pd.date_range("2024-01-15", periods=24, freq="60min", tz="UTC")
        vals = np.full(24, 10.0)
        vals[5] = 50.0   # local peak
        vals[10] = -5.0  # local valley
        df = pd.DataFrame({"demand_kw": vals}, index=idx)
        tod = add_time_of_day_segments(df, cfg)
        out = classify_load_shape(df, tod, cfg)
        assert out.iloc[0]["has_peak_valley_pattern"] == True  # noqa: E712

    def test_nan_row_from_tod_merge_does_not_satisfy_every_rule(self, cfg):
        # Two days of interval data, but a TOD frame missing one date entirely
        # (simulating a merge producing NaN segment columns for that day) must
        # not make every boolean flag spuriously True via NaN-is-truthy bugs.
        df1 = _flat_day_frame(date="2024-01-15")
        df2 = _flat_day_frame(date="2024-01-16")
        combined = pd.concat([df1, df2])
        tod_full = add_time_of_day_segments(combined, cfg)
        tod_missing_day2 = tod_full.iloc[[0]]  # drop 2024-01-16's TOD row

        out = classify_load_shape(combined, tod_missing_day2, cfg)
        day2_row = out[out["date"] == pd.Timestamp("2024-01-16", tz="UTC")].iloc[0]
        assert day2_row["der_primary_shape"] != "morning_peak"
        assert day2_row.get("has_morning_peak") != True  # noqa: E712

    def test_priority_order_afternoon_before_evening(self, cfg):
        idx = pd.date_range("2024-01-15", periods=24, freq="60min", tz="UTC")
        vals = np.full(24, 10.0)
        vals[15] = 100.0  # afternoon spike (14-18)
        vals[19] = 100.0  # evening spike (18-22), same magnitude
        df = pd.DataFrame({"demand_kw": vals}, index=idx)
        tod = add_time_of_day_segments(df, cfg)
        out = classify_load_shape(df, tod, cfg)
        row = out.iloc[0]
        assert row["has_afternoon_peak"] == True  # noqa: E712
        assert row["has_evening_peak"] == True  # noqa: E712
        assert row["der_primary_shape"] == "afternoon_peak"
