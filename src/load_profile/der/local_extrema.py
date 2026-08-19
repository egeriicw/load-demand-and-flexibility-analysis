"""
Local peak/valley detection via simple 3-point comparison (DER spec §5.4).

Deliberately separate from ``events.py``'s prominence/plateau-based peak
detection on the smoothed series — this is a strict per-interval boolean
comparator on the raw (unsmoothed) ``demand_kw`` value.
"""

from __future__ import annotations

import pandas as pd


def add_local_extrema_flags(
    interval_df: pd.DataFrame, value_col: str = "demand_kw"
) -> pd.DataFrame:
    """
    Add ``is_local_peak`` / ``is_local_valley`` boolean columns.

    Interval ``i`` is a local peak iff ``d[i] > d[i-1] and d[i] > d[i+1]``
    (valley: reversed inequalities). Boundary points (first/last row) and any
    point with a NaN neighbor cannot be classified and default to ``False``.
    """
    d = interval_df[value_col]
    prev_d = d.shift(1)
    next_d = d.shift(-1)
    classifiable = d.notna() & prev_d.notna() & next_d.notna()

    is_peak = classifiable & (d > prev_d) & (d > next_d)
    is_valley = classifiable & (d < prev_d) & (d < next_d)

    out = interval_df.copy()
    out["is_local_peak"] = is_peak.fillna(False)
    out["is_local_valley"] = is_valley.fillna(False)
    return out
