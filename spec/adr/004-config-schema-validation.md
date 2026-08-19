# ADR 004 — Configuration Schema Validation

**Date:** 2026-08-19
**Status:** DECIDED
**Related:** DER Opportunity Analysis integration, Phase 0

## Context

`config.py` loaded the TOML file with `tomllib` and returned a plain dict with
no schema checking at all — malformed values (bad units, out-of-range
fractions, misspelled severity levels) were only ever discovered later, deep
inside whichever module happened to read that key, often as a silent
fallback to a hardcoded default rather than a clear error.

The DER Opportunity Analysis spec being integrated into this codebase
requires config validation to run *before* any data is loaded, producing a
list of findings with severity `INFO`/`WARNING`/`ERROR`, with any `ERROR`
aborting the run with a readable multi-line message. Every later integration
phase (multi-meter/portfolio model, temperature, clustering, etc.) adds new
config sections that need the same guarantee.

## Decision

Add `src/load_profile/config_schema.py` with `validate_config(cfg) ->
ConfigValidationReport`, purely structural (never touches the data file).
`load_config()` calls it by default (`validate: bool = True` parameter, opt
out with `validate=False`) and raises `ConfigValidationError` on any `ERROR`
finding.

Findings are `ConfigIssue(severity, path, message)` records collected in a
`ConfigValidationReport`; `report.has_errors` / `report.is_valid` gate
whether the run proceeds.

The validator is additive/incremental: each Phase 0-6 of the DER work adds
its own section-specific validation function (e.g. a future
`_validate_meter_groups_section`) rather than one monolithic function, so the
schema grows alongside the config sections it covers.

## Rationale

- Fail-fast with a readable message beats a `KeyError`/silent-default three
  modules downstream.
- Purely structural (no data access) keeps validation cheap and safe to run
  on every `load_config()` call by default.
- Per-section validator functions mirror how the rest of this codebase
  organizes per-concern modules (`baseline.py`, `states.py`, etc.) — easy to
  extend without touching unrelated checks.
- Cycle detection for `[[meter_groups]]` (needed in Phase 1) is included now
  as a standalone `_detect_meter_group_cycles(group_children)` DFS helper,
  decoupled from the not-yet-defined TOML key names, so Phase 1 only has to
  wire the adjacency map, not write the algorithm.

## Consequences

- `load_config()` now validates by default; any caller relying on loading a
  config with an existing structural defect (rare, since none existed before)
  must pass `validate=False` explicitly.
- New DER config sections in later phases must add a corresponding validator
  function or they will silently pass schema validation despite being
  unchecked — validation coverage is not automatic, it is written per
  section.
