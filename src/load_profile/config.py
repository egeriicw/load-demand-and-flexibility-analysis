"""Load and validate the TOML configuration file."""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any


def load_config(path: str | Path | None = None) -> dict[str, Any]:
    """
    Load analysis configuration from a TOML file.

    Parameters
    ----------
    path : str or Path, optional
        Path to the TOML file. Defaults to ``config/analysis_config.toml``
        relative to the project root (two levels above this file).

    Returns
    -------
    dict
        Nested configuration dictionary.
    """
    if path is None:
        here = Path(__file__).resolve().parent
        path = here.parent.parent / "config" / "analysis_config.toml"
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Configuration file not found: {path}")
    with open(path, "rb") as fh:
        cfg = tomllib.load(fh)
    return cfg


def cfg_get(cfg: dict, *keys: str, default: Any = None) -> Any:
    """Safely navigate a nested config dict."""
    node = cfg
    for k in keys:
        if not isinstance(node, dict):
            return default
        node = node.get(k, default)
    return node
