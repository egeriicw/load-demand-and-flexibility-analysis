"""
DER output layout (DER spec §5.10/§23) — assembles the canonical multi-meter
output tables from a ``DERResult`` and optionally exports them to CSV.

Five tables are always attempted; tables with no underlying data remain empty
DataFrames (never raise). Export writes only non-empty tables for which a path
is configured under ``[der.output]``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd

from .pipeline import DERResult


@dataclass
class DEROutputBundle:
    """Canonical DER output tables, ready for inspection or CSV export.

    All fields default to an empty DataFrame — callers check ``.empty`` before
    using a table rather than testing for ``None``.
    """

    meter_interval: pd.DataFrame = field(default_factory=pd.DataFrame)
    """One row per (meter, timestamp). Columns: ``datetime``, ``meter_id``,
    ``demand_kw``, ``demand_kw_raw``, ``data_quality_flag``, and any additional
    columns present in ``DERResult.interval_df_multi``."""

    entity_interval: pd.DataFrame = field(default_factory=pd.DataFrame)
    """One row per (entity, timestamp). Columns: ``datetime``, ``entity_id``,
    ``demand_kw``, ``n_meters_reporting``, ``is_missing``, plus calendar columns
    (``date``, ``season``, ``day_type``, etc.) when Phase 2 enrichment ran."""

    entity_daily: pd.DataFrame = field(default_factory=pd.DataFrame)
    """One row per (entity, date). Columns: ``entity_id``, ``date``,
    ``is_complete_day``, ``daily_energy_kwh``, ``maximum_demand_kw``,
    ``peak_time_minutes``, plus TOD segment columns (``morning_peak_kw``, etc.)
    when Phase 2 enrichment ran."""

    study_coincidence: pd.DataFrame = field(default_factory=pd.DataFrame)
    """One row per entity. Columns: ``entity_id``, ``success``,
    ``coincidence_factor``, ``group_peak_kw``, ``sum_of_individual_peaks_kw``,
    ``coincident_peak_timestamp``, ``n_meters``."""

    daily_coincidence: pd.DataFrame = field(default_factory=pd.DataFrame)
    """One row per (entity, date). Columns: ``entity_id``, ``date``,
    ``coincidence_factor``, ``group_peak_kw``, ``sum_of_individual_peaks_kw``,
    ``coincident_peak_timestamp``, ``n_meters_reporting``."""


# ---------------------------------------------------------------------------
# Private assembly helpers
# ---------------------------------------------------------------------------

def _build_meter_interval(der_result: DERResult) -> pd.DataFrame:
    df = der_result.interval_df_multi
    if df.empty:
        return pd.DataFrame()
    out = df.copy()
    out.index.name = "datetime"
    return out.reset_index()


def _stack_entity_frames(frames: dict[str, pd.DataFrame]) -> pd.DataFrame:
    parts = []
    for entity_id, frame in frames.items():
        if frame.empty:
            continue
        tagged = frame.copy()
        tagged.insert(0, "entity_id", entity_id)
        tagged.index.name = "datetime"
        parts.append(tagged.reset_index())
    return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()


def _build_entity_daily(der_result: DERResult, cfg: dict[str, Any]) -> pd.DataFrame:
    from .patterns import build_daily_summary

    parts = []
    for entity_id, frame in der_result.entity_frames.items():
        if frame.empty:
            continue
        summary = build_daily_summary(frame, value_col="demand_kw")
        summary.insert(0, "entity_id", entity_id)

        tod = der_result.entity_tod_frames.get(entity_id)
        if tod is not None and not tod.empty:
            summary = summary.merge(tod, on="date", how="left")

        parts.append(summary)
    return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()


def _build_study_coincidence(der_result: DERResult, cfg: dict[str, Any]) -> pd.DataFrame:
    from .coincidence import compute_coincidence_factor

    rows = []
    for entity_id, meter_ids in der_result.entity_meter_ids.items():
        r = compute_coincidence_factor(der_result.interval_df_multi, meter_ids, cfg)
        rows.append({
            "entity_id": entity_id,
            "success": r.success,
            "coincidence_factor": r.coincidence_factor,
            "group_peak_kw": r.group_peak_kw,
            "sum_of_individual_peaks_kw": r.sum_of_individual_peaks_kw,
            "coincident_peak_timestamp": r.coincident_peak_timestamp,
            "n_meters": r.n_meters,
        })
    return pd.DataFrame(rows) if rows else pd.DataFrame()


def _build_daily_coincidence(der_result: DERResult, cfg: dict[str, Any]) -> pd.DataFrame:
    from .coincidence import compute_daily_coincidence

    parts = []
    for entity_id, meter_ids in der_result.entity_meter_ids.items():
        df = compute_daily_coincidence(der_result.interval_df_multi, meter_ids, cfg)
        if not df.empty:
            df = df.copy()
            df.insert(0, "entity_id", entity_id)
            parts.append(df)
    return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def build_der_output(der_result: DERResult, cfg: dict[str, Any]) -> DEROutputBundle:
    """
    Assemble the five canonical DER output tables from a ``DERResult``.

    ``entity_interval`` uses Phase 2 calendar-enriched frames when available
    (``DERResult.entity_calendar_frames``), falling back to the base entity
    frames. ``entity_daily`` joins per-day pattern summary with TOD segment
    features from ``DERResult.entity_tod_frames`` when populated. Coincidence
    tables are computed here (they are not stored on ``DERResult``); entities
    with fewer than ``[der.coincidence].min_meters`` meters are represented
    with ``success=False`` in ``study_coincidence`` and omitted from
    ``daily_coincidence``.
    """
    interval_source = der_result.entity_calendar_frames or der_result.entity_frames

    return DEROutputBundle(
        meter_interval=_build_meter_interval(der_result),
        entity_interval=_stack_entity_frames(interval_source),
        entity_daily=_build_entity_daily(der_result, cfg),
        study_coincidence=_build_study_coincidence(der_result, cfg),
        daily_coincidence=_build_daily_coincidence(der_result, cfg),
    )


def export_der_output(
    bundle: DEROutputBundle, cfg: dict[str, Any]
) -> dict[str, Path]:
    """
    Write each non-empty table in ``bundle`` to its configured CSV path.

    Paths are read from ``[der.output]``:
      - ``meter_interval_csv``
      - ``entity_interval_csv``
      - ``entity_daily_csv``
      - ``study_coincidence_csv``
      - ``daily_coincidence_csv``

    Parent directories are created automatically. Tables without a configured
    path (key absent or empty string) are silently skipped.

    Returns
    -------
    dict[str, Path]
        Mapping of table name to the ``Path`` that was written, for tables
        that were actually exported.
    """
    ocfg = cfg.get("der", {}).get("output", {})
    table_keys = {
        "meter_interval": "meter_interval_csv",
        "entity_interval": "entity_interval_csv",
        "entity_daily": "entity_daily_csv",
        "study_coincidence": "study_coincidence_csv",
        "daily_coincidence": "daily_coincidence_csv",
    }

    written: dict[str, Path] = {}
    for table_name, cfg_key in table_keys.items():
        path_str = ocfg.get(cfg_key)
        if not path_str:
            continue
        df: pd.DataFrame = getattr(bundle, table_name)
        if df.empty:
            continue
        path = Path(path_str)
        path.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(path, index=False)
        written[table_name] = path

    return written
