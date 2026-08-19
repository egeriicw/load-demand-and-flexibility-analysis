"""Tests for der/output.py — DER output layout (Phase 6)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from load_profile.der.output import DEROutputBundle, build_der_output, export_der_output
from load_profile.der.pipeline import DERResult
from load_profile.der.calendar_features import add_calendar_features, add_time_of_day_segments


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_interval(meter_id: str, n_days: int = 2, tz: str = "UTC") -> pd.DataFrame:
    n = 24 * n_days
    idx = pd.date_range("2024-01-15", periods=n, freq="60min", tz=tz)
    vals = np.tile(np.concatenate([np.full(23, 10.0), [100.0]]), n_days)
    return pd.DataFrame({"demand_kw": vals, "meter_id": meter_id}, index=idx)


def _make_der_result(cfg, n_days: int = 2) -> DERResult:
    """Minimal DERResult with two meters and one entity group."""
    m1 = _make_interval("M1", n_days=n_days)
    m2 = _make_interval("M2", n_days=n_days)
    m2["demand_kw"] *= 0.8
    multi = pd.concat([m1, m2])

    idx = m1.index
    entity_vals = m1["demand_kw"].values + m2["demand_kw"].values
    entity_frame = pd.DataFrame(
        {"demand_kw": entity_vals, "n_meters_reporting": 2, "is_missing": False},
        index=idx,
    )

    return DERResult(
        meter_tables={},
        interval_df_multi=multi,
        entity_frames={"G1": entity_frame},
        entity_calendar_frames={},
        entity_tod_frames={},
        entity_temperature_frames={},
        entity_meter_ids={"G1": ["M1", "M2"]},
    )


def _make_enriched_der_result(cfg, n_days: int = 2) -> DERResult:
    """DERResult with calendar and TOD frames populated (simulating Phase 2)."""
    base = _make_der_result(cfg, n_days=n_days)
    entity_frame = base.entity_frames["G1"]

    cal_frame = add_calendar_features(entity_frame, cfg)
    tod_frame = add_time_of_day_segments(entity_frame, cfg)

    return DERResult(
        meter_tables=base.meter_tables,
        interval_df_multi=base.interval_df_multi,
        entity_frames=base.entity_frames,
        entity_calendar_frames={"G1": cal_frame},
        entity_tod_frames={"G1": tod_frame},
        entity_temperature_frames={},
        entity_meter_ids=base.entity_meter_ids,
    )


# ---------------------------------------------------------------------------
# DEROutputBundle — defaults
# ---------------------------------------------------------------------------

class TestDEROutputBundleDefaults:
    def test_all_fields_default_to_empty_dataframe(self):
        bundle = DEROutputBundle()
        for field in ("meter_interval", "entity_interval", "entity_daily",
                      "study_coincidence", "daily_coincidence"):
            assert getattr(bundle, field).empty, f"{field} should default to empty"


# ---------------------------------------------------------------------------
# build_der_output — meter_interval
# ---------------------------------------------------------------------------

class TestBuildMeterInterval:
    def test_meter_id_column_present(self, cfg):
        result = _make_der_result(cfg)
        bundle = build_der_output(result, cfg)
        assert "meter_id" in bundle.meter_interval.columns

    def test_datetime_becomes_column(self, cfg):
        result = _make_der_result(cfg)
        bundle = build_der_output(result, cfg)
        assert "datetime" in bundle.meter_interval.columns

    def test_row_count_equals_multi_interval(self, cfg):
        result = _make_der_result(cfg)
        bundle = build_der_output(result, cfg)
        assert len(bundle.meter_interval) == len(result.interval_df_multi)

    def test_both_meters_present(self, cfg):
        result = _make_der_result(cfg)
        bundle = build_der_output(result, cfg)
        assert set(bundle.meter_interval["meter_id"].unique()) == {"M1", "M2"}

    def test_empty_multi_returns_empty(self, cfg):
        result = DERResult()
        bundle = build_der_output(result, cfg)
        assert bundle.meter_interval.empty


# ---------------------------------------------------------------------------
# build_der_output — entity_interval
# ---------------------------------------------------------------------------

class TestBuildEntityInterval:
    def test_entity_id_column_present(self, cfg):
        result = _make_der_result(cfg)
        bundle = build_der_output(result, cfg)
        assert "entity_id" in bundle.entity_interval.columns

    def test_entity_id_values_correct(self, cfg):
        result = _make_der_result(cfg)
        bundle = build_der_output(result, cfg)
        assert set(bundle.entity_interval["entity_id"].unique()) == {"G1"}

    def test_uses_calendar_frames_when_populated(self, cfg):
        result = _make_enriched_der_result(cfg)
        bundle = build_der_output(result, cfg)
        assert "season" in bundle.entity_interval.columns
        assert "day_type" in bundle.entity_interval.columns

    def test_falls_back_to_entity_frames(self, cfg):
        result = _make_der_result(cfg)  # no calendar frames
        bundle = build_der_output(result, cfg)
        # Should still have entity_interval with demand_kw
        assert "demand_kw" in bundle.entity_interval.columns

    def test_datetime_column_present(self, cfg):
        result = _make_der_result(cfg)
        bundle = build_der_output(result, cfg)
        assert "datetime" in bundle.entity_interval.columns


# ---------------------------------------------------------------------------
# build_der_output — entity_daily
# ---------------------------------------------------------------------------

class TestBuildEntityDaily:
    def test_entity_id_column_present(self, cfg):
        result = _make_der_result(cfg)
        bundle = build_der_output(result, cfg)
        assert "entity_id" in bundle.entity_daily.columns

    def test_has_daily_summary_columns(self, cfg):
        result = _make_der_result(cfg)
        bundle = build_der_output(result, cfg)
        for col in ("is_complete_day", "daily_energy_kwh", "maximum_demand_kw", "peak_time_minutes"):
            assert col in bundle.entity_daily.columns, f"Missing column: {col}"

    def test_one_row_per_entity_per_day(self, cfg):
        result = _make_der_result(cfg, n_days=3)
        bundle = build_der_output(result, cfg)
        assert len(bundle.entity_daily) == 3  # 1 entity × 3 days

    def test_joins_tod_features_when_available(self, cfg):
        result = _make_enriched_der_result(cfg)
        bundle = build_der_output(result, cfg)
        assert "morning_peak_kw" in bundle.entity_daily.columns

    def test_no_tod_columns_without_tod_frames(self, cfg):
        result = _make_der_result(cfg)  # no TOD frames
        bundle = build_der_output(result, cfg)
        assert "morning_peak_kw" not in bundle.entity_daily.columns


# ---------------------------------------------------------------------------
# build_der_output — study_coincidence
# ---------------------------------------------------------------------------

class TestBuildStudyCoincidence:
    def test_one_row_per_entity(self, cfg):
        result = _make_der_result(cfg)
        bundle = build_der_output(result, cfg)
        assert len(bundle.study_coincidence) == len(result.entity_meter_ids)

    def test_entity_id_column_present(self, cfg):
        result = _make_der_result(cfg)
        bundle = build_der_output(result, cfg)
        assert "entity_id" in bundle.study_coincidence.columns

    def test_coincidence_factor_column_present(self, cfg):
        result = _make_der_result(cfg)
        bundle = build_der_output(result, cfg)
        assert "coincidence_factor" in bundle.study_coincidence.columns

    def test_success_column_present(self, cfg):
        result = _make_der_result(cfg)
        bundle = build_der_output(result, cfg)
        assert "success" in bundle.study_coincidence.columns

    def test_two_meter_entity_succeeds(self, cfg):
        result = _make_der_result(cfg)
        bundle = build_der_output(result, cfg)
        row = bundle.study_coincidence[bundle.study_coincidence["entity_id"] == "G1"].iloc[0]
        assert row["success"]

    def test_single_meter_entity_fails_with_default_min_meters(self, cfg):
        """An entity with only one resolved meter should have success=False."""
        result = _make_der_result(cfg)
        result.entity_meter_ids["solo"] = ["M1"]
        bundle = build_der_output(result, cfg)
        row = bundle.study_coincidence[bundle.study_coincidence["entity_id"] == "solo"].iloc[0]
        assert not row["success"]


# ---------------------------------------------------------------------------
# build_der_output — daily_coincidence
# ---------------------------------------------------------------------------

class TestBuildDailyCoincidence:
    def test_entity_id_column_present(self, cfg):
        result = _make_der_result(cfg)
        bundle = build_der_output(result, cfg)
        assert "entity_id" in bundle.daily_coincidence.columns

    def test_one_row_per_entity_per_day(self, cfg):
        result = _make_der_result(cfg, n_days=3)
        bundle = build_der_output(result, cfg)
        g1 = bundle.daily_coincidence[bundle.daily_coincidence["entity_id"] == "G1"]
        assert len(g1) == 3

    def test_coincidence_factor_values_valid(self, cfg):
        result = _make_der_result(cfg)
        bundle = build_der_output(result, cfg)
        cf = bundle.daily_coincidence["coincidence_factor"]
        assert (cf > 0).all()
        assert (cf <= 1.0 + 1e-9).all()  # <=1 for full-coverage data

    def test_entity_with_single_meter_omitted(self, cfg):
        """Entity failing min_meters guard should not appear in daily_coincidence."""
        result = _make_der_result(cfg)
        result.entity_meter_ids["solo"] = ["M1"]
        bundle = build_der_output(result, cfg)
        assert "solo" not in bundle.daily_coincidence["entity_id"].values


# ---------------------------------------------------------------------------
# export_der_output
# ---------------------------------------------------------------------------

class TestExportDerOutput:
    def test_writes_configured_tables(self, cfg, tmp_path):
        result = _make_der_result(cfg)
        bundle = build_der_output(result, cfg)

        cfg.setdefault("der", {})["output"] = {
            "meter_interval_csv": str(tmp_path / "meter_interval.csv"),
            "entity_interval_csv": str(tmp_path / "entity_interval.csv"),
            "entity_daily_csv": str(tmp_path / "entity_daily.csv"),
            "study_coincidence_csv": str(tmp_path / "study_coincidence.csv"),
            "daily_coincidence_csv": str(tmp_path / "daily_coincidence.csv"),
        }

        written = export_der_output(bundle, cfg)
        assert set(written.keys()) == {
            "meter_interval", "entity_interval", "entity_daily",
            "study_coincidence", "daily_coincidence",
        }
        for path in written.values():
            assert path.exists()
            assert path.stat().st_size > 0

    def test_csv_readable_as_dataframe(self, cfg, tmp_path):
        result = _make_der_result(cfg)
        bundle = build_der_output(result, cfg)
        cfg.setdefault("der", {})["output"] = {
            "entity_daily_csv": str(tmp_path / "entity_daily.csv"),
        }
        export_der_output(bundle, cfg)
        loaded = pd.read_csv(tmp_path / "entity_daily.csv")
        assert "entity_id" in loaded.columns
        assert "daily_energy_kwh" in loaded.columns

    def test_unconfigured_table_not_written(self, cfg, tmp_path):
        result = _make_der_result(cfg)
        bundle = build_der_output(result, cfg)
        cfg.setdefault("der", {})["output"] = {}  # no paths configured
        written = export_der_output(bundle, cfg)
        assert written == {}

    def test_creates_parent_directories(self, cfg, tmp_path):
        result = _make_der_result(cfg)
        bundle = build_der_output(result, cfg)
        nested = tmp_path / "subdir" / "deep" / "meter.csv"
        cfg.setdefault("der", {})["output"] = {"meter_interval_csv": str(nested)}
        export_der_output(bundle, cfg)
        assert nested.exists()

    def test_empty_table_not_written(self, cfg, tmp_path):
        bundle = DEROutputBundle()  # all empty
        cfg.setdefault("der", {})["output"] = {
            "meter_interval_csv": str(tmp_path / "meter.csv"),
        }
        written = export_der_output(bundle, cfg)
        assert written == {}
        assert not (tmp_path / "meter.csv").exists()
