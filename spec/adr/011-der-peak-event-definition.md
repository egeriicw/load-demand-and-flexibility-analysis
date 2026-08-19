# ADR 011 — DER Peak Event Definition (Coexists With `events.PeakEvent`)

**Date:** 2026-08-19
**Status:** DECIDED
**Related:** DER Opportunity Analysis integration, Phase 3

## Context

DER spec §5.5 defines "peak events" as: given ANY boolean "meets criterion" series
(threshold/percentile/rank from §5.3, or any other boolean column) and an
`allowable_gap_intervals`, walk qualifying interval positions in order; start a new
event whenever the gap since the last qualifying interval **exceeds**
`allowable_gap_intervals`; otherwise extend the current event to *include* the
intervening non-qualifying intervals. This is a fundamentally different definition
from `events.PeakEvent` (prominence/plateau/separation-based, operating on the
*smoothed* series, one "primary peak of the day" ranking).

## Decision

- New `src/load_profile/der/peak_events.py`: `DERPeakEvent` dataclass
  (`event_id`, `entity_id`, `peak_definition`, `start_time`, `end_time`,
  `duration_hours`, `max/mean/min_demand_kw`, `n_intervals`, `duration_class`) and
  `detect_der_peak_events(interval_df, meets_criterion, entity_id, definition, cfg)`.
- `event_id` format: `f"{entity_id}_{definition}_{seq:04d}"` exactly per spec.
- `duration_class = "sustained"` if `duration_hours >= sustained_threshold_hours`
  (config `der.peak_events.sustained_threshold_hours`, default `1.0`), else `"short"`.
- Zero qualifying intervals returns `[]`, not an error.
- **Explicitly a new, separate object from `events.PeakEvent`.** `events.py` is
  untouched. A caller wanting "the DER spec's peak events" calls
  `detect_der_peak_events` with a boolean series from `demand_classification.classify_demand_families`
  (or any other boolean column); a caller wanting "this repo's existing prominence-based
  peak detection" still calls `events.detect_peaks` exactly as before.

## Rationale

- The two definitions solve different problems: `events.PeakEvent` answers "what are
  this day's characteristic peaks, ranked and de-duplicated by prominence/separation
  for classification purposes"; `DERPeakEvent` answers "give me every contiguous span
  where some caller-defined boolean condition held, gap-bridged by a tolerance" — a
  general grouping primitive, not peak-specific in mechanism (it would work identically
  for any other boolean series).
- Reusing the name `PeakEvent` for a structurally different object would be a silent
  trap for anyone importing from either module expecting the other's fields/semantics.

## Consequences

- Two "peak event" concepts now exist side by side in this codebase, deliberately, by
  name (`events.PeakEvent` vs. `der.peak_events.DERPeakEvent`) and by definition. Any
  future documentation/notebook work should be explicit about which one it's referring
  to.
- `detect_der_peak_events` takes the boolean series as a parameter rather than
  computing it internally, so it composes directly with any of §5.3's three
  classification families (or a caller's own custom boolean column) without
  `peak_events.py` needing to know about `demand_classification.py` at all.
