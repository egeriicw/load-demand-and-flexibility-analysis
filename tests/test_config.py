from __future__ import annotations

import pytest

from load_profile.config import cfg_get, load_config


def test_load_config_default_path():
    cfg = load_config()
    assert "input" in cfg
    assert "baseline" in cfg


def test_load_config_explicit_path(tmp_path):
    toml_text = """
    [input]
    demand_col = "kw"
    """
    p = tmp_path / "custom.toml"
    p.write_text(toml_text)
    cfg = load_config(p)
    assert cfg["input"]["demand_col"] == "kw"


def test_load_config_missing_file_raises(tmp_path):
    missing = tmp_path / "does_not_exist.toml"
    with pytest.raises(FileNotFoundError):
        load_config(missing)


def test_cfg_get_nested_present():
    cfg = {"a": {"b": {"c": 42}}}
    assert cfg_get(cfg, "a", "b", "c") == 42


def test_cfg_get_missing_key_returns_default():
    cfg = {"a": {"b": {}}}
    assert cfg_get(cfg, "a", "b", "c") is None
    assert cfg_get(cfg, "a", "b", "c", default="fallback") == "fallback"


def test_cfg_get_non_dict_intermediate_returns_default():
    cfg = {"a": 5}
    assert cfg_get(cfg, "a", "b", default="fallback") == "fallback"


def test_cfg_get_empty_keys_returns_whole_dict():
    cfg = {"a": 1}
    assert cfg_get(cfg) == cfg
