"""
Event detection: startup transitions, shutdown transitions, ramp events, peak events.

Architecture: measurement and event detection only.
Classification is handled separately by classification.py.

All events are scored; the highest-scoring candidate becomes the probable event.
Confidence is a normalised [0, 1] float. The system may return None if no credible
event is found rather than inventing a spurious one.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any

import numpy as np
import pandas as pd

from .states import STATE_BASELINE, STATE_OPERATING, STATE_UNKNOWN


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class StartEvent:
    transition_time: pd.Timestamp         # Beginning of the upward ramp
    threshold_crossing_time: pd.Timestamp  # When demand first crossed operating threshold
    start_kw: float                        # Demand at transition_time
    threshold_kw: float                    # Operating threshold value
    delta_kw: float                        # Demand change over transition
    duration_hours: float                  # Transition duration
    ramp_rate_kw_per_hr: float             # Average ramp rate
    max_ramp_rate_kw_per_hr: float         # Maximum interval ramp rate
    persistence_hours: float               # How long demand stayed above threshold after crossing
    score: float                           # Candidate score [0, 1]
    confidence: float                      # Final confidence [0, 1]
    is_gradual: bool                       # True if ramp is extended (>60 min)


@dataclass
class EndEvent:
    transition_time: pd.Timestamp
    threshold_crossing_time: pd.Timestamp
    end_kw: float
    threshold_kw: float
    delta_kw: float
    duration_hours: float
    ramp_rate_kw_per_hr: float
    max_ramp_rate_kw_per_hr: float
    persistence_hours: float
    score: float
    confidence: float
    is_gradual: bool


@dataclass
class RampEvent:
    event_type: str          # "UP" | "DOWN"
    start_time: pd.Timestamp
    end_time: pd.Timestamp
    start_kw: float
    end_kw: float
    delta_kw: float
    duration_hours: float
    average_ramp_kw_per_hr: float
    max_ramp_kw_per_hr: float
    percent_change: float
    normalized_ramp_rate: float  # per hour in normalised demand units
    confidence: float
    is_operating_transition: bool


@dataclass
class PeakEvent:
    rank: int                     # 1 = primary
    peak_time: pd.Timestamp
    peak_kw: float
    peak_is_interpolated: bool
    prominence_kw: float
    prominence_fraction: float   # relative to baseline-to-peak range
    width_70_hours: float
    width_80_hours: float
    width_90_hours: float
    separation_from_primary_hours: float  # 0 for primary peak
    confidence: float


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def detect_start(
    series: pd.Series,
    states: pd.Series,
    baseline_result: dict[str, Any],
    cfg: dict[str, Any],
) -> StartEvent | None:
    """
    Detect the most probable operating start transition for one day.

    Returns None when no credible start is found (e.g. continuous operation
    or the building never leaves baseline).
    """
    sd_cfg  = cfg.get("start_detection", {})
    ot_cfg  = cfg.get("operating_threshold", {})
    alpha_e = ot_cfg.get("alpha_entry", 0.20)

    baseline_kw = baseline_result.get("baseline_kw", np.nan)
    peak_kw     = baseline_result.get("peak_kw",     np.nan)
    if np.isnan(baseline_kw) or np.isnan(peak_kw):
        return None

    op_range  = peak_kw - baseline_kw
    thresh    = baseline_kw + alpha_e * op_range

    min_mag   = sd_cfg.get("min_magnitude_kw",        10.0)
    min_rate  = sd_cfg.get("min_ramp_rate_kw_per_hr",  5.0)
    min_per   = sd_cfg.get("min_persistence_minutes",  30.0)

    w_mag  = sd_cfg.get("weight_ramp_magnitude", 0.30)
    w_rate = sd_cfg.get("weight_ramp_rate",       0.25)
    w_per  = sd_cfg.get("weight_persistence",     0.25)
    w_sep  = sd_cfg.get("weight_baseline_sep",    0.20)

    # Find BASELINE→OPERATING transitions in the state series
    candidates = _find_upward_transitions(states, series, thresh)

    if not candidates:
        return None

    # Score each candidate
    scored = []
    for cand in candidates:
        mag_score  = min(1.0, cand["delta_kw"]          / max(op_range, 1e-6))
        rate_score = min(1.0, cand["avg_rate"]           / max(min_rate * 10, 1e-6))
        per_score  = min(1.0, cand["persistence_hours"]  / 4.0)
        sep_score  = min(1.0, cand["baseline_sep"]       / max(op_range, 1e-6))

        score = w_mag * mag_score + w_rate * rate_score + w_per * per_score + w_sep * sep_score

        # Filter by minimum thresholds
        if cand["delta_kw"] < min_mag:
            continue
        if cand["avg_rate"] < min_rate:
            continue
        if cand["persistence_hours"] * 60 < min_per:
            continue

        scored.append((score, cand))

    if not scored:
        return None

    best_score, best = max(scored, key=lambda x: x[0])

    gradual_threshold_hr = cfg.get("smoothing", {}).get("window_minutes", 60) / 60
    is_gradual = best["duration_hours"] > gradual_threshold_hr

    # Confidence: score adjusted down by data quality issues
    confidence = _quality_adjusted_confidence(best_score, series, best["transition_time"])

    return StartEvent(
        transition_time            = best["transition_time"],
        threshold_crossing_time    = best["crossing_time"],
        start_kw                   = round(best["start_kw"], 2),
        threshold_kw               = round(thresh, 2),
        delta_kw                   = round(best["delta_kw"], 2),
        duration_hours             = round(best["duration_hours"], 4),
        ramp_rate_kw_per_hr        = round(best["avg_rate"], 2),
        max_ramp_rate_kw_per_hr    = round(best["max_rate"], 2),
        persistence_hours          = round(best["persistence_hours"], 4),
        score                      = round(best_score, 4),
        confidence                 = round(confidence, 4),
        is_gradual                 = is_gradual,
    )


def detect_end(
    series: pd.Series,
    states: pd.Series,
    baseline_result: dict[str, Any],
    cfg: dict[str, Any],
) -> EndEvent | None:
    """
    Detect the most probable operating shutdown transition for one day.
    Symmetric to detect_start but operates on downward transitions.
    """
    ed_cfg  = cfg.get("end_detection", {})
    ot_cfg  = cfg.get("operating_threshold", {})
    alpha_x = ot_cfg.get("alpha_exit", 0.15)

    baseline_kw = baseline_result.get("baseline_kw", np.nan)
    peak_kw     = baseline_result.get("peak_kw",     np.nan)
    if np.isnan(baseline_kw) or np.isnan(peak_kw):
        return None

    op_range = peak_kw - baseline_kw
    thresh   = baseline_kw + alpha_x * op_range

    min_mag  = ed_cfg.get("min_magnitude_kw",        10.0)
    min_rate = ed_cfg.get("min_ramp_rate_kw_per_hr",  5.0)
    min_per  = ed_cfg.get("min_persistence_minutes",  30.0)

    w_mag  = ed_cfg.get("weight_ramp_magnitude", 0.30)
    w_rate = ed_cfg.get("weight_ramp_rate",       0.25)
    w_per  = ed_cfg.get("weight_persistence",     0.25)
    w_sep  = ed_cfg.get("weight_baseline_sep",    0.20)

    candidates = _find_downward_transitions(states, series, thresh)

    if not candidates:
        return None

    scored = []
    for cand in candidates:
        mag_score  = min(1.0, cand["delta_kw"]          / max(op_range, 1e-6))
        rate_score = min(1.0, cand["avg_rate"]           / max(min_rate * 10, 1e-6))
        per_score  = min(1.0, cand["persistence_hours"]  / 4.0)
        sep_score  = min(1.0, cand["baseline_sep"]       / max(op_range, 1e-6))

        score = w_mag * mag_score + w_rate * rate_score + w_per * per_score + w_sep * sep_score

        if cand["delta_kw"] < min_mag:
            continue
        if cand["avg_rate"] < min_rate:
            continue
        if cand["persistence_hours"] * 60 < min_per:
            continue

        scored.append((score, cand))

    if not scored:
        return None

    best_score, best = max(scored, key=lambda x: x[0])

    gradual_threshold_hr = cfg.get("smoothing", {}).get("window_minutes", 60) / 60
    is_gradual = best["duration_hours"] > gradual_threshold_hr

    confidence = _quality_adjusted_confidence(best_score, series, best["transition_time"])

    return EndEvent(
        transition_time            = best["transition_time"],
        threshold_crossing_time    = best["crossing_time"],
        end_kw                     = round(best["end_kw"], 2),
        threshold_kw               = round(thresh, 2),
        delta_kw                   = round(best["delta_kw"], 2),
        duration_hours             = round(best["duration_hours"], 4),
        ramp_rate_kw_per_hr        = round(best["avg_rate"], 2),
        max_ramp_rate_kw_per_hr    = round(best["max_rate"], 2),
        persistence_hours          = round(best["persistence_hours"], 4),
        score                      = round(best_score, 4),
        confidence                 = round(confidence, 4),
        is_gradual                 = is_gradual,
    )


def detect_ramps(
    series: pd.Series,
    baseline_result: dict[str, Any],
    states: pd.Series,
    cfg: dict[str, Any],
) -> list[RampEvent]:
    """
    Detect all meaningful ramp events (up and down) in a day's demand series.

    A ramp event is a sustained monotonic demand change with allowance for
    small reversals (configurable tolerance).

    Returns
    -------
    list of RampEvent, sorted by start_time.
    """
    r_cfg = cfg.get("ramp_detection", {})
    min_mag  = r_cfg.get("min_magnitude_kw",         10.0)
    min_rate = r_cfg.get("min_rate_kw_per_hr",         5.0)
    min_dur  = r_cfg.get("min_duration_minutes",       10.0)
    rev_tol  = r_cfg.get("reversal_tolerance_fraction", 0.10)
    min_sep  = r_cfg.get("min_separation_minutes",     15.0)

    baseline_kw = baseline_result.get("baseline_kw",     np.nan)
    op_range    = baseline_result.get("operating_range_kw", np.nan)

    valid = series.dropna()
    if len(valid) < 3:
        return []

    interval_ramps = _compute_interval_ramps(series)
    events = _group_ramp_events(
        series, interval_ramps, min_reversal_fraction=rev_tol
    )

    results: list[RampEvent] = []
    last_end_time = None

    for ev in events:
        dur_min = (ev["end_time"] - ev["start_time"]).total_seconds() / 60
        delta   = abs(ev["end_kw"] - ev["start_kw"])
        avg_rate = delta / (dur_min / 60) if dur_min > 0 else 0.0

        # Minimum separation from last event
        if last_end_time is not None:
            sep_min = (ev["start_time"] - last_end_time).total_seconds() / 60
            if sep_min < min_sep:
                continue

        if delta < min_mag:
            continue
        if avg_rate < min_rate:
            continue
        if dur_min < min_dur:
            continue

        # Compute all three ramp-rate representations
        pct_change = (delta / abs(ev["start_kw"])) * 100 if ev["start_kw"] != 0 else np.nan
        norm_rate  = (delta / max(op_range, 1e-6)) / (dur_min / 60) if not np.isnan(op_range) else np.nan
        max_iv_rate = float(abs(interval_ramps[ev["start_time"]:ev["end_time"]]).max()) if not interval_ramps[ev["start_time"]:ev["end_time"]].empty else avg_rate

        is_op_transition = _is_operating_transition(
            ev["start_time"], ev["end_time"], states
        )

        confidence = min(1.0, (delta / max(op_range, 1e-6)) * 0.5 + min(avg_rate / 100.0, 0.5))

        results.append(RampEvent(
            event_type              = "UP" if ev["end_kw"] > ev["start_kw"] else "DOWN",
            start_time              = ev["start_time"],
            end_time                = ev["end_time"],
            start_kw                = round(ev["start_kw"], 2),
            end_kw                  = round(ev["end_kw"], 2),
            delta_kw                = round(delta, 2),
            duration_hours          = round(dur_min / 60, 4),
            average_ramp_kw_per_hr  = round(avg_rate, 2),
            max_ramp_kw_per_hr      = round(max_iv_rate, 2),
            percent_change          = round(pct_change, 2) if not np.isnan(pct_change) else np.nan,
            normalized_ramp_rate    = round(norm_rate, 4) if not np.isnan(norm_rate) else np.nan,
            confidence              = round(confidence, 4),
            is_operating_transition = is_op_transition,
        ))
        last_end_time = ev["end_time"]

    return results


def detect_peaks(
    series: pd.Series,
    is_interpolated: pd.Series,
    baseline_result: dict[str, Any],
    cfg: dict[str, Any],
) -> list[PeakEvent]:
    """
    Detect primary and secondary peak events for one day.

    Returns
    -------
    list of PeakEvent sorted by rank (rank=1 is the primary/highest peak).
    """
    pk_cfg  = cfg.get("peak_detection", {})
    min_prom_frac = pk_cfg.get("min_prominence_fraction", 0.10)
    min_sep_min   = pk_cfg.get("min_separation_minutes",  30.0)
    plateau_tol   = pk_cfg.get("plateau_tolerance_fraction", 0.01)

    br_cfg  = cfg.get("breadth", {})
    peak_thresholds = br_cfg.get("peak_thresholds", [0.70, 0.80, 0.90])

    baseline_kw = baseline_result.get("baseline_kw",     np.nan)
    peak_kw     = baseline_result.get("peak_kw",         np.nan)
    op_range    = baseline_result.get("operating_range_kw", np.nan)

    if np.isnan(baseline_kw) or np.isnan(op_range) or op_range <= 0:
        return []

    valid = series.dropna()
    if valid.empty:
        return []

    min_prom_kw = min_prom_frac * op_range

    # Normalised series for width calculations
    norm = (series - baseline_kw) / op_range

    # Find local maxima
    local_max_idx = _find_local_maxima(series, plateau_tolerance=plateau_tol)

    if not local_max_idx:
        return []

    # Filter by prominence
    peaks_filtered = _filter_by_prominence(series, local_max_idx, min_prom_kw)

    # Filter by temporal separation (keep higher-prominence peak in conflicts)
    peaks_filtered = _filter_by_separation(peaks_filtered, series, min_sep_min)

    if not peaks_filtered:
        return []

    # Sort by demand (highest first)
    peaks_filtered.sort(key=lambda ts: series.at[ts], reverse=True)

    primary_ts = peaks_filtered[0]
    primary_kw = float(series.at[primary_ts])

    events: list[PeakEvent] = []
    for rank, ts in enumerate(peaks_filtered, start=1):
        kw        = float(series.at[ts])
        prom      = _compute_prominence(series, ts, local_max_idx)
        prom_frac = prom / op_range

        widths = {}
        for thr in peak_thresholds:
            widths[thr] = _compute_peak_width(norm, ts, thr)

        sep_hrs = abs((ts - primary_ts).total_seconds()) / 3600 if rank > 1 else 0.0

        is_interp = bool(is_interpolated.get(ts, False))
        confidence = min(1.0, prom_frac * 2)

        events.append(PeakEvent(
            rank                          = rank,
            peak_time                     = ts,
            peak_kw                       = round(kw, 2),
            peak_is_interpolated          = is_interp,
            prominence_kw                 = round(prom, 2),
            prominence_fraction           = round(prom_frac, 4),
            width_70_hours                = round(widths.get(0.70, 0.0), 4),
            width_80_hours                = round(widths.get(0.80, 0.0), 4),
            width_90_hours                = round(widths.get(0.90, 0.0), 4),
            separation_from_primary_hours = round(sep_hrs, 4),
            confidence                    = round(confidence, 4),
        ))

    return events


def detect_operating_periods(
    states: pd.Series,
    cfg: dict[str, Any],
) -> list[dict[str, Any]]:
    """
    Identify distinct OPERATING periods in a state series.

    Returns
    -------
    list of dicts with keys:
        ``start``, ``end``, ``duration_hours``, ``rank``
    Sorted by duration descending; rank 1 is the longest/primary period.
    """
    mp_cfg  = cfg.get("multiple_periods", {})
    min_gap = mp_cfg.get("min_baseline_gap_minutes",   60.0)
    min_dur = mp_cfg.get("min_period_duration_minutes", 30.0)

    # Extract runs of OPERATING
    in_op  = False
    op_start = None
    periods: list[dict] = []

    for ts, state in states.items():
        if state == STATE_OPERATING:
            if not in_op:
                in_op = True
                op_start = ts
        else:
            if in_op:
                dur_min = (ts - op_start).total_seconds() / 60
                if dur_min >= min_dur:
                    periods.append({
                        "start": op_start,
                        "end":   ts,
                        "duration_hours": dur_min / 60,
                    })
                in_op = False

    if in_op and op_start is not None:
        ts = states.index[-1]
        dur_min = (ts - op_start).total_seconds() / 60
        if dur_min >= min_dur:
            periods.append({
                "start": op_start,
                "end":   ts,
                "duration_hours": dur_min / 60,
            })

    # Merge periods separated by a gap shorter than min_gap
    merged = _merge_close_periods(periods, min_gap_minutes=min_gap)

    # Rank by duration
    merged.sort(key=lambda p: p["duration_hours"], reverse=True)
    for i, p in enumerate(merged, start=1):
        p["rank"] = i

    return merged


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _compute_interval_ramps(series: pd.Series) -> pd.Series:
    """
    Compute the ramp rate (kW/hour) between each pair of adjacent intervals.
    Returned Series has the same index as ``series``; first value is NaN.
    """
    elapsed_hr = series.index.to_series().diff().dt.total_seconds() / 3600
    demand_diff = series.diff()
    ramps = demand_diff / elapsed_hr
    return ramps.rename("ramp_kw_per_hr")


def _group_ramp_events(
    series: pd.Series,
    interval_ramps: pd.Series,
    min_reversal_fraction: float,
) -> list[dict]:
    """
    Group consecutive same-direction interval ramps into ramp events.
    Small reversals (< min_reversal_fraction * cumulative change) are tolerated.
    """
    events: list[dict] = []
    valid_ramps = interval_ramps.dropna()

    if valid_ramps.empty:
        return []

    i = 0
    idxs = valid_ramps.index.tolist()

    while i < len(idxs):
        direction = np.sign(valid_ramps.iloc[i])
        if direction == 0:
            i += 1
            continue

        ev_start = idxs[i - 1] if i > 0 else idxs[i]
        cumulative = 0.0
        j = i

        while j < len(idxs):
            step = valid_ramps.iloc[j]
            if np.sign(step) == direction:
                cumulative += step * (
                    series.index[series.index.get_loc(idxs[j])] -
                    series.index[series.index.get_loc(idxs[j]) - 1]
                ).total_seconds() / 3600 if series.index.get_loc(idxs[j]) > 0 else 0
                j += 1
            elif step == 0:
                # A true flat interval (no movement) ends the event rather
                # than being absorbed as a "reversal" -- reversal_mag would
                # be 0, which is always < any positive tolerance threshold,
                # so without this branch a plateau of any length gets
                # silently swallowed into the ramp regardless of duration.
                break
            else:
                # Reversal tolerance
                reversal_mag = abs(step)
                if cumulative != 0 and reversal_mag < min_reversal_fraction * abs(cumulative):
                    j += 1  # absorb small reversal
                else:
                    break

        ev_end = idxs[j - 1] if j > i else ev_start
        start_kw = float(series.at[ev_start]) if ev_start in series.index else np.nan
        end_kw   = float(series.at[ev_end])   if ev_end   in series.index else np.nan

        if ev_start != ev_end and not np.isnan(start_kw) and not np.isnan(end_kw):
            events.append({
                "start_time": ev_start,
                "end_time":   ev_end,
                "start_kw":   start_kw,
                "end_kw":     end_kw,
                "direction":  direction,
            })

        i = j if j > i else i + 1

    return events


def _find_upward_transitions(
    states: pd.Series,
    series: pd.Series,
    threshold: float,
) -> list[dict]:
    """Find BASELINE→OPERATING transition candidates."""
    candidates = []
    prev_state = None
    transition_start = None
    transition_start_kw = None

    for ts, state in states.items():
        if prev_state in (STATE_BASELINE, None) and state == STATE_OPERATING:
            # Find where the upward ramp began (look back for local minimum)
            lookback_end   = ts
            lookback_start = ts - pd.Timedelta(hours=2)
            lookback = series[lookback_start:lookback_end].dropna()
            if not lookback.empty:
                transition_start    = lookback.idxmin()
                transition_start_kw = float(lookback.min())
            else:
                transition_start    = ts
                transition_start_kw = float(series.at[ts]) if ts in series.index else np.nan

        if (transition_start is not None and state == STATE_OPERATING
                and prev_state in (STATE_BASELINE, None)):
            # Measure persistence
            op_segment = series[ts:]
            if not op_segment.empty:
                persist_end  = _first_below_threshold(op_segment, threshold)
                persist_hr   = (persist_end - ts).total_seconds() / 3600
            else:
                persist_hr = 0.0

            dur_hr  = (ts - transition_start).total_seconds() / 3600
            delta   = float(series.at[ts]) - transition_start_kw if not np.isnan(transition_start_kw) else 0.0
            avg_rate = delta / dur_hr if dur_hr > 0 else 0.0

            # Max interval rate during transition window
            window  = series[transition_start:ts].dropna()
            diffs   = window.diff().dropna()
            times_h = window.index.to_series().diff().dropna().dt.total_seconds() / 3600
            max_rate = float((diffs.abs() / times_h.clip(lower=1e-9)).max()) if not diffs.empty else avg_rate

            sep = float(series.at[ts]) - threshold if ts in series.index else 0.0

            candidates.append({
                "transition_time":  transition_start,
                "crossing_time":    ts,
                "start_kw":         transition_start_kw,
                "delta_kw":         delta,
                "duration_hours":   dur_hr,
                "avg_rate":         avg_rate,
                "max_rate":         max_rate,
                "persistence_hours": persist_hr,
                "baseline_sep":     sep,
            })
            transition_start = None

        prev_state = state

    return candidates


def _find_downward_transitions(
    states: pd.Series,
    series: pd.Series,
    threshold: float,
) -> list[dict]:
    """Find OPERATING→BASELINE transition candidates."""
    candidates = []
    prev_state = None

    for ts, state in states.items():
        if prev_state == STATE_OPERATING and state == STATE_BASELINE:
            # Find where the downward ramp actually began: the last local
            # high before the decline (mirrors the backward lookback used
            # by upward transitions to find the pre-rise low). Without this,
            # an abrupt single-interval drop uses the already-dropped value
            # at `ts` as its own origin, producing a spurious delta of ~0.
            lookback_start = ts - pd.Timedelta(hours=2)
            lookback = series[lookback_start:ts].dropna()
            if not lookback.empty:
                origin_time = lookback.idxmax()
                origin_kw   = float(lookback.max())
            else:
                origin_time = ts
                origin_kw   = float(series.at[ts]) if ts in series.index else np.nan

            # Find where ramp ends (look forward for local minimum)
            lookahead_end = ts + pd.Timedelta(hours=2)
            lookahead = series[ts:lookahead_end].dropna()
            transition_end    = lookahead.idxmin() if not lookahead.empty else ts
            transition_end_kw = float(lookahead.min()) if not lookahead.empty else np.nan

            dur_hr   = (transition_end - origin_time).total_seconds() / 3600
            delta    = (
                origin_kw - transition_end_kw
                if not np.isnan(transition_end_kw) and not np.isnan(origin_kw)
                else 0.0
            )
            avg_rate = delta / dur_hr if dur_hr > 0 else 0.0

            window   = series[origin_time:transition_end].dropna()
            diffs    = window.diff().dropna()
            times_h  = window.index.to_series().diff().dropna().dt.total_seconds() / 3600
            max_rate = float((diffs.abs() / times_h.clip(lower=1e-9)).max()) if not diffs.empty else avg_rate

            # How long demand was below threshold before this (persistence low)
            baseline_seg = states[:ts]
            if not baseline_seg.empty:
                bl_count = (baseline_seg == STATE_BASELINE).sum()
                persist_hr = bl_count * (
                    series.index.to_series().diff().median().total_seconds() / 3600
                )
            else:
                persist_hr = 0.0

            sep = transition_end_kw - threshold if not np.isnan(transition_end_kw) else 0.0

            candidates.append({
                "transition_time":   ts,
                "crossing_time":     transition_end,
                "end_kw":            transition_end_kw,
                "delta_kw":          delta,
                "duration_hours":    dur_hr,
                "avg_rate":          avg_rate,
                "max_rate":          max_rate,
                "persistence_hours": persist_hr,
                "baseline_sep":      abs(sep),
            })

        prev_state = state

    return candidates


def _first_below_threshold(series: pd.Series, threshold: float) -> pd.Timestamp:
    """Return timestamp of first value below threshold, or end of series."""
    below = series[series < threshold]
    return below.index[0] if not below.empty else series.index[-1]


def _is_operating_transition(
    start_time: pd.Timestamp,
    end_time: pd.Timestamp,
    states: pd.Series,
) -> bool:
    """True if the ramp spans a BASELINE↔OPERATING boundary."""
    segment = states[start_time:end_time]
    return (STATE_BASELINE in segment.values) and (STATE_OPERATING in segment.values)


def _find_local_maxima(
    series: pd.Series,
    plateau_tolerance: float = 0.01,
) -> list[pd.Timestamp]:
    """
    Find local maxima, collapsing flat-top plateaus to their midpoint.
    """
    vals  = series.dropna()
    idxs  = vals.index.tolist()
    peaks: list[pd.Timestamp] = []

    i = 0
    while i < len(idxs):
        ts  = idxs[i]
        kw  = float(vals.at[ts])
        # Extend plateau
        j = i + 1
        while j < len(idxs) and abs(float(vals.at[idxs[j]]) - kw) / max(kw, 1e-6) <= plateau_tolerance:
            j += 1
        plateau = idxs[i:j]

        is_left_higher  = (i > 0       and float(vals.at[idxs[i - 1]]) > kw)
        is_right_higher = (j < len(idxs) and float(vals.at[idxs[j]])   > kw)

        if not is_left_higher and not is_right_higher and j > i:
            # Local maximum — use midpoint of plateau
            mid = len(plateau) // 2
            peaks.append(plateau[mid])

        i = j

    return peaks


def _filter_by_prominence(
    series: pd.Series,
    peak_idxs: list[pd.Timestamp],
    min_prominence_kw: float,
) -> list[pd.Timestamp]:
    """Keep only peaks with prominence ≥ min_prominence_kw."""
    return [
        ts for ts in peak_idxs
        if _compute_prominence(series, ts, peak_idxs) >= min_prominence_kw
    ]


def _compute_prominence(
    series: pd.Series,
    ts: pd.Timestamp,
    all_peaks: list[pd.Timestamp],
) -> float:
    """
    Peak prominence: height above the highest valley connecting this peak
    to any higher peak.  Simplified version using the minimum demand between
    this peak and the nearest higher peak (left and right).
    """
    kw    = float(series.at[ts])
    valid = series.dropna()

    higher = [p for p in all_peaks if float(series.at[p]) > kw and p != ts]

    if not higher:
        # Highest peak — prominence = height above global minimum
        return kw - float(valid.min())

    left_higher  = [p for p in higher if p < ts]
    right_higher = [p for p in higher if p > ts]

    valleys = []
    if left_higher:
        nearest_left = max(left_higher)
        valley_l = float(valid[nearest_left:ts].min())
        valleys.append(valley_l)
    if right_higher:
        nearest_right = min(right_higher)
        valley_r = float(valid[ts:nearest_right].min())
        valleys.append(valley_r)

    if not valleys:
        return kw - float(valid.min())

    return kw - max(valleys)


def _filter_by_separation(
    peak_idxs: list[pd.Timestamp],
    series: pd.Series,
    min_sep_min: float,
) -> list[pd.Timestamp]:
    """Remove peaks that are too close together; keep the higher one."""
    if not peak_idxs:
        return []

    sorted_peaks = sorted(peak_idxs, key=lambda ts: float(series.at[ts]), reverse=True)
    kept: list[pd.Timestamp] = []

    for ts in sorted_peaks:
        too_close = any(
            abs((ts - k).total_seconds()) / 60 < min_sep_min
            for k in kept
        )
        if not too_close:
            kept.append(ts)

    return kept


def _compute_peak_width(
    norm_series: pd.Series,
    peak_ts: pd.Timestamp,
    threshold_fraction: float,
) -> float:
    """
    Duration (hours) that normalised demand stays above ``threshold_fraction``
    in the contiguous region around ``peak_ts``.
    """
    above = norm_series >= threshold_fraction
    if not above.at[peak_ts] if peak_ts in above.index else False:
        return 0.0

    # Walk left from peak
    idxs = norm_series.index.tolist()
    pos  = idxs.index(peak_ts)

    left = pos
    while left > 0 and above.iloc[left - 1]:
        left -= 1

    right = pos
    while right < len(idxs) - 1 and above.iloc[right + 1]:
        right += 1

    t_left  = idxs[left]
    t_right = idxs[right]
    return (t_right - t_left).total_seconds() / 3600


def _quality_adjusted_confidence(
    base_score: float,
    series: pd.Series,
    event_time: pd.Timestamp,
) -> float:
    """
    Reduce confidence if the event falls near a missing-data window.
    """
    window_start = event_time - pd.Timedelta(hours=1)
    window_end   = event_time + pd.Timedelta(hours=1)
    window = series[window_start:window_end]
    missing_frac = window.isna().mean() if not window.empty else 0.0
    return base_score * (1.0 - 0.5 * missing_frac)


def _merge_close_periods(
    periods: list[dict],
    min_gap_minutes: float,
) -> list[dict]:
    """Merge operating periods separated by a gap shorter than min_gap_minutes."""
    if not periods:
        return []

    sorted_p = sorted(periods, key=lambda p: p["start"])
    merged   = [sorted_p[0].copy()]

    for p in sorted_p[1:]:
        last = merged[-1]
        gap  = (p["start"] - last["end"]).total_seconds() / 60
        if gap < min_gap_minutes:
            # Extend last period
            last["end"] = p["end"]
            last["duration_hours"] = (last["end"] - last["start"]).total_seconds() / 3600
        else:
            merged.append(p.copy())

    return merged
