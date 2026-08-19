"""
Baseline demand estimation for a single calendar day.

Architecture: measure first, classify later.

The baseline represents the building's low-demand (inactive) level.
It is NOT simply the minimum; it is the median of the longest sustained
low-demand region of the day (hybrid Method D).

If no sustained low-demand region exists (24/7 operation), a fallback
percentile of the full distribution is used and the day is flagged.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def estimate_baseline(
    series: pd.Series,
    resolution_minutes: float,
    cfg: dict[str, Any],
) -> dict[str, Any]:
    """
    Estimate the baseline demand level for one day's smoothed demand series.

    Parameters
    ----------
    series : Series (float)
        ``analysis_demand_kw`` for one calendar day. Index must be a
        tz-aware DatetimeIndex. NaN values are excluded.
    resolution_minutes : float
    cfg : dict

    Returns
    -------
    dict
        ``baseline_kw``        – scalar kW value used as the day's baseline
        ``baseline_method``    – "hybrid_sustained" | "fallback_percentile"
        ``baseline_period_start`` – start of the identified baseline region (or None)
        ``baseline_period_end``   – end of the identified baseline region (or None)
        ``baseline_period_duration_hours`` – duration of that region
        ``is_continuous_operation`` – bool
        ``peak_kw``            – highest observed (non-NaN) demand
        ``operating_range_kw`` – peak_kw - baseline_kw
    """
    bl_cfg  = cfg.get("baseline", {})
    min_per = bl_cfg.get("min_persistence_minutes", 60)
    lo_pct  = bl_cfg.get("low_demand_percentile", 10)
    fb_pct  = bl_cfg.get("continuous_operation_fallback_percentile", 10)
    co_frac = bl_cfg.get("continuous_operation_range_fraction", 0.15)

    valid = series.dropna()
    if valid.empty:
        return _empty_result()

    peak_kw = float(valid.max())
    daily_mean = float(valid.mean())

    # Step 1: identify the low-demand threshold
    lo_threshold = float(np.percentile(valid.values, lo_pct))

    # Step 2: find candidate low-demand intervals
    low_mask = series <= lo_threshold

    # Step 3: find the longest contiguous sustained low-demand region
    region = _longest_sustained_region(
        series, low_mask, min_persistence_minutes=min_per
    )

    if region is not None:
        region_vals = series.loc[region["start"]:region["end"]].dropna()
        baseline_kw = float(region_vals.median())
        method = "hybrid_sustained"
        bl_start = region["start"]
        bl_end   = region["end"]
        bl_dur   = region["duration_hours"]
    else:
        # No sustained low region — use percentile of full day
        baseline_kw = float(np.percentile(valid.values, fb_pct))
        method = "fallback_percentile"
        bl_start = None
        bl_end   = None
        bl_dur   = 0.0

    operating_range = peak_kw - baseline_kw

    # Continuous-operation flag: range too small relative to daily mean
    is_continuous = (operating_range / daily_mean) < co_frac if daily_mean > 0 else False

    return {
        "baseline_kw":                    round(baseline_kw, 2),
        "baseline_method":                method,
        "baseline_period_start":          bl_start,
        "baseline_period_end":            bl_end,
        "baseline_period_duration_hours": round(bl_dur, 3),
        "is_continuous_operation":        bool(is_continuous),
        "peak_kw":                        round(peak_kw, 2),
        "operating_range_kw":             round(operating_range, 2),
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _longest_sustained_region(
    series: pd.Series,
    low_mask: pd.Series,
    min_persistence_minutes: float,
) -> dict[str, Any] | None:
    """
    Find the longest contiguous run where ``low_mask`` is True, provided
    its elapsed duration meets ``min_persistence_minutes``.

    Returns dict with ``start``, ``end``, ``duration_hours``, or None.
    """
    best: dict[str, Any] | None = None
    best_dur = 0.0

    in_run = False
    run_start_ts = None

    for ts, is_low in low_mask.items():
        if is_low:
            if not in_run:
                in_run = True
                run_start_ts = ts
        else:
            if in_run:
                dur_min = (ts - run_start_ts).total_seconds() / 60
                dur_hr  = dur_min / 60
                if dur_min >= min_persistence_minutes and dur_hr > best_dur:
                    best_dur = dur_hr
                    best = {
                        "start": run_start_ts,
                        "end":   ts,
                        "duration_hours": dur_hr,
                    }
                in_run = False

    # Handle run extending to end of series
    if in_run and run_start_ts is not None:
        ts = series.index[-1]
        dur_min = (ts - run_start_ts).total_seconds() / 60
        dur_hr  = dur_min / 60
        if dur_min >= min_persistence_minutes and dur_hr > best_dur:
            best = {
                "start": run_start_ts,
                "end":   ts,
                "duration_hours": dur_hr,
            }

    return best


def _empty_result() -> dict[str, Any]:
    return {
        "baseline_kw":                    np.nan,
        "baseline_method":                "none",
        "baseline_period_start":          None,
        "baseline_period_end":            None,
        "baseline_period_duration_hours": 0.0,
        "is_continuous_operation":        False,
        "peak_kw":                        np.nan,
        "operating_range_kw":             np.nan,
    }
