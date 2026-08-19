"""
End-to-end analysis pipeline for a single DataFrame of demand data.

Wires together all analytical modules in dependency order and returns:
  - interval_df   : interval-level diagnostic DataFrame
  - daily_df      : one row per day (feature vector + classification)
  - ramp_df       : one row per detected ramp event
  - peak_df       : one row per detected peak event

Callers can run this directly or step through the modules individually.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

import numpy as np
import pandas as pd

from .data_ingestion import validate_input, convert_units, _detect_resolution
from .time_series import regularize, assess_quality, segment_days, apply_smoothing
from .baseline import estimate_baseline
from .states import detect_states, compute_normalized_demand
from .events import (
    detect_start, detect_end, detect_ramps, detect_peaks,
    detect_operating_periods,
)
from .features import build_daily_features
from .classification import classify_day


def run_pipeline(
    df: pd.DataFrame,
    cfg: dict[str, Any],
    meter_id: str | None = None,
    building_id: str | None = None,
    verbose: bool = True,
) -> dict[str, pd.DataFrame]:
    """
    Run the full characterisation pipeline on a loaded demand DataFrame.

    Parameters
    ----------
    df : DataFrame
        Output of ``load_demand_data`` — tz-aware DatetimeIndex, ``demand_kw`` column.
    cfg : dict
        Full configuration dict from ``load_config()``.
    meter_id, building_id : optional identity labels
    verbose : bool
        Print progress messages.

    Returns
    -------
    dict with keys:
        ``interval_df``  – per-interval diagnostic table
        ``daily_df``     – per-day feature + classification table
        ``ramp_df``      – all detected ramp events
        ``peak_df``      – all detected peak events
    """
    # ── 1. Validation ─────────────────────────────────────────────────────
    validation = validate_input(df, cfg)
    res_min = validation["detected_resolution_minutes"]
    if verbose:
        print(f"[pipeline] Resolution detected: {res_min} min | "
              f"Duplicates: {validation['duplicate_timestamp_count']} | "
              f"Irregular: {validation['irregular_interval_count']}")

    # validate_input() reports duplicate timestamps but doesn't drop them;
    # regularize()'s reindex requires a unique index, so drop here.
    if validation["duplicate_timestamp_count"]:
        df = df[~df.index.duplicated(keep="first")]

    # ── 1b. Unit conversion (kWh → kW if configured) ──────────────────────
    df, unit_meta = convert_units(df, res_min, cfg)
    if verbose and unit_meta["conversion_applied"]:
        print(f"[pipeline] Unit conversion: kWh → kW "
              f"(factor {unit_meta['conversion_factor']:.4g} "
              f"= 60 / {res_min} min)")

    # ── 2. Regularisation + interpolation ─────────────────────────────────
    df_reg = regularize(df, res_min, cfg)
    if verbose:
        print(f"[pipeline] Regularised: {len(df_reg)} intervals")

    # ── 3. Segment by calendar day ────────────────────────────────────────
    day_map = segment_days(df_reg)
    if verbose:
        print(f"[pipeline] Days to analyse: {len(day_map)}")

    all_daily:    list[dict] = []
    all_ramps:    list[dict] = []
    all_peaks:    list[dict] = []
    all_interval: list[pd.DataFrame] = []

    for date, df_day in day_map.items():
        if verbose:
            print(f"[pipeline]   {date} ({len(df_day)} intervals)", end=" ")

        result = _analyse_day(
            date=date,
            df_day=df_day,
            res_min=res_min,
            cfg=cfg,
            meter_id=meter_id,
            building_id=building_id,
        )

        all_daily.append(result["features"] | result["classification"])

        for r in result["ramp_events"]:
            rd = asdict(r) if hasattr(r, "__dataclass_fields__") else dict(r)
            rd["date"] = date
            all_ramps.append(rd)

        for p in result["peak_events"]:
            pd_row = asdict(p) if hasattr(p, "__dataclass_fields__") else dict(p)
            pd_row["date"] = date
            all_peaks.append(pd_row)

        all_interval.append(result["interval_df"])

        if verbose:
            cls = result["classification"]["primary_class"]
            conf = result["classification"]["classification_confidence"]
            print(f"→ {cls} (conf {conf:.2f})")

    daily_df    = pd.DataFrame(all_daily)
    ramp_df     = pd.DataFrame(all_ramps)
    peak_df     = pd.DataFrame(all_peaks)
    interval_df = pd.concat(all_interval) if all_interval else pd.DataFrame()

    return {
        "interval_df": interval_df,
        "daily_df":    daily_df,
        "ramp_df":     ramp_df,
        "peak_df":     peak_df,
    }


def _analyse_day(
    date: str,
    df_day: pd.DataFrame,
    res_min: float,
    cfg: dict[str, Any],
    meter_id: str | None,
    building_id: str | None,
) -> dict[str, Any]:
    """
    Run all analytical steps for a single calendar day.

    Returns
    -------
    dict with keys: features, classification, ramp_events, peak_events, interval_df
    """
    # Data quality
    quality = assess_quality(df_day, res_min, cfg)

    # Smoothing
    series_raw    = df_day["demand_kw"]
    series_smooth = apply_smoothing(series_raw, cfg, res_min)

    # Baseline
    baseline = estimate_baseline(series_smooth, res_min, cfg)

    # Normalised demand
    norm = compute_normalized_demand(series_raw, baseline, cfg)

    # State detection
    states = detect_states(series_smooth, baseline, cfg)

    # Event detection
    start_ev = detect_start(series_smooth, states, baseline, cfg)
    end_ev   = detect_end(  series_smooth, states, baseline, cfg)
    ramp_evs = detect_ramps(series_smooth, baseline, states, cfg)
    peak_evs = detect_peaks(series_raw, df_day.get("is_interpolated", pd.Series(False, index=df_day.index)), baseline, cfg)
    op_periods = detect_operating_periods(states, cfg)

    # Features
    features = build_daily_features(
        date=date,
        meter_id=meter_id,
        building_id=building_id,
        df_day=df_day,
        series_raw=series_raw,
        series_smooth=series_smooth,
        states=states,
        baseline_result=baseline,
        quality=quality,
        start_event=start_ev,
        end_event=end_ev,
        ramp_events=ramp_evs,
        peak_events=peak_evs,
        operating_periods=op_periods,
        norm_demand=norm,
        cfg=cfg,
        resolution_minutes=res_min,
    )

    # Classification
    classification = classify_day(features, cfg)

    # Interval-level diagnostic table
    iv_df = df_day[["demand_kw", "is_observed", "is_interpolated", "is_missing"]].copy()
    iv_df["analysis_demand_kw"] = series_smooth
    iv_df["normalized_demand"]  = norm
    iv_df["baseline_kw"]        = baseline.get("baseline_kw", np.nan)
    iv_df["state"]              = states

    return {
        "features":        features,
        "classification":  classification,
        "ramp_events":     ramp_evs,
        "peak_events":     peak_evs,
        "interval_df":     iv_df,
    }
