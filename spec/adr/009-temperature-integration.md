# ADR 009 — External Temperature Integration

**Date:** 2026-08-19
**Status:** DECIDED
**Related:** DER Opportunity Analysis integration, Phase 2

## Context

DER spec §5.2 requires: loading external temperature data, a nearest-timestamp
(`merge_asof`) join onto the canonical timestamp (temperature is site-level, not
per-meter — one join, not fan-out per meter), an `override_existing` policy, an
optional `join_tolerance_minutes` window, and banding via `pd.cut` into configurable
boundaries. None of this existed in the codebase; the only prior mention of
temperature was `spec/SPEC.md`'s own §5 listing it as an unused optional future input
column.

## Decision

- `der/temperature.load_temperature_data(source, cfg) -> DataFrame` — mirrors
  `data_ingestion.load_demand_data`'s loading pattern (CSV path or DataFrame,
  configurable column mapping via `[der.temperature.column_mapping]`, reuses
  `data_ingestion._parse_timestamps` rather than re-implementing timestamp parsing).
  Returns a single `temperature_f` column, tz-aware, sorted.
- `der/temperature.merge_temperature(interval_df, temp_df, cfg) -> DataFrame` —
  `pd.merge_asof(..., direction="nearest", tolerance=...)` on the index directly
  (`left_index=True, right_index=True`), so it joins onto whatever frame it's given
  (an entity frame or a meter's own `interval_df`) without meter-specific logic.
  `override_existing` (default `False`): external only fills existing-NaN
  `temperature_f`; `True`: external wins wherever `merge_asof` found a match within
  tolerance, falling back to the existing value outside tolerance (via the same
  `.where()` pattern in both directions, per spec).
- `der/temperature.band_temperature(df, cfg) -> DataFrame` — `pd.cut` on configurable
  `[der.temperature.bands].boundaries` (default `[32, 50, 65, 80, 90]`), producing
  `"below-32"`, `"32-50"`, ..., `"90-above"` labels. NaN temperature -> NaN band
  (pandas' native `pd.cut` behavior, no special-casing needed).
- `der.pipeline.run_der_pipeline` loads the configured `[der.temperature].source`
  **once** (not per entity) if set, and merges+bands it onto every non-empty entity's
  calendar-enriched frame. If no `source` is configured, `entity_temperature_frames`
  stays empty — temperature-dependent analysis degrades gracefully, matching spec
  §5.2's "must degrade gracefully, never crash the pipeline" requirement.

## Rationale

- A single per-source load, then N merges, avoids redundant CSV/DataFrame parsing per
  entity — temperature is one external signal shared across the whole portfolio.
- Joining on the index (not a plain column) keeps the function agnostic to whether the
  caller passes an aggregated entity frame or a raw meter interval frame — same
  contract either way.

## Consequences

- A real bug was caught by the pipeline-level integration test
  (`tests/der/test_der_pipeline_enrichment.py::test_temperature_source_populates_temperature_frames`):
  the original `if temp_source:` guard in `run_der_pipeline` raised
  `ValueError: The truth value of a DataFrame is ambiguous` whenever a DataFrame (not a
  path string) was passed as the temperature source — `[der.temperature].source` must
  be checked with `is not None`, not plain truthiness, because `MeterSpec.source` /
  `der.temperature.source` both accept in-memory DataFrames. Fixed before merge; the
  same `is not None` care should be applied anywhere else a DataFrame-or-path config
  value is branched on.
- Full change-point/balance-point regression against temperature (2P/3P/4P/5P family)
  is explicitly **not** part of this phase — that's Phase 3 (`der.change_point`).
