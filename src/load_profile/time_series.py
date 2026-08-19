"""
Time-series regularization, linear interpolation, and data-quality assessment.

All duration calculations use actual elapsed time, not interval counts, so
DST transition days (92 or 100 intervals for 15-min data) are handled correctly.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def regularize(
    df: pd.DataFrame,
    resolution_minutes: float,
    cfg: dict[str, Any],
) -> pd.DataFrame:
    """
    Reindex ``df`` to a regular grid and fill gaps with linear interpolation.

    Parameters
    ----------
    df : DataFrame
        Must have a tz-aware DatetimeIndex and a ``demand_kw`` column.
    resolution_minutes : float
        Target interval in minutes (detected by ``validate_input``).
    cfg : dict
        Full configuration dictionary.

    Returns
    -------
    DataFrame
        Regular-grid DataFrame with columns:

        ``demand_kw``          – working demand (NaN where missing/uninterpolatable)
        ``demand_kw_raw``      – original meter values (NaN for injected grid points)
        ``is_observed``        – True for original meter readings
        ``is_interpolated``    – True for linearly interpolated values
        ``interpolation_method`` – "linear" | "none" | NaN
        ``is_missing``         – True where demand remains NaN after interpolation
        ``data_quality_flag``  – "observed" | "interpolated" | "missing"
                                  (derived from the three booleans above; DER-spec
                                  canonical field, precedence observed > interpolated > missing)
    """
    max_gap_min = cfg.get("data_quality", {}).get("max_interpolation_gap_minutes", 60)

    # Build regular date-range covering entire span
    start = df.index.min()
    end   = df.index.max()
    freq  = pd.tseries.frequencies.to_offset(pd.Timedelta(minutes=resolution_minutes))
    regular_index = pd.date_range(start=start, end=end, freq=freq, tz=df.index.tz)

    # Reindex — NaN for missing slots
    df_reg = df.reindex(regular_index)
    df_reg.index.name = "datetime"

    # Track provenance before filling
    is_observed = df_reg["demand_kw"].notna()

    # Treat negative demand as missing (configurable future extension)
    df_reg.loc[df_reg["demand_kw"] < 0, "demand_kw"] = np.nan

    # Linear interpolation, time-aware, bounded by max_gap_min
    demand_interp, interp_mask = _interpolate_with_gap_limit(
        df_reg["demand_kw"], max_gap_min
    )

    df_reg["demand_kw"] = demand_interp
    df_reg["is_observed"] = is_observed
    df_reg["is_interpolated"] = interp_mask & ~is_observed
    df_reg["interpolation_method"] = np.where(df_reg["is_interpolated"], "linear", pd.NA)
    df_reg["is_missing"] = df_reg["demand_kw"].isna()
    df_reg["data_quality_flag"] = np.select(
        [df_reg["is_observed"], df_reg["is_interpolated"]],
        ["observed", "interpolated"],
        default="missing",
    )

    # Preserve raw values for originally-observed points
    if "demand_kw_raw" not in df_reg.columns:
        df_reg["demand_kw_raw"] = np.where(is_observed, df_reg["demand_kw"], np.nan)

    return df_reg


def assess_quality(
    df_day: pd.DataFrame,
    resolution_minutes: float,
    cfg: dict[str, Any],
) -> dict[str, Any]:
    """
    Compute data-quality metrics for a single calendar day.

    Parameters
    ----------
    df_day : DataFrame
        Regular-grid DataFrame for one day (output of ``regularize`` then
        filtered to a single date).
    resolution_minutes : float
    cfg : dict

    Returns
    -------
    dict
        ``expected_intervals``, ``observed_intervals``, ``interpolated_intervals``,
        ``missing_intervals``, ``completeness_fraction``,
        ``interpolation_fraction``, ``longest_missing_gap_minutes``,
        ``quality_status`` ("GOOD" | "ACCEPTABLE" | "POOR" | "UNUSABLE").
    """
    n_expected = len(df_day)
    n_observed  = int(df_day["is_observed"].sum())
    n_interp    = int(df_day["is_interpolated"].sum())
    n_missing   = int(df_day["is_missing"].sum())

    completeness  = n_observed  / n_expected if n_expected else 0.0
    interp_frac   = n_interp    / n_expected if n_expected else 0.0

    # Longest contiguous missing run (actual elapsed time)
    longest_gap = _longest_missing_gap_minutes(df_day)

    min_comp = cfg.get("data_quality", {}).get("min_completeness_fraction", 0.75)
    if completeness >= min_comp and longest_gap <= 60:
        status = "GOOD"
    elif completeness >= 0.50:
        status = "ACCEPTABLE"
    elif completeness >= 0.25:
        status = "POOR"
    else:
        status = "UNUSABLE"

    return {
        "expected_intervals":      n_expected,
        "observed_intervals":      n_observed,
        "interpolated_intervals":  n_interp,
        "missing_intervals":       n_missing,
        "completeness_fraction":   round(completeness, 4),
        "interpolation_fraction":  round(interp_frac, 4),
        "longest_missing_gap_minutes": round(longest_gap, 1),
        "quality_status":          status,
    }


def segment_days(df: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """
    Split a multi-day regularized DataFrame into per-local-calendar-day slices.

    Returns
    -------
    dict mapping ISO date string ("YYYY-MM-DD") -> DataFrame slice
    """
    day_map: dict[str, pd.DataFrame] = {}
    local_dates = df.index.normalize()
    for date in pd.DatetimeIndex(local_dates.unique()):
        key = date.date().isoformat()
        day_map[key] = df[local_dates == date]
    return day_map


def apply_smoothing(
    series: pd.Series,
    cfg: dict[str, Any],
    resolution_minutes: float,
) -> pd.Series:
    """
    Apply the configured smoothing method to a demand series.

    Parameters
    ----------
    series : Series (float)
        ``demand_kw`` for one day (may contain NaN).
    cfg : dict
    resolution_minutes : float

    Returns
    -------
    Series
        Smoothed demand; same index as input. Named ``analysis_demand_kw``.
    """
    sm_cfg = cfg.get("smoothing", {})
    method = sm_cfg.get("method", "rolling_median")
    win_min = sm_cfg.get("window_minutes", 60)

    if method == "none":
        return series.rename("analysis_demand_kw")

    # Convert window from minutes to interval count (must be odd for centred)
    intervals_per_min = 1.0 / resolution_minutes
    win_n = max(1, int(round(win_min * intervals_per_min)))
    if win_n % 2 == 0:
        win_n += 1

    if method == "rolling_mean":
        smoothed = series.rolling(window=win_n, center=True, min_periods=1).mean()
    else:  # rolling_median (default)
        smoothed = series.rolling(window=win_n, center=True, min_periods=1).median()

    return smoothed.rename("analysis_demand_kw")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _interpolate_with_gap_limit(
    series: pd.Series,
    max_gap_minutes: float,
) -> tuple[pd.Series, pd.Series]:
    """
    Linear interpolation limited to gaps shorter than ``max_gap_minutes``.

    Returns
    -------
    (interpolated_series, was_interpolated_mask)
        ``was_interpolated_mask`` is True where a value was filled.
    """
    was_nan_before = series.isna()
    interpolated = series.copy()

    # Find NaN runs and their elapsed duration
    null_groups = series.isna().astype(int)
    # Label each contiguous NaN run
    runs = (null_groups.diff() != 0).cumsum()
    for run_id, grp in series[series.isna()].groupby(runs[series.isna()]):
        idx = grp.index
        # Find bracketing valid observations
        pos_before = series.index.get_loc(idx[0])
        pos_after  = series.index.get_loc(idx[-1])
        if pos_before == 0 or pos_after == len(series) - 1:
            continue  # can't interpolate at edges without both brackets

        t_start = series.index[pos_before - 1]
        t_end   = series.index[pos_after + 1]
        gap_min = (t_end - t_start).total_seconds() / 60

        if gap_min <= max_gap_minutes:
            v_start = series.iloc[pos_before - 1]
            v_end   = series.iloc[pos_after + 1]
            for ts in idx:
                frac = (ts - t_start).total_seconds() / (t_end - t_start).total_seconds()
                interpolated.at[ts] = v_start + frac * (v_end - v_start)

    was_interpolated = was_nan_before & interpolated.notna()
    return interpolated, was_interpolated


def _longest_missing_gap_minutes(df_day: pd.DataFrame) -> float:
    """Return the longest contiguous missing-data gap in minutes."""
    if not df_day["is_missing"].any():
        return 0.0
    longest = 0.0
    in_gap = False
    gap_start = None
    for ts, row in df_day.iterrows():
        if row["is_missing"]:
            if not in_gap:
                in_gap = True
                gap_start = ts
        else:
            if in_gap:
                gap_min = (ts - gap_start).total_seconds() / 60
                longest = max(longest, gap_min)
                in_gap = False
    if in_gap and gap_start is not None:
        gap_min = (df_day.index[-1] - gap_start).total_seconds() / 60
        longest = max(longest, gap_min)
    return longest
