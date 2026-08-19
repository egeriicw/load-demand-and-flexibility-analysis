"""
Meter coincidence analysis (DER spec §5.9/§22) — statistical, not causal.

Coincidence factor (CF) = coincident_group_peak / sum_of_individual_meter_peaks.

CF = 1.0 means all meters peak simultaneously; CF approaching 0 means complete
temporal diversity. Reported at both study-period and per-day granularity.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd


@dataclass
class CoincidenceResult:
    success: bool
    coincidence_factor: float = float("nan")
    """CF = group_peak_kw / sum_of_individual_peaks_kw. Range (0, 1] under
    typical (no-NaN-gap) conditions; see ADR 015 for the edge case where
    uneven meter coverage can produce CF > 1."""
    group_peak_kw: float = float("nan")
    """Maximum of the summed entity demand across all timestamps."""
    sum_of_individual_peaks_kw: float = float("nan")
    """Sum of each participating meter's peak demand (non-coincident sum)."""
    coincident_peak_timestamp: pd.Timestamp | None = None
    """Timestamp at which the group demand reaches its maximum."""
    n_meters: int = 0
    meter_peak_kw: dict[str, float] = field(default_factory=dict)
    """Per-meter peak demand over the study period."""


def _pivot(
    interval_df_multi: pd.DataFrame,
    meter_ids: list[str],
    value_col: str,
) -> pd.DataFrame:
    """Filter to meter_ids and pivot to (datetime × meter_id)."""
    subset = interval_df_multi[interval_df_multi["meter_id"].isin(meter_ids)]
    tmp = subset[[value_col, "meter_id"]].copy()
    tmp.index.name = "datetime"
    return tmp.reset_index().pivot_table(
        index="datetime", columns="meter_id", values=value_col, aggfunc="first"
    )


def compute_coincidence_factor(
    interval_df_multi: pd.DataFrame,
    meter_ids: list[str],
    cfg: dict[str, Any],
    value_col: str = "demand_kw",
) -> CoincidenceResult:
    """
    Study-period coincidence factor for a set of meters.

    Parameters
    ----------
    interval_df_multi:
        All-meter interval DataFrame with a ``meter_id`` column
        (``DERResult.interval_df_multi``).
    meter_ids:
        The meters to include in this entity's coincidence calculation.
    cfg:
        Full analysis config dict; reads ``[der.coincidence]``.
    value_col:
        Demand column name (default ``"demand_kw"``).

    Returns
    -------
    CoincidenceResult
        ``success=False`` when fewer than ``min_meters`` meters are available
        or the group demand is entirely NaN.
    """
    ccfg = cfg.get("der", {}).get("coincidence", {})
    min_meters = ccfg.get("min_meters", 2)

    pivoted = _pivot(interval_df_multi, meter_ids, value_col)
    available = list(pivoted.columns)

    if len(available) < min_meters:
        return CoincidenceResult(success=False, n_meters=len(available))

    group_demand = pivoted.sum(axis=1, min_count=1)
    if group_demand.isna().all():
        return CoincidenceResult(success=False, n_meters=len(available))

    group_peak_kw = float(group_demand.max())
    coincident_peak_ts = group_demand.idxmax()

    meter_peak_kw = {
        m: float(pivoted[m].max())
        for m in available
        if not pivoted[m].isna().all()
    }
    sum_individual = sum(meter_peak_kw.values())

    if sum_individual == 0:
        return CoincidenceResult(success=False, n_meters=len(available))

    return CoincidenceResult(
        success=True,
        coincidence_factor=group_peak_kw / sum_individual,
        group_peak_kw=group_peak_kw,
        sum_of_individual_peaks_kw=sum_individual,
        coincident_peak_timestamp=coincident_peak_ts,
        n_meters=len(available),
        meter_peak_kw=meter_peak_kw,
    )


def compute_daily_coincidence(
    interval_df_multi: pd.DataFrame,
    meter_ids: list[str],
    cfg: dict[str, Any],
    value_col: str = "demand_kw",
) -> pd.DataFrame:
    """
    Per-day coincidence factor for a set of meters.

    Returns a DataFrame with one row per date that has enough data to compute
    a CF (days where group demand is entirely NaN are skipped). Columns:
    ``date``, ``coincidence_factor``, ``group_peak_kw``,
    ``sum_of_individual_peaks_kw``, ``coincident_peak_timestamp``,
    ``n_meters_reporting``.

    Returns an empty DataFrame (with the above columns) when fewer than
    ``min_meters`` meters are available.
    """
    ccfg = cfg.get("der", {}).get("coincidence", {})
    min_meters = ccfg.get("min_meters", 2)

    _empty_cols = [
        "date", "coincidence_factor", "group_peak_kw",
        "sum_of_individual_peaks_kw", "coincident_peak_timestamp",
        "n_meters_reporting",
    ]
    empty = pd.DataFrame(columns=_empty_cols)

    pivoted = _pivot(interval_df_multi, meter_ids, value_col)
    available = list(pivoted.columns)

    if len(available) < min_meters:
        return empty

    date_index = pd.DatetimeIndex(pivoted.index).normalize()
    rows = []
    for d, grp in pivoted.groupby(date_index):
        group_demand = grp.sum(axis=1, min_count=1)
        if group_demand.isna().all():
            continue

        group_peak = float(group_demand.max())
        peak_ts = group_demand.idxmax()
        n_reporting = int((~grp.isna().all(axis=0)).sum())

        meter_peaks = {
            m: float(grp[m].max())
            for m in available
            if not grp[m].isna().all()
        }
        sum_ind = sum(meter_peaks.values())
        cf = group_peak / sum_ind if sum_ind > 0 else float("nan")

        rows.append({
            "date": d.date() if hasattr(d, "date") and callable(d.date) else d,
            "coincidence_factor": cf,
            "group_peak_kw": group_peak,
            "sum_of_individual_peaks_kw": sum_ind,
            "coincident_peak_timestamp": peak_ts,
            "n_meters_reporting": n_reporting,
        })

    return pd.DataFrame(rows) if rows else empty
