from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from load_profile.baseline import estimate_baseline
from load_profile.events import (
    detect_end,
    detect_operating_periods,
    detect_peaks,
    detect_ramps,
    detect_start,
)
from load_profile.states import detect_states


def _series(vals, freq="15min", tz="America/Chicago", start="2024-01-15"):
    idx = pd.date_range(start, periods=len(vals), freq=freq, tz=tz)
    return pd.Series(vals, index=idx)


def _pipeline_pieces(vals, cfg, freq="15min"):
    """Run baseline + states for a synthetic demand array; return (series, baseline, states)."""
    s = _series(vals, freq=freq)
    baseline = estimate_baseline(s, 15, cfg)
    states = detect_states(s, baseline, cfg)
    return s, baseline, states


def _startup_day(n_per=32):
    return [50.0] * n_per + [450.0] * n_per + [50.0] * n_per


def _ramped_startup_day():
    """Overnight baseline, ramped startup, plateau, ramped shutdown (2-hr ramps at 15-min res)."""
    low = [50.0] * 20
    up = list(np.linspace(50.0, 450.0, 8))
    plateau = [450.0] * 20
    down = list(np.linspace(450.0, 50.0, 8))
    tail = [50.0] * 20
    return low + up + plateau + down + tail


# ---------------------------------------------------------------------------
# detect_start / detect_end
# ---------------------------------------------------------------------------

class TestDetectStart:
    def test_none_when_baseline_missing(self, cfg):
        s = _series([100.0] * 10)
        baseline_result = {"baseline_kw": np.nan, "peak_kw": np.nan}
        states = detect_states(s, baseline_result, cfg)
        assert detect_start(s, states, baseline_result, cfg) is None

    def test_none_for_continuous_flat_load(self, cfg):
        rng = np.random.default_rng(1)
        vals = list(500.0 + rng.normal(0, 5, 96))
        s, baseline, states = _pipeline_pieces(vals, cfg)
        assert detect_start(s, states, baseline, cfg) is None

    def test_detects_startup_transition(self, cfg):
        s, baseline, states = _pipeline_pieces(_startup_day(), cfg)
        ev = detect_start(s, states, baseline, cfg)
        assert ev is not None
        assert ev.delta_kw > 0
        assert ev.confidence >= 0.0
        assert ev.confidence <= 1.0

    def test_none_when_ramp_too_small(self, cfg):
        cfg["start_detection"]["min_magnitude_kw"] = 1000.0
        s, baseline, states = _pipeline_pieces(_startup_day(), cfg)
        ev = detect_start(s, states, baseline, cfg)
        assert ev is None


class TestDetectEnd:
    def test_none_when_baseline_missing(self, cfg):
        s = _series([100.0] * 10)
        baseline_result = {"baseline_kw": np.nan, "peak_kw": np.nan}
        states = detect_states(s, baseline_result, cfg)
        assert detect_end(s, states, baseline_result, cfg) is None

    def test_detects_shutdown_transition(self, cfg):
        s, baseline, states = _pipeline_pieces(_ramped_startup_day(), cfg)
        ev = detect_end(s, states, baseline, cfg)
        assert ev is not None
        assert ev.delta_kw > 0

    def test_start_before_end(self, cfg):
        s, baseline, states = _pipeline_pieces(_ramped_startup_day(), cfg)
        start_ev = detect_start(s, states, baseline, cfg)
        end_ev = detect_end(s, states, baseline, cfg)
        assert start_ev.transition_time < end_ev.transition_time


# ---------------------------------------------------------------------------
# detect_ramps
# ---------------------------------------------------------------------------

class TestDetectRamps:
    def test_too_few_points_returns_empty(self, cfg):
        s = _series([50.0, 60.0])
        baseline_result = {"baseline_kw": 50.0, "operating_range_kw": 50.0}
        states = _series(["BASELINE", "OPERATING"])
        assert detect_ramps(s, baseline_result, states, cfg) == []

    def test_flat_series_no_ramps(self, cfg):
        s, baseline, states = _pipeline_pieces([100.0] * 30, cfg)
        ramps = detect_ramps(s, baseline, states, cfg)
        assert ramps == []

    def test_up_ramp_detected_in_isolation(self, cfg):
        vals = [50.0] * 20 + list(np.linspace(50.0, 450.0, 8)) + [450.0] * 20
        s, baseline, states = _pipeline_pieces(vals, cfg)
        ramps = detect_ramps(s, baseline, states, cfg)
        assert len(ramps) >= 1
        assert ramps[0].event_type == "UP"
        assert ramps[0].delta_kw > 0

    def test_down_ramp_detected_in_isolation(self, cfg):
        vals = [450.0] * 20 + list(np.linspace(450.0, 50.0, 8)) + [50.0] * 20
        s, baseline, states = _pipeline_pieces(vals, cfg)
        ramps = detect_ramps(s, baseline, states, cfg)
        assert len(ramps) >= 1
        assert ramps[0].event_type == "DOWN"
        assert ramps[0].delta_kw > 0

    def test_startup_and_shutdown_ramps_both_detected(self, cfg):
        # A flat plateau now correctly ends the preceding ramp event instead
        # of being absorbed into it, so the UP and DOWN ramps of a full
        # startup/plateau/shutdown day are both detected as separate events.
        s, baseline, states = _pipeline_pieces(_ramped_startup_day(), cfg)
        ramps = detect_ramps(s, baseline, states, cfg)
        assert len(ramps) == 2
        assert ramps[0].event_type == "UP"
        assert ramps[1].event_type == "DOWN"

    def test_ramp_events_sorted_by_start_time(self, cfg):
        s, baseline, states = _pipeline_pieces(_startup_day(), cfg)
        ramps = detect_ramps(s, baseline, states, cfg)
        starts = [r.start_time for r in ramps]
        assert starts == sorted(starts)

    def test_min_magnitude_filters_small_ramps(self, cfg):
        cfg["ramp_detection"]["min_magnitude_kw"] = 10000.0
        s, baseline, states = _pipeline_pieces(_startup_day(), cfg)
        ramps = detect_ramps(s, baseline, states, cfg)
        assert ramps == []


# ---------------------------------------------------------------------------
# detect_peaks
# ---------------------------------------------------------------------------

class TestDetectPeaks:
    def test_no_op_range_returns_empty(self, cfg):
        s = _series([100.0] * 10)
        baseline_result = {"baseline_kw": 100.0, "peak_kw": 100.0, "operating_range_kw": 0.0}
        is_interp = pd.Series(False, index=s.index)
        assert detect_peaks(s, is_interp, baseline_result, cfg) == []

    def test_single_peak_detected(self, cfg):
        s, baseline, states = _pipeline_pieces(_startup_day(), cfg)
        is_interp = pd.Series(False, index=s.index)
        peaks = detect_peaks(s, is_interp, baseline, cfg)
        assert len(peaks) >= 1
        assert peaks[0].rank == 1
        assert peaks[0].peak_kw == pytest.approx(450.0, abs=20)

    def test_two_separated_peaks_detected(self, cfg):
        vals = [50.0] * 10 + [500.0] * 8 + [50.0] * 10 + [480.0] * 8 + [50.0] * 10
        s, baseline, states = _pipeline_pieces(vals, cfg)
        is_interp = pd.Series(False, index=s.index)
        peaks = detect_peaks(s, is_interp, baseline, cfg)
        assert len(peaks) >= 2
        assert peaks[0].peak_kw >= peaks[1].peak_kw

    def test_peaks_respect_min_prominence(self, cfg):
        cfg["peak_detection"]["min_prominence_fraction"] = 0.99
        vals = [50.0] * 10 + [500.0] * 8 + [50.0] * 10 + [480.0] * 8 + [50.0] * 10
        s, baseline, states = _pipeline_pieces(vals, cfg)
        is_interp = pd.Series(False, index=s.index)
        peaks = detect_peaks(s, is_interp, baseline, cfg)
        # With near-impossible prominence threshold, at most the global peak survives
        assert len(peaks) <= 1

    def test_peak_is_interpolated_flag_propagated(self, cfg):
        vals = [50.0] * 40 + [450.0] + [50.0] * 40  # single-interval spike, unambiguous peak
        s, baseline, states = _pipeline_pieces(vals, cfg)
        is_interp = pd.Series(False, index=s.index)
        peak_ts = s.idxmax()
        is_interp.loc[peak_ts] = True
        peaks = detect_peaks(s, is_interp, baseline, cfg)
        primary = next(p for p in peaks if p.rank == 1)
        assert primary.peak_time == peak_ts
        assert primary.peak_is_interpolated is True


# ---------------------------------------------------------------------------
# detect_operating_periods
# ---------------------------------------------------------------------------

class TestDetectOperatingPeriods:
    def test_no_operating_periods(self, cfg):
        states = _series(["BASELINE"] * 20)
        periods = detect_operating_periods(states, cfg)
        assert periods == []

    def test_single_period_detected(self, cfg):
        states = pd.Series(
            ["BASELINE"] * 10 + ["OPERATING"] * 20 + ["BASELINE"] * 10,
            index=pd.date_range("2024-01-15", periods=40, freq="15min"),
        )
        periods = detect_operating_periods(states, cfg)
        assert len(periods) == 1
        assert periods[0]["rank"] == 1

    def test_two_periods_merged_if_gap_small(self, cfg):
        cfg["multiple_periods"]["min_baseline_gap_minutes"] = 120
        states = pd.Series(
            ["BASELINE"] * 10 + ["OPERATING"] * 10 + ["BASELINE"] * 2 + ["OPERATING"] * 10 + ["BASELINE"] * 10,
            index=pd.date_range("2024-01-15", periods=42, freq="15min"),
        )
        periods = detect_operating_periods(states, cfg)
        assert len(periods) == 1  # merged due to short gap

    def test_two_periods_kept_separate_if_gap_large(self, cfg):
        cfg["multiple_periods"]["min_baseline_gap_minutes"] = 30
        cfg["multiple_periods"]["min_period_duration_minutes"] = 30
        states = pd.Series(
            ["BASELINE"] * 10 + ["OPERATING"] * 10 + ["BASELINE"] * 20 + ["OPERATING"] * 10 + ["BASELINE"] * 10,
            index=pd.date_range("2024-01-15", periods=60, freq="15min"),
        )
        periods = detect_operating_periods(states, cfg)
        assert len(periods) == 2

    def test_periods_ranked_by_duration_descending(self, cfg):
        cfg["multiple_periods"]["min_baseline_gap_minutes"] = 30
        states = pd.Series(
            ["BASELINE"] * 10 + ["OPERATING"] * 5 + ["BASELINE"] * 20 + ["OPERATING"] * 15 + ["BASELINE"] * 10,
            index=pd.date_range("2024-01-15", periods=60, freq="15min"),
        )
        periods = detect_operating_periods(states, cfg)
        assert periods[0]["duration_hours"] >= periods[-1]["duration_hours"]
        assert periods[0]["rank"] == 1

    def test_short_period_below_min_duration_excluded(self, cfg):
        cfg["multiple_periods"]["min_period_duration_minutes"] = 60
        states = pd.Series(
            ["BASELINE"] * 10 + ["OPERATING"] * 2 + ["BASELINE"] * 10,
            index=pd.date_range("2024-01-15", periods=22, freq="15min"),
        )
        periods = detect_operating_periods(states, cfg)
        assert periods == []
