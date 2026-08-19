from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from load_profile.der.calendar_features import add_time_of_day_segments


def _day_frame(date="2024-01-15", tz="UTC"):
    idx = pd.date_range(date, periods=24, freq="60min", tz=tz)
    # demand_kw[h] = h, so peaks/means are easy to hand-verify
    return pd.DataFrame({"demand_kw": np.arange(24, dtype=float)}, index=idx)


class TestAddTimeOfDaySegments:
    def test_one_row_per_date(self, cfg):
        df = pd.concat([_day_frame("2024-01-15"), _day_frame("2024-01-16")])
        out = add_time_of_day_segments(df, cfg)
        assert len(out) == 2
        assert set(out["date"].astype(str).str[:10]) == {"2024-01-15", "2024-01-16"}

    def test_segment_peak_is_max_within_window(self, cfg):
        df = _day_frame()
        out = add_time_of_day_segments(df, cfg)
        row = out.iloc[0]
        # morning [6,10) -> hours 6,7,8,9 -> max=9
        assert row["morning_peak_kw"] == pytest.approx(9.0)
        # midday [10,14) -> hours 10..13 -> max=13
        assert row["midday_peak_kw"] == pytest.approx(13.0)
        # afternoon [14,18) -> hours 14..17 -> max=17
        assert row["afternoon_peak_kw"] == pytest.approx(17.0)
        # evening [18,22) -> hours 18..21 -> max=21
        assert row["evening_peak_kw"] == pytest.approx(21.0)

    def test_overnight_and_daytime_means(self, cfg):
        df = _day_frame()
        out = add_time_of_day_segments(df, cfg)
        row = out.iloc[0]
        overnight_hours = [22, 23, 0, 1, 2, 3, 4, 5]
        daytime_hours = list(range(6, 22))
        assert row["overnight_mean_kw"] == pytest.approx(np.mean(overnight_hours))
        assert row["nighttime_mean_kw"] == row["overnight_mean_kw"]
        assert row["daytime_mean_kw"] == pytest.approx(np.mean(daytime_hours))

    def test_window_with_no_data_is_nan(self, cfg):
        idx = pd.date_range("2024-01-15 06:00", periods=4, freq="60min", tz="UTC")
        df = pd.DataFrame({"demand_kw": [1.0, 2.0, 3.0, 4.0]}, index=idx)  # only 6-9
        out = add_time_of_day_segments(df, cfg)
        assert np.isnan(out.iloc[0]["evening_peak_kw"])

    def test_custom_segments_from_config(self, cfg):
        cfg["der"]["time_of_day"]["segments"] = {"custom": [0, 2]}
        df = _day_frame()
        out = add_time_of_day_segments(df, cfg)
        assert out.iloc[0]["custom_peak_kw"] == pytest.approx(1.0)  # hours 0,1 -> max=1
