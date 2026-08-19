from __future__ import annotations

import numpy as np
import pandas as pd

from load_profile.der.calendar_features import add_calendar_features


def _frame(dates, freq="60min", tz="UTC"):
    idx = pd.date_range(dates[0], dates[-1], freq=freq, tz=tz, inclusive="left")
    return pd.DataFrame({"demand_kw": np.arange(len(idx), dtype=float)}, index=idx)


class TestAddCalendarFeatures:
    def test_basic_fields_present(self, cfg):
        df = _frame(["2024-01-15", "2024-01-16"])
        out = add_calendar_features(df, cfg)
        for col in [
            "date", "year", "month", "day", "day_of_year", "hour", "minute",
            "day_of_week", "day_name", "is_weekday", "is_weekend", "season", "day_type",
        ]:
            assert col in out.columns

    def test_monday_is_day_of_week_zero(self, cfg):
        # 2024-01-15 is a Monday
        df = _frame(["2024-01-15", "2024-01-16"])
        out = add_calendar_features(df, cfg)
        assert out["day_of_week"].iloc[0] == 0
        assert out["day_name"].iloc[0] == "Monday"
        assert out["is_weekday"].iloc[0] == True  # noqa: E712
        assert out["is_weekend"].iloc[0] == False  # noqa: E712

    def test_saturday_is_weekend(self, cfg):
        # 2024-01-20 is a Saturday
        df = _frame(["2024-01-20", "2024-01-21"])
        out = add_calendar_features(df, cfg)
        assert out["is_weekend"].iloc[0] == True  # noqa: E712
        assert out["day_type"].iloc[0] == "weekend"

    def test_default_season_map_january_is_winter(self, cfg):
        df = _frame(["2024-01-15", "2024-01-16"])
        out = add_calendar_features(df, cfg)
        assert (out["season"] == "winter").all()

    def test_default_season_map_july_is_summer(self, cfg):
        df = _frame(["2024-07-15", "2024-07-16"])
        out = add_calendar_features(df, cfg)
        assert (out["season"] == "summer").all()

    def test_holiday_overrides_weekday(self, cfg):
        # 2024-01-15 is a Monday (weekday); mark it a holiday.
        cfg["der"]["calendar"]["holidays"] = ["2024-01-15"]
        df = _frame(["2024-01-15", "2024-01-16"])
        out = add_calendar_features(df, cfg)
        assert (out["day_type"] == "holiday").all()
        # is_weekday/is_weekend stay calendar-only, unaffected by holiday
        assert (out["is_weekday"] == True).all()  # noqa: E712

    def test_custom_season_map_applied(self, cfg):
        cfg["der"]["calendar"]["season_map"] = {str(m): "custom" for m in range(1, 13)}
        df = _frame(["2024-01-15", "2024-01-16"])
        out = add_calendar_features(df, cfg)
        assert (out["season"] == "custom").all()
