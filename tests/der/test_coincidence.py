from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from load_profile.der.coincidence import (
    CoincidenceResult,
    compute_coincidence_factor,
    compute_daily_coincidence,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_multi(meter_profiles: dict[str, list[float]], freq: str = "60min") -> pd.DataFrame:
    """
    Build a minimal interval_df_multi from {meter_id: [hourly demand values]}.
    All meters share the same hourly index starting 2024-01-15 UTC.
    """
    n = max(len(v) for v in meter_profiles.values())
    idx = pd.date_range("2024-01-15", periods=n, freq=freq, tz="UTC")
    frames = []
    for meter_id, values in meter_profiles.items():
        df = pd.DataFrame({"demand_kw": values, "meter_id": meter_id}, index=idx[:len(values)])
        frames.append(df)
    return pd.concat(frames)


def _flat_profile(n: int = 24, value: float = 10.0) -> list[float]:
    return [value] * n


def _peak_at(hour: int, peak: float = 100.0, base: float = 10.0, n: int = 24) -> list[float]:
    vals = [base] * n
    vals[hour] = peak
    return vals


# ---------------------------------------------------------------------------
# CoincidenceResult — sanity
# ---------------------------------------------------------------------------

class TestCoincidenceResult:
    def test_default_failed_result(self):
        r = CoincidenceResult(success=False)
        assert not r.success
        assert np.isnan(r.coincidence_factor)
        assert r.meter_peak_kw == {}


# ---------------------------------------------------------------------------
# compute_coincidence_factor — study-period level
# ---------------------------------------------------------------------------

class TestComputeCoincidenceFactor:
    def test_perfect_coincidence_is_1(self, cfg):
        """Two identical profiles peak at the same time — CF must be 1.0."""
        multi = _make_multi({"M1": _peak_at(8), "M2": _peak_at(8)})
        result = compute_coincidence_factor(multi, ["M1", "M2"], cfg)
        assert result.success
        assert result.coincidence_factor == pytest.approx(1.0)

    def test_staggered_peaks_cf_below_1(self, cfg):
        """Meters peak at different hours — group peak < sum of individual peaks."""
        multi = _make_multi({
            "M1": _peak_at(8,  peak=100.0),
            "M2": _peak_at(18, peak=100.0),
        })
        result = compute_coincidence_factor(multi, ["M1", "M2"], cfg)
        assert result.success
        # group peak = max(100+10, 10+100, ...) = 110; sum of individual = 200
        assert result.coincidence_factor == pytest.approx(110.0 / 200.0)

    def test_group_peak_kw_is_max_of_sum(self, cfg):
        multi = _make_multi({
            "M1": _peak_at(8,  peak=80.0, base=5.0),
            "M2": _peak_at(8,  peak=60.0, base=5.0),
        })
        result = compute_coincidence_factor(multi, ["M1", "M2"], cfg)
        assert result.group_peak_kw == pytest.approx(140.0)  # both peak at hour 8

    def test_sum_of_individual_peaks_correct(self, cfg):
        multi = _make_multi({
            "M1": _peak_at(8,  peak=80.0, base=5.0),
            "M2": _peak_at(18, peak=60.0, base=5.0),
        })
        result = compute_coincidence_factor(multi, ["M1", "M2"], cfg)
        assert result.sum_of_individual_peaks_kw == pytest.approx(140.0)

    def test_coincident_peak_timestamp_correct(self, cfg):
        multi = _make_multi({"M1": _peak_at(8), "M2": _peak_at(8)})
        result = compute_coincidence_factor(multi, ["M1", "M2"], cfg)
        assert result.coincident_peak_timestamp.hour == 8

    def test_meter_peak_kw_populated(self, cfg):
        multi = _make_multi({"M1": _peak_at(8, peak=90.0), "M2": _peak_at(18, peak=70.0)})
        result = compute_coincidence_factor(multi, ["M1", "M2"], cfg)
        assert result.meter_peak_kw["M1"] == pytest.approx(90.0)
        assert result.meter_peak_kw["M2"] == pytest.approx(70.0)

    def test_n_meters_reported(self, cfg):
        multi = _make_multi({"M1": _peak_at(8), "M2": _peak_at(8)})
        result = compute_coincidence_factor(multi, ["M1", "M2"], cfg)
        assert result.n_meters == 2

    def test_fewer_than_min_meters_fails(self, cfg):
        """Only one meter available; default min_meters=2 should fail."""
        multi = _make_multi({"M1": _peak_at(8)})
        result = compute_coincidence_factor(multi, ["M1", "M2"], cfg)
        assert not result.success

    def test_unknown_meter_ids_ignored(self, cfg):
        """Requesting a non-existent meter_id degrades to fewer available meters."""
        multi = _make_multi({"M1": _peak_at(8)})
        result = compute_coincidence_factor(multi, ["M1", "GHOST"], cfg)
        assert not result.success  # only 1 real meter found

    def test_min_meters_1_accepts_single_meter(self, cfg):
        """With min_meters=1 override, single-meter CF should equal 1.0."""
        cfg.setdefault("der", {})["coincidence"] = {"min_meters": 1}
        multi = _make_multi({"M1": _peak_at(8, peak=50.0)})
        result = compute_coincidence_factor(multi, ["M1"], cfg)
        assert result.success
        assert result.coincidence_factor == pytest.approx(1.0)

    def test_three_meters_partial_coincidence(self, cfg):
        """Three meters; M1+M2 peak together, M3 at a different hour."""
        multi = _make_multi({
            "M1": _peak_at(8,  peak=50.0, base=5.0),
            "M2": _peak_at(8,  peak=50.0, base=5.0),
            "M3": _peak_at(18, peak=50.0, base=5.0),
        })
        result = compute_coincidence_factor(multi, ["M1", "M2", "M3"], cfg)
        assert result.success
        # group peak at hour 8: 50+50+5 = 105; sum individual = 150
        assert result.group_peak_kw == pytest.approx(105.0)
        assert result.sum_of_individual_peaks_kw == pytest.approx(150.0)
        assert result.coincidence_factor == pytest.approx(105.0 / 150.0)


# ---------------------------------------------------------------------------
# compute_daily_coincidence — per-day level
# ---------------------------------------------------------------------------

class TestComputeDailyCoincidence:
    def _two_day_multi(self):
        """Two meters, two complete days; M1 peaks at hour 8, M2 at hour 18."""
        idx1 = pd.date_range("2024-01-15", periods=24, freq="60min", tz="UTC")
        idx2 = pd.date_range("2024-01-16", periods=24, freq="60min", tz="UTC")

        def _profile(idx, peak_hour, peak_val=100.0, base=10.0):
            vals = [base] * 24
            vals[peak_hour] = peak_val
            return pd.DataFrame({"demand_kw": vals, "meter_id": "placeholder"}, index=idx)

        m1_d1 = _profile(idx1, 8)
        m1_d1["meter_id"] = "M1"
        m2_d1 = _profile(idx1, 18)
        m2_d1["meter_id"] = "M2"
        m1_d2 = _profile(idx2, 8)
        m1_d2["meter_id"] = "M1"
        m2_d2 = _profile(idx2, 8)   # both peak at 8 on day 2
        m2_d2["meter_id"] = "M2"
        return pd.concat([m1_d1, m2_d1, m1_d2, m2_d2])

    def test_returns_one_row_per_day(self, cfg):
        multi = self._two_day_multi()
        result = compute_daily_coincidence(multi, ["M1", "M2"], cfg)
        assert len(result) == 2

    def test_perfect_coincidence_day_cf_is_1(self, cfg):
        """Day 2: both meters peak at hour 8 → CF = 1.0."""
        multi = self._two_day_multi()
        result = compute_daily_coincidence(multi, ["M1", "M2"], cfg)
        day2 = result[result["date"] == pd.Timestamp("2024-01-16").date()]
        assert day2["coincidence_factor"].iloc[0] == pytest.approx(1.0)

    def test_staggered_day_cf_below_1(self, cfg):
        """Day 1: M1 peaks at 8, M2 at 18 → CF < 1.0."""
        multi = self._two_day_multi()
        result = compute_daily_coincidence(multi, ["M1", "M2"], cfg)
        day1 = result[result["date"] == pd.Timestamp("2024-01-15").date()]
        cf = day1["coincidence_factor"].iloc[0]
        assert cf < 1.0
        assert cf > 0.0

    def test_fewer_than_min_meters_returns_empty(self, cfg):
        multi = _make_multi({"M1": _peak_at(8)})
        result = compute_daily_coincidence(multi, ["M1", "M2"], cfg)
        assert result.empty

    def test_columns_present(self, cfg):
        multi = self._two_day_multi()
        result = compute_daily_coincidence(multi, ["M1", "M2"], cfg)
        expected = {
            "date", "coincidence_factor", "group_peak_kw",
            "sum_of_individual_peaks_kw", "coincident_peak_timestamp",
            "n_meters_reporting",
        }
        assert expected.issubset(result.columns)

    def test_n_meters_reporting_correct(self, cfg):
        multi = self._two_day_multi()
        result = compute_daily_coincidence(multi, ["M1", "M2"], cfg)
        assert (result["n_meters_reporting"] == 2).all()

    def test_all_nan_day_excluded(self, cfg):
        """A day where both meters are NaN should not appear in output."""
        idx = pd.date_range("2024-01-15", periods=24, freq="60min", tz="UTC")
        idx_nan = pd.date_range("2024-01-16", periods=24, freq="60min", tz="UTC")
        frames = []
        for m in ("M1", "M2"):
            df = pd.DataFrame({"demand_kw": _peak_at(8), "meter_id": m}, index=idx)
            df_nan = pd.DataFrame(
                {"demand_kw": [float("nan")] * 24, "meter_id": m}, index=idx_nan
            )
            frames.extend([df, df_nan])
        multi = pd.concat(frames)
        result = compute_daily_coincidence(multi, ["M1", "M2"], cfg)
        assert len(result) == 1
        assert result["date"].iloc[0] == pd.Timestamp("2024-01-15").date()
