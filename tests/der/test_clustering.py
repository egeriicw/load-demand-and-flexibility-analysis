from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from load_profile.der.clustering import (
    build_daily_profile_matrix,
    cluster_daily_profiles,
    cluster_entity_daily_profiles,
    peak_normalized_series,
    select_k,
)

# Synthetic fixtures below deliberately use only 2 distinct day-shapes, so
# k > 2 candidates in select_k's grid search collapse to fewer effective
# clusters than requested (duplicate profile points) -- expected, not a bug.
pytestmark = pytest.mark.filterwarnings(
    "ignore::sklearn.exceptions.ConvergenceWarning"
)


def _day(date, hours=24, peak_hour=8, peak_value=100.0, base_value=10.0):
    idx = pd.date_range(date, periods=hours, freq="60min", tz="UTC")
    vals = np.full(hours, base_value)
    vals[peak_hour] = peak_value
    return pd.DataFrame({"demand_kw": vals}, index=idx)


def _two_shape_dataset(n_per_shape=4):
    frames = []
    day = 15
    for _ in range(n_per_shape):
        frames.append(_day(f"2024-01-{day:02d}", peak_hour=8, peak_value=100.0))
        day += 1
    for _ in range(n_per_shape):
        frames.append(_day(f"2024-01-{day:02d}", peak_hour=18, peak_value=50.0))
        day += 1
    return pd.concat(frames)


class TestPeakNormalizedSeries:
    def test_normalizes_to_daily_peak(self):
        df = _day("2024-01-15", peak_value=100.0, base_value=10.0)
        norm = peak_normalized_series(df)
        assert norm.max() == pytest.approx(1.0)
        assert norm.iloc[0] == pytest.approx(0.1)

    def test_zero_peak_day_is_all_nan(self):
        idx = pd.date_range("2024-01-15", periods=24, freq="60min", tz="UTC")
        df = pd.DataFrame({"demand_kw": np.zeros(24)}, index=idx)
        norm = peak_normalized_series(df)
        assert norm.isna().all()


class TestBuildDailyProfileMatrix:
    def test_only_complete_days_included(self):
        complete = _day("2024-01-15")
        incomplete_idx = pd.date_range("2024-01-16", periods=10, freq="60min", tz="UTC")
        incomplete = pd.DataFrame({"demand_kw": np.arange(10.0)}, index=incomplete_idx)
        combined = pd.concat([complete, incomplete])
        matrix = build_daily_profile_matrix(combined)
        assert len(matrix) == 1
        assert matrix.shape[1] == 24

    def test_day_with_nan_excluded(self):
        df = _day("2024-01-15")
        df.iloc[3, df.columns.get_loc("demand_kw")] = np.nan
        matrix = build_daily_profile_matrix(df)
        assert len(matrix) == 0

    def test_no_complete_days_returns_empty_frame(self):
        idx = pd.date_range("2024-01-15", periods=5, freq="60min", tz="UTC")
        df = pd.DataFrame({"demand_kw": np.arange(5.0)}, index=idx)
        matrix = build_daily_profile_matrix(df)
        assert matrix.empty


class TestSelectK:
    def test_fewer_than_4_days_forces_k1(self):
        matrix = pd.DataFrame(np.random.default_rng(0).normal(size=(3, 24)))
        k, scores = select_k(matrix)
        assert k == 1
        assert scores == {}

    def test_two_clear_clusters_found(self):
        matrix = build_daily_profile_matrix(_two_shape_dataset(n_per_shape=5))
        k, scores = select_k(matrix)
        assert k == 2
        assert scores  # non-empty silhouette scores dict


class TestClusterDailyProfiles:
    def test_fewer_than_2_days_fails(self, cfg):
        matrix = build_daily_profile_matrix(_day("2024-01-15"))
        result = cluster_daily_profiles(matrix, cfg)
        assert result.success is False

    def test_reproducible_across_runs(self, cfg):
        matrix = build_daily_profile_matrix(_two_shape_dataset(n_per_shape=5))
        r1 = cluster_daily_profiles(matrix, cfg)
        r2 = cluster_daily_profiles(matrix, cfg)
        assert r1.k == r2.k
        assert r1.labels == r2.labels

    def test_cluster_sizes_sum_to_n_days(self, cfg):
        matrix = build_daily_profile_matrix(_two_shape_dataset(n_per_shape=5))
        result = cluster_daily_profiles(matrix, cfg)
        assert result.clusters["cluster_size"].sum() == len(matrix)

    def test_two_shapes_separated_into_two_clusters(self, cfg):
        matrix = build_daily_profile_matrix(_two_shape_dataset(n_per_shape=5))
        result = cluster_daily_profiles(matrix, cfg)
        assert result.success
        assert result.k == 2
        assert len(result.clusters) == 2

    def test_fewer_than_4_days_forces_k1_end_to_end(self, cfg):
        df = pd.concat([_day(f"2024-01-{d}") for d in (15, 16, 17)])
        matrix = build_daily_profile_matrix(df)
        result = cluster_daily_profiles(matrix, cfg)
        assert result.success
        assert result.k == 1


class TestClusterEntityDailyProfiles:
    def test_computes_both_absolute_and_normalized(self, cfg):
        df = _two_shape_dataset(n_per_shape=5)
        results = cluster_entity_daily_profiles(df, cfg)
        assert set(results.keys()) == {"absolute", "normalized"}
        assert results["absolute"].success
        assert results["normalized"].success
