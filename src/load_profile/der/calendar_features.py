"""
Calendar and time-of-day segment features (DER spec §2.4, §5.1).

Both functions are generic: they operate on any DataFrame with a tz-aware
``DatetimeIndex`` and (for ``add_time_of_day_segments``) a ``demand_kw``
column — usable equally on an entity's aggregated interval frame
(``der.aggregation.build_entity_frame`` output) or on a single meter's own
``interval_df`` (``pipeline.run_pipeline`` output). ``der.pipeline.run_der_pipeline``
applies them to entity frames automatically; callers wanting per-meter
calendar/TOD features call these directly on a meter's own interval_df.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

# Meteorological Northern-Hemisphere default (month -> season)
DEFAULT_SEASON_MAP: dict[int, str] = {
    12: "winter", 1: "winter", 2: "winter",
    3: "spring", 4: "spring", 5: "spring",
    6: "summer", 7: "summer", 8: "summer",
    9: "fall", 10: "fall", 11: "fall",
}

# Fixed hour windows [start, end), per DER spec §5.1
DEFAULT_SEGMENTS: dict[str, tuple[int, int]] = {
    "morning": (6, 10),
    "midday": (10, 14),
    "afternoon": (14, 18),
    "evening": (18, 22),
}


def add_calendar_features(interval_df: pd.DataFrame, cfg: dict[str, Any]) -> pd.DataFrame:
    """
    Add calendar-derived columns from the (interval-ending) DatetimeIndex.

    Adds: ``date``, ``year``, ``month``, ``day``, ``day_of_year``, ``hour``,
    ``minute``, ``day_of_week`` (Monday=0), ``day_name``, ``is_weekday``,
    ``is_weekend`` (calendar-only, holiday-independent), ``season``
    (config-driven month->season map, default meteorological Northern
    Hemisphere), ``day_type`` (``"weekday"|"weekend"|"holiday"`` — holiday
    overrides weekday/weekend).
    """
    ccfg = cfg.get("der", {}).get("calendar", {})
    raw_season_map = ccfg.get("season_map")
    season_map = (
        {int(k): v for k, v in raw_season_map.items()} if raw_season_map else DEFAULT_SEASON_MAP
    )
    holidays = set(pd.to_datetime(ccfg.get("holidays", [])).date)

    idx = interval_df.index
    out = interval_df.copy()
    out["date"] = idx.date
    out["year"] = idx.year
    out["month"] = idx.month
    out["day"] = idx.day
    out["day_of_year"] = idx.dayofyear
    out["hour"] = idx.hour
    out["minute"] = idx.minute
    out["day_of_week"] = idx.dayofweek
    out["day_name"] = idx.day_name()
    out["is_weekday"] = idx.dayofweek < 5
    out["is_weekend"] = ~out["is_weekday"]
    out["season"] = out["month"].map(season_map)

    is_holiday = out["date"].isin(holidays)
    out["day_type"] = np.select(
        [is_holiday, out["is_weekday"]],
        ["holiday", "weekday"],
        default="weekend",
    )
    return out


def add_time_of_day_segments(interval_df: pd.DataFrame, cfg: dict[str, Any]) -> pd.DataFrame:
    """
    Compute per-day time-of-day segment features from interval-level ``demand_kw``.

    Returns one row per calendar date with columns:
        ``{segment}_peak_kw``  – max demand within each configured window
                                  (NaN if the window has no present data)
        ``overnight_mean_kw``  – mean over hours {22,23,0..5}
        ``nighttime_mean_kw``  – alias of overnight_mean_kw (same value)
        ``daytime_mean_kw``    – mean over hours {6..21}
    All aggregations skip NaN.
    """
    tcfg = cfg.get("der", {}).get("time_of_day", {})
    segments: dict[str, tuple[int, int]] = tcfg.get("segments", DEFAULT_SEGMENTS)

    hour = interval_df.index.hour
    date = interval_df.index.normalize()
    demand = interval_df["demand_kw"]

    result = pd.DataFrame(index=pd.Index(date, name="date").unique()).sort_index()

    for seg_name, (start, end) in segments.items():
        seg_mask = (hour >= start) & (hour < end)
        seg_demand = pd.Series(demand.where(seg_mask).values, index=date)
        result[f"{seg_name}_peak_kw"] = seg_demand.groupby(level=0).max()

    overnight_mask = (hour >= 22) | (hour < 6)
    overnight_demand = pd.Series(demand.where(overnight_mask).values, index=date)
    result["overnight_mean_kw"] = overnight_demand.groupby(level=0).mean()
    result["nighttime_mean_kw"] = result["overnight_mean_kw"]

    daytime_demand = pd.Series(demand.where(~overnight_mask).values, index=date)
    result["daytime_mean_kw"] = daytime_demand.groupby(level=0).mean()

    result.index.name = "date"
    return result.reset_index()
