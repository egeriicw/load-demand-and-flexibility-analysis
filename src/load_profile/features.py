"""
Assemble the daily feature vector from all intermediate analytical results.

All values are plain Python scalars or None; the result is suitable for
direct conversion to a DataFrame row.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from .events import StartEvent, EndEvent, RampEvent, PeakEvent
from .states import STATE_OPERATING, STATE_BASELINE


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def build_daily_features(
    date: str,
    meter_id: str | None,
    building_id: str | None,
    df_day: pd.DataFrame,           # full interval-level DataFrame for the day
    series_raw: pd.Series,          # demand_kw (with NaN)
    series_smooth: pd.Series,       # analysis_demand_kw
    states: pd.Series,
    baseline_result: dict[str, Any],
    quality: dict[str, Any],
    start_event: StartEvent | None,
    end_event: EndEvent | None,
    ramp_events: list[RampEvent],
    peak_events: list[PeakEvent],
    operating_periods: list[dict],
    norm_demand: pd.Series,
    cfg: dict[str, Any],
    resolution_minutes: float,
) -> dict[str, Any]:
    """
    Produce one flat feature dictionary representing a single calendar day.

    Parameters
    ----------
    (see individual analysis modules for type docs)

    Returns
    -------
    dict
        All keys described in the specification's provisional feature vector.
    """
    feat: dict[str, Any] = {}

    # ── Identity ──────────────────────────────────────────────────────────
    feat["date"]        = date
    feat["meter_id"]    = meter_id
    feat["building_id"] = building_id
    feat["timezone"]    = str(series_raw.index.tz) if series_raw.index.tz else None
    feat["resolution_minutes"] = resolution_minutes

    # ── Data quality ──────────────────────────────────────────────────────
    feat.update({f"dq_{k}": v for k, v in quality.items()})

    # ── Basic statistics ───────────────────────────────────────────────────
    valid = series_raw.dropna()
    feat["baseline_kw"]  = baseline_result.get("baseline_kw")
    feat["average_kw"]   = _safe(valid.mean())
    feat["median_kw"]    = _safe(valid.median())
    feat["minimum_kw"]   = _safe(valid.min())
    feat["maximum_kw"]   = _safe(valid.max())
    feat["std_kw"]       = _safe(valid.std())
    feat["cv"]           = _safe(valid.std() / valid.mean()) if valid.mean() != 0 else None

    # ── Continuous-operation flag ──────────────────────────────────────────
    feat["is_continuous_operation"] = baseline_result.get("is_continuous_operation", False)

    # ── Start event ────────────────────────────────────────────────────────
    if start_event:
        feat["probable_start_time"]         = start_event.transition_time.isoformat()
        feat["start_threshold_crossing"]    = start_event.threshold_crossing_time.isoformat()
        feat["start_kw"]                    = start_event.start_kw
        feat["startup_delta_kw"]            = start_event.delta_kw
        feat["startup_duration_hours"]      = start_event.duration_hours
        feat["startup_ramp_kw_per_hr"]      = start_event.ramp_rate_kw_per_hr
        feat["startup_max_ramp_kw_per_hr"]  = start_event.max_ramp_rate_kw_per_hr
        feat["start_confidence"]            = start_event.confidence
        feat["start_is_gradual"]            = start_event.is_gradual
    else:
        for k in ["probable_start_time", "start_threshold_crossing", "start_kw",
                  "startup_delta_kw", "startup_duration_hours", "startup_ramp_kw_per_hr",
                  "startup_max_ramp_kw_per_hr", "start_confidence", "start_is_gradual"]:
            feat[k] = None

    # ── End event ─────────────────────────────────────────────────────────
    if end_event:
        feat["probable_end_time"]            = end_event.transition_time.isoformat()
        feat["end_threshold_crossing"]       = end_event.threshold_crossing_time.isoformat()
        feat["end_kw"]                       = end_event.end_kw
        feat["shutdown_delta_kw"]            = end_event.delta_kw
        feat["shutdown_duration_hours"]      = end_event.duration_hours
        feat["shutdown_ramp_kw_per_hr"]      = end_event.ramp_rate_kw_per_hr
        feat["shutdown_max_ramp_kw_per_hr"]  = end_event.max_ramp_rate_kw_per_hr
        feat["end_confidence"]               = end_event.confidence
        feat["end_is_gradual"]               = end_event.is_gradual
    else:
        for k in ["probable_end_time", "end_threshold_crossing", "end_kw",
                  "shutdown_delta_kw", "shutdown_duration_hours", "shutdown_ramp_kw_per_hr",
                  "shutdown_max_ramp_kw_per_hr", "end_confidence", "end_is_gradual"]:
            feat[k] = None

    # ── Operating periods ─────────────────────────────────────────────────
    feat["operating_period_count"] = len(operating_periods)
    total_op = sum(p["duration_hours"] for p in operating_periods)
    feat["total_operating_duration_hours"] = round(total_op, 4)

    # ── Breadth ────────────────────────────────────────────────────────────
    op_thresholds  = cfg.get("breadth", {}).get("operating_thresholds",  [0.20, 0.40, 0.60, 0.80, 0.90])
    do_energy      = cfg.get("breadth", {}).get("compute_energy_breadth", True)
    elapsed_hours  = _elapsed_hours(series_raw.index)

    op_range = baseline_result.get("operating_range_kw", np.nan)
    for thr in op_thresholds:
        label = f"duration_above_{int(thr*100)}pct_hours"
        feat[label] = _duration_above_norm_threshold(norm_demand, thr, elapsed_hours)

    if do_energy and not np.isnan(op_range) and op_range > 0:
        total_energy = (valid * elapsed_hours).sum() if not valid.empty else 0.0
        for thr in op_thresholds:
            mask  = norm_demand >= thr
            label = f"energy_frac_above_{int(thr*100)}pct"
            above_energy = (series_raw[mask].dropna() * elapsed_hours).sum()
            feat[label] = round(above_energy / total_energy, 4) if total_energy > 0 else None

    # ── Primary peak ───────────────────────────────────────────────────────
    primary = next((p for p in peak_events if p.rank == 1), None)
    if primary:
        feat["peak_kw"]                   = primary.peak_kw
        feat["peak_time"]                 = primary.peak_time.isoformat()
        feat["peak_is_interpolated"]      = primary.peak_is_interpolated
        feat["peak_prominence_kw"]        = primary.prominence_kw
        feat["peak_prominence_fraction"]  = primary.prominence_fraction
        feat["peak_width_70_hours"]       = primary.width_70_hours
        feat["peak_width_80_hours"]       = primary.width_80_hours
        feat["peak_width_90_hours"]       = primary.width_90_hours
        feat["peak_confidence"]           = primary.confidence
    else:
        for k in ["peak_kw", "peak_time", "peak_is_interpolated", "peak_prominence_kw",
                  "peak_prominence_fraction", "peak_width_70_hours", "peak_width_80_hours",
                  "peak_width_90_hours", "peak_confidence"]:
            feat[k] = None

    # ── Peakiness ──────────────────────────────────────────────────────────
    bl_kw = baseline_result.get("baseline_kw", np.nan)
    if not valid.empty and not np.isnan(bl_kw):
        avg_kw = float(valid.mean())
        pk_kw  = float(valid.max())
        feat["peak_to_average_ratio"] = round(pk_kw / avg_kw, 4) if avg_kw > 0 else None
        feat["peak_to_baseline_ratio"] = round(pk_kw / bl_kw, 4) if bl_kw > 0 else None
        feat["load_factor"] = round(avg_kw / pk_kw, 4) if pk_kw > 0 else None
        # Peak concentration: fraction of energy in top 1-hr and 2-hr windows
        feat["peak_concentration_1hr"] = _peak_concentration(series_raw, series_raw.idxmax(), hours=1.0)
        feat["peak_concentration_2hr"] = _peak_concentration(series_raw, series_raw.idxmax(), hours=2.0)
    else:
        for k in ["peak_to_average_ratio", "peak_to_baseline_ratio", "load_factor",
                  "peak_concentration_1hr", "peak_concentration_2hr"]:
            feat[k] = None

    # ── Secondary peaks ────────────────────────────────────────────────────
    feat["secondary_peak_count"] = max(0, len(peak_events) - 1)

    # ── Ramps ─────────────────────────────────────────────────────────────
    feat["ramp_event_count"] = len(ramp_events)
    up_ramps   = [r for r in ramp_events if r.event_type == "UP"]
    down_ramps = [r for r in ramp_events if r.event_type == "DOWN"]
    feat["up_ramp_count"]   = len(up_ramps)
    feat["down_ramp_count"] = len(down_ramps)

    # ── Variability ────────────────────────────────────────────────────────
    if not valid.empty:
        feat["mean_absolute_ramp_kw_per_hr"] = _safe(
            abs(series_raw.diff() / (series_raw.index.to_series().diff().dt.total_seconds() / 3600)).dropna().mean()
        )
        feat["intraday_variability"] = feat["cv"]
    else:
        feat["mean_absolute_ramp_kw_per_hr"] = None
        feat["intraday_variability"] = None

    return feat


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _safe(val: Any) -> Any:
    """Convert numpy scalars to Python floats; preserve None."""
    if val is None:
        return None
    try:
        v = float(val)
        return round(v, 4) if not np.isnan(v) else None
    except (TypeError, ValueError):
        return None


def _elapsed_hours(index: pd.DatetimeIndex) -> float:
    """Median interval duration in hours (for energy approximations)."""
    if len(index) < 2:
        return 0.0
    return float(pd.Series(index).diff().dropna().dt.total_seconds().median()) / 3600


def _duration_above_norm_threshold(
    norm_demand: pd.Series,
    threshold: float,
    interval_hours: float,
) -> float | None:
    """Hours where normalised demand >= threshold."""
    if norm_demand.empty or interval_hours == 0:
        return None
    count = (norm_demand >= threshold).sum()
    return round(float(count) * interval_hours, 4)


def _peak_concentration(
    series: pd.Series,
    peak_ts: pd.Timestamp,
    hours: float,
) -> float | None:
    """
    Fraction of total daily energy that falls within ``hours`` of ``peak_ts``.
    """
    half = pd.Timedelta(hours=hours / 2)
    window = series[peak_ts - half : peak_ts + half].dropna()
    total  = series.dropna()

    if total.empty or total.sum() == 0:
        return None
    return round(float(window.sum()) / float(total.sum()), 4)
