from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from load_profile.der.temperature import band_temperature, load_temperature_data, merge_temperature


def _interval_df(n=5, freq="60min", tz="UTC", start="2024-01-15", extra_temp=None):
    idx = pd.date_range(start, periods=n, freq=freq, tz=tz)
    data = {"demand_kw": np.arange(n, dtype=float)}
    if extra_temp is not None:
        data["temperature_f"] = extra_temp
    return pd.DataFrame(data, index=idx)


def _temp_df(n=5, freq="60min", tz="UTC", start="2024-01-15", values=None):
    idx = pd.date_range(start, periods=n, freq=freq, tz=tz)
    values = values if values is not None else np.arange(n, dtype=float) * 10
    return pd.DataFrame({"temperature_f": values}, index=idx)


class TestLoadTemperatureData:
    def test_loads_from_dataframe_with_default_column_names(self, cfg):
        df = pd.DataFrame({"datetime": pd.date_range("2024-01-15", periods=3, freq="60min"),
                            "temperature_f": [40.0, 41.0, 42.0]})
        out = load_temperature_data(df, cfg)
        assert list(out.columns) == ["temperature_f"]
        assert out.index.tz is not None

    def test_custom_column_mapping(self, cfg):
        cfg["der"]["temperature"]["column_mapping"] = {"timestamp": "ts", "temperature_f": "tempF"}
        df = pd.DataFrame({"ts": pd.date_range("2024-01-15", periods=3, freq="60min"),
                            "tempF": [40.0, 41.0, 42.0]})
        out = load_temperature_data(df, cfg)
        assert out["temperature_f"].tolist() == [40.0, 41.0, 42.0]

    def test_missing_column_raises(self, cfg):
        df = pd.DataFrame({"datetime": pd.date_range("2024-01-15", periods=3, freq="60min")})
        with pytest.raises(ValueError, match="temperature"):
            load_temperature_data(df, cfg)


class TestMergeTemperature:
    def test_nearest_join_fills_temperature(self, cfg):
        left = _interval_df()
        right = _temp_df()
        merged = merge_temperature(left, right, cfg)
        assert merged["temperature_f"].tolist() == [0.0, 10.0, 20.0, 30.0, 40.0]

    def test_no_existing_column_uses_external(self, cfg):
        left = _interval_df()
        right = _temp_df(values=[99.0] * 5)
        merged = merge_temperature(left, right, cfg)
        assert (merged["temperature_f"] == 99.0).all()

    def test_existing_not_overridden_by_default(self, cfg):
        left = _interval_df(extra_temp=[50.0, np.nan, 52.0, np.nan, 54.0])
        right = _temp_df(values=[99.0] * 5)
        merged = merge_temperature(left, right, cfg)
        # existing values kept; only the NaN slots get filled from external
        assert merged["temperature_f"].tolist() == [50.0, 99.0, 52.0, 99.0, 54.0]

    def test_override_existing_true_prefers_external(self, cfg):
        cfg["der"]["temperature"]["override_existing"] = True
        left = _interval_df(extra_temp=[50.0, 51.0, 52.0, 53.0, 54.0])
        right = _temp_df(values=[99.0] * 5)
        merged = merge_temperature(left, right, cfg)
        assert (merged["temperature_f"] == 99.0).all()

    def test_tolerance_excludes_far_matches(self, cfg):
        cfg["der"]["temperature"]["join_tolerance_minutes"] = 30
        left = _interval_df(n=1, start="2024-01-15 00:00")
        right = _temp_df(n=1, start="2024-01-15 05:00", values=[77.0])
        merged = merge_temperature(left, right, cfg)
        assert np.isnan(merged["temperature_f"].iloc[0])

    def test_tolerance_includes_near_matches(self, cfg):
        cfg["der"]["temperature"]["join_tolerance_minutes"] = 30
        left = _interval_df(n=1, start="2024-01-15 00:00")
        right = _temp_df(n=1, start="2024-01-15 00:10", values=[77.0])
        merged = merge_temperature(left, right, cfg)
        assert merged["temperature_f"].iloc[0] == pytest.approx(77.0)


class TestBandTemperature:
    def test_default_boundaries(self, cfg):
        df = pd.DataFrame({"temperature_f": [10.0, 40.0, 60.0, 75.0, 85.0, 95.0]})
        out = band_temperature(df, cfg)
        assert out["temperature_band"].astype(str).tolist() == [
            "below-32", "32-50", "50-65", "65-80", "80-90", "90-above",
        ]

    def test_nan_temperature_gives_nan_band(self, cfg):
        df = pd.DataFrame({"temperature_f": [np.nan]})
        out = band_temperature(df, cfg)
        assert pd.isna(out["temperature_band"].iloc[0])

    def test_custom_boundaries(self, cfg):
        cfg["der"]["temperature"]["bands"]["boundaries"] = [50, 80]
        df = pd.DataFrame({"temperature_f": [10.0, 60.0, 90.0]})
        out = band_temperature(df, cfg)
        assert out["temperature_band"].astype(str).tolist() == ["below-50", "50-80", "80-above"]
