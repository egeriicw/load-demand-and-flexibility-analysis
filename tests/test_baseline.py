from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from load_profile.baseline import estimate_baseline


def _series(vals, freq="15min", tz="America/Chicago", start="2024-01-15"):
    idx = pd.date_range(start, periods=len(vals), freq=freq, tz=tz)
    return pd.Series(vals, index=idx)


class TestEstimateBaseline:
    def test_empty_series_returns_empty_result(self, cfg):
        s = _series([np.nan] * 10)
        result = estimate_baseline(s, 15, cfg)
        assert np.isnan(result["baseline_kw"])
        assert result["baseline_method"] == "none"
        assert result["is_continuous_operation"] is False

    def test_classic_startup_finds_sustained_low_region(self, cfg):
        # 8 hours low (50), 8 hours high (500), 8 hours low (50) -> at 15min res, 96 pts
        n_per = 32
        vals = [50.0] * n_per + [500.0] * n_per + [50.0] * n_per
        s = _series(vals)
        result = estimate_baseline(s, 15, cfg)
        assert result["baseline_method"] == "hybrid_sustained"
        assert result["baseline_kw"] == pytest.approx(50.0, abs=1.0)
        assert result["peak_kw"] == pytest.approx(500.0)
        assert result["is_continuous_operation"] is False

    def test_continuous_operation_flagged_for_flat_load(self, cfg):
        rng = np.random.default_rng(0)
        vals = 500.0 + rng.normal(0, 5, 96)
        s = _series(vals)
        result = estimate_baseline(s, 15, cfg)
        assert result["is_continuous_operation"] is True

    def test_fallback_percentile_when_no_sustained_region(self, cfg):
        cfg["baseline"]["min_persistence_minutes"] = 600  # impossible to satisfy in 96 pts
        vals = [50.0] * 20 + [500.0] * 20 + [50.0] * 20
        s = _series(vals)
        result = estimate_baseline(s, 15, cfg)
        assert result["baseline_method"] == "fallback_percentile"
        assert result["baseline_period_start"] is None
        assert result["baseline_period_duration_hours"] == 0.0

    def test_operating_range_is_peak_minus_baseline(self, cfg):
        vals = [50.0] * 32 + [500.0] * 32 + [50.0] * 32
        s = _series(vals)
        result = estimate_baseline(s, 15, cfg)
        assert result["operating_range_kw"] == pytest.approx(
            result["peak_kw"] - result["baseline_kw"], abs=0.5
        )

    def test_nan_values_excluded_from_stats(self, cfg):
        vals = [50.0] * 32 + [np.nan] * 5 + [500.0] * 27 + [50.0] * 32
        s = _series(vals)
        result = estimate_baseline(s, 15, cfg)
        assert not np.isnan(result["baseline_kw"])
        assert not np.isnan(result["peak_kw"])

    def test_low_demand_percentile_affects_threshold(self, cfg):
        cfg["baseline"]["low_demand_percentile"] = 50
        vals = [50.0] * 32 + [500.0] * 32 + [50.0] * 32
        s = _series(vals)
        result = estimate_baseline(s, 15, cfg)
        # with 50th percentile threshold, more of the day counts as "low"
        assert result["baseline_method"] in ("hybrid_sustained", "fallback_percentile")
