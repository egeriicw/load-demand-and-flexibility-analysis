"""
Demand classification families (DER spec §5.3) — threshold, percentile, and
rank, kept as independent, non-collapsing boolean columns. Contrast with
``classification.classify_day``'s single mutually-exclusive ``primary_class``:
these three families are never merged into one generic "is_peak" flag.
"""

from __future__ import annotations

from typing import Any

import pandas as pd


def _fmt_num(x: float) -> str:
    """Column-name-safe number formatting: 100 -> "100", 0.99 -> "0_99"."""
    if float(x).is_integer():
        return str(int(x))
    return str(x).replace(".", "_").replace("-", "neg")


def classify_demand_families(
    interval_df: pd.DataFrame,
    cfg: dict[str, Any],
    value_col: str = "demand_kw",
) -> pd.DataFrame:
    """
    Add independent threshold / percentile / rank boolean column families.

    - ``meets_threshold_<kw>`` per configured ``der.demand_classification.thresholds_kw``:
      ``demand_kw >= threshold``.
    - ``top_pct_<pp>`` per configured ``.top_percentiles`` (e.g. 0.99, 0.95):
      ``demand_kw >= quantile(p)`` (quantile computed over the full series passed in).
    - ``top_rank_<n>`` per configured ``.top_n_hours``: the N highest-demand
      intervals (``rank(method="first", ascending=False) <= n``).
    """
    dcfg = cfg.get("der", {}).get("demand_classification", {})
    thresholds_kw = dcfg.get("thresholds_kw", [])
    top_percentiles = dcfg.get("top_percentiles", [])
    top_n_hours = dcfg.get("top_n_hours", [])

    out = interval_df.copy()
    demand = out[value_col]

    for kw in thresholds_kw:
        out[f"meets_threshold_{_fmt_num(kw)}"] = demand >= kw

    for p in top_percentiles:
        q = demand.quantile(p)
        out[f"top_pct_{_fmt_num(p)}"] = demand >= q

    for n in top_n_hours:
        ranks = demand.rank(method="first", ascending=False)
        out[f"top_rank_{n}"] = ranks <= n

    return out
