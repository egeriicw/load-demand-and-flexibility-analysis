"""
K-means clustering of daily demand profiles (DER spec §5.7/§19-20) —
statistical, not causal. Both absolute (``demand_kw``) and peak-normalized
(``normalized_demand``) clustering are computed, never just one.

Note: DER's ``normalized_demand`` (§2.7: ``demand_kw / daily_peak_demand_kw``,
NaN if the day's peak is 0/NaN) is a simple **peak-fraction** normalization —
a different thing from this codebase's ``states.compute_normalized_demand``
(baseline-subtracted: ``(D-baseline)/(peak-baseline)``). This module computes
its own peak-normalized series rather than reusing that function; see ADR 013
(the same category of naming-collision risk flagged in ADR 007 for
``analysis_demand_kw``).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.metrics import silhouette_score

from ._daily import complete_day_dates


@dataclass
class ClusteringResult:
    success: bool
    k: int = 0
    labels: dict[Any, int] = field(default_factory=dict)
    """date -> cluster_id, for complete days only."""
    cluster_centers: dict[int, np.ndarray] = field(default_factory=dict)
    """cluster_id -> centroid array (length = interval count per day)."""
    silhouette_scores: dict[int, float] = field(default_factory=dict)
    """k -> silhouette score, for every k tried during auto-k search."""
    clusters: pd.DataFrame = field(default_factory=pd.DataFrame)
    """One row per cluster: cluster_id, cluster_size, percentage_of_days,
    representative_peak, within_cluster_variability."""


def peak_normalized_series(interval_df: pd.DataFrame, value_col: str = "demand_kw") -> pd.Series:
    """DER spec §2.7 ``normalized_demand`` — NOT ``states.compute_normalized_demand``."""
    date = interval_df.index.normalize()
    demand = interval_df[value_col]
    daily_peak = demand.groupby(date).transform("max")
    normalized = demand / daily_peak
    normalized = normalized.where(daily_peak.notna() & (daily_peak != 0))
    return normalized.rename("normalized_demand")


def build_daily_profile_matrix(interval_df: pd.DataFrame, value_col: str = "demand_kw") -> pd.DataFrame:
    """
    Pivot complete days only into a (day x interval_index) matrix.

    Returns an empty DataFrame (no error) if no day is complete.
    """
    complete_dates = complete_day_dates(interval_df, value_col=value_col)
    if len(complete_dates) == 0:
        return pd.DataFrame()

    date = interval_df.index.normalize()
    tmp = pd.DataFrame(
        {"date": date, "value": interval_df[value_col].to_numpy()}, index=interval_df.index
    )
    tmp["interval_index"] = tmp.groupby("date").cumcount()
    complete = tmp[tmp["date"].isin(complete_dates)]

    matrix = complete.pivot(index="date", columns="interval_index", values="value")
    return matrix.sort_index()


def select_k(
    matrix: pd.DataFrame, max_k: int = 8, random_state: int = 42
) -> tuple[int, dict[int, float]]:
    """
    Auto-k via silhouette score.

    Fewer than 4 complete days forces k=1 (too little data to cluster
    meaningfully). Otherwise tries k = 2..min(max_k, n_days-1), scoring each
    by silhouette (a k that collapses to 1 effective cluster is skipped as
    unscoreable), and keeps the k with the highest score. If nothing is
    scoreable, falls back to k=1.
    """
    n_days = len(matrix)
    if n_days < 4:
        return 1, {}

    scores: dict[int, float] = {}
    upper = min(max_k, n_days - 1)
    for k in range(2, upper + 1):
        labels = KMeans(n_clusters=k, random_state=random_state, n_init=10).fit_predict(
            matrix.to_numpy()
        )
        if len(set(labels)) < 2:
            continue
        scores[k] = float(silhouette_score(matrix.to_numpy(), labels))

    if not scores:
        return 1, scores
    best_k = max(scores, key=scores.get)
    return best_k, scores


def cluster_daily_profiles(matrix: pd.DataFrame, cfg: dict[str, Any]) -> ClusteringResult:
    """
    K-means cluster a (day x interval_index) matrix (``build_daily_profile_matrix`` output).

    ``random_state`` is fixed (config-driven, default 42) — clustering is
    reproducible. Fewer than 2 complete days returns ``success=False`` (not
    an error).
    """
    ccfg = cfg.get("der", {}).get("clustering", {})
    max_k = ccfg.get("max_k", 8)
    random_state = ccfg.get("random_state", 42)

    n_days = len(matrix)
    if n_days < 2:
        return ClusteringResult(success=False)

    k, silhouette_scores = select_k(matrix, max_k=max_k, random_state=random_state)

    km = KMeans(n_clusters=k, random_state=random_state, n_init=10)
    values = matrix.to_numpy()
    labels = km.fit_predict(values)

    labels_by_date = dict(zip(matrix.index, labels))
    centers = {i: km.cluster_centers_[i] for i in range(k)}

    rows = []
    for cluster_id in range(k):
        member_mask = labels == cluster_id
        cluster_size = int(member_mask.sum())
        centroid = centers[cluster_id]
        representative_peak = float(np.nanmax(centroid))
        if cluster_size > 1:
            member_values = values[member_mask]
            within_cluster_variability = float(np.nanmean(np.nanstd(member_values, axis=0)))
        else:
            within_cluster_variability = 0.0
        rows.append({
            "cluster_id": cluster_id,
            "cluster_size": cluster_size,
            "percentage_of_days": 100.0 * cluster_size / n_days,
            "representative_peak": representative_peak,
            "within_cluster_variability": within_cluster_variability,
        })

    return ClusteringResult(
        success=True, k=k, labels=labels_by_date, cluster_centers=centers,
        silhouette_scores=silhouette_scores, clusters=pd.DataFrame(rows),
    )


def cluster_entity_daily_profiles(
    interval_df: pd.DataFrame, cfg: dict[str, Any], value_col: str = "demand_kw"
) -> dict[str, ClusteringResult]:
    """Compute both absolute and peak-normalized clustering — never just one."""
    enriched = interval_df.copy()
    enriched["normalized_demand"] = peak_normalized_series(enriched, value_col=value_col)

    absolute_matrix = build_daily_profile_matrix(enriched, value_col=value_col)
    normalized_matrix = build_daily_profile_matrix(enriched, value_col="normalized_demand")

    return {
        "absolute": cluster_daily_profiles(absolute_matrix, cfg),
        "normalized": cluster_daily_profiles(normalized_matrix, cfg),
    }
