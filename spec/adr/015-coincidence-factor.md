# ADR 015 — Meter Coincidence Factor Definition

**Date:** 2026-08-19
**Status:** DECIDED
**Related:** DER Opportunity Analysis integration, Phase 5

## Context

DER spec §5.9/§22 requires meter coincidence analysis: measuring how often (and how
strongly) multiple meters within an entity peak simultaneously. The standard
power-systems metric is the **coincidence factor**:

```
CF = coincident_group_peak_kw / sum_of_individual_meter_peaks_kw
```

- CF = 1.0 → all meters peak at the same timestamp (fully coincident)
- CF approaching 0 → meters peak at completely different times (full diversity)
- CF > 1.0 → not possible under full data coverage; see edge case below

Two granularities are needed: a study-period CF (one number over all available data)
and a per-day CF (one row per calendar date) for trend/seasonality analysis.

**NaN-gap edge case.** When meters have uneven data coverage, `DataFrame.sum(axis=1,
min_count=1)` (consistent with Phase 1 aggregation semantics) counts only present meters
at each timestamp toward the group demand. But each meter's individual peak is taken as
its global max over whatever data it has — which may be from a timestamp where the
other meters had NaN. In that scenario `group_peak_kw` could theoretically exceed
`sum_of_individual_peaks_kw` at a different timestamp, yielding CF > 1.0. This is
documented, not corrected — the same philosophy as Phase 1's `min_count` choice
(explicit partial-coverage semantics, surfaced rather than hidden).

## Decision

- New `src/load_profile/der/coincidence.py`:
  - `CoincidenceResult` dataclass: `success`, `coincidence_factor`,
    `group_peak_kw`, `sum_of_individual_peaks_kw`, `coincident_peak_timestamp`,
    `n_meters`, `meter_peak_kw` (per-meter peak over the study period).
  - `compute_coincidence_factor(interval_df_multi, meter_ids, cfg, value_col)` —
    study-period CF. Returns `success=False` when fewer than `min_meters` meters are
    available or the group demand is entirely NaN. Uses `DataFrame.sum(axis=1,
    min_count=1)` for the group series (NaN only when all meters are NaN at a
    timestamp), then takes the max of that series as `group_peak_kw`.
  - `compute_daily_coincidence(interval_df_multi, meter_ids, cfg, value_col)` —
    per-day CF. Same logic applied per calendar date; dates where group demand is
    entirely NaN are skipped (not emitted as NaN rows). Reports
    `n_meters_reporting` per day (count of meters with at least one non-NaN value
    for that day) so partial-coverage days are not silently absorbed.
- New config `[der.coincidence]`:
  - `min_meters = 2` (default) — minimum meters required to compute a CF. A
    single meter trivially has CF = 1.0; setting `min_meters = 1` enables it but
    the result is definitionally uninteresting.
- Not wired into `run_der_pipeline` — standalone, caller-driven (same design
  choice as Phase 3 and 4 modules; coincidence can be expensive for large
  portfolios and is not always wanted on every run).

## Rationale

- Using the same `min_count=1` group-sum semantics as Phase 1 (`aggregate_entity`)
  keeps the demand-summing behavior consistent across the codebase — a caller who
  has already seen entity frames will get the same group demand here.
- Reporting `coincident_peak_timestamp` and `meter_peak_kw` alongside the CF
  makes the result actionable: a caller knows *when* the group peak occurred and
  which meters contributed most, without a second query.
- Keeping study-period and daily granularities in the same module (rather than two
  separate modules) reflects that they share the identical pivot/sum/argmax logic
  and that callers virtually always want both.

## Consequences

- CF > 1.0 is possible with uneven meter coverage; callers should check
  `n_meters_reporting` alongside CF when interpreting daily results.
- The module has no import dependency on any other `der/` module — it operates
  purely on `interval_df_multi` (the tagged multi-meter DataFrame from Phase 1).
  Shape labels, cluster assignments, etc. are not required.
