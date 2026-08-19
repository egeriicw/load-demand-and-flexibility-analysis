# ADR 014 — Recurring-Pattern Discovery

**Date:** 2026-08-19
**Status:** DECIDED
**Related:** DER Opportunity Analysis integration, Phase 4

## Context

DER spec §5.8/§21 requires three heuristic/statistical (never causal) pattern-discovery
analyses: recurring peak timing (bucketed), recurring shape (grouped by
`der_primary_shape`), and outlier days (z-score of daily energy and max demand,
computed separately). All three report frequency/dates/statistical support, and all
three operate over **complete days only**.

## Decision

- New `src/load_profile/der/patterns.py`:
  - `build_daily_summary(interval_df, value_col)` — per-day `is_complete_day`,
    `daily_energy_kwh`, `maximum_demand_kw`, `peak_time_minutes`. Deliberately has **no
    import dependency on `load_shape.py`** — a caller wanting shape-pattern discovery
    merges a `der_primary_shape` column onto this function's output themselves (e.g.
    from `load_shape.classify_load_shape`'s output, joined on `date`). This keeps
    `patterns.py` composable with any shape-labeling source, not hard-wired to one.
  - `find_recurring_peak_timing(daily_summary, cfg)` — buckets `peak_time_minutes`
    into `der.patterns.peak_timing_window_minutes` (default 30) buckets over complete
    days only; reports buckets with `>= min_occurrences` (default 3) days,
    `statistical_support = n_days / n_complete_days`.
  - `find_recurring_shape(daily_summary, cfg)` — same `min_occurrences`/support
    convention, grouped by `der_primary_shape`, excluding `"insufficient_data"`.
    Returns empty if the column isn't present (rather than raising) — pattern
    discovery must degrade gracefully when shape labels weren't computed.
  - `find_outlier_days(daily_summary, cfg)` — z-score of `daily_energy_kwh` and
    `maximum_demand_kw` **separately** (two independent z-score passes, not a combined
    metric), flags `|z| >= der.patterns.outlier_z_threshold` (default 2.5), requires
    `>= der.patterns.min_days_for_outliers` (default 5) complete days else empty.
- New config `[der.patterns]` (`peak_timing_window_minutes`, `min_occurrences`,
  `outlier_z_threshold`, `min_days_for_outliers`).
- Both `find_recurring_peak_timing` and `find_recurring_shape` use the **same
  denominator** for `statistical_support` — total complete days, not "days matching
  after excluding insufficient_data" — per the spec's explicit "same support fraction"
  language linking the two.

## Rationale

- Keeping `patterns.py` decoupled from `load_shape.py` (no import) mirrors the Phase 3
  design principle already established for `peak_events.py` (ADR 011): a generic
  analysis module that composes with whatever boolean/categorical column a caller
  supplies, rather than being wired to one specific upstream producer.
- Not wiring Phase 4 (clustering + patterns) into `run_der_pipeline` at all — consistent
  with Phase 3's choice (`der/pipeline.py` was untouched there too) — keeps these as
  standalone, directly-callable analyses rather than forcing every DER run to compute
  clustering/patterns whether or not a caller wants them (K-means in particular is not
  cheap to run unconditionally for every entity on every pipeline run).

## Consequences

- Every discovered pattern is explicitly association, not causation — no code in this
  module makes or implies a causal claim, matching spec.
- A caller wanting the full picture (peak timing + shape + outliers) for one entity
  calls `build_daily_summary`, merges in `der_primary_shape` themselves if wanted, then
  calls all three `find_*` functions — there is no single "run everything" entry point
  in this phase, deliberately (see rationale above).
