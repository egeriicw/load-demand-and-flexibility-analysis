from __future__ import annotations

import numpy as np
import pytest

from load_profile.der.change_point import (
    fit_2p,
    fit_3p_cooling,
    fit_3p_heating,
    fit_4p,
    fit_5p,
    select_best_change_point_model,
)


class TestFit2P:
    def test_recovers_known_linear_relationship(self):
        x = np.linspace(0, 100, 30)
        y = 10.0 + 0.5 * x
        model = fit_2p(x, y)
        assert model.success
        assert model.params["base"] == pytest.approx(10.0, abs=1e-6)
        assert model.params["slope"] == pytest.approx(0.5, abs=1e-6)
        assert model.r_squared == pytest.approx(1.0, abs=1e-6)

    def test_insufficient_points_fails(self):
        model = fit_2p([1, 2, 3], [1, 2, 3])
        assert model.success is False
        assert np.isnan(model.r_squared)

    def test_nan_pairs_dropped_before_fitting(self):
        x = [0, 10, 20, 30, np.nan]
        y = [10, 15, 20, 25, 999]
        model = fit_2p(x, y)
        assert model.success
        assert model.n_points == 4


class TestFit3PCooling:
    def test_recovers_known_breakpoint(self):
        bp = 65.0
        x = np.linspace(30, 100, 60)
        baseload, slope = 20.0, 0.8
        y = baseload + slope * np.maximum(x - bp, 0.0)
        model = fit_3p_cooling(x, y)
        assert model.success
        assert model.breakpoints[0] == pytest.approx(bp, abs=1.0)
        assert model.params["baseload"] == pytest.approx(baseload, abs=1.0)
        assert model.r_squared > 0.99

    def test_insufficient_points_fails(self):
        model = fit_3p_cooling([1, 2, 3, 4], [1, 2, 3, 4])
        assert model.success is False


class TestFit3PHeating:
    def test_recovers_known_breakpoint(self):
        bp = 55.0
        x = np.linspace(0, 90, 60)
        baseload, slope = 15.0, 0.6
        y = baseload + slope * np.maximum(bp - x, 0.0)
        model = fit_3p_heating(x, y)
        assert model.success
        assert model.breakpoints[0] == pytest.approx(bp, abs=1.0)
        assert model.r_squared > 0.99


class TestFit4P:
    def test_recovers_known_shared_breakpoint(self):
        bp = 60.0
        x = np.linspace(20, 100, 80)
        base, h_slope, c_slope = 10.0, 0.4, 0.7
        y = base + h_slope * np.maximum(bp - x, 0.0) + c_slope * np.maximum(x - bp, 0.0)
        model = fit_4p(x, y)
        assert model.success
        assert model.breakpoints[0] == pytest.approx(bp, abs=1.0)
        assert model.params["heating_slope"] >= 0
        assert model.params["cooling_slope"] >= 0
        assert model.r_squared > 0.99

    def test_slopes_never_negative_even_under_noise(self):
        rng = np.random.default_rng(0)
        x = np.linspace(20, 100, 80)
        y = 10.0 + rng.normal(0, 0.5, size=x.shape)  # ~flat, noisy
        model = fit_4p(x, y)
        if model.success:
            assert model.params["heating_slope"] >= 0
            assert model.params["cooling_slope"] >= 0

    def test_insufficient_points_fails(self):
        model = fit_4p(list(range(5)), list(range(5)))
        assert model.success is False


class TestFit5P:
    def test_recovers_known_independent_breakpoints(self):
        h_bp, c_bp = 50.0, 70.0
        x = np.linspace(10, 110, 100)
        base, h_slope, c_slope = 8.0, 0.5, 0.9
        y = base + h_slope * np.maximum(h_bp - x, 0.0) + c_slope * np.maximum(x - c_bp, 0.0)
        model = fit_5p(x, y)
        assert model.success
        assert model.breakpoints[0] == pytest.approx(h_bp, abs=1.0)
        assert model.breakpoints[1] == pytest.approx(c_bp, abs=1.0)
        assert model.breakpoints[0] <= model.breakpoints[1]

    def test_insufficient_points_fails(self):
        model = fit_5p(list(range(9)), list(range(9)))
        assert model.success is False


class TestSelectBestChangePointModel:
    def test_picks_2p_for_purely_linear_data(self):
        x = np.linspace(0, 100, 40)
        y = 5.0 + 0.3 * x
        best = select_best_change_point_model(x, y)
        assert best is not None
        assert best.model_type == "2P"

    def test_picks_4p_for_clear_v_shaped_data(self):
        bp = 60.0
        x = np.linspace(10, 110, 80)
        y = 10.0 + 0.8 * np.maximum(bp - x, 0.0) + 0.6 * np.maximum(x - bp, 0.0)
        best = select_best_change_point_model(x, y)
        assert best is not None
        assert best.model_type in ("4P", "5P")  # richer model should win on a real V-shape

    def test_none_when_all_candidates_insufficient_data(self):
        best = select_best_change_point_model([1, 2], [1, 2])
        assert best is None

    def test_ties_go_to_simpler_model(self):
        # Perfectly linear data: every model that CAN fit it reaches r2=1.0;
        # adjusted R^2 for 2P is then >= that of richer models (fewer params
        # penalized less), so 2P should still win outright, not just on a tie.
        x = np.linspace(0, 100, 50)
        y = 3.0 + 0.25 * x
        best = select_best_change_point_model(x, y)
        assert best.model_type == "2P"
