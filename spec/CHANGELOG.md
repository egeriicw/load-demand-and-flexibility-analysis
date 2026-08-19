# Specification Changelog

Append-only. Newest entries at the top.

Format:

```
## YYYY-MM-DD — [summary]
- Section N: [what changed and why]
- ADR created: adr/NNN-name.md
```

---

## 2026-08-19 — DER Opportunity Analysis integration, Phase 5: meter coincidence analysis

- New section: Meter Coincidence Analysis (SPEC.md §57).
- `src/load_profile/der/coincidence.py` (new): `compute_coincidence_factor()` —
  study-period CF (`group_peak_kw / sum_of_individual_peaks_kw`), `coincident_peak_timestamp`,
  `meter_peak_kw` per meter. `compute_daily_coincidence()` — same logic per calendar date,
  reports `n_meters_reporting` per day (partial coverage surfaced, not hidden), skips
  entirely-NaN days rather than emitting NaN rows. `CoincidenceResult` dataclass.
  No import dependency on any other `der/` module — operates directly on
  `DERResult.interval_df_multi`.
- `config/analysis_config.toml`: new `[der.coincidence]` (`min_meters = 2`).
- Group-demand computed via `DataFrame.sum(axis=1, min_count=1)` — consistent with
  Phase 1 aggregation semantics. CF > 1.0 is possible (but rare) under uneven meter
  coverage; documented in ADR 015 rather than silently clamped.
- Not wired into `run_der_pipeline` — standalone, caller-driven (same design as Phase
  3 and Phase 4 modules).
- Tests: `tests/der/test_coincidence.py` (perfect coincidence CF=1.0, staggered peaks
  CF<1.0, three-meter partial coincidence, per-day granularity, all-NaN day skipping,
  `n_meters_reporting` correctness, `min_meters` guard, unknown meter_id degradation).
- ADR created: adr/015-coincidence-factor.md
- Phase 6 of the DER integration (DER output layout) follows next.

---

## 2026-08-19 — DER Opportunity Analysis integration, Phase 4: K-means clustering, pattern discovery

- New section: Clustering & Pattern Discovery (SPEC.md Part II).
- `pyproject.toml`: added `scikit-learn>=1.7.0` (new dependency; not previously used
  by this project).
- `src/load_profile/der/clustering.py` (new): `peak_normalized_series()` (DER's own
  §2.7 peak-fraction definition — deliberately not `states.compute_normalized_demand`,
  which is a different, baseline-subtracted quantity — see ADR 013),
  `build_daily_profile_matrix()`, `select_k()` (silhouette-driven auto-k, `<4` days
  forces k=1), `cluster_daily_profiles()` (`KMeans(random_state=42, n_init=10)`,
  cluster_size/percentage_of_days/representative_peak/within_cluster_variability per
  cluster, `<2` days = `success=False`), `cluster_entity_daily_profiles()` (computes
  absolute AND normalized clustering together). `ClusteringResult` dataclass.
- `src/load_profile/der/patterns.py` (new): `build_daily_summary()`,
  `find_recurring_peak_timing()`, `find_recurring_shape()` (excludes
  `insufficient_data`, same support-fraction denominator as peak timing),
  `find_outlier_days()` (z-score of daily energy and max demand computed separately,
  `>=5` complete days required). Deliberately no import dependency on `load_shape.py`
  — see ADR 014.
- `src/load_profile/der/_daily.py` (new): `infer_resolution_minutes`,
  `expected_intervals_per_day`, `complete_day_dates` — factored out of `load_shape.py`
  (Phase 3) once `clustering.py`/`patterns.py` needed the same day-completeness logic a
  third/fourth time; `load_shape.py` now imports from here instead of its own copy.
- `config/analysis_config.toml`: new `[der.clustering]`, `[der.patterns]`.
- **Neither clustering nor pattern discovery is wired into `run_der_pipeline`** —
  consistent with Phase 3's choice to keep these standalone/directly-callable rather
  than forcing every DER run to compute (non-cheap) K-means clustering for every
  entity unconditionally. See ADR 014.
- Tests: `tests/der/test_clustering.py` (reproducibility across runs, cluster-size-sums-
  to-n-days invariant, `<2`/`<4`-day edge cases, both absolute+normalized computed),
  `tests/der/test_patterns.py`.
- ADR created: adr/013-clustering-methodology.md
- ADR created: adr/014-pattern-discovery.md
- Phase 5 of the DER integration (meter coincidence analysis) follows next.

---

## 2026-08-19 — DER Opportunity Analysis integration, Phase 3: change-point regression, demand classification families, DER peak events, load-shape classification

- New section: Change-Point Regression, Demand Classification, DER Peak Events,
  Load-Shape Classification (SPEC.md Part II).
- `src/load_profile/der/change_point.py` (new): `fit_2p`, `fit_3p_cooling`,
  `fit_3p_heating`, `fit_4p`, `fit_5p` (full ASHRAE GL14/IPMVP family, grid search +
  OLS/bounded-LSQ via `scipy.optimize.lsq_linear`), `select_best_change_point_model`
  (adjusted-R², simpler-model tie-break, `None` if every candidate excluded).
  `ChangePointModel` dataclass.
- `src/load_profile/der/demand_classification.py` (new): `classify_demand_families()`
  — threshold/percentile/rank boolean families, kept independent (never collapsed).
- `src/load_profile/der/local_extrema.py` (new): `add_local_extrema_flags()` — 3-point
  comparator `is_local_peak`/`is_local_valley`, NaN-neighbor/boundary safe.
- `src/load_profile/der/peak_events.py` (new): `detect_der_peak_events()` — contiguous
  gap-bridged grouping (`allowable_gap_intervals`), `event_id` format
  `{entity}_{definition}_{seq:04d}`, sustained-vs-short. `DERPeakEvent` dataclass,
  explicitly separate from `events.PeakEvent` (see ADR 011).
- `src/load_profile/der/load_shape.py` (new): `classify_load_shape()` — independent
  shape boolean flags + priority-ordered `der_primary_shape` (distinctly named vs.
  `classify_day`'s `primary_class`, see ADR 012).
- `config/analysis_config.toml`: new `[der.peak_events]`, `[der.demand_classification]`,
  `[der.load_shape]`.
- Bug caught by `tests/der/test_load_shape.py::test_nan_row_from_tod_merge_does_not_satisfy_every_rule`
  and fixed before merge: `bool(float("nan"))` is `True` in Python, so a naive
  truthiness check on a boolean flag left `NaN` by a day-keyed left join would silently
  satisfy every rule. Fixed via an explicit `_is_true()` helper (`x is True or x ==
  True`) used throughout `_primary_shape`. See ADR 012.
- Tests: `tests/der/test_change_point.py` (known-breakpoint recovery for all five
  models, model-selection ties), `tests/der/test_demand_classification.py`,
  `tests/der/test_der_peak_events.py` (gap-bridging, event_id format, sustained
  threshold), `tests/der/test_local_extrema.py` (NaN-neighbor edge cases),
  `tests/der/test_load_shape.py` (incl. the NaN-truthiness regression test above).
- ADR created: adr/010-change-point-model-family.md
- ADR created: adr/011-der-peak-event-definition.md
- ADR created: adr/012-load-shape-classification.md
- Phase 4 of the DER integration (K-means clustering, pattern discovery) follows next.

---

## 2026-08-19 — DER Opportunity Analysis integration, Phase 2: calendar features, time-of-day segments, external temperature

- New section: Calendar & Time-of-Day Features, External Temperature (SPEC.md Part II).
- `src/load_profile/der/calendar_features.py` (new): `add_calendar_features()` (date,
  year, month, day, day_of_year, hour, minute, day_of_week, day_name, is_weekday,
  is_weekend, season, day_type with holiday override), `add_time_of_day_segments()`
  (per-day `{segment}_peak_kw` for morning/midday/afternoon/evening windows,
  `overnight_mean_kw`/`nighttime_mean_kw`/`daytime_mean_kw`). Both are generic —
  operate on any tz-aware-indexed DataFrame, not entity-frame-specific.
- `src/load_profile/der/temperature.py` (new): `load_temperature_data()` (reuses
  `data_ingestion._parse_timestamps`), `merge_temperature()` (`merge_asof` nearest join
  on the index, `override_existing`/`join_tolerance_minutes` policy), `band_temperature()`
  (`pd.cut` into configurable boundaries, default `[32,50,65,80,90]`).
- `src/load_profile/der/pipeline.py`: `run_der_pipeline()` now applies calendar/TOD
  enrichment to every non-empty entity frame, and merges+bands temperature once
  (loaded once, not per entity) when `[der.temperature].source` is configured.
  `DERResult` gained `entity_calendar_frames`, `entity_tod_frames`,
  `entity_temperature_frames`.
- `config/analysis_config.toml`: new `[der.calendar]` (`holidays`, optional
  `season_map`), `[der.time_of_day.segments]` (window defaults matching spec),
  `[der.temperature]` + `[der.temperature.column_mapping]` + `[der.temperature.bands]`.
- Bug caught by the new pipeline-integration test and fixed before merge:
  `run_der_pipeline`'s temperature-source check used plain `if temp_source:` truthiness,
  which raised `ValueError: The truth value of a DataFrame is ambiguous` whenever a
  DataFrame (rather than a path) was passed as the source — changed to `is not None`.
  See ADR 009.
- Tests: `tests/der/test_calendar_features.py`, `tests/der/test_time_of_day.py`,
  `tests/der/test_temperature.py`, `tests/der/test_der_pipeline_enrichment.py`.
- ADR created: adr/008-calendar-and-tod-features.md
- ADR created: adr/009-temperature-integration.md
- Phase 3 of the DER integration (change-point regression, demand classification
  families, DER peak events, load-shape classification) follows next.

---

## 2026-08-19 — DER Opportunity Analysis integration, Phase 1: multi-meter/portfolio model + entity aggregation

- New section: Multi-Meter & Portfolio Model, Entity Aggregation (SPEC.md Part II).
- New subpackage `src/load_profile/der/` — multi-meter DER layer, built on top of the
  unchanged single-meter `pipeline.run_pipeline` (see ADR 006).
- `src/load_profile/der/meters.py` (new): `MeterSpec`, `build_meter_specs()`,
  `resolve_meter_groups()` (recursive, memoized, flat/hierarchical/overlapping, cycle
  detection via Phase 0's `_detect_meter_group_cycles`), `resolve_portfolio()`
  (all meters minus `[portfolio].excluded_meters`).
- `src/load_profile/der/aggregation.py` (new): `aggregate_entity()` — SUM (never
  average) across meters via `groupby(...).sum(min_count=...)`, `n_meters_reporting`
  count column, NaN-preserving for all-missing groups. `build_entity_frame()` wraps it
  with `entity_id`/`is_missing`. See ADR 007 for the corrected `demand_kw` (not the
  smoothed `analysis_demand_kw`) column mapping this aggregates.
- `src/load_profile/der/pipeline.py` (new): `run_der_pipeline(cfg)` — loops
  `[[meters]]`, calls `pipeline.run_pipeline()` once per meter unchanged, tags/concats
  interval tables with `meter_id`, builds an aggregated entity frame per resolved
  group and the portfolio. Returns `DERResult`.
- `src/load_profile/time_series.py`: `regularize()` gained an additive
  `data_quality_flag` column (`"observed"|"interpolated"|"missing"`, `np.select` over
  existing booleans) — DER spec canonical field, no existing column changed.
- `src/load_profile/pipeline.py`: `_analyse_day()`'s returned `interval_df` now also
  carries `demand_kw_raw` and `data_quality_flag` (both already computed by
  `regularize()`, previously not selected into the output).
- `config/analysis_config.toml`: new `[[meters]]`/`[[meter_groups]]` example blocks
  (commented, empty by default — DER pipeline inert until populated), new `[portfolio]`
  (`excluded_meters`), new `[der.aggregation]` (`min_count = 1`).
- `src/load_profile/config_schema.py`: added `_validate_meters_section` (unique
  meter_id; empty array = WARNING not ERROR per spec), `_validate_meter_groups_section`
  (known references, no self-reference, cycle detection), `_validate_portfolio_section`
  (excluded meter_ids must exist).
- Tests: `tests/der/conftest.py`, `tests/der/test_meters.py`,
  `tests/der/test_aggregation.py` (explicit sum-not-average + NaN-preservation +
  min_count invariant tests), `tests/der/test_der_pipeline.py`.
- ADR created: adr/006-multi-meter-portfolio-model.md
- ADR created: adr/007-entity-aggregation-semantics.md
- Phase 2 of the DER integration (calendar features, time-of-day segments, external
  temperature) follows next.

---

## 2026-08-19 — DER Opportunity Analysis integration, Phase 0: config schema validation + negative-demand severity

- New section: Configuration Validation (structural, runs before any data load).
- `src/load_profile/config_schema.py` (new): `validate_config()`, `ConfigValidationReport`,
  `ConfigIssue`, `ConfigValidationError`, `_detect_meter_group_cycles()` (DFS cycle
  detector, algorithm added now for reuse by Phase 1's `[[meter_groups]]`).
- `src/load_profile/config.py`: `load_config(path=None, validate=True)` now validates by
  default and raises `ConfigValidationError` on any `ERROR`-severity finding.
- `config/analysis_config.toml [data_quality]`: added `negative_demand_severity`
  (`"INFO"|"WARNING"|"ERROR"`, default `"ERROR"`) — behavior change, see ADR 005.
- `src/load_profile/data_ingestion.py`: `validate_input()` routes negative-demand
  findings into `issues` (ERROR) vs `warnings` (WARNING) vs silent-count (INFO) based on
  the new severity key. New `check_validation_report(report, cfg)` raises `ValueError`
  when the configured severity dictates rejection; `validate_input()` itself remains
  non-raising.
- `src/load_profile/pipeline.py`: `run_pipeline()` calls `check_validation_report()`
  immediately after `validate_input()`.
- `tests/test_data_ingestion.py`: updated negative-demand test to assert the new default
  `ERROR`/issues behavior; added a companion test for the `WARNING` downgrade path.
- `tests/test_pipeline.py`: added `TestPipelineNegativeDemandSeverity` (default-rejects,
  downgrade-allows).
- `tests/test_config_schema.py` (new): schema validation + cycle-detector coverage.
- ADR created: adr/004-config-schema-validation.md
- ADR created: adr/005-negative-demand-severity.md
- This is Phase 0 of a multi-phase DER Opportunity Analysis integration (see plan);
  Phases 1-6 (multi-meter/portfolio model, calendar/temperature features, change-point
  regression, classification families, clustering, pattern discovery, coincidence
  analysis, DER output layout) follow in subsequent changes.

---

## 2026-08-18 — Added kWh input support (unit conversion)

- Section 5 (new): Unit Conversion added to architecture between input validation and regularization.
- `config/analysis_config.toml [input]`: Added `unit` field ("kW" | "kWh"). Default: "kW".
- `src/load_profile/data_ingestion.py`: Added `convert_units()` function.
  - Conversion formula: `kW = kWh × (60 / resolution_minutes)`
  - Provenance: original meter reading preserved in `demand_input_raw` column.
  - No-op when unit is already "kW".
- `src/load_profile/pipeline.py`: `convert_units()` called after `validate_input()`, before `regularize()`.
- Notebook: Section 5 (Unit Conversion) added with formula table, side-by-side sample display, and Section 11 (round-trip verification comparing kW vs kWh inputs).
- Example files: `data/examples/office_building_15min_kwh.csv` added (same building, 15-min, values = kW ÷ 4).
- Round-trip verified: kW and kWh inputs produce identical baseline_kw, peak_kw, average_kw, classification, and start time (diff = 0.0000 across all days).

---

## 2026-08-18 — V1 implementation; provisional defaults applied for all unresolved questions

The V1 implementation (`src/load_profile/`) was built from the handoff package. The
following provisional defaults were chosen for unresolved questions so code could be
produced. Each should be confirmed or overridden during the Round 2 elicitation sessions.

**Baseline (Round 2A questions 8–19)**
- Q8: Accepted hybrid lowest-sustained-demand baseline (Method D). STATUS: DECIDED.
- Q9–12: Rolling median smoothing, 60-min window. STATUS: PROVISIONAL.
- Q13–14: 60-min minimum baseline persistence. STATUS: PROVISIONAL.
- Q15–16: Low-demand candidates = intervals below 10th percentile; representative value = median of longest qualifying run.
- Q17: Baseline is a single scalar per day. STATUS: DECIDED.
- Q18–19: Continuous-operation flag triggered when (peak − baseline) / daily_mean < 0.15.

**State detection (Round 2B questions 24–33)**
- Q24–25: V1 uses simple BASELINE / OPERATING two-state model. STATUS: DECIDED.
- Q26–27: Entry threshold α = 0.20; Exit threshold α = 0.15 (hysteresis). STATUS: PROVISIONAL.
- Q28–30: Hysteresis used; exit is a fixed lower fraction of range. STATUS: DECIDED.
- Q31–32: Minimum state persistence = 30 min. STATUS: PROVISIONAL.

**Normalization (Round 2C)**
- Q20–21: D_norm = (D − baseline) / (peak − baseline); peak = observed maximum. STATUS: DECIDED.
- Q22: peak == baseline → returns NaN (no division by zero). STATUS: DECIDED.

**Start/end detection (Round 2D–2E)**
- Q34–44 / Q45–52: Scoring-based candidate selection with configurable weights. Gradual start = transition duration > smoothing window. STATUS: PROVISIONAL.

**Ramp detection (Round 2F)**
- Q59–67: Reversal tolerance = 10% of cumulative change; all three rate units computed. STATUS: PROVISIONAL.

**Peak detection (Round 2G)**
- Q68–76: Local maxima with plateau collapse; prominence filter = 10% of range; minimum separation = 30 min. STATUS: PROVISIONAL.

**Breadth (Round 2H)**
- Q77–78: Operating thresholds 20/40/60/80/90%; peak thresholds 70/80/90%. STATUS: PROVISIONAL.
- Q79: Energy breadth computed (configurable). STATUS: PROVISIONAL.

**Classification (Round 2I)**
- Q87–93: One primary class (timing-based) + independent attribute list; rules TOML-driven. STATUS: DECIDED.

**Confidence (Round 2J)**
- Q94–100: 0–1 float; quality-adjusted by missing-data fraction near event. STATUS: PROVISIONAL.

**Max interpolation gap**
- Q1: Default = 60 min. STATUS: PROVISIONAL (not yet confirmed by user).

- ADR created: adr/001-baseline-method.md
- ADR created: adr/002-state-model.md
- ADR created: adr/003-classification-architecture.md
