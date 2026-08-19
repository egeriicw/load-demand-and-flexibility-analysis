# Specification Changelog

Append-only. Newest entries at the top.

Format:

```
## YYYY-MM-DD — [summary]
- Section N: [what changed and why]
- ADR created: adr/NNN-name.md
```

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
