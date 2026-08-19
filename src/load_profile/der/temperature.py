"""
External temperature ingestion, nearest-timestamp merge, and banding
(DER spec §5.2, partial — the change-point regression model family is
Phase 3, see ``der.change_point``).

Temperature is site-level, not per-meter: ``merge_temperature`` joins onto
whatever DataFrame's own DatetimeIndex it's given (an entity frame, or a
single meter's ``interval_df``) without any meter-specific fan-out.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from ..data_ingestion import _parse_timestamps

DEFAULT_BAND_BOUNDARIES: list[float] = [32, 50, 65, 80, 90]


def load_temperature_data(source: str | Path | pd.DataFrame, cfg: dict[str, Any]) -> pd.DataFrame:
    """
    Load external temperature data.

    Parameters
    ----------
    source : str, Path, or DataFrame
        CSV path or already-loaded DataFrame.
    cfg : dict
        Full configuration dictionary. Reads
        ``der.temperature.column_mapping.{timestamp,temperature_f}`` (source
        column names, default ``"datetime"``/``"temperature_f"``) and
        ``timezone.default_tz`` for naive-timestamp localization.

    Returns
    -------
    DataFrame
        Single ``temperature_f`` column, tz-aware DatetimeIndex named
        ``datetime``, sorted ascending.
    """
    tcfg = cfg.get("der", {}).get("temperature", {})
    mapping = tcfg.get("column_mapping", {})
    ts_col = mapping.get("timestamp", "datetime")
    temp_col = mapping.get("temperature_f", "temperature_f")
    tz_default = cfg.get("timezone", {}).get("default_tz", "UTC")

    df = pd.read_csv(source) if isinstance(source, (str, Path)) else source.copy()

    if ts_col not in df.columns:
        raise ValueError(f"temperature timestamp column '{ts_col}' not found in data")
    if temp_col not in df.columns:
        raise ValueError(f"temperature column '{temp_col}' not found in data")

    df = df.rename(columns={ts_col: "datetime", temp_col: "temperature_f"})
    df["datetime"] = _parse_timestamps(df["datetime"], tz_default)
    df = df.set_index("datetime").sort_index()
    return df[["temperature_f"]]


def merge_temperature(
    interval_df: pd.DataFrame,
    temp_df: pd.DataFrame,
    cfg: dict[str, Any],
) -> pd.DataFrame:
    """
    Nearest-timestamp join of ``temperature_f`` onto ``interval_df``.

    Parameters
    ----------
    interval_df : DataFrame
        tz-aware DatetimeIndex. May already have a ``temperature_f`` column
        (e.g. supplied inline in the source data).
    temp_df : DataFrame
        Output of ``load_temperature_data`` (single ``temperature_f`` column,
        tz-aware DatetimeIndex).
    cfg : dict
        Reads ``der.temperature.join_tolerance_minutes`` (nearest-match
        window; unset = unlimited) and ``der.temperature.override_existing``
        (bool, default False: external values only fill *missing*
        temperature_f; True = external wins wherever a match is found within
        tolerance, falling back to the existing value outside tolerance).

    Returns
    -------
    DataFrame
        ``interval_df`` with a single ``temperature_f`` column reflecting
        the merge policy above.
    """
    tcfg = cfg.get("der", {}).get("temperature", {})
    tol_min = tcfg.get("join_tolerance_minutes")
    override_existing = tcfg.get("override_existing", False)

    left = interval_df.sort_index()
    right = temp_df[["temperature_f"]].sort_index().rename(
        columns={"temperature_f": "_external_temperature_f"}
    )
    tolerance = pd.Timedelta(minutes=tol_min) if tol_min is not None else None

    merged = pd.merge_asof(
        left, right, left_index=True, right_index=True,
        direction="nearest", tolerance=tolerance,
    )

    if "temperature_f" not in merged.columns:
        merged["temperature_f"] = merged["_external_temperature_f"]
    elif override_existing:
        merged["temperature_f"] = merged["_external_temperature_f"].where(
            merged["_external_temperature_f"].notna(), merged["temperature_f"]
        )
    else:
        merged["temperature_f"] = merged["temperature_f"].where(
            merged["temperature_f"].notna(), merged["_external_temperature_f"]
        )

    return merged.drop(columns=["_external_temperature_f"])


def band_temperature(df: pd.DataFrame, cfg: dict[str, Any]) -> pd.DataFrame:
    """
    Bin ``temperature_f`` into configurable bands via ``pd.cut``.

    ``der.temperature.bands.boundaries`` (default ``[32, 50, 65, 80, 90]``)
    produces bins ``(-inf,32], (32,50], ..., (90,inf)`` labeled
    ``"below-32"``, ``"32-50"``, ..., ``"90-above"``. NaN temperature -> NaN
    band.
    """
    tcfg = cfg.get("der", {}).get("temperature", {})
    boundaries = tcfg.get("bands", {}).get("boundaries", DEFAULT_BAND_BOUNDARIES)
    edges = [-np.inf, *boundaries, np.inf]

    labels = []
    for i in range(len(edges) - 1):
        lo, hi = edges[i], edges[i + 1]
        if lo == -np.inf:
            labels.append(f"below-{int(hi)}")
        elif hi == np.inf:
            labels.append(f"{int(lo)}-above")
        else:
            labels.append(f"{int(lo)}-{int(hi)}")

    out = df.copy()
    out["temperature_band"] = pd.cut(out["temperature_f"], bins=edges, labels=labels)
    return out
