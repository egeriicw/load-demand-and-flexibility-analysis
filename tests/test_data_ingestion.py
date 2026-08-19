from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from load_profile.data_ingestion import (
    _detect_resolution,
    _parse_timestamps,
    convert_units,
    load_demand_data,
    validate_input,
)


def _simple_df(n=10, freq="15min", tz="America/Chicago", start="2024-01-15 00:00"):
    idx = pd.date_range(start, periods=n, freq=freq, tz=tz)
    return pd.DataFrame({"datetime": idx.tz_localize(None), "demand_kw": np.arange(n, dtype=float)})


# ---------------------------------------------------------------------------
# load_demand_data
# ---------------------------------------------------------------------------

class TestLoadDemandData:
    def test_basic_dataframe_source(self, cfg):
        df_in = _simple_df()
        out = load_demand_data(df_in, cfg)
        assert "demand_kw" in out.columns
        assert "demand_kw_raw" in out.columns
        assert isinstance(out.index, pd.DatetimeIndex)
        assert out.index.tz is not None
        assert out.index.name == "datetime"

    def test_sorts_by_index(self, cfg):
        idx = pd.to_datetime(["2024-01-15 02:00", "2024-01-15 00:00", "2024-01-15 01:00"])
        df_in = pd.DataFrame({"datetime": idx, "demand_kw": [2.0, 0.0, 1.0]})
        out = load_demand_data(df_in, cfg)
        assert list(out["demand_kw"]) == [0.0, 1.0, 2.0]

    def test_missing_datetime_column_raises(self, cfg):
        df_in = pd.DataFrame({"demand_kw": [1.0, 2.0]})
        with pytest.raises(ValueError, match="datetime column"):
            load_demand_data(df_in, cfg)

    def test_missing_demand_column_raises(self, cfg):
        df_in = pd.DataFrame({"datetime": pd.to_datetime(["2024-01-15"])})
        with pytest.raises(ValueError, match="demand column"):
            load_demand_data(df_in, cfg)

    def test_optional_meter_and_building_columns(self, cfg):
        cfg["input"]["meter_id_col"] = "meter"
        cfg["input"]["building_id_col"] = "bldg"
        df_in = _simple_df(n=3)
        df_in["meter"] = "M1"
        df_in["bldg"] = "B1"
        out = load_demand_data(df_in, cfg)
        assert "meter_id" in out.columns
        assert "building_id" in out.columns
        assert (out["meter_id"] == "M1").all()

    def test_demand_kw_raw_preserves_original(self, cfg):
        df_in = _simple_df(n=5)
        out = load_demand_data(df_in, cfg)
        assert list(out["demand_kw"]) == list(out["demand_kw_raw"])

    def test_csv_source(self, cfg, tmp_path):
        df_in = _simple_df(n=5)
        p = tmp_path / "data.csv"
        df_in.to_csv(p, index=False)
        out = load_demand_data(p, cfg)
        assert len(out) == 5

    def test_custom_column_names(self, cfg):
        cfg["input"]["datetime_col"] = "ts"
        cfg["input"]["demand_col"] = "kw"
        idx = pd.date_range("2024-01-15", periods=4, freq="15min")
        df_in = pd.DataFrame({"ts": idx, "kw": [1.0, 2.0, 3.0, 4.0]})
        out = load_demand_data(df_in, cfg)
        assert list(out["demand_kw"]) == [1.0, 2.0, 3.0, 4.0]


# ---------------------------------------------------------------------------
# convert_units
# ---------------------------------------------------------------------------

class TestConvertUnits:
    def test_no_conversion_when_kw(self, cfg):
        cfg["input"]["unit"] = "kW"
        df = pd.DataFrame({"demand_kw": [10.0], "demand_kw_raw": [10.0]})
        out, meta = convert_units(df, 15, cfg)
        assert meta["conversion_applied"] is False
        assert meta["conversion_factor"] == 1.0
        assert out["demand_kw"].iloc[0] == 10.0

    def test_kwh_to_kw_15min(self, cfg):
        cfg["input"]["unit"] = "kWh"
        df = pd.DataFrame({"demand_kw": [10.0], "demand_kw_raw": [10.0]})
        out, meta = convert_units(df, 15, cfg)
        assert meta["conversion_applied"] is True
        assert meta["conversion_factor"] == pytest.approx(4.0)
        assert out["demand_kw"].iloc[0] == pytest.approx(40.0)

    def test_kwh_to_kw_60min_is_noop_factor(self, cfg):
        cfg["input"]["unit"] = "kWh"
        df = pd.DataFrame({"demand_kw": [10.0], "demand_kw_raw": [10.0]})
        out, meta = convert_units(df, 60, cfg)
        assert meta["conversion_factor"] == pytest.approx(1.0)

    def test_invalid_unit_raises(self, cfg):
        cfg["input"]["unit"] = "MW"
        df = pd.DataFrame({"demand_kw": [1.0], "demand_kw_raw": [1.0]})
        with pytest.raises(ValueError, match="cfg.input.unit"):
            convert_units(df, 15, cfg)

    def test_zero_resolution_raises_for_kwh(self, cfg):
        cfg["input"]["unit"] = "kWh"
        df = pd.DataFrame({"demand_kw": [1.0], "demand_kw_raw": [1.0]})
        with pytest.raises(ValueError, match="Cannot convert"):
            convert_units(df, 0, cfg)

    def test_preserves_demand_input_raw(self, cfg):
        cfg["input"]["unit"] = "kWh"
        df = pd.DataFrame({"demand_kw": [10.0], "demand_kw_raw": [10.0]})
        out, _ = convert_units(df, 15, cfg)
        assert out["demand_input_raw"].iloc[0] == 10.0


# ---------------------------------------------------------------------------
# validate_input
# ---------------------------------------------------------------------------

class TestValidateInput:
    def test_clean_data_no_issues(self, cfg):
        idx = pd.date_range("2024-01-15", periods=20, freq="15min", tz="UTC")
        df = pd.DataFrame({"demand_kw": np.full(20, 100.0)}, index=idx)
        report = validate_input(df, cfg)
        assert report["duplicate_timestamp_count"] == 0
        assert report["negative_demand_count"] == 0
        assert report["issues"] == []
        assert report["detected_resolution_minutes"] == 15.0

    def test_duplicate_timestamps_flagged(self, cfg):
        idx = pd.date_range("2024-01-15", periods=5, freq="15min", tz="UTC")
        idx = idx.insert(2, idx[2])
        df = pd.DataFrame({"demand_kw": np.arange(6, dtype=float)}, index=idx)
        report = validate_input(df, cfg)
        assert report["duplicate_timestamp_count"] == 1
        assert any("duplicate" in i for i in report["issues"])

    def test_negative_demand_flagged_as_error_by_default(self, cfg):
        # Default data_quality.negative_demand_severity is "ERROR": negative
        # demand is unsupported by design and rejected.
        idx = pd.date_range("2024-01-15", periods=5, freq="15min", tz="UTC")
        df = pd.DataFrame({"demand_kw": [-1.0, 2.0, 3.0, 4.0, 5.0]}, index=idx)
        report = validate_input(df, cfg)
        assert report["negative_demand_count"] == 1
        assert any("negative" in i for i in report["issues"])
        assert report["warnings"] == []

    def test_negative_demand_flagged_as_warning_when_downgraded(self, cfg):
        cfg["data_quality"]["negative_demand_severity"] = "WARNING"
        idx = pd.date_range("2024-01-15", periods=5, freq="15min", tz="UTC")
        df = pd.DataFrame({"demand_kw": [-1.0, 2.0, 3.0, 4.0, 5.0]}, index=idx)
        report = validate_input(df, cfg)
        assert report["negative_demand_count"] == 1
        assert any("negative" in w for w in report["warnings"])
        assert report["issues"] == []

    def test_zero_demand_counted(self, cfg):
        idx = pd.date_range("2024-01-15", periods=5, freq="15min", tz="UTC")
        df = pd.DataFrame({"demand_kw": [0.0, 0.0, 3.0, 4.0, 5.0]}, index=idx)
        report = validate_input(df, cfg)
        assert report["zero_demand_count"] == 2

    def test_irregular_intervals_flagged(self, cfg):
        idx = pd.to_datetime(
            ["2024-01-15 00:00", "2024-01-15 00:15", "2024-01-15 00:45", "2024-01-15 01:00"]
        ).tz_localize("UTC")
        df = pd.DataFrame({"demand_kw": [1.0, 2.0, 3.0, 4.0]}, index=idx)
        report = validate_input(df, cfg)
        assert report["irregular_interval_count"] >= 1
        assert any("irregular" in w for w in report["warnings"])


# ---------------------------------------------------------------------------
# private helpers
# ---------------------------------------------------------------------------

class TestParseTimestamps:
    def test_naive_localized_to_default_tz(self):
        s = pd.Series(pd.to_datetime(["2024-01-15 00:00", "2024-01-15 01:00"]))
        out = _parse_timestamps(s, "America/Chicago")
        assert out.dt.tz is not None
        assert str(out.dt.tz) == "America/Chicago"

    def test_already_tz_aware_preserved(self):
        s = pd.Series(pd.to_datetime(["2024-01-15 00:00+00:00", "2024-01-15 01:00+00:00"]))
        out = _parse_timestamps(s, "America/Chicago")
        assert out.dt.tz is not None


class TestDetectResolution:
    def test_regular_15min(self):
        idx = pd.date_range("2024-01-15", periods=10, freq="15min")
        assert _detect_resolution(idx) == 15.0

    def test_regular_60min(self):
        idx = pd.date_range("2024-01-15", periods=10, freq="60min")
        assert _detect_resolution(idx) == 60.0

    def test_mode_ignores_minority_outliers(self):
        base = pd.date_range("2024-01-15", periods=20, freq="15min").tolist()
        # introduce one larger gap by dropping an interval
        del base[5]
        idx = pd.DatetimeIndex(base)
        assert _detect_resolution(idx) == 15.0

    def test_too_few_timestamps_raises(self):
        idx = pd.date_range("2024-01-15", periods=1, freq="15min")
        with pytest.raises(ValueError, match="at least 2"):
            _detect_resolution(idx)
