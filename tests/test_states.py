from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from load_profile.states import (
    STATE_BASELINE,
    STATE_OPERATING,
    STATE_UNKNOWN,
    compute_normalized_demand,
    detect_states,
)


def _series(vals, freq="15min", tz="America/Chicago", start="2024-01-15"):
    idx = pd.date_range(start, periods=len(vals), freq=freq, tz=tz)
    return pd.Series(vals, index=idx)


class TestDetectStates:
    def test_missing_baseline_returns_all_unknown(self, cfg):
        s = _series([100.0] * 10)
        baseline_result = {"baseline_kw": np.nan, "peak_kw": np.nan}
        states = detect_states(s, baseline_result, cfg)
        assert (states == STATE_UNKNOWN).all()

    def test_zero_operating_range_returns_all_baseline(self, cfg):
        s = _series([100.0] * 10)
        baseline_result = {"baseline_kw": 100.0, "peak_kw": 100.0}
        states = detect_states(s, baseline_result, cfg)
        assert (states == STATE_BASELINE).all()

    def test_nan_demand_is_unknown(self, cfg):
        s = _series([np.nan, 100.0, 100.0, 100.0, 100.0])
        baseline_result = {"baseline_kw": 50.0, "peak_kw": 150.0}
        states = detect_states(s, baseline_result, cfg)
        assert states.iloc[0] == STATE_UNKNOWN

    def test_high_demand_persists_to_operating(self, cfg):
        cfg["operating_threshold"]["min_state_persistence_minutes"] = 30
        # baseline=50, peak=150 -> entry thresh = 50+0.2*100=70
        vals = [50.0] * 8 + [150.0] * 20
        s = _series(vals)
        baseline_result = {"baseline_kw": 50.0, "peak_kw": 150.0}
        states = detect_states(s, baseline_result, cfg)
        assert states.iloc[-1] == STATE_OPERATING
        assert states.iloc[0] == STATE_BASELINE

    def test_transient_excursion_below_persistence_collapsed(self, cfg):
        cfg["operating_threshold"]["min_state_persistence_minutes"] = 60
        cfg["operating_threshold"]["alpha_entry"] = 0.20
        cfg["operating_threshold"]["alpha_exit"] = 0.15
        # Single 15-min spike above threshold; too short to persist as OPERATING
        vals = [50.0] * 10 + [150.0] + [50.0] * 10
        s = _series(vals)
        baseline_result = {"baseline_kw": 50.0, "peak_kw": 150.0}
        states = detect_states(s, baseline_result, cfg)
        # Persistence enforcement should merge short excursion back into BASELINE
        assert states.iloc[10] != STATE_OPERATING or (states == STATE_OPERATING).sum() == 0

    def test_hysteresis_entry_exceeds_exit(self, cfg):
        alpha_e = cfg["operating_threshold"]["alpha_entry"]
        alpha_x = cfg["operating_threshold"]["alpha_exit"]
        assert alpha_e > alpha_x


class TestComputeNormalizedDemand:
    def test_normalization_basic(self, cfg):
        s = _series([50.0, 100.0, 150.0])
        baseline_result = {"baseline_kw": 50.0, "peak_kw": 150.0, "operating_range_kw": 100.0}
        norm = compute_normalized_demand(s, baseline_result, cfg)
        assert norm.iloc[0] == pytest.approx(0.0)
        assert norm.iloc[1] == pytest.approx(0.5)
        assert norm.iloc[2] == pytest.approx(1.0)

    def test_super_peak_exceeds_one(self, cfg):
        s = _series([50.0, 200.0])
        baseline_result = {"baseline_kw": 50.0, "peak_kw": 150.0, "operating_range_kw": 100.0}
        norm = compute_normalized_demand(s, baseline_result, cfg)
        assert norm.iloc[1] > 1.0

    def test_nan_baseline_returns_all_nan(self, cfg):
        s = _series([50.0, 100.0])
        baseline_result = {"baseline_kw": np.nan, "peak_kw": 150.0, "operating_range_kw": np.nan}
        norm = compute_normalized_demand(s, baseline_result, cfg)
        assert norm.isna().all()

    def test_zero_range_returns_all_nan(self, cfg):
        s = _series([50.0, 100.0])
        baseline_result = {"baseline_kw": 100.0, "peak_kw": 100.0, "operating_range_kw": 0.0}
        norm = compute_normalized_demand(s, baseline_result, cfg)
        assert norm.isna().all()

    def test_p99_normalization_mode(self, cfg):
        cfg["normalization"]["peak_for_normalization"] = "p99"
        s = _series(list(range(100)), freq="15min")  # 0..99
        baseline_result = {"baseline_kw": 0.0, "peak_kw": 99.0, "operating_range_kw": 99.0}
        norm = compute_normalized_demand(s, baseline_result, cfg)
        assert not norm.isna().all()
