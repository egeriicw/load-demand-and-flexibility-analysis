"""
Recurring-pattern discovery (DER spec §5.8/§21) — heuristic/statistical,
never causal. Every discovered pattern reports frequency/dates/statistical
support and must be documented as *association*, not physical causation.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from ._daily import expected_intervals_per_day, infer_resolution_minutes


def build_daily_summary(interval_df: pd.DataFrame, value_col: str = "demand_kw") -> pd.DataFrame:
    """
    Per-day summary used by the pattern-discovery functions below:
    ``date``, ``is_complete_day``, ``daily_energy_kwh``, ``maximum_demand_kw``,
    ``peak_time_minutes`` (minutes since local midnight of the day's max
    interval; NaN for a day with no non-NaN demand).

    Callers wanting shape-pattern discovery merge in a ``der_primary_shape``
    column themselves (e.g. from ``load_shape.classify_load_shape``'s
    output, joined on ``date``) — this function stays independent of that
    module so it has no forced import relationship with it.
    """
    expected = expected_intervals_per_day(interval_df.index)
    res_min = infer_resolution_minutes(interval_df.index)
    date = interval_df.index.normalize()
    demand = interval_df[value_col]

    tmp = pd.DataFrame({"date": date, "demand_kw": demand.to_numpy()}, index=interval_df.index)
    grouped = tmp.groupby("date")

    sizes = grouped.size()
    counts = grouped["demand_kw"].count()
    is_complete = (sizes == expected) & (counts == expected)

    daily_energy_kwh = grouped["demand_kw"].sum(min_count=1) * res_min / 60.0
    maximum_demand_kw = grouped["demand_kw"].max()

    non_null = tmp.dropna(subset=["demand_kw"])
    idxmax = non_null.groupby("date")["demand_kw"].idxmax()
    peak_minutes = pd.Series(
        {d: (ts.hour * 60 + ts.minute) for d, ts in idxmax.items()}, dtype=float
    )

    summary = pd.DataFrame({
        "is_complete_day": is_complete,
        "daily_energy_kwh": daily_energy_kwh,
        "maximum_demand_kw": maximum_demand_kw,
    })
    summary["peak_time_minutes"] = peak_minutes
    return summary.reset_index()


def find_recurring_peak_timing(daily_summary: pd.DataFrame, cfg: dict[str, Any]) -> pd.DataFrame:
    """
    Bucket each complete day's peak_time into ``window_minutes`` buckets;
    report buckets occurring on >= ``min_occurrences`` days.
    """
    pcfg = cfg.get("der", {}).get("patterns", {})
    window_minutes = pcfg.get("peak_timing_window_minutes", 30)
    min_occurrences = pcfg.get("min_occurrences", 3)

    complete = daily_summary[
        daily_summary["is_complete_day"] & daily_summary["peak_time_minutes"].notna()
    ]
    n_complete = int(daily_summary["is_complete_day"].sum())
    empty = pd.DataFrame(
        columns=["window_start_minutes", "window_end_minutes", "n_days", "statistical_support", "dates"]
    )
    if n_complete == 0 or complete.empty:
        return empty

    bucket = (complete["peak_time_minutes"] // window_minutes) * window_minutes
    rows = []
    for bucket_start, grp in complete.assign(_bucket=bucket).groupby("_bucket"):
        n_days = len(grp)
        if n_days < min_occurrences:
            continue
        rows.append({
            "window_start_minutes": int(bucket_start),
            "window_end_minutes": int(bucket_start + window_minutes),
            "n_days": n_days,
            "statistical_support": n_days / n_complete,
            "dates": sorted(grp["date"].tolist()),
        })
    return pd.DataFrame(rows) if rows else empty


def find_recurring_shape(daily_summary: pd.DataFrame, cfg: dict[str, Any]) -> pd.DataFrame:
    """
    Group complete days by ``der_primary_shape`` (excluding ``insufficient_data``);
    report shapes occurring on >= ``min_occurrences`` days, same support
    fraction convention as ``find_recurring_peak_timing`` (fraction of
    complete days).

    Requires ``daily_summary`` to already carry a ``der_primary_shape`` column.
    """
    pcfg = cfg.get("der", {}).get("patterns", {})
    min_occurrences = pcfg.get("min_occurrences", 3)

    empty = pd.DataFrame(columns=["primary_shape", "n_days", "statistical_support", "dates"])
    if "der_primary_shape" not in daily_summary.columns:
        return empty

    n_complete = int(daily_summary["is_complete_day"].sum())
    if n_complete == 0:
        return empty

    eligible = daily_summary[
        daily_summary["is_complete_day"]
        & daily_summary["der_primary_shape"].notna()
        & (daily_summary["der_primary_shape"] != "insufficient_data")
    ]

    rows = []
    for shape, grp in eligible.groupby("der_primary_shape"):
        n_days = len(grp)
        if n_days < min_occurrences:
            continue
        rows.append({
            "primary_shape": shape,
            "n_days": n_days,
            "statistical_support": n_days / n_complete,
            "dates": sorted(grp["date"].tolist()),
        })
    return pd.DataFrame(rows) if rows else empty


def find_outlier_days(daily_summary: pd.DataFrame, cfg: dict[str, Any]) -> pd.DataFrame:
    """
    Z-score of ``daily_energy_kwh`` and ``maximum_demand_kw``, computed
    **separately**, over complete days only; flag ``|z| >= z_threshold``.
    Requires >= ``min_days_for_outliers`` complete days, else empty (not
    enough data for a meaningful std).
    """
    pcfg = cfg.get("der", {}).get("patterns", {})
    z_threshold = pcfg.get("outlier_z_threshold", 2.5)
    min_days = pcfg.get("min_days_for_outliers", 5)

    empty = pd.DataFrame(columns=["date", "metric", "value", "z_score"])
    complete = daily_summary[daily_summary["is_complete_day"]]
    if len(complete) < min_days:
        return empty

    rows = []
    for metric in ("daily_energy_kwh", "maximum_demand_kw"):
        values = complete[metric]
        std = values.std()
        if not std or np.isnan(std):
            continue
        z = (values - values.mean()) / std
        for i in z.index[z.abs() >= z_threshold]:
            rows.append({
                "date": complete.loc[i, "date"], "metric": metric,
                "value": float(complete.loc[i, metric]), "z_score": float(z.loc[i]),
            })
    return pd.DataFrame(rows) if rows else empty
