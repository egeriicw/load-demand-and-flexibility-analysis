from __future__ import annotations

import pytest

from load_profile.config import load_config
from load_profile.config_schema import (
    ConfigValidationError,
    _detect_meter_group_cycles,
    validate_config,
)


class TestValidateConfig:
    def test_real_config_validates_cleanly(self, base_cfg):
        report = validate_config(base_cfg)
        assert report.has_errors is False
        assert report.is_valid is True

    def test_bad_input_unit_is_error(self, cfg):
        cfg["input"]["unit"] = "BTU"
        report = validate_config(cfg)
        assert report.has_errors is True
        assert any(i.path == "input.unit" for i in report.issues)

    def test_bad_negative_demand_severity_is_error(self, cfg):
        cfg["data_quality"]["negative_demand_severity"] = "CRITICAL"
        report = validate_config(cfg)
        assert report.has_errors is True

    def test_out_of_range_completeness_fraction_is_error(self, cfg):
        cfg["data_quality"]["min_completeness_fraction"] = 1.5
        report = validate_config(cfg)
        assert report.has_errors is True

    def test_weight_sum_mismatch_is_warning_not_error(self, cfg):
        cfg["start_detection"]["weight_ramp_magnitude"] = 0.99
        report = validate_config(cfg)
        assert report.has_errors is False
        assert any(i.severity == "WARNING" for i in report.issues)

    def test_non_dict_config_is_error(self):
        report = validate_config([])  # type: ignore[arg-type]
        assert report.has_errors is True


class TestLoadConfigValidation:
    def test_load_config_validates_by_default(self):
        cfg = load_config()
        assert isinstance(cfg, dict)

    def test_load_config_raises_on_invalid(self, tmp_path):
        bad = tmp_path / "bad.toml"
        bad.write_text('[input]\nunit = "BTU"\n')
        with pytest.raises(ConfigValidationError):
            load_config(bad)

    def test_load_config_skip_validation(self, tmp_path):
        bad = tmp_path / "bad.toml"
        bad.write_text('[input]\nunit = "BTU"\n')
        cfg = load_config(bad, validate=False)
        assert cfg["input"]["unit"] == "BTU"


class TestDetectMeterGroupCycles:
    def test_acyclic_graph_returns_empty(self):
        assert _detect_meter_group_cycles({"a": ["b"], "b": ["c"], "c": []}) == []

    def test_self_reference_is_a_cycle(self):
        cycle = _detect_meter_group_cycles({"a": ["a"]})
        assert cycle == ["a", "a"]

    def test_indirect_cycle_detected(self):
        cycle = _detect_meter_group_cycles({"a": ["b"], "b": ["c"], "c": ["a"]})
        assert set(cycle) == {"a", "b", "c"}

    def test_unknown_child_reference_ignored_not_a_cycle(self):
        assert _detect_meter_group_cycles({"a": ["unknown_group"]}) == []
