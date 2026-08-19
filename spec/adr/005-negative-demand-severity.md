# ADR 005 — Configurable Negative-Demand Severity

**Date:** 2026-08-19
**Status:** DECIDED
**Related:** DER Opportunity Analysis integration, Phase 0

## Context

Previously, `validate_input()` only *counted* negative demand values and
appended a warning string; it never rejected them. `time_series.regularize()`
unconditionally nulled negative values to NaN and let the normal gap-limited
interpolation logic fill them (or leave them missing if the gap was too
large). There was no way to reject a file containing negative demand outright.

The DER spec states negative demand is "unsupported by design" and is an
`ERROR` by default, with severity configurable per the standard
`INFO`/`WARNING`/`ERROR` scale used throughout its validation model.

## Decision

- New config key `data_quality.negative_demand_severity` (`"INFO" |
  "WARNING" | "ERROR"`), **default `"ERROR"`** — a deliberate behavior change
  from the previous implicit warn-then-NaN.
- `validate_input()` stays non-raising (report-only contract, unchanged) but
  now routes the negative-demand finding into `report["issues"]` (blocking)
  when severity is `"ERROR"`, `report["warnings"]` (informational) when
  `"WARNING"`, or emits no message at all (count-only) when `"INFO"`.
- New `data_ingestion.check_validation_report(report, cfg)` is the
  caller-side gate: raises `ValueError` if `report["negative_demand_severity"]
  == "ERROR"` and negative values were found. `pipeline.run_pipeline()` calls
  it immediately after `validate_input()`, before any further processing.
- `time_series.regularize()` is **unchanged** — it still unconditionally
  nulls negative values to NaN. This is deliberate: `regularize()` is a pure
  transform with no knowledge of "was this run supposed to have already
  aborted"; the actual rejection happens once, at the `run_pipeline()` gate,
  before `regularize()` is ever reached in the `"ERROR"` case. Downgrading to
  `"WARNING"`/`"INFO"` lets a caller bypass the gate and still get the
  original graceful missing-data treatment.

## Rationale

- Keeping `regularize()` unconditional avoids scattering severity-branching
  logic into a function whose contract (reindex + gap-limited interpolate)
  has nothing to do with validation policy, and preserves its existing
  direct-call test coverage (`tests/test_time_series.py`) unmodified.
- A single caller-side gate (`check_validation_report`) is easy to reason
  about and matches the existing pattern where `validate_input()` reports and
  `run_pipeline()` decides what to do about it (it already does this for
  duplicate timestamps, just without raising).
- Defaulting to `"ERROR"` matches the DER spec exactly; anyone relying on the
  old warn-then-NaN behavior opts back in with one config line.

## Consequences

- Existing tests that fed negative demand through the *default* `cfg`
  fixture and expected a warning (`tests/test_data_ingestion.py`) were
  updated: one test now asserts the new default `"ERROR"`/issues behavior,
  a second explicitly downgrades severity to `"WARNING"` and asserts the old
  behavior still works.
- `tests/test_time_series.py::test_negative_demand_treated_as_missing_then_interpolated`
  needed no change — it calls `regularize()` directly, which is unaffected.
- Any downstream caller building a DataFrame with negative demand and
  calling `run_pipeline()` with the default config will now get a `ValueError`
  instead of a silently-NaN'd value — a breaking change for that call
  pattern, intentional per the DER spec.
