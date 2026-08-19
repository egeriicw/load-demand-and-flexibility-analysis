# ADR 012 — Load-Shape Classification (Coexists With `classify_day`)

**Date:** 2026-08-19
**Status:** DECIDED
**Related:** DER Opportunity Analysis integration, Phase 3

## Context

DER spec §5.6 defines a rule-based load-shape taxonomy: independent boolean flags
(`is_flat`, `is_highly_peaked`, `has_{segment}_peak` per Phase 2's TOD windows,
`is_overnight_heavy`, `is_multi_peak`, `has_sharp_peak`, `has_sustained_high_load`,
`has_peak_valley_pattern`, `is_unusual`) plus a priority-ordered `primary_shape`. This
is vocabulary- and rule-incompatible with `classification.classify_day`'s
`CONTINUOUS`/`EARLY_START`/`MORNING_START`/etc. taxonomy (start-timing driven, not
shape driven) — the two classify genuinely different things about a day.

## Decision

- New `src/load_profile/der/load_shape.py`: `classify_load_shape(interval_df, tod_df, cfg)`
  merges per-day stats (mean/std/max/CV/peak-to-average, computed here) with Phase 2's
  `add_time_of_day_segments` output (`tod_df`) and Phase 3's local extrema flags
  (computed via `local_extrema.add_local_extrema_flags` if not already present), and
  emits all the boolean flags above plus a **`der_primary_shape`** column — deliberately
  *not* named `primary_shape`, to avoid any possibility of collision if a caller ever
  joins this output against `classify_day`'s `daily_df`.
- `primary_shape` priority order implemented exactly per spec: `insufficient_data` (if
  `is_unusual`) → `morning_peak`/`afternoon_peak`/`evening_peak`/`midday_peak`
  (highly-peaked + sharp + that segment contains the peak; morning specifically
  requires *no* afternoon/evening peak) → `multi_peak` → `overnight_heavy` → `flat` →
  `mixed_other`.
- `is_multi_peak` uses the local-peak count directly (§5.4's `is_local_peak`), always —
  the spec's documented fallback ("else falling back to counting how many named
  segments contain a peak") is not implemented separately since local extrema are
  computed unconditionally here, making the fallback path unreachable by construction.
  This is a deliberate simplification, called out here rather than left undocumented.

## Rationale — NaN-truthiness bug avoided by design

Merging `tod_df` onto per-day stats via a `date`-keyed left join can leave `NaN` in any
`has_{segment}_peak`/boolean column for a day absent from `tod_df` (e.g. a day the TOD
computation skipped). **`bool(float("nan"))` is `True` in Python** — a naive
`if row["has_morning_peak"]:` check would silently treat a missing/NaN flag as
satisfied. Every flag check in `_primary_shape` uses an explicit `_is_true(x)` helper
(`x is True or x == True`, where `NaN == True` evaluates `False`) instead of plain
truthiness. This was caught and fixed during implementation, before merge, via
`tests/der/test_load_shape.py::test_nan_row_from_tod_merge_does_not_satisfy_every_rule`,
which deliberately constructs a `tod_df` missing one date's row and asserts that day's
`der_primary_shape` is not spuriously classified.

## Consequences

- `classify_load_shape` requires both `interval_df` and a matching `tod_df` (Phase 2
  output) — it is not a drop-in replacement for `classify_day`'s single-frame call
  signature, by design (different inputs for a different classification).
- Any future boolean-flag classifier added to this codebase should audit for the same
  NaN-truthiness hazard whenever a left-join can introduce missing rows before a
  boolean check.
