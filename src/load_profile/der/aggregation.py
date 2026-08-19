"""
Entity (meter group / portfolio) load aggregation.

All aggregation across meters is **summation, never averaging** — an entity's
demand at a timestamp is the sum of its constituent meters' interval-level
``demand_kw`` (the quality-cascaded observed-else-interpolated-else-NaN
value; see ``time_series.regularize``'s ``data_quality_flag`` column for the
per-interval provenance this value already reflects).

Partial coverage stays visible: ``n_meters_reporting`` is attached alongside
the sum, and an all-non-reporting timestamp for the given meter subset stays
NaN (via pandas' native ``sum(min_count=...)`` semantics) rather than
silently becoming a false zero.
"""

from __future__ import annotations

from typing import Any

import pandas as pd


def aggregate_entity(
    interval_df_multi: pd.DataFrame,
    meter_ids: list[str],
    min_count: int = 1,
) -> pd.DataFrame:
    """
    Sum ``demand_kw`` across ``meter_ids`` at each timestamp.

    Parameters
    ----------
    interval_df_multi : DataFrame
        Concatenated per-meter interval tables (as produced by
        ``der.pipeline.run_der_pipeline``), tz-aware DatetimeIndex, with
        ``demand_kw`` and ``meter_id`` columns.
    meter_ids : list[str]
        The constituent meters of the entity being aggregated.
    min_count : int
        Minimum number of non-null contributing meters required for a
        timestamp's sum to be non-NaN (pandas ``GroupBy.sum(min_count=...)``
        semantics — a timestamp where fewer than ``min_count`` meters report
        stays NaN rather than becoming a false 0).

    Returns
    -------
    DataFrame indexed by timestamp (name ``datetime``) with columns:
        ``demand_kw``          – summed demand across reporting meters
        ``n_meters_reporting``  – count of meters with non-null demand_kw
    """
    empty = pd.DataFrame(
        {"demand_kw": pd.Series(dtype=float), "n_meters_reporting": pd.Series(dtype=int)}
    )
    empty.index.name = "datetime"

    if not meter_ids or interval_df_multi.empty:
        return empty

    subset = interval_df_multi[interval_df_multi["meter_id"].isin(meter_ids)]
    if subset.empty:
        return empty

    grouped = subset.groupby(subset.index)["demand_kw"]
    demand_kw = grouped.sum(min_count=min_count)
    n_meters_reporting = grouped.count().astype(int)

    out = pd.DataFrame({"demand_kw": demand_kw, "n_meters_reporting": n_meters_reporting})
    out.index.name = "datetime"
    return out.sort_index()


def build_entity_frame(
    entity_id: str,
    meter_ids: list[str],
    interval_df_multi: pd.DataFrame,
    cfg: dict[str, Any],
) -> pd.DataFrame:
    """
    Wrap ``aggregate_entity`` and stamp the result with ``entity_id``.

    Note: aggregate-level ``is_observed``/``is_interpolated`` quality flags
    are deliberately not derived here — those booleans describe a single
    meter's provenance and don't have a well-defined cross-meter aggregate
    meaning (one meter could be observed while another is interpolated at
    the same timestamp). ``n_meters_reporting`` is the aggregate's own
    partial-coverage signal instead. ``is_missing`` is still meaningful at
    the aggregate level (the sum itself is NaN) and is included.
    """
    min_count = cfg.get("der", {}).get("aggregation", {}).get("min_count", 1)
    agg = aggregate_entity(interval_df_multi, meter_ids, min_count=min_count)
    agg = agg.copy()
    agg["entity_id"] = entity_id
    agg["is_missing"] = agg["demand_kw"].isna()
    return agg
