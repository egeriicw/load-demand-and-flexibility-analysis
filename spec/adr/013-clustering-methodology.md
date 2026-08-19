# ADR 013 — K-Means Clustering of Daily Profiles

**Date:** 2026-08-19
**Status:** DECIDED
**Related:** DER Opportunity Analysis integration, Phase 4

## Context

DER spec §5.7/§19-20 requires K-means clustering of daily demand profiles, computed
for **both** absolute (`demand_kw`) and peak-normalized (`normalized_demand`) values —
never just one. Auto-k via silhouette score (max_k=8, `<4` complete days forces k=1,
`<2` days is a failure), fixed `random_state=42` for reproducibility, complete-days-only
pivot into a `(day × interval_index)` matrix. `scikit-learn` was not previously a
dependency of this project.

A second naming-collision risk surfaced here, the same category as ADR 007's
`analysis_demand_kw` issue: DER spec §2.7's `normalized_demand` (`demand_kw /
daily_peak_demand_kw`, a simple peak-fraction) is **not** this codebase's
`states.compute_normalized_demand` (baseline-subtracted: `(D-baseline)/(peak-baseline)`,
can exceed 1.0). Reusing the existing function would have clustered the wrong
mathematical quantity.

## Decision

- Added `scikit-learn>=1.7.0` to `pyproject.toml` dependencies.
- New `src/load_profile/der/clustering.py`:
  - `peak_normalized_series(interval_df, value_col="demand_kw")` — DER's own §2.7
    definition, computed fresh (NOT calling `states.compute_normalized_demand`).
  - `build_daily_profile_matrix(interval_df, value_col)` — pivots complete days only
    (via the shared `der/_daily.py` completeness helper, see ADR 007's note extended
    here — factored out to avoid a third copy of the same logic after `load_shape.py`).
  - `select_k(matrix, max_k=8, random_state=42)` — `<4` days forces k=1; otherwise
    grid k=2..min(max_k, n_days-1), `KMeans(random_state=..., n_init=10)` per k, scored
    by `sklearn.metrics.silhouette_score`; a k collapsing to 1 effective cluster is
    skipped as unscoreable; falls back to k=1 if nothing is scoreable.
  - `cluster_daily_profiles(matrix, cfg)` — `<2` days returns `success=False`;
    otherwise fits the selected k and reports `cluster_id`, `cluster_size`,
    `percentage_of_days`, `representative_peak` (max of centroid),
    `within_cluster_variability` (mean of per-interval std across member days).
  - `cluster_entity_daily_profiles(interval_df, cfg)` — computes absolute AND
    normalized clustering together, returning both as a `dict`.
- New `src/load_profile/der/_daily.py`: `infer_resolution_minutes`,
  `expected_intervals_per_day`, `complete_day_dates` — factored out of `load_shape.py`
  (Phase 3) once `clustering.py` and `patterns.py` needed the identical "is this day
  complete" logic a third and fourth time. `load_shape.py` was refactored to import
  from here instead of keeping its own private copy.
- New config `[der.clustering]` (`max_k`, `random_state`).

## Rationale

- Factoring the day-completeness helper avoids the exact class of bug that would come
  from three slightly-diverging reimplementations of "expected intervals per day."
- Computing `normalized_demand` fresh here (rather than importing
  `states.compute_normalized_demand`) is the same discipline established in ADR 007:
  when a DER spec term and an existing codebase term share a name, verify the
  definitions match before reusing — they didn't here either.

## Consequences

- `select_k`'s grid search on very-low-variance/near-duplicate synthetic data produces
  `sklearn` `ConvergenceWarning`s (a k-candidate collapsing to fewer effective clusters
  than requested) — cosmetic, not a correctness issue; the resulting k is still scored
  correctly (or skipped) either way. `tests/der/test_clustering.py` suppresses this
  specific warning class since its fixtures deliberately use few distinct day-shapes.
- Anyone adding a fourth per-day "is this day complete" reimplementation anywhere in
  `der/` should use `der._daily` instead.
