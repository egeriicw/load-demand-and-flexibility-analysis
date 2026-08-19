"""
Rule-based daily load-profile classification.

Architecture: classification consumes already-measured features; it does not
re-derive measurements.

Output: one primary shape class + a set of independent boolean attributes.
All rules are driven by config thresholds so nothing important is buried as
a Python literal.
"""

from __future__ import annotations

from typing import Any


# ---------------------------------------------------------------------------
# Primary class constants
# ---------------------------------------------------------------------------

CLASS_CONTINUOUS       = "CONTINUOUS"
CLASS_EARLY_START      = "EARLY_START"        # start before 06:00
CLASS_MORNING_START    = "MORNING_START"       # start 06:00–10:00
CLASS_MIDDAY_START     = "MIDDAY_START"        # start 10:00–14:00
CLASS_EVENING_START    = "EVENING_START"       # start ≥ 14:00
CLASS_NO_CLEAR_START   = "NO_CLEAR_START"      # operating but no credible start
CLASS_MINIMAL_LOAD     = "MINIMAL_LOAD"        # demand too flat to characterise
CLASS_UNKNOWN          = "UNKNOWN"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def classify_day(
    features: dict[str, Any],
    cfg: dict[str, Any],
) -> dict[str, Any]:
    """
    Classify a day's load profile using rule-based logic.

    Parameters
    ----------
    features : dict
        Output of ``build_daily_features``.
    cfg : dict
        Full configuration dictionary.

    Returns
    -------
    dict
        ``primary_class``       – one of the CLASS_* constants
        ``attributes``          – list of active boolean attribute strings
        ``classification_confidence`` – float [0, 1]
        ``classification_notes``– human-readable explanation string
    """
    cl_cfg = cfg.get("classification", {})

    early_hr    = cl_cfg.get("early_start_before_hour",   6)
    morning_hr  = cl_cfg.get("morning_start_before_hour",  10)
    midday_hr   = cl_cfg.get("midday_start_before_hour",   14)
    rapid_kw_hr = cl_cfg.get("rapid_start_ramp_kw_per_hr", 50.0)
    long_op_hr  = cl_cfg.get("long_operation_hours",       10.0)
    short_op_hr = cl_cfg.get("short_operation_hours",       4.0)
    broad_80    = cl_cfg.get("broad_peak_width_80_hours",   3.0)
    sharp_80    = cl_cfg.get("sharp_peak_width_80_hours",   1.0)
    hi_cv       = cl_cfg.get("high_variability_cv_threshold", 0.30)
    mp_min      = cl_cfg.get("multi_period_min_count",       2)

    notes: list[str] = []
    attrs:  list[str] = []

    # ── Primary class ──────────────────────────────────────────────────────

    if features.get("is_continuous_operation"):
        primary = CLASS_CONTINUOUS
        notes.append("Operating range too small relative to daily mean.")

    elif _is_minimal_load(features):
        primary = CLASS_MINIMAL_LOAD
        notes.append("Daily demand range is negligible.")

    elif features.get("probable_start_time") is not None:
        start_hour = _hour_of(features["probable_start_time"])
        if start_hour is not None:
            if start_hour < early_hr:
                primary = CLASS_EARLY_START
            elif start_hour < morning_hr:
                primary = CLASS_MORNING_START
            elif start_hour < midday_hr:
                primary = CLASS_MIDDAY_START
            else:
                primary = CLASS_EVENING_START
        else:
            primary = CLASS_NO_CLEAR_START
    elif features.get("total_operating_duration_hours", 0) or 0 > 0:
        primary = CLASS_NO_CLEAR_START
        notes.append("Building operated but no credible start transition was detected.")
    else:
        primary = CLASS_UNKNOWN
        notes.append("Insufficient information to classify.")

    # ── Independent attributes ─────────────────────────────────────────────

    # Start characteristics
    if features.get("startup_ramp_kw_per_hr") and features["startup_ramp_kw_per_hr"] >= rapid_kw_hr:
        attrs.append("rapid_start")
    elif features.get("start_is_gradual"):
        attrs.append("gradual_start")

    if features.get("shutdown_ramp_kw_per_hr") and features["shutdown_ramp_kw_per_hr"] >= rapid_kw_hr:
        attrs.append("rapid_shutdown")
    elif features.get("end_is_gradual"):
        attrs.append("gradual_shutdown")

    # Operating duration
    op_dur = features.get("total_operating_duration_hours") or 0.0
    if op_dur >= long_op_hr:
        attrs.append("long_operating_duration")
    elif op_dur <= short_op_hr and op_dur > 0:
        attrs.append("short_operating_duration")

    # Peak shape
    w80 = features.get("peak_width_80_hours")
    if w80 is not None:
        if w80 >= broad_80:
            attrs.append("broad_peak")
        elif w80 <= sharp_80:
            attrs.append("sharp_peak")

    # Peak concentration
    pc1 = features.get("peak_concentration_1hr")
    if pc1 is not None and pc1 >= 0.40:
        attrs.append("high_peak_concentration")

    # Multiple periods
    n_periods = features.get("operating_period_count") or 0
    if n_periods >= mp_min:
        attrs.append("multiple_operating_periods")

    # Multiple peaks
    n_sec = features.get("secondary_peak_count") or 0
    if n_sec >= 1:
        attrs.append("multiple_peaks")

    # Variability
    cv = features.get("cv")
    if cv is not None and cv >= hi_cv:
        attrs.append("high_intraday_variability")

    # ── Confidence ────────────────────────────────────────────────────────
    confidence = _compute_classification_confidence(features, primary)
    notes_str  = " ".join(notes) if notes else "Classified from rule-based logic."

    return {
        "primary_class":              primary,
        "attributes":                 attrs,
        "classification_confidence":  round(confidence, 4),
        "classification_notes":       notes_str,
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _hour_of(iso_str: str | None) -> float | None:
    """Extract the hour of day (float) from an ISO-formatted timestamp string."""
    if iso_str is None:
        return None
    try:
        ts = pd.Timestamp(iso_str)
        return ts.hour + ts.minute / 60 + ts.second / 3600
    except Exception:
        return None


def _is_minimal_load(features: dict[str, Any]) -> bool:
    """True if the day's demand range is too small to characterise."""
    mn = features.get("minimum_kw")
    mx = features.get("maximum_kw")
    if mn is None or mx is None:
        return True
    return (mx - mn) < 5.0  # < 5 kW range is considered flat


def _compute_classification_confidence(
    features: dict[str, Any],
    primary_class: str,
) -> float:
    """
    Heuristic classification confidence:
    - Start from data quality completeness fraction
    - Boost by start/end detection confidence
    - Reduce if class is UNKNOWN or NO_CLEAR_START
    """
    base = features.get("dq_completeness_fraction") or 0.5

    sc = features.get("start_confidence") or 0.0
    ec = features.get("end_confidence")   or 0.0
    event_boost = (sc + ec) / 2

    confidence = 0.5 * base + 0.5 * event_boost

    if primary_class in (CLASS_UNKNOWN, CLASS_NO_CLEAR_START):
        confidence *= 0.5

    return min(1.0, confidence)


# Pandas is needed for _hour_of; import here to avoid circular at module level.
import pandas as pd  # noqa: E402
