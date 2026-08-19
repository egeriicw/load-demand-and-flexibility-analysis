"""Shared fixtures for the DER (multi-meter) test suite.

Composes on top of the root ``tests/conftest.py`` (``base_cfg``/``cfg``
fixtures) rather than duplicating it.
"""

from __future__ import annotations

import pytest

from load_profile.synthetic import generate_synthetic_day


def _meter_df(scenario="classic_morning_startup", date="2024-01-15", **kwargs):
    df, _ = generate_synthetic_day(scenario, date=date, **kwargs)
    return df.reset_index()


@pytest.fixture
def two_meter_cfg(cfg):
    """cfg with two independent meters, both DataFrame-sourced (no group/portfolio exclusions)."""
    cfg["meters"] = [
        {"meter_id": "M1", "building_id": "B1", "source": _meter_df()},
        {"meter_id": "M2", "building_id": "B1", "source": _meter_df()},
    ]
    return cfg


@pytest.fixture
def grouped_cfg(cfg):
    """cfg with 3 meters, one flat group, one portfolio exclusion."""
    cfg["meters"] = [
        {"meter_id": "M1", "building_id": "B1", "source": _meter_df()},
        {"meter_id": "M2", "building_id": "B1", "source": _meter_df()},
        {"meter_id": "M3", "building_id": "B2", "source": _meter_df()},
    ]
    cfg["meter_groups"] = [
        {"name": "building_a", "meters": ["M1", "M2"], "child_groups": []},
    ]
    cfg["portfolio"] = {"excluded_meters": ["M3"]}
    return cfg
