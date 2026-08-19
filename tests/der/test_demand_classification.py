from __future__ import annotations

import pandas as pd
import pytest

from load_profile.der.demand_classification import classify_demand_families


def _df(values):
    idx = pd.date_range("2024-01-15", periods=len(values), freq="15min", tz="UTC")
    return pd.DataFrame({"demand_kw": values}, index=idx)


class TestClassifyDemandFamilies:
    def test_threshold_family(self, cfg):
        cfg["der"]["demand_classification"]["thresholds_kw"] = [50]
        out = classify_demand_families(_df([10.0, 60.0, 40.0, 90.0]), cfg)
        assert out["meets_threshold_50"].tolist() == [False, True, False, True]

    def test_percentile_family(self, cfg):
        cfg["der"]["demand_classification"]["top_percentiles"] = [0.75]
        out = classify_demand_families(_df([10.0, 20.0, 30.0, 40.0]), cfg)
        q = out["demand_kw"].quantile(0.75)
        assert out["top_pct_0_75"].tolist() == (out["demand_kw"] >= q).tolist()

    def test_rank_family_picks_exactly_n_highest(self, cfg):
        cfg["der"]["demand_classification"]["top_n_hours"] = [2]
        out = classify_demand_families(_df([10.0, 40.0, 30.0, 20.0]), cfg)
        assert out["top_rank_2"].sum() == 2
        assert out.loc[out["top_rank_2"], "demand_kw"].tolist() == [40.0, 30.0]

    def test_families_are_independent_columns_not_collapsed(self, cfg):
        cfg["der"]["demand_classification"] = {
            "thresholds_kw": [50], "top_percentiles": [0.5], "top_n_hours": [1],
        }
        out = classify_demand_families(_df([10.0, 60.0, 40.0, 90.0]), cfg)
        assert {"meets_threshold_50", "top_pct_0_5", "top_rank_1"} <= set(out.columns)

    def test_no_config_produces_no_new_columns(self, cfg):
        out = classify_demand_families(_df([10.0, 60.0]), cfg)
        assert list(out.columns) == ["demand_kw"]
