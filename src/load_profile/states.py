"""
Demand-state detection: BASELINE | OPERATING | UNKNOWN.

Uses separate entry/exit thresholds (hysteresis) and enforces a minimum
state-persistence duration so transient excursions are not mis-classified.
All duration calculations use actual elapsed time.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# State constants
# ---------------------------------------------------------------------------

STATE_BASELINE   = "BASELINE"
STATE_OPERATING  = "OPERATING"
STATE_UNKNOWN    = "UNKNOWN"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def detect_states(
    series: pd.Series,
    baseline_result: dict[str, Any],
    cfg: dict[str, Any],
) -> pd.Series:
    """
    Assign a demand state to every interval of a smoothed daily demand series.

    Parameters
    ----------
    series : Series (float)
        ``analysis_demand_kw`` for one calendar day.
    baseline_result : dict
        Output of ``estimate_baseline``.
    cfg : dict

    Returns
    -------
    Series (str)
        Same index as ``series``; values are STATE_* constants.
        NaN demand intervals get STATE_UNKNOWN.
    """
    ot_cfg  = cfg.get("operating_threshold", {})
    alpha_e = ot_cfg.get("alpha_entry", 0.20)
    alpha_x = ot_cfg.get("alpha_exit",  0.15)
    min_per = ot_cfg.get("min_state_persistence_minutes", 30)

    baseline_kw = baseline_result.get("baseline_kw", np.nan)
    peak_kw     = baseline_result.get("peak_kw",     np.nan)

    if np.isnan(baseline_kw) or np.isnan(peak_kw):
        return pd.Series(STATE_UNKNOWN, index=series.index, dtype=str)

    op_range = peak_kw - baseline_kw
    if op_range <= 0:
        # Zero range → everything is BASELINE (continuous flat load)
        return pd.Series(STATE_BASELINE, index=series.index, dtype=str)

    thresh_entry = baseline_kw + alpha_e * op_range
    thresh_exit  = baseline_kw + alpha_x * op_range

    # Raw state from thresholds (no persistence enforcement yet)
    raw_state = _apply_hysteresis(series, thresh_entry, thresh_exit)

    # Enforce minimum persistence
    final_state = _enforce_persistence(raw_state, series.index, min_per)

    return final_state


def compute_normalized_demand(
    series: pd.Series,
    baseline_result: dict[str, Any],
    cfg: dict[str, Any],
) -> pd.Series:
    """
    Normalise demand to [0, 1] where 0 = baseline and 1 = peak.

    D_norm(t) = (D(t) - baseline) / (peak - baseline)

    Parameters
    ----------
    series : Series (float)
        Raw or smoothed demand.
    baseline_result : dict

    Returns
    -------
    Series (float)
        Normalised demand; can exceed 1 for super-peak intervals.
        NaN propagated.
    """
    baseline_kw = baseline_result.get("baseline_kw", np.nan)
    op_range    = baseline_result.get("operating_range_kw", np.nan)

    peak_cfg = cfg.get("normalization", {}).get("peak_for_normalization", "observed_max")

    if peak_cfg == "p99":
        valid = series.dropna()
        peak_kw = float(np.percentile(valid.values, 99)) if not valid.empty else np.nan
    else:
        peak_kw = baseline_result.get("peak_kw", np.nan)

    if np.isnan(baseline_kw) or np.isnan(peak_kw) or (peak_kw - baseline_kw) <= 0:
        return pd.Series(np.nan, index=series.index)

    norm = (series - baseline_kw) / (peak_kw - baseline_kw)
    return norm.rename("normalized_demand")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _apply_hysteresis(
    series: pd.Series,
    thresh_entry: float,
    thresh_exit: float,
) -> pd.Series:
    """
    Apply entry/exit hysteresis to produce initial state labels.

    State starts as BASELINE. Transitions to OPERATING when demand ≥ thresh_entry;
    returns to BASELINE when demand ≤ thresh_exit.
    NaN intervals → UNKNOWN.
    """
    states = []
    current = STATE_BASELINE

    for val in series:
        if pd.isna(val):
            states.append(STATE_UNKNOWN)
            continue
        if current == STATE_BASELINE and val >= thresh_entry:
            current = STATE_OPERATING
        elif current == STATE_OPERATING and val <= thresh_exit:
            current = STATE_BASELINE
        states.append(current)

    return pd.Series(states, index=series.index, dtype=str)


def _enforce_persistence(
    raw_state: pd.Series,
    index: pd.DatetimeIndex,
    min_persistence_minutes: float,
) -> pd.Series:
    """
    Remove transient state changes shorter than ``min_persistence_minutes``.

    A state change that reverts before persisting long enough is collapsed
    back into the preceding state.
    """
    final = raw_state.copy()
    n = len(final)
    if n == 0:
        return final

    # Identify runs of the same state
    runs: list[dict] = []
    cur_state = final.iloc[0]
    run_start = 0

    for i in range(1, n):
        if final.iloc[i] != cur_state:
            runs.append({"state": cur_state, "start": run_start, "end": i - 1})
            cur_state = final.iloc[i]
            run_start = i
    runs.append({"state": cur_state, "start": run_start, "end": n - 1})

    # Merge short runs into the preceding state
    changed = True
    while changed:
        changed = False
        merged: list[dict] = []
        i = 0
        while i < len(runs):
            run = runs[i]
            t_start = index[run["start"]]
            t_end   = index[run["end"]]
            dur_min = (t_end - t_start).total_seconds() / 60

            if dur_min < min_persistence_minutes and run["state"] != STATE_UNKNOWN:
                if merged:
                    # Extend the previous run
                    merged[-1]["end"] = run["end"]
                    changed = True
                else:
                    # Nothing before this run; keep it as-is
                    merged.append(run)
            else:
                merged.append(run)
            i += 1
        runs = merged

    # Reconstruct the series from cleaned runs
    result = final.copy()
    for run in runs:
        result.iloc[run["start"] : run["end"] + 1] = run["state"]
    return result
