# ADR 010 — Change-Point (Balance-Point) Regression Model Family

**Date:** 2026-08-19
**Status:** DECIDED
**Related:** DER Opportunity Analysis integration, Phase 3

## Context

DER spec §5.2 requires the full ASHRAE GL14 / IPMVP change-point model family — 2P
(plain OLS), 3P-cooling, 3P-heating (single breakpoint, grid search), 4P (one shared
breakpoint, both a heating and cooling slope, bounded ≥0), 5P (independent
heating/cooling breakpoints, `heating_bp ≤ cooling_bp`) — plus
`select_best_change_point_model` choosing among them by adjusted R² with a
simpler-model tie-break. None of this existed in the codebase; `scipy` was already a
dependency (added for future use, first actually used here via `scipy.optimize.lsq_linear`).

## Decision

- New `src/load_profile/der/change_point.py`: `fit_2p`, `fit_3p_cooling`,
  `fit_3p_heating`, `fit_4p`, `fit_5p`, `select_best_change_point_model`, all
  operating on plain `x`/`y` arrays (not DataFrame-bound) — callers filter to
  weekday-only, daily-mean-vs-daily-mean-demand, etc. themselves; these functions are
  agnostic to what `x`/`y` represent, matching how `fit_2p(x, y)` reads as a general
  linear-regression primitive rather than a temperature-specific one.
- Grid search is 1°F-step (`_breakpoint_candidates`, parameterizable step, default
  1.0), excluding the extremes of the observed range so every candidate breakpoint
  always leaves at least one point on each side — this **is** the "degenerate
  candidates are skipped" rule from spec, enforced structurally by the candidate range
  rather than by a runtime check.
- 4P/5P use `scipy.optimize.lsq_linear` with `bounds=([-inf,0,0],[inf,inf,inf])` so
  heating/cooling slopes can never be fit negative, per spec ("heating/cooling load
  can't physically decrease as you move further from the breakpoint").
- Each fitter's minimum-point guard (4/5/5/8/10 for 2P/3P-cooling/3P-heating/4P/5P)
  returns `success=False` with no `r_squared` rather than attempting a meaningless fit
  on insufficient data.
- `select_best_change_point_model` excludes any candidate that failed its guard *or*
  where `n - p - 1 <= 0` from scoring (not scored as "worse" — excluded entirely), sorts
  by `(adjusted_r_squared, -param_count)` descending so ties go to the simpler model,
  and returns `None` if every candidate is excluded.

## Rationale

- OLS via `numpy.linalg.lstsq` (2P, 3P families) and bounded LS via `scipy.optimize.lsq_linear`
  (4P/5P, where the non-negativity constraint actually matters) match the spec's stated
  method per model exactly — no reason to use one solver everywhere when only 4P/5P need
  the bound.
- A dataclass (`ChangePointModel`) mirrors the `StartEvent`/`RampEvent`/`PeakEvent`
  pattern already established in `events.py`, keeping event/model records consistent
  across the codebase.

## Consequences

- `fit_5p`'s joint grid search is `O(candidates²)` — for a ~100°F observed range at
  1°F steps that's ~10,000 candidate breakpoint pairs, each a small `lsq_linear` call.
  This shows up as the slowest tests in `tests/der/test_change_point.py`
  (`TestSelectBestChangePointModel` cases take ~4s each, since selecting the best model
  always fits 5P too). Acceptable for correctness-first test coverage at this data
  scale; if real portfolios need faster fits over wider temperature ranges, a
  configurable coarser step or a smarter 2-D search (not required by spec) would be
  the next optimization, not implemented here.
- `select_best_change_point_model` returning `None` must be surfaced by callers as "no
  model fit," never silently treated as "temperature-independent" — this is
  spec-mandated and worth re-flagging since it's an easy misinterpretation.
