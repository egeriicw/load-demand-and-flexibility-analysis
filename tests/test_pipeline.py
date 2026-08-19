from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from load_profile.data_ingestion import load_demand_data
from load_profile.pipeline import run_pipeline
from load_profile.synthetic import generate_synthetic_day


def _load_and_run(scenario, cfg, **gen_kwargs):
    df_raw, expected = generate_synthetic_day(scenario, **gen_kwargs)
    df_raw = df_raw.reset_index()
    df = load_demand_data(df_raw, cfg)
    result = run_pipeline(df, cfg, verbose=False)
    return result, expected


class TestRunPipelineStructure:
    def test_returns_expected_keys(self, cfg):
        result, _ = _load_and_run("classic_morning_startup", cfg)
        assert set(result.keys()) == {"interval_df", "daily_df", "ramp_df", "peak_df"}

    def test_daily_df_has_one_row_per_day(self, cfg):
        result, _ = _load_and_run("classic_morning_startup", cfg)
        assert len(result["daily_df"]) == 1

    def test_interval_df_has_expected_columns(self, cfg):
        result, _ = _load_and_run("classic_morning_startup", cfg)
        for col in ["demand_kw", "analysis_demand_kw", "normalized_demand", "baseline_kw", "state"]:
            assert col in result["interval_df"].columns

    def test_multi_day_input_produces_multiple_rows(self, cfg):
        df1, _ = generate_synthetic_day("classic_morning_startup", date="2024-01-15")
        df2, _ = generate_synthetic_day("classic_morning_startup", date="2024-01-16")
        combined = pd.concat([df1, df2]).reset_index()
        df = load_demand_data(combined, cfg)
        result = run_pipeline(df, cfg, verbose=False)
        assert len(result["daily_df"]) == 2

    def test_meter_and_building_id_propagated(self, cfg):
        df_raw, _ = generate_synthetic_day("classic_morning_startup")
        df_raw = df_raw.reset_index()
        df = load_demand_data(df_raw, cfg)
        result = run_pipeline(df, cfg, meter_id="M1", building_id="B1", verbose=False)
        assert result["daily_df"]["meter_id"].iloc[0] == "M1"
        assert result["daily_df"]["building_id"].iloc[0] == "B1"

    def test_ramp_and_peak_events_have_date_column(self, cfg):
        result, _ = _load_and_run("classic_morning_startup", cfg)
        assert "date" in result["ramp_df"].columns
        assert "date" in result["peak_df"].columns


class TestPipelineKWhConversion:
    def test_kwh_input_produces_higher_kw_values(self, cfg):
        df_raw, _ = generate_synthetic_day("flat_continuous")
        df_raw = df_raw.reset_index()
        cfg_kwh = dict(cfg)
        cfg_kwh["input"] = dict(cfg["input"])
        cfg_kwh["input"]["unit"] = "kWh"
        df = load_demand_data(df_raw, cfg_kwh)
        result_kwh = run_pipeline(df, cfg_kwh, verbose=False)

        df2 = load_demand_data(df_raw, cfg)
        result_kw = run_pipeline(df2, cfg, verbose=False)

        # 15-min kWh -> kW is *4
        assert result_kwh["daily_df"]["average_kw"].iloc[0] == pytest.approx(
            result_kw["daily_df"]["average_kw"].iloc[0] * 4, rel=0.01
        )
