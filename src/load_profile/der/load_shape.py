"""
Rule-based/heuristic load-shape classification (DER spec §5.6) — independent
boolean flags plus a priority-ordered ``der_primary_shape``. A deliberately
different taxonomy from ``classification.classify_day``'s ``primary_class``
(different rules, different vocabulary); stored under a distinctly named
column (``der_primary_shape``) so the two never collide if joined together.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from .local_extrema import add_local_extrema_flags

_DEFAULTS = {
    "flat_cv_max": 0.15,
    "highly_peaked_ratio_min": 2.0,
    "sharp_peak_width_frac_max": 0.10,
    "sustained_high_frac_min": 0.30,
    "sustained_high_pct_of_peak": 0.90,
    "overnight_heavy_ratio_min": 1.1,
    "multi_peak_min_count": 2,
    "near_peak_segment_fraction": 0.85,
}


def _infer_resolution_minutes(index: pd.DatetimeIndex) -> float:
    diffs = index.to_series().diff().dropna().dt.total_seconds() / 60
    if diffs.empty:
        return 60.0
    return float(diffs.mode().iloc[0])


def _is_true(value: Any) -> bool:
    """NaN-safe boolean check — ``bool(float("nan"))`` is True in Python, so
    every flag comparison in this module uses ``== True`` (via this helper)
    rather than plain truthiness to avoid silently treating a NaN row
    (e.g. a day missing from the TOD merge) as satisfying every rule."""
    return value is True or value == True  # noqa: E712


def classify_load_shape(
    interval_df: pd.DataFrame,
    tod_df: pd.DataFrame,
    cfg: dict[str, Any],
    value_col: str = "demand_kw",
) -> pd.DataFrame:
    """
    Per calendar date, compute independent load-shape boolean flags and a
    priority-ordered ``der_primary_shape``.

    Parameters
    ----------
    interval_df : DataFrame
        tz-aware DatetimeIndex, ``value_col`` demand column. Local
        peak/valley flags are computed here if not already present.
    tod_df : DataFrame
        Output of ``calendar_features.add_time_of_day_segments`` — supplies
        the ``{segment}_peak_kw``, ``overnight_mean_kw``, ``daytime_mean_kw``
        columns this function merges on ``date``.
    cfg : dict
        Reads ``der.load_shape.*`` thresholds (see ``_DEFAULTS`` for names).
    """
    lcfg = {**_DEFAULTS, **cfg.get("der", {}).get("load_shape", {})}

    if "is_local_peak" not in interval_df.columns or "is_local_valley" not in interval_df.columns:
        interval_df = add_local_extrema_flags(interval_df, value_col=value_col)

    expected_per_day = (24 * 60) / _infer_resolution_minutes(interval_df.index)

    daily = pd.DataFrame(
        {
            "date": interval_df.index.normalize(),
            "demand_kw": interval_df[value_col].to_numpy(),
            "is_local_peak": interval_df["is_local_peak"].to_numpy(),
            "is_local_valley": interval_df["is_local_valley"].to_numpy(),
        }
    )

    stats = daily.groupby("date").agg(
        mean_demand_kw=("demand_kw", "mean"),
        std_demand_kw=("demand_kw", "std"),
        max_demand_kw=("demand_kw", "max"),
        n_observed=("demand_kw", "count"),
        n_local_peaks=("is_local_peak", "sum"),
        n_local_valleys=("is_local_valley", "sum"),
    ).reset_index()

    stats["cv"] = stats["std_demand_kw"] / stats["mean_demand_kw"]
    stats["peak_to_average_ratio"] = stats["max_demand_kw"] / stats["mean_demand_kw"]
    stats["is_unusual"] = (stats["n_observed"] / expected_per_day) < 0.50

    merged = stats.merge(tod_df, on="date", how="left")

    segment_cols = [c for c in tod_df.columns if c.endswith("_peak_kw")]
    for col in segment_cols:
        seg_name = col[: -len("_peak_kw")]
        merged[f"has_{seg_name}_peak"] = merged[col] >= (
            lcfg["near_peak_segment_fraction"] * merged["max_demand_kw"]
        )

    merged["is_flat"] = merged["cv"] <= lcfg["flat_cv_max"]
    merged["is_highly_peaked"] = merged["peak_to_average_ratio"] >= lcfg["highly_peaked_ratio_min"]
    merged["is_overnight_heavy"] = (
        merged["overnight_mean_kw"] / merged["daytime_mean_kw"]
    ) >= lcfg["overnight_heavy_ratio_min"]
    merged["is_multi_peak"] = merged["n_local_peaks"] >= lcfg["multi_peak_min_count"]
    merged["has_peak_valley_pattern"] = (merged["n_local_peaks"] >= 1) & (
        merged["n_local_valleys"] >= 1
    )

    # sharp vs. sustained: fraction of the day's *observed* intervals at/above
    # sustained_high_pct_of_peak * daily_max
    high_frac = daily.merge(stats[["date", "max_demand_kw"]], on="date")
    high_frac["is_high"] = high_frac["demand_kw"] >= (
        lcfg["sustained_high_pct_of_peak"] * high_frac["max_demand_kw"]
    )
    high_frac_by_day = (
        high_frac.groupby("date")["is_high"].mean().rename("high_fraction").reset_index()
    )
    merged = merged.merge(high_frac_by_day, on="date", how="left")
    merged["has_sharp_peak"] = merged["high_fraction"] <= lcfg["sharp_peak_width_frac_max"]
    merged["has_sustained_high_load"] = (
        merged["high_fraction"] >= lcfg["sustained_high_frac_min"]
    )

    merged["der_primary_shape"] = merged.apply(_primary_shape, axis=1)

    return merged


def _primary_shape(row: pd.Series) -> str:
    if _is_true(row.get("is_unusual")):
        return "insufficient_data"

    if _is_true(row.get("is_highly_peaked")) and _is_true(row.get("has_sharp_peak")):
        if _is_true(row.get("has_morning_peak")) and not _is_true(
            row.get("has_afternoon_peak")
        ) and not _is_true(row.get("has_evening_peak")):
            return "morning_peak"
        if _is_true(row.get("has_afternoon_peak")):
            return "afternoon_peak"
        if _is_true(row.get("has_evening_peak")):
            return "evening_peak"
        if _is_true(row.get("has_midday_peak")):
            return "midday_peak"

    if _is_true(row.get("is_multi_peak")):
        return "multi_peak"
    if _is_true(row.get("is_overnight_heavy")):
        return "overnight_heavy"
    if _is_true(row.get("is_flat")):
        return "flat"
    return "mixed_other"
