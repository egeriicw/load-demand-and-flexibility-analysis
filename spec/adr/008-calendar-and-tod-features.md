# ADR 008 — Calendar and Time-of-Day Segment Features

**Date:** 2026-08-19
**Status:** DECIDED
**Related:** DER Opportunity Analysis integration, Phase 2

## Context

DER spec §2.4 requires calendar-derived fields (day-of-week, season, holiday-aware
`day_type`, etc.) from the interval-ending timestamp, and §5.1 requires fixed
time-of-day segment features (morning/midday/afternoon/evening peaks, overnight/daytime
means) per `(entity_id, date)`. Neither existed in this codebase; the closest analog,
`time_series.segment_days`, only splits a multi-day frame into per-date slices — it
doesn't derive any calendar attributes or segment aggregates.

## Decision

- `der/calendar_features.add_calendar_features(interval_df, cfg) -> DataFrame` — adds
  `date`, `year`, `month`, `day`, `day_of_year`, `hour`, `minute`, `day_of_week`
  (Monday=0), `day_name`, `is_weekday`, `is_weekend` (calendar-only), `season`
  (config-driven month->season map, default meteorological Northern Hemisphere),
  `day_type` (`"weekday"|"weekend"|"holiday"`, holiday overrides).
- `der/calendar_features.add_time_of_day_segments(interval_df, cfg) -> DataFrame` —
  one row per date, `{segment}_peak_kw` for each configured window (default
  morning[6,10)/midday[10,14)/afternoon[14,18)/evening[18,22)), `overnight_mean_kw` /
  `nighttime_mean_kw` (alias, same value), `daytime_mean_kw`. Implemented via
  `Series.where(mask)` + `groupby(date).max()`/`.mean()` (native NaN-skip, no `.apply()`)
  rather than a Python-level per-day loop.
- Both functions are **generic** — they take any DataFrame with a tz-aware
  `DatetimeIndex` (and, for the TOD function, a `demand_kw` column). They are not
  hard-wired to entity frames specifically. `der.pipeline.run_der_pipeline` applies
  them automatically to every non-empty entity frame; a caller wanting per-meter
  calendar/TOD features calls them directly on a meter's own `interval_df`
  (`meter_tables[meter_id]["interval_df"]`) — `run_pipeline`'s own return contract is
  untouched (see "must not touch" list).
- New config: `[der.calendar]` (`holidays`, optional `season_map`),
  `[der.time_of_day.segments]` (window boundaries, defaults matching spec).

## Rationale

- Keeping these functions signature-generic (DataFrame + cfg in, DataFrame out) avoids
  a forced choice between "entity-only" and "meter-only" now, and costs nothing —
  neither function needs to know what produced its input frame.
- Vectorized `where()` + `groupby().max()/.mean()` avoids pandas' `apply()` deprecation
  churn around grouping-column inclusion and is materially faster for large date ranges.

## Consequences

- `DERResult` gained `entity_calendar_frames` and `entity_tod_frames` (populated for
  every entity whose aggregated frame is non-empty; skipped — not errored — for empty
  ones, e.g. an unconfigured portfolio).
- Anyone consuming per-meter calendar/TOD features must call these functions
  themselves on `meter_tables[...]["interval_df"]`; they are not auto-applied there.
