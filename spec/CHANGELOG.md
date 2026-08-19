# Specification Changelog

Append-only. Newest entries at the top.

Format:

```
## YYYY-MM-DD — [summary]
- Section N: [what changed and why]
- ADR created: adr/NNN-name.md
```

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
