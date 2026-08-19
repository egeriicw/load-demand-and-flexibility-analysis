from __future__ import annotations

import pytest

from load_profile.der.meters import (
    build_meter_specs,
    resolve_meter_groups,
    resolve_portfolio,
)


class TestBuildMeterSpecs:
    def test_builds_one_spec_per_meter(self, grouped_cfg):
        specs = build_meter_specs(grouped_cfg)
        assert [s.meter_id for s in specs] == ["M1", "M2", "M3"]

    def test_empty_meters_is_empty_list(self, cfg):
        assert build_meter_specs(cfg) == []


class TestResolveMeterGroups:
    def test_flat_group(self, grouped_cfg):
        groups = resolve_meter_groups(grouped_cfg)
        assert groups["building_a"] == ["M1", "M2"]

    def test_hierarchical_group_unions_child(self, cfg):
        cfg["meters"] = [{"meter_id": m} for m in ("M1", "M2", "M3")]
        cfg["meter_groups"] = [
            {"name": "child", "meters": ["M3"], "child_groups": []},
            {"name": "parent", "meters": ["M1"], "child_groups": ["child"]},
        ]
        groups = resolve_meter_groups(cfg)
        assert groups["parent"] == ["M1", "M3"]
        assert groups["child"] == ["M3"]

    def test_overlapping_membership_allowed(self, cfg):
        cfg["meters"] = [{"meter_id": m} for m in ("M1", "M2")]
        cfg["meter_groups"] = [
            {"name": "g1", "meters": ["M1", "M2"], "child_groups": []},
            {"name": "g2", "meters": ["M2"], "child_groups": []},
        ]
        groups = resolve_meter_groups(cfg)
        assert "M2" in groups["g1"] and "M2" in groups["g2"]

    def test_dedup_and_sorted(self, cfg):
        cfg["meters"] = [{"meter_id": m} for m in ("M1", "M2", "M3")]
        cfg["meter_groups"] = [
            {"name": "child", "meters": ["M2"], "child_groups": []},
            {"name": "parent", "meters": ["M2", "M1", "M3"], "child_groups": ["child"]},
        ]
        groups = resolve_meter_groups(cfg)
        assert groups["parent"] == ["M1", "M2", "M3"]

    def test_cyclic_group_raises(self, cfg):
        cfg["meters"] = []
        cfg["meter_groups"] = [
            {"name": "a", "meters": [], "child_groups": ["b"]},
            {"name": "b", "meters": [], "child_groups": ["a"]},
        ]
        with pytest.raises(ValueError, match="[Cc]ycl"):
            resolve_meter_groups(cfg)

    def test_empty_groups_returns_empty_dict(self, cfg):
        assert resolve_meter_groups(cfg) == {}


class TestResolvePortfolio:
    def test_all_meters_minus_excluded(self, grouped_cfg):
        assert resolve_portfolio(grouped_cfg) == ["M1", "M2"]

    def test_no_exclusions_returns_all(self, two_meter_cfg):
        assert resolve_portfolio(two_meter_cfg) == ["M1", "M2"]

    def test_no_meters_returns_empty(self, cfg):
        assert resolve_portfolio(cfg) == []
