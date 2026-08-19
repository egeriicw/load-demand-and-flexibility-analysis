# ADR 016 — DER Output Layout

**Date:** 2026-08-19
**Status:** DECIDED
**Related:** DER Opportunity Analysis integration, Phase 6

## Context

The multi-meter DER pipeline (Phases 1–5) accumulates results across multiple
objects: `DERResult` (entity frames, calendar frames, TOD frames), standalone
analysis calls (clustering, patterns, load shape, coincidence). No single function
assembled these into a consistent, exportable set of named tables — callers had to
gather outputs themselves. Phase 6 defines the canonical DER output layout.

## Decision

- New `src/load_profile/der/output.py`:
  - `DEROutputBundle` dataclass — five named `pd.DataFrame` fields, all defaulting
    to an empty DataFrame (never `None`). Callers check `.empty` before use.
  - `build_der_output(der_result, cfg) -> DEROutputBundle` — assembles all five
    tables from a `DERResult`. Coincidence tables are computed here (not stored on
    `DERResult`); all other tables come from data already on `DERResult`.
  - `export_der_output(bundle, cfg) -> dict[str, Path]` — writes each non-empty
    table to its configured CSV path; returns the mapping of table name to path.
    Creates parent directories automatically. Tables without a configured path are
    silently skipped; empty tables are not written.

- **Five canonical tables:**

  | Table | Granularity | Source |
  |---|---|---|
  | `meter_interval` | (meter, timestamp) | `DERResult.interval_df_multi` reset to column |
  | `entity_interval` | (entity, timestamp) | `entity_calendar_frames` (Phase 2 enriched) or `entity_frames` |
  | `entity_daily` | (entity, date) | `build_daily_summary` + `entity_tod_frames` left-join |
  | `study_coincidence` | entity | `compute_coincidence_factor` per entity |
  | `daily_coincidence` | (entity, date) | `compute_daily_coincidence` per entity, stacked |

- **Config** `[der.output]` — five optional path keys (all absent by default):
  `meter_interval_csv`, `entity_interval_csv`, `entity_daily_csv`,
  `study_coincidence_csv`, `daily_coincidence_csv`.

## Rationale

**What goes in `build_der_output` vs. stays standalone.** Clustering, load-shape
classification, change-point regression, and pattern discovery are left as
standalone callers — same design principle as Phases 3 and 4. Coincidence *is*
computed inside `build_der_output` because it is cheap (no model fitting, pure
pivot/max operations), always meaningful once multiple meters are present, and
naturally produces two of the five canonical output tables. The expensive/optional
analyses (K-means, load-shape, change-point) are not forced on every output call.

**`entity_interval` source priority.** Calendar-enriched frames (`entity_calendar_frames`)
are preferred over base entity frames when present, because Phase 2 enrichment is
almost always wanted in the output. The fallback ensures Phase 6 remains useful
even when Phase 2 was not run.

**`entity_daily` TOD join.** `build_daily_summary` (patterns.py) and
`add_time_of_day_segments` both use tz-aware Timestamps as their "date" key
(from `DatetimeIndex.normalize()`). The left-join on "date" is safe because they
share the same key type and origin.

**Empty-not-None contract.** Every field defaults to `pd.DataFrame()` so callers
can always call `.empty` or iterate columns without `None` checks. `export_der_output`
skips empty tables rather than writing zero-row CSVs.

## Consequences

- `study_coincidence` contains a `success` column (from `CoincidenceResult.success`).
  Entities that fail the `min_meters` guard appear with `success=False` and NaN
  numeric columns — they are not silently dropped, so callers can see which entities
  were not coincidence-scored and why.
- Clustering, load-shape, and pattern results are not in the bundle — callers that
  want them attach them to `entity_daily` themselves before calling `export_der_output`
  (the bundle fields are plain DataFrames, freely extensible).
- Phase 6 completes the six-phase DER integration (Phases 0–6). The codebase now
  supports the full pipeline from config validation through multi-meter aggregation,
  enrichment, classification, clustering, coincidence, and structured output export.
