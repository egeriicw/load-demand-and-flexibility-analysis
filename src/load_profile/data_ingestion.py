"""
Input loading, timestamp validation, and initial data integrity checks.

All functions return a DataFrame with a DatetimeIndex that is timezone-aware.
The original demand column is always preserved as ``demand_kw_raw``.
"""

from __future__ import annotations

import warnings
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def load_demand_data(
    source: str | Path | pd.DataFrame,
    cfg: dict[str, Any],
) -> pd.DataFrame:
    """
    Load raw demand data from a CSV file or a pre-existing DataFrame.

    Parameters
    ----------
    source : str, Path, or DataFrame
        CSV path or already-loaded DataFrame.
    cfg : dict
        Full configuration dictionary (from ``load_config()``).

    Returns
    -------
    DataFrame
        Columns: ``demand_kw``, ``demand_kw_raw``, ``meter_id`` (if present),
        ``building_id`` (if present). Index: timezone-aware DatetimeIndex
        named ``datetime``.
    """
    inc = cfg.get("input", {})
    dt_col  = inc.get("datetime_col",  "datetime")
    dem_col = inc.get("demand_col",    "demand_kw")
    mid_col = inc.get("meter_id_col",  "")
    bid_col = inc.get("building_id_col", "")

    if isinstance(source, (str, Path)):
        df = pd.read_csv(source)
    else:
        df = source.copy()

    if dt_col not in df.columns:
        raise ValueError(f"datetime column '{dt_col}' not found in data")
    if dem_col not in df.columns:
        raise ValueError(f"demand column '{dem_col}' not found in data")

    # Parse timestamps
    tz_default = cfg.get("timezone", {}).get("default_tz", "UTC")
    df[dt_col] = _parse_timestamps(df[dt_col], tz_default)
    df = df.set_index(dt_col)
    df.index.name = "datetime"

    # Rename demand
    df = df.rename(columns={dem_col: "demand_kw"})
    df["demand_kw_raw"] = df["demand_kw"].copy()

    # Optional identity columns
    keep_cols = ["demand_kw", "demand_kw_raw"]
    for src_col, dst_col in [(mid_col, "meter_id"), (bid_col, "building_id")]:
        if src_col and src_col in df.columns:
            df = df.rename(columns={src_col: dst_col})
            keep_cols.append(dst_col)

    return df[keep_cols].sort_index()


def convert_units(
    df: pd.DataFrame,
    resolution_minutes: float,
    cfg: dict[str, Any],
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """
    Convert the ``demand_kw`` column to kilowatts if the source data are in kWh.

    The conversion from energy-per-interval to average demand is:

        kW = kWh × (60 / resolution_minutes)

    Examples
    --------
    - 15-min kWh data: multiply by 4   (4 intervals per hour)
    - 30-min kWh data: multiply by 2
    - 60-min kWh data: multiply by 1   (already kWh/hr = kW average)

    When the configured unit is already "kW" this function is a no-op.

    Parameters
    ----------
    df : DataFrame
        Output of ``load_demand_data``.  Must contain ``demand_kw`` and
        ``demand_kw_raw`` columns.
    resolution_minutes : float
        Detected interval length in minutes (from ``validate_input``).
    cfg : dict
        Full configuration dictionary.

    Returns
    -------
    (df, metadata)
        ``df``       — copy of input with ``demand_kw`` expressed in kW and a new
                       ``demand_input_raw`` column holding the original meter
                       readings in their source unit.
        ``metadata`` — dict with keys ``input_unit``, ``output_unit``,
                       ``conversion_factor``, ``conversion_applied``.
    """
    unit = cfg.get("input", {}).get("unit", "kW").strip().lower()

    if unit not in ("kw", "kwh"):
        raise ValueError(
            f"cfg.input.unit must be 'kW' or 'kWh'; got '{unit}'"
        )

    df = df.copy()

    # Always store a column with the original meter reading in its source unit.
    # This preserves provenance regardless of whether conversion is applied.
    df["demand_input_raw"] = df["demand_kw_raw"].copy()

    if unit == "kwh":
        if resolution_minutes <= 0:
            raise ValueError(
                f"Cannot convert kWh to kW: resolution_minutes={resolution_minutes}"
            )
        factor = 60.0 / resolution_minutes
        df["demand_kw"]     = df["demand_kw"]     * factor
        df["demand_kw_raw"] = df["demand_kw_raw"] * factor
        metadata = {
            "input_unit":         "kWh",
            "output_unit":        "kW",
            "conversion_factor":  factor,
            "conversion_applied": True,
        }
    else:
        metadata = {
            "input_unit":         "kW",
            "output_unit":        "kW",
            "conversion_factor":  1.0,
            "conversion_applied": False,
        }

    return df, metadata


def validate_input(df: pd.DataFrame, cfg: dict[str, Any]) -> dict[str, Any]:
    """
    Run pre-analysis integrity checks and return a validation report.

    Parameters
    ----------
    df : DataFrame
        Output of ``load_demand_data``.
    cfg : dict
        Full configuration dictionary.

    Returns
    -------
    dict
        Keys: ``issues`` (list of str), ``warnings`` (list of str),
        ``negative_demand_count``, ``zero_demand_count``,
        ``duplicate_timestamp_count``, ``irregular_interval_count``,
        ``detected_resolution_minutes``.
    """
    report: dict[str, Any] = {
        "issues": [],
        "warnings": [],
    }

    # Duplicate timestamps
    dup_count = df.index.duplicated().sum()
    report["duplicate_timestamp_count"] = int(dup_count)
    if dup_count:
        report["issues"].append(
            f"{dup_count} duplicate timestamp(s) found — keeping first occurrence"
        )
        df = df[~df.index.duplicated(keep="first")]

    # Negative demand
    neg = (df["demand_kw"] < 0).sum()
    report["negative_demand_count"] = int(neg)
    severity = cfg.get("data_quality", {}).get("negative_demand_severity", "ERROR")
    report["negative_demand_severity"] = severity
    if neg:
        if severity == "ERROR":
            report["issues"].append(
                f"{neg} negative demand value(s) — rejected (negative demand is "
                f"unsupported by design; set data_quality.negative_demand_severity "
                f"= \"WARNING\" to treat as missing instead)"
            )
        elif severity == "WARNING":
            report["warnings"].append(
                f"{neg} negative demand value(s) — will be treated as missing during analysis"
            )
        # "INFO": counted only, no message appended.

    # Zero demand
    zero = (df["demand_kw"] == 0).sum()
    report["zero_demand_count"] = int(zero)

    # Resolution detection
    res = _detect_resolution(df.index)
    report["detected_resolution_minutes"] = res

    # Irregular intervals
    diffs = df.index.to_series().diff().dropna()
    expected_delta = pd.Timedelta(minutes=res)
    irregular = (diffs != expected_delta).sum()
    report["irregular_interval_count"] = int(irregular)
    if irregular:
        report["warnings"].append(
            f"{irregular} irregular interval(s) detected (expected {res} min)"
        )

    return report


def check_validation_report(report: dict[str, Any], cfg: dict[str, Any]) -> None:
    """
    Raise ``ValueError`` if ``report`` (from ``validate_input``) contains a
    condition the configured severity marks as fatal.

    ``validate_input`` itself never raises — it only reports. This is the
    caller-side gate (used by ``pipeline.run_pipeline``) that turns an
    ``ERROR``-severity finding into an aborted run.
    """
    if report.get("negative_demand_severity") == "ERROR" and report.get(
        "negative_demand_count", 0
    ):
        raise ValueError(
            f"Rejecting input: {report['negative_demand_count']} negative demand "
            f"value(s) found (data_quality.negative_demand_severity = \"ERROR\"). "
            f"Set it to \"WARNING\" to treat negative readings as missing instead."
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_timestamps(series: pd.Series, tz_default: str) -> pd.Series:
    """
    Parse a series of timestamp strings or objects into tz-aware Timestamps.

    Strategy:
      1. Try pd.to_datetime — preserves tz info if present in ISO strings.
      2. If result is tz-naive, localise using tz_default.
      3. If result is tz-aware but not uniform, convert to tz_default.
    """
    parsed = pd.to_datetime(series, utc=False)
    if parsed.dt.tz is None:
        parsed = parsed.dt.tz_localize(tz_default, ambiguous="infer", nonexistent="shift_forward")
    return parsed


def _detect_resolution(index: pd.DatetimeIndex) -> float:
    """
    Infer the native sampling interval in minutes from the most common gap
    between consecutive timestamps.

    Returns
    -------
    float
        Resolution in minutes (e.g. 15.0, 30.0, 60.0).
    """
    if len(index) < 2:
        raise ValueError("Need at least 2 timestamps to detect resolution")
    diffs_min = index.to_series().diff().dropna().dt.total_seconds() / 60
    # Most common gap (mode), ignoring outliers from missing data
    mode_val = float(diffs_min.mode().iloc[0])
    if mode_val <= 0:
        raise ValueError(f"Detected non-positive resolution: {mode_val} min")
    return round(mode_val, 4)
