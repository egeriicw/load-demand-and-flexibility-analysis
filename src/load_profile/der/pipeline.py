"""
Multi-meter DER orchestration layer.

Calls the existing single-meter ``pipeline.run_pipeline`` once per configured
meter, tags/concatenates the results, then builds aggregated entity frames
for every resolved meter group and the portfolio. Never bypasses or forks
``run_pipeline`` — see ADR 006.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from ..data_ingestion import load_demand_data
from ..pipeline import run_pipeline
from .aggregation import build_entity_frame
from .meters import MeterSpec, build_meter_specs, resolve_meter_groups, resolve_portfolio

PORTFOLIO_ENTITY_ID = "Portfolio"


@dataclass
class DERResult:
    meter_tables: dict[str, dict[str, pd.DataFrame]] = field(default_factory=dict)
    """meter_id -> {interval_df, daily_df, ramp_df, peak_df} (run_pipeline's own output)."""

    entity_frames: dict[str, pd.DataFrame] = field(default_factory=dict)
    """entity_id (group name or "Portfolio") -> aggregated interval frame."""

    entity_meter_ids: dict[str, list[str]] = field(default_factory=dict)
    """entity_id -> resolved constituent meter_ids."""

    interval_df_multi: pd.DataFrame = field(default_factory=pd.DataFrame)
    """All meters' interval_df concatenated, tagged with meter_id."""


def _tag_meter_id(interval_df: pd.DataFrame, meter_id: str) -> pd.DataFrame:
    tagged = interval_df.copy()
    tagged["meter_id"] = meter_id
    return tagged


def run_der_pipeline(cfg: dict[str, Any], verbose: bool = True) -> DERResult:
    """
    Run the single-meter engine once per configured meter, then aggregate.

    Returns
    -------
    DERResult
        Per-meter tables (unchanged ``run_pipeline`` output), per-entity
        (group/portfolio) aggregated interval frames, and the resolved
        entity -> meter_ids mapping.
    """
    specs: list[MeterSpec] = build_meter_specs(cfg)

    meter_tables: dict[str, dict[str, pd.DataFrame]] = {}
    tagged_intervals: list[pd.DataFrame] = []

    for spec in specs:
        if verbose:
            print(f"[der.pipeline] Running meter '{spec.meter_id}'")
        df = load_demand_data(spec.source, cfg)
        result = run_pipeline(
            df, cfg, meter_id=spec.meter_id, building_id=spec.building_id, verbose=verbose,
        )
        meter_tables[spec.meter_id] = result
        tagged_intervals.append(_tag_meter_id(result["interval_df"], spec.meter_id))

    if tagged_intervals:
        interval_df_multi = pd.concat(tagged_intervals)
    else:
        interval_df_multi = pd.DataFrame(columns=["demand_kw", "meter_id"])
        interval_df_multi.index.name = "datetime"

    entity_meter_ids: dict[str, list[str]] = dict(resolve_meter_groups(cfg))
    entity_meter_ids[PORTFOLIO_ENTITY_ID] = resolve_portfolio(cfg)

    entity_frames = {
        entity_id: build_entity_frame(entity_id, meter_ids, interval_df_multi, cfg)
        for entity_id, meter_ids in entity_meter_ids.items()
    }

    return DERResult(
        meter_tables=meter_tables,
        entity_frames=entity_frames,
        entity_meter_ids=entity_meter_ids,
        interval_df_multi=interval_df_multi,
    )
