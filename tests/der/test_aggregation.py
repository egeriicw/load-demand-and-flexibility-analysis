from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from load_profile.der.aggregation import aggregate_entity, build_entity_frame


def _interval_df_multi():
    idx = pd.date_range("2024-01-15", periods=4, freq="15min", tz="UTC")
    m1 = pd.DataFrame({"demand_kw": [10.0, 20.0, np.nan, 40.0]}, index=idx)
    m1["meter_id"] = "M1"
    m2 = pd.DataFrame({"demand_kw": [1.0, np.nan, np.nan, 4.0]}, index=idx)
    m2["meter_id"] = "M2"
    return pd.concat([m1, m2])


class TestAggregateEntity:
    def test_sums_never_averages(self):
        out = aggregate_entity(_interval_df_multi(), ["M1", "M2"])
        idx0 = out.index[0]
        assert out.loc[idx0, "demand_kw"] == pytest.approx(11.0)  # 10 + 1, not 5.5

    def test_min_count_1_uses_partial_coverage(self):
        out = aggregate_entity(_interval_df_multi(), ["M1", "M2"], min_count=1)
        idx1 = out.index[1]  # M1=20, M2=NaN
        assert out.loc[idx1, "demand_kw"] == pytest.approx(20.0)
        assert out.loc[idx1, "n_meters_reporting"] == 1

    def test_all_nan_group_stays_nan_not_zero(self):
        out = aggregate_entity(_interval_df_multi(), ["M1", "M2"], min_count=1)
        idx2 = out.index[2]  # both NaN
        assert np.isnan(out.loc[idx2, "demand_kw"])
        assert out.loc[idx2, "n_meters_reporting"] == 0

    def test_min_count_2_requires_both_meters(self):
        out = aggregate_entity(_interval_df_multi(), ["M1", "M2"], min_count=2)
        idx1 = out.index[1]  # only M1 reports -> below min_count
        assert np.isnan(out.loc[idx1, "demand_kw"])
        idx0 = out.index[0]  # both report
        assert out.loc[idx0, "demand_kw"] == pytest.approx(11.0)

    def test_single_meter_subset_returns_that_meter_unchanged(self):
        out = aggregate_entity(_interval_df_multi(), ["M1"])
        assert out["demand_kw"].tolist()[:2] == [10.0, 20.0]
        assert (out["n_meters_reporting"] <= 1).all()

    def test_empty_meter_ids_returns_empty_frame_with_expected_columns(self):
        out = aggregate_entity(_interval_df_multi(), [])
        assert list(out.columns) == ["demand_kw", "n_meters_reporting"]
        assert len(out) == 0

    def test_empty_interval_df_returns_empty_frame(self):
        empty = pd.DataFrame(columns=["demand_kw", "meter_id"])
        out = aggregate_entity(empty, ["M1"])
        assert len(out) == 0


class TestBuildEntityFrame:
    def test_stamps_entity_id(self, cfg):
        out = build_entity_frame("Portfolio", ["M1", "M2"], _interval_df_multi(), cfg)
        assert (out["entity_id"] == "Portfolio").all()

    def test_is_missing_matches_nan_demand(self, cfg):
        out = build_entity_frame("Portfolio", ["M1", "M2"], _interval_df_multi(), cfg)
        idx2 = out.index[2]
        assert out.loc[idx2, "is_missing"] == True  # noqa: E712

    def test_uses_configured_min_count(self, cfg):
        cfg["der"]["aggregation"]["min_count"] = 2
        out = build_entity_frame("Portfolio", ["M1", "M2"], _interval_df_multi(), cfg)
        idx1 = out.index[1]
        assert out.loc[idx1, "is_missing"] == True  # noqa: E712
