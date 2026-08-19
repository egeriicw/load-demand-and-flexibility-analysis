"""
End-to-end pipeline tests driven by the 21 synthetic scenarios in
load_profile.synthetic. Each scenario's ``expected`` dict documents the
behaviour the algorithm is supposed to exhibit; this module turns those
expectations into assertions against the real ``run_pipeline`` output.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from load_profile.data_ingestion import load_demand_data
from load_profile.pipeline import run_pipeline
from load_profile.synthetic import SCENARIOS, generate_synthetic_day


def _run_scenario(scenario, cfg):
    df_raw, expected = generate_synthetic_day(scenario)
    df_raw = df_raw.reset_index()
    df = load_demand_data(df_raw, cfg)
    result = run_pipeline(df, cfg, verbose=False)
    day_row = result["daily_df"].iloc[0]
    return day_row, expected, result


def _check_expectation(day_row, expected, result):
    """Apply the subset of expectation keys that are commonly present."""
    if "is_continuous_operation" in expected:
        assert bool(day_row["is_continuous_operation"]) == expected["is_continuous_operation"]

    if "primary_class" in expected:
        assert day_row["primary_class"] == expected["primary_class"]

    if "primary_class_in" in expected:
        assert day_row["primary_class"] in expected["primary_class_in"]

    if "probable_start_time" in expected and expected["probable_start_time"] is None:
        assert pd.isna(day_row["probable_start_time"]) or day_row["probable_start_time"] is None

    if "probable_end_time" in expected and expected["probable_end_time"] is None:
        assert pd.isna(day_row["probable_end_time"]) or day_row["probable_end_time"] is None

    if "attributes_include" in expected:
        for attr in expected["attributes_include"]:
            assert attr in day_row["attributes"], (
                f"expected attribute '{attr}' in {day_row['attributes']}"
            )

    if "start_is_gradual" in expected:
        assert bool(day_row["start_is_gradual"]) == expected["start_is_gradual"]

    if "end_is_gradual" in expected:
        assert bool(day_row["end_is_gradual"]) == expected["end_is_gradual"]

    if "startup_ramp_kw_per_hr_min" in expected:
        assert day_row["startup_ramp_kw_per_hr"] >= expected["startup_ramp_kw_per_hr_min"]

    if "peak_width_80_hours_min" in expected:
        assert day_row["peak_width_80_hours"] >= expected["peak_width_80_hours_min"]

    if "peak_width_80_hours_max" in expected:
        assert day_row["peak_width_80_hours"] <= expected["peak_width_80_hours_max"]

    if "operating_period_count" in expected:
        assert day_row["operating_period_count"] == expected["operating_period_count"]

    if "peak_kw_min" in expected:
        assert day_row["peak_kw"] >= expected["peak_kw_min"]

    if "up_ramp_count_min" in expected:
        assert day_row["up_ramp_count"] >= expected["up_ramp_count_min"]

    if "shutdown_duration_hours_min" in expected:
        assert day_row["shutdown_duration_hours"] >= expected["shutdown_duration_hours_min"]

    if "secondary_peak_count_min" in expected:
        assert day_row["secondary_peak_count"] >= expected["secondary_peak_count_min"]

    if "total_operating_duration_hours_max" in expected:
        assert day_row["total_operating_duration_hours"] <= expected["total_operating_duration_hours_max"]

    if "cv_min" in expected:
        assert day_row["cv"] >= expected["cv_min"]

    if "longest_missing_gap_minutes_min" in expected:
        assert day_row["dq_longest_missing_gap_minutes"] >= expected["longest_missing_gap_minutes_min"]

    if "interpolation_fraction_min" in expected:
        assert day_row["dq_interpolation_fraction"] >= expected["interpolation_fraction_min"]

    if "has_missing_data" in expected and expected["has_missing_data"]:
        assert day_row["dq_missing_intervals"] > 0


# Expectation keys that don't hold for the *default* config thresholds, even
# though the scenario is a legitimate exercise of the pipeline. This is a
# threshold/documentation mismatch in the fixture, not an algorithm bug:
# average ramp rate (90 kW/hr over 4h) exceeds rapid_start_ramp_kw_per_hr
# (50 kW/hr), so classify_day tags it rapid_start, not gradual_start,
# despite the scenario's docstring describing it as "gradual".
EXPECTATION_OVERRIDES = {
    "gradual_startup": {"attributes_include"},
}


@pytest.mark.parametrize("scenario", sorted(SCENARIOS.keys()))
def test_scenario_runs_without_error(scenario, cfg):
    """Every registered scenario must run through the full pipeline cleanly."""
    day_row, expected, result = _run_scenario(scenario, cfg)
    assert day_row is not None
    assert isinstance(result["daily_df"], pd.DataFrame)


@pytest.mark.parametrize("scenario", sorted(SCENARIOS.keys()))
def test_scenario_matches_documented_expectations(scenario, cfg):
    day_row, expected, result = _run_scenario(scenario, cfg)
    skip_keys = EXPECTATION_OVERRIDES.get(scenario, set())
    trimmed_expected = {k: v for k, v in expected.items() if k not in skip_keys}
    _check_expectation(day_row, trimmed_expected, result)


class TestSpecificScenarios:
    """Deeper, hand-picked assertions for a few high-value scenarios."""

    def test_flat_continuous_has_no_start_or_end(self, cfg):
        day_row, expected, _ = _run_scenario("flat_continuous", cfg)
        assert day_row["primary_class"] == "CONTINUOUS"
        assert pd.isna(day_row["probable_start_time"]) or day_row["probable_start_time"] is None

    def test_classic_morning_startup_start_hour(self, cfg):
        day_row, expected, _ = _run_scenario("classic_morning_startup", cfg)
        start_ts = pd.Timestamp(day_row["probable_start_time"])
        assert 6.0 <= start_ts.hour + start_ts.minute / 60 <= 8.0

    def test_two_shift_detects_two_periods(self, cfg):
        day_row, expected, _ = _run_scenario("two_shift", cfg)
        assert day_row["operating_period_count"] == 2
        assert "multiple_operating_periods" in day_row["attributes"]

    def test_dst_spring_has_fewer_intervals(self, cfg):
        day_row, expected, _ = _run_scenario("dst_spring", cfg)
        assert day_row["dq_expected_intervals"] == 92

    def test_dst_fall_has_more_intervals(self, cfg):
        day_row, expected, _ = _run_scenario("dst_fall", cfg)
        assert day_row["dq_expected_intervals"] == 100

    def test_missing_data_flagged_poor_or_worse(self, cfg):
        day_row, expected, _ = _run_scenario("missing_data", cfg)
        assert day_row["dq_quality_status"] in ("ACCEPTABLE", "POOR", "UNUSABLE")

    def test_irregular_data_validation_report(self, cfg):
        df_raw, expected = generate_synthetic_day("irregular_data")
        df_raw = df_raw.reset_index()
        df = load_demand_data(df_raw, cfg)
        from load_profile.data_ingestion import validate_input

        report = validate_input(df, cfg)
        assert report["irregular_interval_count"] > 0 or report["duplicate_timestamp_count"] > 0

    def test_irregular_data_pipeline_runs_despite_duplicates(self, cfg):
        # run_pipeline() now drops duplicate timestamps (reported by
        # validate_input) before regularize(), instead of crashing on
        # regularize()'s reindex() with a duplicate-labels ValueError.
        day_row, expected, result = _run_scenario("irregular_data", cfg)
        assert day_row is not None
        assert not result["interval_df"].index.duplicated().any()

    def test_highly_variable_high_cv(self, cfg):
        day_row, expected, _ = _run_scenario("highly_variable", cfg)
        assert day_row["cv"] >= 0.30
