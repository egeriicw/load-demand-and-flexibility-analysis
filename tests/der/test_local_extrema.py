from __future__ import annotations

import numpy as np
import pandas as pd

from load_profile.der.local_extrema import add_local_extrema_flags


def _df(values):
    idx = pd.date_range("2024-01-15", periods=len(values), freq="15min", tz="UTC")
    return pd.DataFrame({"demand_kw": values}, index=idx)


class TestAddLocalExtremaFlags:
    def test_simple_peak_and_valley(self):
        out = add_local_extrema_flags(_df([1.0, 5.0, 1.0, -3.0, 1.0]))
        assert out["is_local_peak"].tolist() == [False, True, False, False, False]
        assert out["is_local_valley"].tolist() == [False, False, False, True, False]

    def test_boundary_points_never_classified(self):
        out = add_local_extrema_flags(_df([10.0, 1.0, 2.0, 3.0, 20.0]))
        assert out["is_local_peak"].iloc[0] == False  # noqa: E712
        assert out["is_local_peak"].iloc[-1] == False  # noqa: E712
        assert out["is_local_valley"].iloc[0] == False  # noqa: E712
        assert out["is_local_valley"].iloc[-1] == False  # noqa: E712

    def test_nan_neighbor_prevents_classification(self):
        out = add_local_extrema_flags(_df([1.0, np.nan, 1.0, 5.0, 1.0]))
        # index 2 (value 1.0) has a NaN left-neighbor -> can't classify
        assert out["is_local_peak"].iloc[2] == False  # noqa: E712
        assert out["is_local_valley"].iloc[2] == False  # noqa: E712
        # index 3 (value 5.0) has valid neighbors 1.0/1.0 -> still a peak
        assert out["is_local_peak"].iloc[3] == True  # noqa: E712

    def test_monotonic_series_has_no_extrema(self):
        out = add_local_extrema_flags(_df([1.0, 2.0, 3.0, 4.0, 5.0]))
        assert not out["is_local_peak"].any()
        assert not out["is_local_valley"].any()

    def test_plateau_is_not_a_peak(self):
        # equal neighbors fail strict > / < comparison
        out = add_local_extrema_flags(_df([1.0, 5.0, 5.0, 1.0]))
        assert out["is_local_peak"].tolist() == [False, False, False, False]
