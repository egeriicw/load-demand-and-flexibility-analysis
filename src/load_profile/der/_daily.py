"""Internal helpers shared across der/ modules for per-day grouping and
completeness (DER spec §2.7's ``is_complete_day`` rule: interval count ==
expected for the resolution AND none NaN)."""

from __future__ import annotations

import pandas as pd


def infer_resolution_minutes(index: pd.DatetimeIndex) -> float:
    diffs = index.to_series().diff().dropna().dt.total_seconds() / 60
    if diffs.empty:
        return 60.0
    return float(diffs.mode().iloc[0])


def expected_intervals_per_day(index: pd.DatetimeIndex) -> int:
    res_min = infer_resolution_minutes(index)
    return int(round((24 * 60) / res_min)) if res_min else 0


def complete_day_dates(interval_df: pd.DataFrame, value_col: str = "demand_kw") -> pd.DatetimeIndex:
    """Dates where interval count == expected AND no NaN in ``value_col``."""
    expected = expected_intervals_per_day(interval_df.index)
    date = interval_df.index.normalize()
    tmp = pd.DataFrame({"date": date, "value": interval_df[value_col].to_numpy()})
    sizes = tmp.groupby("date").size()
    counts = tmp.groupby("date")["value"].count()
    complete = sizes[(sizes == expected) & (counts == expected)].index
    return pd.DatetimeIndex(complete)
