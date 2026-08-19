"""
Multi-meter configuration model: individual meters, groups, and portfolio.

Groups may be flat (direct ``meters`` only), hierarchical (``child_groups``
only), or overlapping (a meter or group may appear under multiple parents).
Resolution is recursive with memoization; cycles are rejected both by
config-schema validation (``config_schema.validate_config``) and defensively
here if a cycle is reached directly.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from ..config_schema import _detect_meter_group_cycles


@dataclass
class MeterSpec:
    meter_id: str
    display_name: str | None = None
    building_id: str | None = None
    source: str | Path | pd.DataFrame | None = None


def build_meter_specs(cfg: dict[str, Any]) -> list[MeterSpec]:
    """Build ``MeterSpec`` objects from the ``[[meters]]`` config array."""
    return [
        MeterSpec(
            meter_id=m["meter_id"],
            display_name=m.get("display_name"),
            building_id=m.get("building_id"),
            source=m.get("source"),
        )
        for m in cfg.get("meters", [])
    ]


def resolve_meter_groups(cfg: dict[str, Any]) -> dict[str, list[str]]:
    """
    Recursively resolve every ``[[meter_groups]]`` entry to its full,
    deduplicated, sorted set of leaf meter_ids.

    A group's resolved membership is its own ``meters`` plus the union of
    its ``child_groups``' *resolved* membership (never averaged/deduped
    away — a meter reachable via multiple parents simply appears in each
    parent's resolved set).
    """
    groups = {g["name"]: g for g in cfg.get("meter_groups", [])}
    child_map = {name: g.get("child_groups", []) for name, g in groups.items()}

    cycle = _detect_meter_group_cycles(child_map)
    if cycle:
        raise ValueError(f"Cyclic meter_groups reference: {' -> '.join(cycle)}")

    memo: dict[str, list[str]] = {}

    def resolve(name: str, stack: tuple[str, ...] = ()) -> list[str]:
        if name in memo:
            return memo[name]
        if name in stack:
            raise ValueError(
                f"Cyclic meter_groups reference detected while resolving "
                f"'{name}' (path: {' -> '.join(stack + (name,))})"
            )
        group = groups.get(name)
        if group is None:
            raise ValueError(f"Unknown meter group referenced: '{name}'")

        members = set(group.get("meters", []))
        for child_name in group.get("child_groups", []):
            members |= set(resolve(child_name, stack + (name,)))

        result = sorted(members)
        memo[name] = result
        return result

    return {name: resolve(name) for name in groups}


def resolve_portfolio(cfg: dict[str, Any]) -> list[str]:
    """Portfolio = all configured ``[[meters]]`` minus ``[portfolio].excluded_meters``."""
    all_meters = {m["meter_id"] for m in cfg.get("meters", [])}
    excluded = set(cfg.get("portfolio", {}).get("excluded_meters", []))
    return sorted(all_meters - excluded)
