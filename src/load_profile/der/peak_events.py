"""
DER peak events (DER spec §5.5) — contiguous grouping of a boolean
"meets criterion" series with gap-bridging, distinct from ``events.PeakEvent``
(prominence/width-based, defined on the smoothed series). See ADR 011 for why
these coexist rather than one replacing the other.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd


@dataclass
class DERPeakEvent:
    event_id: str
    entity_id: str
    peak_definition: str
    start_time: pd.Timestamp
    end_time: pd.Timestamp
    duration_hours: float
    max_demand_kw: float
    mean_demand_kw: float
    min_demand_kw: float
    n_intervals: int
    duration_class: str  # "sustained" | "short"


def detect_der_peak_events(
    interval_df: pd.DataFrame,
    meets_criterion: pd.Series,
    entity_id: str,
    definition: str,
    cfg: dict[str, Any],
    value_col: str = "demand_kw",
) -> list[DERPeakEvent]:
    """
    Group qualifying intervals (``meets_criterion`` True) into contiguous events.

    Walks qualifying interval positions in order; starts a new event whenever
    the gap (count of intervening non-qualifying intervals) since the last
    qualifying interval **exceeds** ``der.peak_events.allowable_gap_intervals``;
    otherwise extends the current event to *include* the intervening
    non-qualifying intervals, so the event's own stats reflect the full
    contiguous span, not just the qualifying points.

    Zero qualifying intervals returns an empty list (not an error).
    """
    pcfg = cfg.get("der", {}).get("peak_events", {})
    allowable_gap = pcfg.get("allowable_gap_intervals", 0)
    sustained_threshold_hours = pcfg.get("sustained_threshold_hours", 1.0)

    mask = meets_criterion.reindex(interval_df.index).fillna(False).to_numpy(dtype=bool)
    qualifying_positions = np.flatnonzero(mask)
    if len(qualifying_positions) == 0:
        return []

    events: list[DERPeakEvent] = []
    seq = 1
    group_start_pos = qualifying_positions[0]
    prev_pos = qualifying_positions[0]

    def _flush(start_pos: int, end_pos: int) -> None:
        nonlocal seq
        span = interval_df.iloc[start_pos : end_pos + 1]
        vals = span[value_col]
        start_time = span.index[0]
        end_time = span.index[-1]
        duration_hours = (end_time - start_time).total_seconds() / 3600.0
        events.append(
            DERPeakEvent(
                event_id=f"{entity_id}_{definition}_{seq:04d}",
                entity_id=entity_id,
                peak_definition=definition,
                start_time=start_time,
                end_time=end_time,
                duration_hours=duration_hours,
                max_demand_kw=float(vals.max()),
                mean_demand_kw=float(vals.mean()),
                min_demand_kw=float(vals.min()),
                n_intervals=len(span),
                duration_class=(
                    "sustained" if duration_hours >= sustained_threshold_hours else "short"
                ),
            )
        )
        seq += 1

    for pos in qualifying_positions[1:]:
        gap = pos - prev_pos - 1  # count of intervening non-qualifying intervals
        if gap > allowable_gap:
            _flush(group_start_pos, prev_pos)
            group_start_pos = pos
        prev_pos = pos
    _flush(group_start_pos, prev_pos)

    return events
