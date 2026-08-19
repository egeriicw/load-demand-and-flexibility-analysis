from __future__ import annotations

import pandas as pd
import pytest

from load_profile.der.peak_events import detect_der_peak_events


def _df(n=10, freq="15min"):
    idx = pd.date_range("2024-01-15", periods=n, freq=freq, tz="UTC")
    return pd.DataFrame({"demand_kw": [float(i) for i in range(n)]}, index=idx)


class TestDetectDerPeakEvents:
    def test_no_qualifying_intervals_returns_empty_list(self, cfg):
        df = _df()
        mask = pd.Series(False, index=df.index)
        assert detect_der_peak_events(df, mask, "M1", "threshold_50", cfg) == []

    def test_single_contiguous_run_is_one_event(self, cfg):
        df = _df()
        mask = pd.Series(False, index=df.index)
        mask.iloc[2:5] = True
        events = detect_der_peak_events(df, mask, "M1", "threshold_50", cfg)
        assert len(events) == 1
        assert events[0].n_intervals == 3
        assert events[0].start_time == df.index[2]
        assert events[0].end_time == df.index[4]

    def test_gap_within_allowance_merges_into_one_event(self, cfg):
        cfg["der"]["peak_events"]["allowable_gap_intervals"] = 1
        df = _df()
        mask = pd.Series(False, index=df.index)
        mask.iloc[2] = True
        mask.iloc[4] = True  # 1 non-qualifying interval between (index 3)
        events = detect_der_peak_events(df, mask, "M1", "threshold_50", cfg)
        assert len(events) == 1
        # extends through the intervening non-qualifying interval
        assert events[0].n_intervals == 3
        assert events[0].start_time == df.index[2]
        assert events[0].end_time == df.index[4]

    def test_gap_beyond_allowance_starts_new_event(self, cfg):
        cfg["der"]["peak_events"]["allowable_gap_intervals"] = 0
        df = _df()
        mask = pd.Series(False, index=df.index)
        mask.iloc[2] = True
        mask.iloc[4] = True  # 1 intervening interval > allowance of 0
        events = detect_der_peak_events(df, mask, "M1", "threshold_50", cfg)
        assert len(events) == 2
        assert events[0].n_intervals == 1
        assert events[1].n_intervals == 1

    def test_event_id_format(self, cfg):
        df = _df()
        mask = pd.Series(False, index=df.index)
        mask.iloc[0] = True
        mask.iloc[7] = True
        events = detect_der_peak_events(df, mask, "Portfolio", "top_pct_0_95", cfg)
        assert events[0].event_id == "Portfolio_top_pct_0_95_0001"
        assert events[1].event_id == "Portfolio_top_pct_0_95_0002"

    def test_sustained_vs_short_duration_class(self, cfg):
        cfg["der"]["peak_events"]["sustained_threshold_hours"] = 1.0
        df = _df(n=10, freq="30min")
        mask = pd.Series(False, index=df.index)
        mask.iloc[0:3] = True  # 0:00-1:00 span -> 1.0h, sustained
        events = detect_der_peak_events(df, mask, "M1", "threshold_50", cfg)
        assert events[0].duration_hours == pytest.approx(1.0)
        assert events[0].duration_class == "sustained"

        mask2 = pd.Series(False, index=df.index)
        mask2.iloc[5:6] = True  # single interval -> 0h duration, short
        events2 = detect_der_peak_events(df, mask2, "M1", "threshold_50", cfg)
        assert events2[0].duration_class == "short"

    def test_max_mean_min_demand_reflect_full_span(self, cfg):
        df = _df()  # demand_kw = 0..9
        mask = pd.Series(False, index=df.index)
        mask.iloc[[3, 5]] = True  # qualifying at 3kw and 5kw; span includes 4kw too
        cfg["der"]["peak_events"]["allowable_gap_intervals"] = 1
        events = detect_der_peak_events(df, mask, "M1", "threshold_50", cfg)
        assert events[0].max_demand_kw == 5.0
        assert events[0].min_demand_kw == 3.0
        assert events[0].mean_demand_kw == pytest.approx(4.0)
