from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from load_profile.baseline import estimate_baseline
from load_profile.events import detect_end, detect_operating_periods, detect_peaks, detect_ramps, detect_start
from load_profile.features import build_daily_features
from load_profile.states import compute_normalized_demand, detect_states


def _build_day(vals, freq="15min", tz="America/Chicago", start="2024-01-15"):
    idx = pd.date_range(start, periods=len(vals), freq=freq, tz=tz)
    df_day = pd.DataFrame(
        {
            "demand_kw": vals,
            "is_observed": True,
            "is_interpolated": False,
            "is_missing": False,
        },
        index=idx,
    )
    return df_day


def _full_features(vals, cfg, date="2024-01-15"):
    df_day = _build_day(vals)
    series_raw = df_day["demand_kw"]
    series_smooth = series_raw.rename("analysis_demand_kw")  # no smoothing for determinism
    baseline = estimate_baseline(series_smooth, 15, cfg)
    norm = compute_normalized_demand(series_raw, baseline, cfg)
    states = detect_states(series_smooth, baseline, cfg)
    start_ev = detect_start(series_smooth, states, baseline, cfg)
    end_ev = detect_end(series_smooth, states, baseline, cfg)
    ramp_evs = detect_ramps(series_smooth, baseline, states, cfg)
    peak_evs = detect_peaks(series_raw, df_day["is_interpolated"], baseline, cfg)
    op_periods = detect_operating_periods(states, cfg)

    return build_daily_features(
        date=date,
        meter_id="M1",
        building_id="B1",
        df_day=df_day,
        series_raw=series_raw,
        series_smooth=series_smooth,
        states=states,
        baseline_result=baseline,
        quality={"completeness_fraction": 1.0},
        start_event=start_ev,
        end_event=end_ev,
        ramp_events=ramp_evs,
        peak_events=peak_evs,
        operating_periods=op_periods,
        norm_demand=norm,
        cfg=cfg,
        resolution_minutes=15,
    )


def _startup_vals():
    low = [50.0] * 20
    up = list(np.linspace(50.0, 450.0, 8))
    plateau = [450.0] * 20
    down = list(np.linspace(450.0, 50.0, 8))
    tail = [50.0] * 20
    return low + up + plateau + down + tail


class TestBuildDailyFeatures:
    def test_identity_fields(self, cfg):
        feat = _full_features(_startup_vals(), cfg)
        assert feat["date"] == "2024-01-15"
        assert feat["meter_id"] == "M1"
        assert feat["building_id"] == "B1"
        assert feat["resolution_minutes"] == 15

    def test_dq_prefix_applied(self, cfg):
        feat = _full_features(_startup_vals(), cfg)
        assert feat["dq_completeness_fraction"] == 1.0

    def test_basic_statistics_present(self, cfg):
        feat = _full_features(_startup_vals(), cfg)
        assert feat["minimum_kw"] == pytest.approx(50.0, abs=1.0)
        assert feat["maximum_kw"] == pytest.approx(450.0, abs=1.0)
        assert feat["average_kw"] is not None
        assert feat["cv"] is not None

    def test_start_event_fields_populated(self, cfg):
        feat = _full_features(_startup_vals(), cfg)
        assert feat["probable_start_time"] is not None
        assert feat["startup_delta_kw"] > 0

    def test_start_event_fields_none_when_no_event(self, cfg):
        rng = np.random.default_rng(0)
        vals = list(500.0 + rng.normal(0, 3, 96))
        feat = _full_features(vals, cfg)
        assert feat["probable_start_time"] is None
        assert feat["startup_delta_kw"] is None

    def test_operating_period_count(self, cfg):
        feat = _full_features(_startup_vals(), cfg)
        assert feat["operating_period_count"] >= 1
        assert feat["total_operating_duration_hours"] > 0

    def test_breadth_duration_thresholds_present(self, cfg):
        feat = _full_features(_startup_vals(), cfg)
        for thr in cfg["breadth"]["operating_thresholds"]:
            label = f"duration_above_{int(thr*100)}pct_hours"
            assert label in feat

    def test_primary_peak_fields(self, cfg):
        feat = _full_features(_startup_vals(), cfg)
        assert feat["peak_kw"] == pytest.approx(450.0, abs=1.0)
        assert feat["peak_time"] is not None
        assert feat["peak_confidence"] is not None

    def test_peakiness_ratios(self, cfg):
        feat = _full_features(_startup_vals(), cfg)
        assert feat["peak_to_average_ratio"] > 1.0
        assert feat["load_factor"] < 1.0

    def test_secondary_peak_count(self, cfg):
        feat = _full_features(_startup_vals(), cfg)
        assert feat["secondary_peak_count"] >= 0

    def test_ramp_counts(self, cfg):
        feat = _full_features(_startup_vals(), cfg)
        assert feat["ramp_event_count"] == feat["up_ramp_count"] + feat["down_ramp_count"]

    def test_empty_valid_series_handled(self, cfg):
        vals = [np.nan] * 20
        feat = _full_features(vals, cfg)
        assert feat["average_kw"] is None
        assert feat["peak_to_average_ratio"] is None
