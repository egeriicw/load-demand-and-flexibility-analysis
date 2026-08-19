# ADR 007 — Entity Aggregation Semantics

**Date:** 2026-08-19
**Status:** DECIDED
**Related:** DER Opportunity Analysis integration, Phase 1

## Context

The DER spec requires group/portfolio aggregation across meters to be
**summation, never averaging**, computed via a NaN-preserving sum (an
all-missing group at a timestamp stays NaN, not a false 0), with an explicit
`n_meters_reporting` count so partial coverage is never silently absorbed
into the aggregate.

A real naming-collision risk surfaced while designing this phase: an earlier
codebase-exploration pass suggested reusing this repo's existing
`analysis_demand_kw` column name for the DER spec's `analysis_demand_kw`
concept. **That mapping is wrong and was not implemented.** This repo's
`analysis_demand_kw` (produced by `time_series.apply_smoothing`) is a
**rolling-median/mean-smoothed** series used for baseline/state detection —
smoothing is not part of the DER spec's `analysis_demand_kw` definition at
all (DER: observed-else-interpolated-else-NaN, no smoothing). The correct
mapping is: DER's `observed_demand_kw` → this repo's `demand_kw_raw`; DER's
`analysis_demand_kw` → this repo's **`demand_kw`** (the `regularize()`
output column: observed value where present, else linearly interpolated
within the gap cap, else NaN — exactly the DER definition, pre-smoothing).

## Decision

- `der/aggregation.aggregate_entity(interval_df_multi, meter_ids,
  min_count=1) -> DataFrame` sums the **`demand_kw`** column (not
  `analysis_demand_kw`) across the given meter subset, using
  `groupby(...)["demand_kw"].sum(min_count=min_count)` — pandas' native
  NaN-preserving group-sum semantics satisfy the "all-NaN group stays NaN"
  requirement directly, no custom logic needed.
- `n_meters_reporting` = `groupby(...)["demand_kw"].count()` (pandas
  `.count()` already ignores NaN) — count of meters with non-null
  `demand_kw` at that timestamp, attached alongside the sum.
- `min_count` defaults to `1` (new config key `der.aggregation.min_count`,
  default `1`) — a single reporting meter is sufficient for a non-NaN
  aggregate at that timestamp. This was confirmed with the user before
  implementation per the integration plan's flagged open question.
- `der/aggregation.build_entity_frame` wraps `aggregate_entity`, stamps
  `entity_id`, and derives `is_missing` from the aggregate's own NaN demand.
  It deliberately does **not** attempt to derive aggregate-level
  `is_observed`/`is_interpolated` flags — those describe a single meter's
  provenance and have no well-defined cross-meter meaning (one meter can be
  observed while another is interpolated at the same timestamp);
  `n_meters_reporting` is the aggregate's own partial-coverage signal
  instead.
- `pipeline._analyse_day`'s `iv_df` (the interval-level table
  `run_pipeline` returns) was extended to also carry `demand_kw_raw` and
  `data_quality_flag` (both already computed by `regularize()`, just not
  previously selected into the returned frame) — required so the DER layer
  has the canonical fields to work with without recomputing them.

## Rationale

- Reusing the smoothed `analysis_demand_kw` column for aggregation would
  have summed smoothed-per-meter values, which is neither the DER spec's
  definition nor a mathematically sound thing to do (smoothing then summing
  is not equivalent to summing then smoothing) — worth flagging explicitly
  since it's an easy mistake to propagate from a surface-level name match.
- Pandas' `sum(min_count=...)` is the exact primitive the spec's NaN
  semantics describe; no custom "if all NaN then NaN else sum" branch is
  needed.

## Consequences

- Anyone reading `der/aggregation.py` alongside `time_series.py` should not
  assume `analysis_demand_kw` (smoothed) and the DER spec's
  `analysis_demand_kw` (quality-cascaded, unsmoothed) are the same value —
  they share a name only in the DER spec's own vocabulary, not in this
  codebase, where the equivalent column is `demand_kw`.
- `tests/der/test_aggregation.py` explicitly tests the sum-not-average and
  NaN-preservation invariants directly, per the integration plan's
  verification checklist (the single highest-risk-of-silent-bug invariant
  in the DER spec).
