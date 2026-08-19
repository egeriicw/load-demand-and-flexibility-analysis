# ADR 006 — Multi-Meter / Portfolio Model

**Date:** 2026-08-19
**Status:** DECIDED
**Related:** DER Opportunity Analysis integration, Phase 1

## Context

The existing engine (`pipeline.run_pipeline`) analyzes exactly one meter's
DataFrame per call; `meter_id`/`building_id` are pass-through labels, not a
registry. The DER spec requires meters to be analyzable individually, in
configured groups (flat, hierarchical, or overlapping), and as a portfolio
(all configured meters minus an exclusion list) — with recursive,
memoized group resolution and rejection of cyclic group hierarchies.

## Decision

- New `src/load_profile/der/meters.py`:
  - `MeterSpec` dataclass (`meter_id`, `display_name`, `building_id`, `source`)
    built from a new `[[meters]]` TOML array via `build_meter_specs(cfg)`.
  - `resolve_meter_groups(cfg) -> dict[str, list[str]]` — recursive resolution
    of `[[meter_groups]]` (`name`, `meters`, `child_groups`) to deduplicated,
    sorted leaf meter_id lists, memoized per group name. Cycle protection is
    two-layered: config-schema validation (`config_schema.validate_config`)
    rejects cyclic `child_groups` graphs structurally before any data loads;
    `resolve_meter_groups` also raises defensively if a cycle is reached
    directly (e.g. called with an unvalidated cfg), per spec.
  - `resolve_portfolio(cfg) -> list[str]` — all `[[meters]]` minus
    `[portfolio].excluded_meters`, always (no alternate explicit portfolio
    list, matching spec §3.1).
- New `[portfolio]` and commented example `[[meters]]`/`[[meter_groups]]`
  blocks in `config/analysis_config.toml`. `[[meters]]` is empty by default
  — the DER multi-meter pipeline (`der.pipeline.run_der_pipeline`) is
  therefore inert until entries are added; the single-meter pipeline is
  unaffected either way.
- `config_schema.py` gained `_validate_meters_section` (unique meter_id,
  empty-array is a `WARNING` not an `ERROR` per spec), 
  `_validate_meter_groups_section` (known meter/group references, no
  self-reference, cycle detection via the Phase 0 DFS helper), and
  `_validate_portfolio_section` (excluded meter_ids must exist).

## Rationale

- Per-meter column-name/source-file overrides are **not** supported — every
  meter is ingested via the existing global `[input]` column-mapping (all
  source files share the same schema). This is a deliberate simplification:
  the DER spec allows per-meter overrides but nothing in this integration's
  scope requires them yet, and adding unused per-meter config surface would
  be speculative. Revisit if a real multi-source dataset needs it.
- `MeterSpec.source` accepts anything `data_ingestion.load_demand_data`
  already accepts (path or DataFrame) — no new loading code needed.
- Memoized recursive resolution avoids recomputing a shared child group's
  membership once per parent that references it.

## Consequences

- A config with meters but no groups still gets a working `"Portfolio"`
  entity (all meters, since `excluded_meters` defaults to `[]`).
- Every meter/group/portfolio's resolved membership is computed once per
  `run_der_pipeline()` call; there is no cross-call caching (config is
  assumed immutable within a single run, consistent with the rest of the
  codebase's `cfg` deep-copy-per-test convention).
