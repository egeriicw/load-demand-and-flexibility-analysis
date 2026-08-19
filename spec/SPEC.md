# Building Daily Load Profile Characterization Engine
## Working Specification

**Document status:** FROZEN — Version 1.0  
**Frozen:** 2026-08-19  
**Last updated:** 2026-08-19

---

## 1. Project Objective

Build a Python algorithm, ultimately implemented as an IPython/Jupyter notebook plus reusable Python functions/modules, that analyzes a building's daily electrical load profile and characterizes how the building operates.

The system should understand, among other things:

- probable daily start time
- probable daily end time
- startup ramp rate
- shutdown ramp rate
- other meaningful ramp events
- overnight/low-load behavior
- sustained operating demand
- breadth/width of sustained demand
- peak demand
- peak breadth
- peakiness
- multiple operating periods
- multiple peaks
- daily load-shape characteristics
- confidence in inferred events
- data quality and provenance

**Intent:** Not merely to calculate conventional statistics. The goal is to create a daily load-profile characterization engine that understands the behavioral structure of the load curve.

Conceptual example:

```
Demand
  ^
  |                         __________
  |                    ____/          \____
  |               ____/
  |          ____/
  |_________/
  |
  +------------------------------------------------> Time
           start       sustained demand     end
```

The algorithm should distinguish different shapes such as:

- low overnight demand followed by a sharp morning startup
- low overnight demand followed by a gradual startup
- broad sustained daytime operation
- narrow/sharp peaks
- broad/flat peaks
- multiple operating periods/shifts
- continuous/24-7 operation
- irregular or highly variable profiles

---

## 2. Fundamental Analytical Concept

**STATUS: LOCKED**

Preferred architecture:

```
Raw demand data
      |
      v
Timestamp validation
      |
      v
Unit conversion (kWh → kW if configured)
      |
      v
Time-series regularization
      |
      v
Missing-data interpolation
      |
      v
Data-quality assessment
      |
      v
Daily segmentation
      |
      v
Baseline estimation
      |
      v
Demand normalization
      |
      v
Demand-state detection
      |
      v
Transition/event detection
      |
      +-------------------+
      |                   |
      v                   v
  Ramp events        Peak events
      |                   |
      +---------+---------+
                |
                v
        Feature calculation
                |
                v
       Daily classification
                |
                v
       Confidence/diagnostics
                |
                v
             Outputs
```

The system must separate:

1. measurement
2. event detection
3. feature calculation
4. classification

Classification must NOT be responsible for determining the underlying measurements.

**Architectural principle:** The algorithm should first determine that a likely operating transition occurred around a particular time, with a particular magnitude and ramp rate. Only then should classification determine that the day resembles a "sharp morning startup" or similar category.

---

## 3. Current Status — VERSION 1.0 FROZEN 2026-08-19

The V1 implementation is complete and all provisional defaults are accepted as V1.0
decisions. All open questions in Section 50 are now resolved. The DER Opportunity
Analysis integration (Phases 0–6) is also complete (see Part II).

**V1.0 scope boundary**: the frozen spec covers the single-meter daily load profile
characterization engine (Part I) and the multi-meter DER Opportunity Analysis layer
(Part II, Phases 0–6). Future enhancements (composite peakiness scores, real-world
validation profiles, per-metric completeness overrides) are deferred to V2.

---

## 4. Locked Decisions

### 4.1 Timezone — STATUS: LOCKED

The system shall:

- accept timezone-aware timestamps
- use the timezone embedded in the timestamp when present
- use a configured timezone as fallback when timestamps are timezone-naive
- not silently assume UTC

### 4.2 Definition of a Day — STATUS: LOCKED

A day is the local calendar day in the building's specified timezone.

The primary analytical unit is the local calendar period from 00:00:00 through the end of the local calendar day.

The system does not use rolling 24-hour periods as the primary definition of a daily profile.

### 4.3 Daylight Saving Time — STATUS: LOCKED

Preserve actual local intervals.

- normal day may contain the expected number of intervals
- spring DST transition day may contain fewer intervals
- fall DST transition day may contain more intervals

Examples for 15-minute data:

- normal day = 96 intervals
- spring DST day = 92 intervals
- fall DST day = 100 intervals

Do NOT insert artificial observations solely to force every day to contain 24 hours or 96 15-minute intervals.

All duration calculations use actual elapsed time.

### 4.4 Input Time Resolution — STATUS: LOCKED

Support ANY regular interval including but not limited to 5-min, 10-min, 15-min, 30-min, 60-min.

The engine detects the native interval duration from timestamps.

The implementation must NOT hard-code assumptions that the data are 15-minute data.

Time-dependent calculations use actual elapsed duration.

### 4.5 Interpolation Method — STATUS: LOCKED

Linear interpolation, time-based (not interval-count-based):

```
D(t) = D1 + ((t - t1)/(t2 - t1)) * (D2 - D1)
```

### 4.6 Maximum Interpolation Gap — STATUS: PROVISIONAL

A maximum interpolation gap shall be configurable.

**Provisional default:** 60 minutes (`max_interpolation_gap_minutes = 60` in TOML).

> **Open question Q1:** Confirm 60-minute default or specify another value.

### 4.7 Preserve Data Provenance — STATUS: LOCKED

Original observations must not be overwritten. The analytical time series retains:

```
demand_kw
is_observed
is_interpolated
interpolation_method
```

Interpolated values must remain distinguishable from observed values.

### 4.8 Use of Interpolated Values — STATUS: LOCKED

Interpolated values may participate in state detection, transition detection, operating-period analysis, visualization, and profile normalization.

However:

- data-quality calculations must know how much data was interpolated
- outputs must retain provenance
- an interpolated observation must not be represented as an observed meter value

For peaks, distinguish:

```
observed_peak_kw
observed_peak_time
```

from:

```
profile_peak_kw
profile_peak_time
profile_peak_is_interpolated
```

### 4.9 Data Quality — STATUS: DECIDED

Use metric-specific quality requirements plus an overall daily quality assessment. Do not use only one global completeness threshold for every analytical metric.

Daily data-quality dimensions:

- expected interval count
- observed interval count
- interpolated interval count
- missing interval count
- completeness fraction
- interpolation fraction
- irregular timestamp count
- duplicate timestamp count
- longest missing gap
- quality status

> **Open question Q6:** Metric-specific completeness requirements are still unresolved.

---

## 4b. Unit Conversion

**STATUS: LOCKED**

The demand column in the source data may be expressed in either:

- **kW** — instantaneous average demand over the interval
- **kWh** — energy consumed during the interval

The configured unit is set in `[input] unit` in `analysis_config.toml`.

When the source is in kWh, values are converted to kW before any analysis:

```
kW = kWh × (60 / resolution_minutes)
```

| Interval | Factor |
|---|---|
| 5 min | × 12 |
| 15 min | × 4 |
| 30 min | × 2 |
| 60 min | × 1 |

The conversion uses the resolution detected from the timestamps, so it is correct for any regular interval and does not require user specification of the interval length.

**Provenance:** The original meter reading (in input units) is preserved in the `demand_input_raw` column. The `demand_kw` column always holds the working kW value used for all downstream analysis.

**Placement in pipeline:** Unit conversion occurs after timestamp validation and resolution detection, and before time-series regularization. All downstream modules — baseline, state detection, event detection, feature calculation, classification — operate exclusively on kW.

---

## 5. Provisional Core Input Data Model

**STATUS: PROVISIONAL**

Minimum input:

```
datetime
demand_kw
```

Optional fields:

```
meter_id
building_id
site_id
temperature_f
source_id
```

Column mappings are configurable.

---

## 6. Provisional Daily Profile Object

**STATUS: PROVISIONAL**

```python
DailyLoadProfile
```

Expected fields include:

```
date
meter_id
building_id

timezone
resolution_minutes

expected_intervals
observed_intervals
interpolated_intervals
missing_intervals

completeness_fraction
interpolation_fraction
data_quality_status
```

plus analytical features described in Section 36.

---

## 7. Baseline

**STATUS: DECIDED (provisional parameters)**

The baseline represents relatively inactive or lowest sustained building demand. It is NOT simply the minimum observed value.

**Method: Hybrid lowest-sustained-demand (Method D)**

> Identify a sustained low-demand region, then calculate a representative demand from that region using the median.

Implementation:

1. Compute the 10th percentile of the day's demand distribution as the low-demand threshold
2. Find all intervals at or below that threshold
3. Identify the longest contiguous run of such intervals
4. If that run persists for at least the minimum persistence duration, compute its median as the baseline
5. If no qualifying run exists, fall back to the percentile of the full-day distribution (continuous-operation path)

**Provisional parameters (all in TOML):**

```toml
[baseline]
method = "hybrid_sustained"
min_persistence_minutes = 60        # provisional — see Q13
low_demand_percentile = 10          # provisional — see Q15
continuous_operation_fallback_percentile = 10
continuous_operation_range_fraction = 0.15   # see Q18
```

> **Open questions Q13, Q14:** Confirm 60-minute minimum persistence.  
> **Open question Q15:** Confirm 10th percentile as low-demand threshold.  
> **Open question Q16:** Confirm median as the representative statistic.  
> **Open question Q17:** Baseline is a single scalar per day — confirm.  
> **Open questions Q18, Q19:** Continuous-operation criterion and fallback representation.

---

## 8. Smoothing

**STATUS: PROVISIONAL**

**Provisional method:** Rolling median (default).

**Rationale:** Suppresses short spikes without substantially changing transition shape.

**Provisional default window:** 60 minutes.

Both raw and smoothed demand are preserved:

```
demand_kw_raw       — original meter values
analysis_demand_kw  — smoothed signal used for state/event detection
```

> **Open questions Q9–Q12:** Confirm method (rolling_median), window (60 min), configurability, and preservation of raw signal.

---

## 9. Baseline Persistence

**STATUS: PROVISIONAL**

Minimum duration a low-demand region must persist to qualify as a baseline candidate: **60 minutes**.

> **Open questions Q13, Q14:** Confirm 60-minute default.

---

## 10. Continuous / 24-7 Operation

**STATUS: PROVISIONAL**

A building with no meaningful low-demand state is classified as continuous operation.

**Provisional criterion:** If `(peak_kw − baseline_kw) / daily_mean_kw < 0.15`, flag `is_continuous_operation = True`.

The system does NOT manufacture a false startup for continuous-operation days.

> **Open question Q18:** Confirm the exact criterion for continuous-operation detection.  
> **Open question Q19:** Is this a daily classification or a building-level flag?

---

## 11. Demand Normalization

**STATUS: DECIDED**

```
D_norm(t) = (D(t) - D_baseline) / (D_peak - D_baseline)
```

- 0 = baseline
- 1 = daily peak

When `D_peak == D_baseline`, return NaN (no division by zero).

The normalized representation is the primary basis for shape analysis. Absolute kW remains available for magnitude analysis.

**Provisional peak for normalization:** observed maximum (`peak_for_normalization = "observed_max"` in TOML). Alternative: p99.

> **Open questions Q20–Q23:** Confirm normalization form, peak choice, edge-case handling, and whether a robust peak is also needed.

---

## 12. Operating Threshold

**STATUS: PROVISIONAL**

```
T_entry = baseline_kw + alpha_entry * (peak_kw - baseline_kw)
T_exit  = baseline_kw + alpha_exit  * (peak_kw - baseline_kw)
```

**Provisional defaults:**

```toml
[operating_threshold]
alpha_entry = 0.20
alpha_exit  = 0.15
min_state_persistence_minutes = 30
```

> **Open questions Q26–Q33:** Confirm thresholds, hysteresis approach, and persistence duration.

---

## 13. Hysteresis

**STATUS: DECIDED (parameters provisional)**

Separate entry and exit thresholds are used to prevent rapid state flipping.

- Transition to OPERATING when demand ≥ `T_entry`
- Transition to BASELINE when demand ≤ `T_exit`

> **Open question Q30:** Confirm hysteresis magnitude (current: 5% difference between entry and exit).

---

## 14. State Model

**STATUS: DECIDED**

V1 uses a two-state model:

```
BASELINE
OPERATING
UNKNOWN   (intervals with NaN demand)
```

Richer behavior is derived from continuous normalized demand rather than additional discrete states.

> **Open question Q24:** Confirm two-state model or specify additional states for V2.

---

## 15. State Persistence

**STATUS: PROVISIONAL**

Minimum state persistence: **30 minutes**.

A state change that reverts in less than 30 minutes is collapsed back into the preceding state.

> **Open question Q31:** Confirm 30-minute minimum.  
> **Open question Q32:** Define the treatment of temporary excursions.

---

## 16. Start Detection

**STATUS: PROVISIONAL**

Start detection uses a scored-candidate approach:

1. Identify all BASELINE→OPERATING transitions
2. For each: measure ramp magnitude, ramp rate, persistence above threshold, baseline separation
3. Score each candidate using a weighted formula
4. Return the highest-scoring candidate as the probable start
5. Return `None` if no candidate meets minimum thresholds

**Minimum thresholds (provisional):**

```toml
[start_detection]
min_magnitude_kw        = 10.0
min_ramp_rate_kw_per_hr =  5.0
min_persistence_minutes = 30.0
```

**Scoring weights (provisional):**

```toml
weight_ramp_magnitude = 0.30
weight_ramp_rate      = 0.25
weight_persistence    = 0.25
weight_baseline_sep   = 0.20
```

Two timestamps are reported:

```
start_transition_time      — beginning of the upward ramp (before threshold crossing)
threshold_crossing_time    — first interval above T_entry
```

> **Open questions Q34–Q44:** See Section 50.

---

## 17. Gradual Starts

**STATUS: DECIDED**

The system distinguishes gradual from rapid starts.

- `is_gradual = True` when startup transition duration > smoothing window (currently 60 min)

The `start_transition_time` marks the beginning of the ramp; `threshold_crossing_time` is also reported separately.

> **Open question Q35–Q36:** Confirm gradual-start detection criterion.

---

## 18. Multiple Operating Periods

**STATUS: DECIDED (parameters provisional)**

The system supports multiple start/stop periods in one day. All valid periods are retained.

**Provisional parameters:**

```toml
[multiple_periods]
min_baseline_gap_minutes    = 60   # gap required to split two periods
min_period_duration_minutes = 30   # minimum to count as a real period
```

Periods are ranked by duration (rank 1 = longest).

> **Open questions Q53–Q58:** Confirm gap, duration, ranking, and multi-period definition.

---

## 19. Start Candidate Scoring

**STATUS: PROVISIONAL**

Weighted score across:

```
ramp_magnitude   (kW above baseline)
ramp_rate        (kW/hour over transition)
persistence      (hours above threshold after crossing)
baseline_sep     (demand separation from baseline at crossing)
```

Confidence is score adjusted down proportionally to missing-data fraction in a ±1 hour window around the event.

> **Open question Q41–Q43:** Confirm formula and default weights.

---

## 20. End / Shutdown Detection

**STATUS: PROVISIONAL**

Symmetric to start detection; separate TOML section for independent tuning.

Startups and shutdowns may have asymmetric parameters.

> **Open questions Q45–Q52:** See Section 50.

---

## 21. Ramp Definitions

**STATUS: DECIDED**

Three levels:

**Interval ramp** — change between adjacent observations:
```
R_i = (D_i - D_{i-1}) / elapsed_time_hours     [kW/hour]
```

**Ramp event** — a sequence of related positive or negative changes (small reversals tolerated).

**Operating transition** — a ramp event that produces a meaningful state change (BASELINE↔OPERATING).

---

## 22. Ramp Metrics

**STATUS: DECIDED**

For each ramp event:

```
event_type             ("UP" | "DOWN")
start_time
end_time
start_kw
end_kw
delta_kw
duration_hours

average_ramp_kw_per_hr
max_ramp_kw_per_hr
percent_change
normalized_ramp_rate   (per hour in normalised units)
confidence
is_operating_transition
```

---

## 23. Ramp Measurement Basis

**STATUS: DECIDED**

All three representations are computed:

- absolute kW/hour
- percentage change/hour
- normalized demand/hour

---

## 24. Small Reversals Within Ramps

**STATUS: PROVISIONAL**

A reversal within a ramp event is absorbed if its magnitude is less than **10%** of the cumulative preceding change in that direction.

> **Open question Q64:** Confirm 10% reversal tolerance.

---

## 25. What Constitutes a Meaningful Ramp?

**STATUS: PROVISIONAL**

Minimum thresholds (all configurable in TOML, must all be met):

```toml
[ramp_detection]
min_magnitude_kw         = 10.0
min_rate_kw_per_hr       =  5.0
min_duration_minutes     = 10.0
min_separation_minutes   = 15.0
```

> **Open questions Q60–Q61:** Confirm whether all three must be met or whether a scoring combination is used.

---

## 26. Peak Definitions

**STATUS: DECIDED**

Three levels:

**Peak interval** — highest observed demand interval.

**Peak event** — a local maximum satisfying prominence and separation criteria.

**Peak episode** — a sustained high-demand period around a peak (contiguous duration above a threshold fraction of the baseline-to-peak range).

The system does not treat every interval of a flat plateau as a separate peak.

---

## 27. Primary Peak

**STATUS: DECIDED**

Primary peak = highest observed demand interval.

Plateau handling: adjacent intervals within 1% of each other are collapsed to the plateau midpoint.

> **Open questions Q72–Q76:** Handling of interpolated peaks, bad-data spikes, and robust peak calculation.

---

## 28. Peak Episode / Width

**STATUS: PROVISIONAL**

Peak width is the contiguous duration above a normalised demand threshold, measured around the peak.

**Provisional thresholds:**

```toml
[breadth]
peak_thresholds = [0.70, 0.80, 0.90]
```

Outputs:
```
peak_width_70_hours
peak_width_80_hours
peak_width_90_hours
```

> **Open question Q77:** Confirm operating-breadth thresholds: 20/40/60/80/90%.  
> **Open question Q78:** Confirm peak-breadth thresholds: 70/80/90%.

---

## 29. Secondary Peaks

**STATUS: PROVISIONAL**

Secondary peaks satisfy:

```toml
[peak_detection]
min_prominence_fraction = 0.10   # fraction of baseline-to-peak range
min_separation_minutes  = 30.0
min_duration_minutes    =  5.0
```

Each secondary peak retains:

```
peak_time
peak_kw
prominence_kw
prominence_fraction
width_70_hours / width_80_hours / width_90_hours
separation_from_primary_hours
confidence
```

> **Open questions Q68–Q71:** Confirm exact local-peak algorithm, prominence, and separation.

---

## 30. Flat-Top Peaks

**STATUS: DECIDED**

Adjacent intervals within `plateau_tolerance_fraction` (default 1%) of each other are collapsed to a single plateau midpoint. One peak episode, not multiple separate peaks.

---

## 31. Isolated Spikes

**STATUS: PROVISIONAL**

A one-interval spike may be detected as the primary peak. A `robust_peak` (e.g., p99) may be calculated separately for normalization purposes.

> **Open question Q73–Q76:** Whether isolated spikes may be the primary peak and whether they influence normalization.

---

## 32. Peak Separation

**STATUS: PROVISIONAL**

Minimum temporal separation: **30 minutes** (configurable).

When two candidate peaks are closer than this, the one with lower prominence is dropped.

> **Open questions Q69, Q70:** Confirm prominence threshold and separation.

---

## 33. Peakiness

**STATUS: DECIDED**

V1 does not use a single composite peakiness score. Instead, the following independent dimensions are calculated:

```
peak_to_average_ratio
peak_to_baseline_ratio
peak_concentration_1hr       (fraction of daily energy in 1-hr window around peak)
peak_concentration_2hr
peak_width_70_hours
peak_width_80_hours
peak_width_90_hours
peak_prominence_kw
peak_prominence_fraction
```

A composite score may be considered for V2.

> **Open questions Q82–Q86:** Confirm which metrics are required in V1.

---

## 34. Breadth

**STATUS: PROVISIONAL**

**Operating breadth** — fraction of the day demand remains meaningfully above baseline:

```toml
operating_thresholds = [0.20, 0.40, 0.60, 0.80, 0.90]
```

Outputs:
```
duration_above_20pct_hours
duration_above_40pct_hours
duration_above_60pct_hours
duration_above_80pct_hours
duration_above_90pct_hours
```

**Energy breadth** — fraction of daily energy above each threshold (configurable; enabled by default).

> **Open question Q79:** Confirm energy-breadth calculation.  
> **Open question Q80:** How multiple operating periods affect breadth.  
> **Open question Q81:** Treatment of small gaps in duration-above-threshold calculations.

---

## 35. Daily Variability

**STATUS: PROVISIONAL**

V1 computes:

```
std_kw
cv                          (coefficient of variation)
mean_absolute_ramp_kw_per_hr
ramp_event_count
secondary_peak_count
```

> **Open question (see Section 50):** Which additional variability metrics are required in V1.

---

## 36. Provisional Daily Feature Vector

**STATUS: PROVISIONAL**

```
date
meter_id
building_id

timezone
resolution_minutes

dq_expected_intervals
dq_observed_intervals
dq_interpolated_intervals
dq_missing_intervals
dq_completeness_fraction
dq_interpolation_fraction
dq_longest_missing_gap_minutes
dq_quality_status

baseline_kw
average_kw
median_kw
minimum_kw
maximum_kw
std_kw
cv

is_continuous_operation

probable_start_time
start_threshold_crossing
start_kw
startup_delta_kw
startup_duration_hours
startup_ramp_kw_per_hr
startup_max_ramp_kw_per_hr
start_confidence
start_is_gradual

probable_end_time
end_threshold_crossing
end_kw
shutdown_delta_kw
shutdown_duration_hours
shutdown_ramp_kw_per_hr
shutdown_max_ramp_kw_per_hr
end_confidence
end_is_gradual

operating_period_count
total_operating_duration_hours

duration_above_20pct_hours
duration_above_40pct_hours
duration_above_60pct_hours
duration_above_80pct_hours
duration_above_90pct_hours
energy_frac_above_20pct
energy_frac_above_40pct
energy_frac_above_60pct
energy_frac_above_80pct
energy_frac_above_90pct

peak_kw
peak_time
peak_is_interpolated
peak_prominence_kw
peak_prominence_fraction
peak_width_70_hours
peak_width_80_hours
peak_width_90_hours
peak_confidence

peak_to_average_ratio
peak_to_baseline_ratio
load_factor
peak_concentration_1hr
peak_concentration_2hr

secondary_peak_count
ramp_event_count
up_ramp_count
down_ramp_count

mean_absolute_ramp_kw_per_hr
intraday_variability

primary_class
attributes
classification_confidence
classification_notes
```

---

## 37. Classification

**STATUS: DECIDED (taxonomy provisional)**

V1 uses deterministic, explainable, rule-based classification. Rules are configurable in TOML.

**Structure:** One primary daily shape class + multiple independent boolean attributes.

**Primary classes:**

```
CONTINUOUS          no meaningful low-demand state
EARLY_START         start before 06:00
MORNING_START       start 06:00–10:00
MIDDAY_START        start 10:00–14:00
EVENING_START       start ≥ 14:00
NO_CLEAR_START      building operated but no credible start detected
MINIMAL_LOAD        demand range negligible
UNKNOWN             insufficient information
```

**Attributes (independent; multiple may apply):**

```
rapid_start
gradual_start
rapid_shutdown
gradual_shutdown
long_operating_duration
short_operating_duration
broad_peak
sharp_peak
high_peak_concentration
multiple_operating_periods
multiple_peaks
high_intraday_variability
```

> **Open questions Q87–Q93:** Final taxonomy, mutual exclusivity, conflict resolution, rule definitions.

---

## 38. Classification Attribute Rules

**STATUS: PROVISIONAL**

```toml
[classification]
early_start_before_hour        =  6
morning_start_before_hour      = 10
midday_start_before_hour       = 14
rapid_start_ramp_kw_per_hr     = 50.0
long_operation_hours           = 10.0
short_operation_hours          =  4.0
broad_peak_width_80_hours      =  3.0
sharp_peak_width_80_hours      =  1.0
high_variability_cv_threshold  =  0.30
multi_period_min_count         =  2
```

---

## 39. Confidence

**STATUS: PROVISIONAL**

Scale: 0.0 – 1.0 (float).

Event-specific confidence values:

```
start_confidence
end_confidence
peak_confidence
classification_confidence
```

Confidence is reduced proportionally to missing-data fraction in the vicinity of the event.

Qualitative bands (not yet in output — pending decision):

```
HIGH    >= 0.75
MEDIUM  >= 0.50
LOW     >= 0.25
AMBIGUOUS < 0.25
```

> **Open questions Q94–Q100:** Confirm scale, formula, qualitative bands, and candidate-score exposure.

---

## 40. Data Quality and Confidence Interaction

**STATUS: DECIDED**

Data quality and analytical confidence are kept as separate concepts. Data quality is an input to confidence scoring but they are not the same value.

Events near missing-data windows receive reduced confidence proportional to the missing fraction in a ±1 hour window.

---

## 41. Smoothing and Raw Data

**STATUS: DECIDED**

Both signals are preserved and named explicitly:

```
demand_kw_raw       — original meter readings
analysis_demand_kw  — smoothed signal
```

Smoothed signal is used for: baseline estimation, state detection, start/end detection, ramp detection.  
Raw signal is used for: peak magnitude, observed peak time, data quality, provenance.

---

## 42. Configuration

**STATUS: LOCKED**

All material analytical thresholds are externalized to `config/analysis_config.toml`. No important analytical threshold is buried as a Python literal.

Configuration controls:

```
input column mappings
timezone
resolution handling
interpolation
data-quality thresholds
baseline method and parameters
normalization
operating thresholds
start detection
end detection
ramp detection
peak detection
peak-width thresholds
classification rules
smoothing
output paths
visualization settings
```

---

## 43. Notebook Structure

**STATUS: DECIDED**

```
1.  Configuration
2.  Imports
3.  Data Source Selection
4.  Input Validation & Timestamp Processing
5.  Time-Series Regularisation & Interpolation
6.  Daily Segmentation
7.  Data Quality Assessment (per day)
8.  Smoothing
9.  Baseline Estimation
10. Demand Normalization
11. State Detection
12. Start & End Detection
13. Ramp Event Detection
14. Peak Detection
15. Breadth Analysis
16. Feature Vector Assembly
17. Classification
18. Diagnostic Visualization
19. Full Population Run
20. Population-Level Summaries
21. Synthetic Test Suite
22. Export
23. Validation Examples — Visual Inspection
```

The notebook calls reusable Python functions; analytical logic is not embedded directly in cells.

---

## 44. Software Architecture

**STATUS: LOCKED**

Logical components:

```
config.py           configuration loading
data_ingestion.py   input loading, timestamp validation
time_series.py      regularization, interpolation, quality, smoothing, segmentation
baseline.py         baseline estimation
states.py           state detection, normalization
events.py           start, end, ramp, peak, operating-period detection
features.py         daily feature vector assembly
classification.py   rule-based classification
visualization.py    diagnostic and population plots
synthetic.py        test scenario generation
pipeline.py         end-to-end orchestrator
```

All functions use:

- descriptive names
- explicit type hints
- explicit units in variable names where useful
- algorithm explanations where non-obvious

---

## 45. Outputs

**STATUS: DECIDED**

Four output datasets:

| Dataset | Granularity |
|---|---|
| `daily_features` | One row per meter/building/day |
| `ramp_events` | One row per detected ramp event |
| `peak_events` | One row per detected peak event |
| `interval_analysis` | One row per regularised interval (diagnostic) |

All exports are CSV. Paths configurable in TOML.

---

## 46. Visualization Requirements

**STATUS: DECIDED**

For each selected daily profile, display (two-panel diagnostic):

**Panel 1 (absolute demand):**
- raw demand
- smoothed demand
- baseline (horizontal line)
- operating entry threshold
- operating exit threshold
- candidate starts (vertical markers)
- selected start (solid vertical line)
- candidate ends
- selected end
- ramp events (arrows)
- primary peak (star marker)
- secondary peaks (triangle markers)
- operating periods (shaded spans)

**Panel 2 (normalised demand):**
- normalised demand fill
- operating breadth thresholds
- peak breadth thresholds
- 0 and 1 reference lines

Interpolated observations must be visually distinct from observed observations (different color/linestyle).

---

## 47. Synthetic Test Suite

**STATUS: DECIDED**

21 scenarios implemented in `src/load_profile/synthetic.py`:

| # | Scenario | Key expected behaviour |
|---|---|---|
| 1 | `flat_continuous` | CONTINUOUS; no start/end |
| 2 | `classic_morning_startup` | MORNING_START; rapid_start |
| 3 | `gradual_startup` | start_is_gradual=True |
| 4 | `sharp_startup` | rapid_start; high ramp rate |
| 5 | `broad_peak` | broad_peak; width_80 ≥ 3 hr |
| 6 | `narrow_peak` | sharp_peak; width_80 ≤ 1 hr |
| 7 | `two_shift` | multiple_operating_periods |
| 8 | `247_operation` | CONTINUOUS |
| 9 | `demand_spike` | peak detected at spike |
| 10 | `multi_stage_startup` | ≥2 UP ramps |
| 11 | `gradual_shutdown` | end_is_gradual=True |
| 12 | `abrupt_shutdown` | rapid_shutdown |
| 13 | `multiple_peaks` | secondary_peak_count ≥ 1 |
| 14 | `missing_data` | quality flags; gap ≥ 100 min |
| 15 | `interpolated_gaps` | interpolation_fraction > 0 |
| 16 | `irregular_data` | irregular timestamps flagged |
| 17 | `dst_spring` | intervals < normal day |
| 18 | `dst_fall` | intervals > normal day |
| 19 | `short_operating_period` | short_operating_duration |
| 20 | `minimal_variation` | CONTINUOUS or MINIMAL_LOAD |
| 21 | `highly_variable` | high_intraday_variability |

---

## 48. Validation

**STATUS: DECIDED**

For real-world profiles, manual inspection must be possible for:

- baseline
- operating states
- candidate transitions
- selected start/end
- ramps
- peaks
- calculated metrics
- classification

The diagnostic visualization (Section 46) supports this.

---

## 49. Test Acceptance Criteria

**STATUS: UNRESOLVED**

> **Open questions Q101–Q106:** Define acceptable error tolerances for:
> - start/end time detection (e.g. ±1 interval, ±30 min)
> - ramp magnitude and rate
> - peak detection
> - classification pass criteria

For synthetic data, expected values can be exact. For real data, tolerance-based validation is needed.

---

## 50. Open Question Register — ALL RESOLVED (V1.0 FREEZE 2026-08-19)

All questions resolved. Provisionals accepted as V1.0 decisions unless noted otherwise.

### A. Time / Data Quality

- [x] Q1: Max interpolation gap = **60 min** — DECIDED 2026-08-19
- [x] Q2: Duplicate timestamps → **keep first occurrence** — DECIDED 2026-08-19
- [x] Q3: Negative demand → **ERROR severity by default; pipeline aborts. Configurable to WARNING (NaN treatment) or INFO via `[data_quality].negative_demand_severity`. See ADR 005** — DECIDED 2026-08-19
- [x] Q4: Zero demand → **treated as observed (valid)** — DECIDED 2026-08-19
- [x] Q5: Long missing periods → **left as NaN after max gap; no further action** — DECIDED 2026-08-19
- [x] Q6: Metric-specific completeness → **uniform `min_completeness_fraction = 0.75` for all daily metrics; no per-metric override in V1** — DECIDED 2026-08-19
- [x] Q7: DST timestamps → **tz-aware DatetimeIndex throughout; ambiguous DST timestamps localized with `ambiguous='infer'`, non-existent timestamps with `nonexistent='shift_forward'`** — DECIDED 2026-08-19

### B. Baseline

- [x] Q8: Accept hybrid lowest-sustained-demand baseline? **YES — DECIDED 2026-08-18**
- [x] Q9: Smoothing method = **rolling_median** — DECIDED 2026-08-19
- [x] Q10: Rolling median as default = **YES** — DECIDED 2026-08-19
- [x] Q11: Smoothing window = **60 min** — DECIDED 2026-08-19
- [x] Q12: 60 min as default window = **YES** — DECIDED 2026-08-19
- [x] Q13: Minimum baseline persistence = **60 min** — DECIDED 2026-08-19
- [x] Q14: 60 min as default persistence = **YES** — DECIDED 2026-08-19
- [x] Q15: Low-demand candidate region = **intervals below 10th percentile of daily demand** — DECIDED 2026-08-19
- [x] Q16: Representative baseline = **median of the longest qualifying contiguous run** — DECIDED 2026-08-19
- [x] Q17: Baseline is single scalar per day = **YES** — DECIDED 2026-08-19
- [x] Q18: 24/7 identification = **(peak − baseline) / daily_mean < 0.15** — DECIDED 2026-08-19
- [x] Q19: No-meaningful-baseline fallback = **10th percentile of full-day distribution** — DECIDED 2026-08-19

### C. Normalization

- [x] Q20: Baseline-to-peak normalized demand as primary shape representation? **YES — DECIDED 2026-08-18**
- [x] Q21: Peak for normalization = **observed_max by default; `peak_for_normalization = "p99"` configurable** — DECIDED 2026-08-19
- [x] Q22: peak == baseline → **Return NaN — DECIDED 2026-08-18**
- [x] Q23: Robust peak available separately = **YES via config (`peak_for_normalization = "p99"`); not separately exposed as a distinct metric in V1** — DECIDED 2026-08-19

### D. State Detection

- [x] Q24: States in V1 = **BASELINE / OPERATING / UNKNOWN — DECIDED 2026-08-18**
- [x] Q25: Simple two-state model = **YES — DECIDED 2026-08-18**
- [x] Q26: Operating entry threshold = **alpha_entry = 0.20** — DECIDED 2026-08-19
- [x] Q27: 20% as default = **YES** — DECIDED 2026-08-19
- [x] Q28: Exit threshold = **alpha_exit = 0.15** — DECIDED 2026-08-19
- [x] Q29: Hysteresis used = **YES — DECIDED 2026-08-18**
- [x] Q30: Hysteresis magnitude = **5 percentage points (alpha_entry − alpha_exit = 0.05)** — DECIDED 2026-08-19
- [x] Q31: State persistence = **30 min minimum** — DECIDED 2026-08-19
- [x] Q32: Temporary excursion = **state change lasting < min_state_persistence_minutes is suppressed** — DECIDED 2026-08-19
- [x] Q33: State interaction with interpolation = **state machine runs on analysis_demand_kw (regularized + smoothed); interpolated intervals treated identically to observed for state purposes** — DECIDED 2026-08-19

### E. Start Detection

- [x] Q34: Start candidate conditions = **threshold crossing (BASELINE → OPERATING) with minimum magnitude, ramp rate, and post-crossing persistence all met** — DECIDED 2026-08-19
- [x] Q35: Gradual start = **transition duration > smoothing window (60 min)** — DECIDED 2026-08-19
- [x] Q36: `start_transition_time` = **local minimum of analysis_demand_kw immediately before the threshold crossing** — DECIDED 2026-08-19
- [x] Q37: `operating_threshold_crossing_time` reported = **YES** — DECIDED 2026-08-19
- [x] Q38: Minimum startup magnitude = **10 kW** — DECIDED 2026-08-19
- [x] Q39: Minimum startup ramp rate = **5 kW/hr** — DECIDED 2026-08-19
- [x] Q40: Minimum startup persistence = **30 min above threshold** — DECIDED 2026-08-19
- [x] Q41: Candidate scoring = **weighted sum of four components: ramp_magnitude, ramp_rate, persistence, baseline_separation** — DECIDED 2026-08-19
- [x] Q42: Default weights = **0.30 / 0.25 / 0.25 / 0.20** — DECIDED 2026-08-19
- [x] Q43: Data quality effect on confidence = **proportional reduction based on missing-data fraction in ±1-hr window around the start event** — DECIDED 2026-08-19
- [x] Q44: No credible start = **return None; day flagged `start_detected = False`** — DECIDED 2026-08-19

### F. End Detection

- [x] Q45: End candidate conditions = **demand drops below exit threshold (OPERATING → BASELINE) with minimum magnitude, ramp rate, and post-crossing persistence** — DECIDED 2026-08-19
- [x] Q46: Startup/shutdown rules asymmetric = **NO; symmetric defaults (same thresholds and weights)** — DECIDED 2026-08-19
- [x] Q47: Minimum shutdown magnitude = **10 kW** — DECIDED 2026-08-19
- [x] Q48: Minimum shutdown ramp rate = **5 kW/hr** — DECIDED 2026-08-19
- [x] Q49: Minimum shutdown persistence = **30 min below threshold** — DECIDED 2026-08-19
- [x] Q50: End scoring = **same four-component weighted sum as start** — DECIDED 2026-08-19
- [x] Q51: Default end weights = **0.30 / 0.25 / 0.25 / 0.20 (same as start)** — DECIDED 2026-08-19
- [x] Q52: No credible end = **return None; day flagged `end_detected = False`** — DECIDED 2026-08-19

### G. Multiple Periods

- [x] Q53: Period separator = **return to BASELINE for ≥ min_baseline_gap_minutes** — DECIDED 2026-08-19
- [x] Q54: Minimum baseline gap = **60 min** — DECIDED 2026-08-19
- [x] Q55: Minimum period duration = **30 min** — DECIDED 2026-08-19
- [x] Q56: Period ranking = **by duration (longest first)** — DECIDED 2026-08-19
- [x] Q57: MULTI_PERIOD = **operating_period_count ≥ 2** — DECIDED 2026-08-19
- [x] Q58: Primary operating period = **longest by duration** — DECIDED 2026-08-19

### H. Ramp Events

- [x] Q59: Ramp event = **contiguous monotone demand change (with reversal tolerance) meeting all three minimum criteria** — DECIDED 2026-08-19
- [x] Q60: All three criteria required = **YES (magnitude AND rate AND duration)** — DECIDED 2026-08-19
- [x] Q61: Threshold-based, not score-based = **YES; all three are independent minimum gates, not a combined score** — DECIDED 2026-08-19
- [x] Q62: Ramp calculated on = **smoothed demand (analysis_demand_kw)** — DECIDED 2026-08-19
- [x] Q63: Reversal tolerance = **10% of cumulative preceding change** — DECIDED 2026-08-19
- [x] Q64: 10% as default = **YES** — DECIDED 2026-08-19
- [x] Q65: Max gap inside ramp = **none explicit; reversal tolerance handles brief pauses** — DECIDED 2026-08-19
- [x] Q66: Minimum ramp separation = **15 min** — DECIDED 2026-08-19
- [x] Q67: All three ramp metrics computed = **YES (magnitude, rate, duration — all reported)** — DECIDED 2026-08-19

### I. Peaks

- [x] Q68: Peak detection = **local maxima on smoothed demand with plateau collapse** — DECIDED 2026-08-19
- [x] Q69: Minimum prominence = **10% of baseline-to-peak range** — DECIDED 2026-08-19
- [x] Q70: Minimum temporal separation = **30 min** — DECIDED 2026-08-19
- [x] Q71: Minimum duration = **5 min** — DECIDED 2026-08-19
- [x] Q72: Plateaus collapsed = **to plateau midpoint timestamp** — DECIDED 2026-08-19
- [x] Q73: Isolated spikes = **treated as valid peaks if prominence threshold met; flagged as isolated when width = resolution_minutes** — DECIDED 2026-08-19
- [x] Q74: One-interval spike can be primary peak = **YES — global daily maximum is always the primary peak regardless of width** — DECIDED 2026-08-19
- [x] Q75: Robust/analysis peak separate = **NO separate robust peak metric in V1; p99 available only as normalization denominator via config** — DECIDED 2026-08-19
- [x] Q76: Interpolated peak in normalization = **demand_kw value used as-is at peak timestamp; peak flagged `is_interpolated = True`; confidence reduced proportionally** — DECIDED 2026-08-19

### J. Breadth

- [x] Q77: Operating breadth thresholds = **20 / 40 / 60 / 80 / 90%** — DECIDED 2026-08-19
- [x] Q78: Peak breadth thresholds = **70 / 80 / 90%** — DECIDED 2026-08-19
- [x] Q79: Energy breadth computed = **YES, configurable (`compute_energy_breadth = true`)** — DECIDED 2026-08-19
- [x] Q80: Multiple periods and breadth = **breadth computed over the full day; period segmentation does not affect breadth calculation in V1** — DECIDED 2026-08-19
- [x] Q81: Small gaps in duration-above-threshold = **OPERATING state gaps < min_state_persistence_minutes count as OPERATING for breadth; consistent with state persistence model** — DECIDED 2026-08-19

### K. Peakiness

- [x] Q82: Multiple metrics, no composite score = **YES — DECIDED 2026-08-18**
- [x] Q83: V1 peakiness metrics = **all nine listed in Section 33: peak_to_average_ratio, peak_to_baseline_ratio, peak_concentration_1hr, peak_concentration_2hr, peak_width_70/80/90_hours, peak_prominence_kw, peak_prominence_fraction** — DECIDED 2026-08-19
- [x] Q84: Peak concentration = **fraction of daily energy within ±30 min of peak timestamp** — DECIDED 2026-08-19
- [x] Q85: Peak prominence = **height above the highest valley between this peak and the nearest higher-magnitude peak** — DECIDED 2026-08-19
- [x] Q86: Peak isolation = **minimum temporal distance (minutes) to the nearest other detected peak of any prominence** — DECIDED 2026-08-19

### L. Classification

- [x] Q87: Primary classification taxonomy = **as defined in Section 37; TOML-configurable thresholds** — DECIDED 2026-08-19
- [x] Q88: Classification mutually exclusive = **YES — DECIDED 2026-08-18**
- [x] Q89: One primary class plus secondary attributes = **YES — DECIDED 2026-08-18**
- [x] Q90: Rule determination = **TOML-driven priority-ordered rules; first matching rule sets primary_class** — DECIDED 2026-08-19
- [x] Q91: Multiple classes apply equally = **not possible by design — priority ordering guarantees a unique winner** — DECIDED 2026-08-19
- [x] Q92: Classification confidence computed = **YES, as `classification_confidence` (0–1 float)** — DECIDED 2026-08-19
- [x] Q93: Rules fully TOML-configurable = **YES — DECIDED 2026-08-18**

### M. Confidence

- [x] Q94: 0–1 confidence scale = **YES — DECIDED 2026-08-18**
- [x] Q95: Scoring formula = **confidence = base_score × quality_factor; base_score = normalized weighted candidate score (0–1); quality_factor = 1 − missing_fraction in ±1-hr window around event** — DECIDED 2026-08-19
- [x] Q96: Qualitative bands = **HIGH ≥ 0.75 / MEDIUM ≥ 0.50 / LOW ≥ 0.25 / AMBIGUOUS < 0.25** — DECIDED 2026-08-19
- [x] Q97: Ambiguous cases = **AMBIGUOUS band (<0.25) signals confidence too low to rely on; callers should treat the result as provisional** — DECIDED 2026-08-19
- [x] Q98: Confidence event-specific = **YES — DECIDED 2026-08-18**
- [x] Q99: Data quality affects confidence = **YES — DECIDED 2026-08-18**
- [x] Q100: Candidate scores exposed = **NO in V1; only winning confidence value and qualitative band surfaced** — DECIDED 2026-08-19

### N. Testing

- [x] Q101: Expected outputs = **21 synthetic scenarios in `synthetic.py` (Section 47) are the V1 acceptance test suite; current passing test results constitute the frozen expected outputs** — DECIDED 2026-08-19
- [x] Q102: Start/end tolerance = **±30 min (one smoothing window)** — DECIDED 2026-08-19
- [x] Q103: Ramp tolerance = **magnitude ±10%, rate ±20%** — DECIDED 2026-08-19
- [x] Q104: Peak tolerance = **timing ±15 min; magnitude ±5% of daily demand range** — DECIDED 2026-08-19
- [x] Q105: Passing classification = **correct `primary_class` for all 21 synthetic scenarios; secondary attributes must have no false positives** — DECIDED 2026-08-19
- [x] Q106: Real-world profiles = **not required for V1; synthetic suite is sufficient. Deferred to V2** — DECIDED 2026-08-19

---

## 51. Elicitation Rounds — COMPLETE (V1.0 FREEZE 2026-08-19)

All elicitation rounds completed. All questions resolved as of V1.0 freeze.

| Round | Topics | Status |
|---|---|---|
| **2A** | Baseline | ✓ All resolved (Q8–Q19) |
| **2B** | Operating states | ✓ All resolved (Q24–Q33) |
| **2C** | Start detection | ✓ All resolved (Q34–Q44) |
| **2D** | End detection | ✓ All resolved (Q45–Q52) |
| **2E** | Multiple operating periods | ✓ All resolved (Q53–Q58) |
| **2F** | Ramp detection | ✓ All resolved (Q59–Q67) |
| **2G** | Peak detection | ✓ All resolved (Q68–Q76) |
| **2H** | Breadth and peakiness | ✓ All resolved (Q77–Q86) |
| **2I** | Classification | ✓ All resolved (Q87–Q93) |
| **2J** | Confidence | ✓ All resolved (Q94–Q100) |
| **2K** | Testing and acceptance | ✓ All resolved (Q101–Q106) |

The frozen Version 1.0 specification is this document in its current state, incorporating all decisions from the open question register above.

---

## Appendix A: Configuration Schema Reference

See `config/analysis_config.toml` for the full annotated configuration file.

Key sections:

```toml
[input]
[timezone]
[data_quality]
[smoothing]
[baseline]
[normalization]
[operating_threshold]
[start_detection]
[end_detection]
[multiple_periods]
[ramp_detection]
[peak_detection]
[breadth]
[classification]
[output]
[visualization]
```

## Appendix B: Implementation Files

```
src/load_profile/
  config.py
  data_ingestion.py
  time_series.py
  baseline.py
  states.py
  events.py
  features.py
  classification.py
  visualization.py
  synthetic.py
  pipeline.py

notebooks/
  load_profile_analysis.ipynb

config/
  analysis_config.toml

spec/
  SPEC.md          ← this file
  CHANGELOG.md
  README.md
  adr/
```

---

## Part II — DER Opportunity Analysis Integration

A separate functional spec ("Load Pattern, Flexibility, and DER Opportunity Analysis
Engine") is being integrated into this codebase, adding multi-meter/portfolio
analysis, temperature-driven change-point regression, K-means clustering, pattern
discovery, and meter coincidence analysis on top of the single-meter engine described
in Part I above. Integration proceeds in phases (0-6); this part of SPEC.md grows one
section per phase as it lands. See `spec/CHANGELOG.md` for the phase-by-phase log and
`spec/adr/004+` for the individual decisions.

Architecturally: the existing single-meter `run_pipeline()` is unchanged and reused —
a new `src/load_profile/der/` subpackage calls it once per configured meter and builds
all DER-layer capability (aggregation, enrichment, classification, clustering,
coincidence, output) on top of its `interval_df`/`daily_df` results. Nothing under
`der/` is imported by the root package; the dependency direction is one-way.

## 52. Configuration Validation (Phase 0)

**STATUS: DECIDED**

Config loading now runs structural validation before any data is loaded:

- `config_schema.validate_config(cfg) -> ConfigValidationReport` — a list of
  `ConfigIssue(severity, path, message)` findings, severity one of `INFO` / `WARNING`
  / `ERROR`. Purely structural: it never opens the data file.
- `load_config(path=None, validate=True)` calls `validate_config()` and raises
  `ConfigValidationError` if any `ERROR`-severity issue is found. Callers that need the
  raw dict regardless (e.g. tests exercising a deliberately malformed file) pass
  `validate=False`.
- Validation coverage today: `[input].unit`, `[data_quality].max_interpolation_gap_minutes`,
  `[data_quality].min_completeness_fraction`, `[data_quality].negative_demand_severity`,
  and a `WARNING`-level check that `[start_detection]`/`[end_detection]` scoring
  weights sum to ~1.0. Each later integration phase adds its own section's validator
  (e.g. `[[meters]]`/`[[meter_groups]]`/`[portfolio]` in Phase 1) rather than one
  monolithic function.
- Cycle detection for `[[meter_groups]]` (needed starting Phase 1) is implemented now
  as a standalone, TOML-key-agnostic DFS helper:
  `config_schema._detect_meter_group_cycles(group_children: dict[str, list[str]]) ->
  list[str]` — returns the group names forming the first cycle found, or `[]`.

### Configurable negative-demand severity

`data_quality.negative_demand_severity`, one of `INFO`/`WARNING`/`ERROR`, default
`ERROR`: negative demand is unsupported
by design and rejected by default, per the DER spec. `validate_input()` stays
report-only (never raises) — it routes the finding into `report["issues"]` (`ERROR`),
`report["warnings"]` (`WARNING`), or emits nothing beyond the count (`INFO`). The new
`check_validation_report(report, cfg)` is the actual gate: `run_pipeline()` calls it
right after `validate_input()` and raises `ValueError` when severity dictates
rejection. `time_series.regularize()`'s existing negative→NaN handling is unchanged —
it still runs unconditionally for whichever severities don't abort first (see ADR 005
for why that split is deliberate, not an oversight).

## 53. Multi-Meter & Portfolio Model, Entity Aggregation (Phase 1)

**STATUS: DECIDED**

New subpackage `src/load_profile/der/` implements the multi-meter layer. It calls the
unchanged single-meter `pipeline.run_pipeline()` once per configured meter and builds
everything else on top of the results — see ADR 006.

**Configuration** (`config/analysis_config.toml`, all empty/absent by default so the
DER pipeline stays inert until populated):
- `[[meters]]` — `meter_id` (required, unique), `display_name`, `building_id`,
  `source` (path or in-memory DataFrame — anything `load_demand_data` already accepts).
  Every meter shares the *same* `[input]` column-mapping; per-meter column overrides
  are out of scope for now (see ADR 006 rationale).
- `[[meter_groups]]` — `name` (required, unique), `meters` (direct member meter_ids),
  `child_groups` (other group names, resolved recursively). Supports flat, hierarchical,
  and overlapping membership (a meter or group may appear under multiple parents).
- `[portfolio]` — `excluded_meters`; portfolio is always *all* `[[meters]]` minus this
  list.
- `[der.aggregation]` — `min_count` (default `1`): minimum number of reporting meters
  required for an entity's summed demand to be non-NaN at a given timestamp.

**Resolution** (`der/meters.py`):
- `resolve_meter_groups(cfg) -> dict[str, list[str]]` — recursive, memoized, returns
  each group's full deduplicated/sorted leaf meter_id set. Cycles are rejected both by
  `config_schema.validate_config` (structural, before any data loads) and defensively
  inside resolution itself if reached directly.
- `resolve_portfolio(cfg) -> list[str]`.

**Aggregation** (`der/aggregation.py`) — see ADR 007 for the full column-mapping
rationale, summarized here:
- `aggregate_entity(interval_df_multi, meter_ids, min_count=1) -> DataFrame` sums the
  `demand_kw` column (the `regularize()`-output, quality-cascaded,
  observed-else-interpolated-else-NaN value — **not** the smoothed
  `analysis_demand_kw` column used for baseline/state detection) across the given
  meters via `groupby(...).sum(min_count=...)`. **Never averages.** An all-non-reporting
  timestamp for the given subset stays NaN, never a false 0.
- `n_meters_reporting` — count of non-null contributing meters, attached alongside the
  sum so partial coverage is never silently absorbed.
- `build_entity_frame(entity_id, meter_ids, interval_df_multi, cfg)` wraps the above,
  stamps `entity_id`, derives `is_missing`. Deliberately does not attempt aggregate-level
  `is_observed`/`is_interpolated` flags — no well-defined cross-meter meaning.

**Canonical fields** — `regularize()` gained an additive `data_quality_flag` column
(`"observed"|"interpolated"|"missing"`); `run_pipeline()`'s returned `interval_df` now
also surfaces `demand_kw_raw` alongside it (both already computed, previously not
selected into the output). DER spec's `observed_demand_kw` maps onto `demand_kw_raw`;
DER's `analysis_demand_kw` maps onto `demand_kw` (see ADR 007 — explicitly *not* onto
the existing smoothed `analysis_demand_kw` column, despite the name match).

**Orchestration** (`der/pipeline.py`): `run_der_pipeline(cfg) -> DERResult` loops
`[[meters]]`, runs `run_pipeline()` per meter unchanged, tags each meter's `interval_df`
with `meter_id`, concatenates, then builds an aggregated entity frame for every resolved
group and the portfolio. `DERResult` holds per-meter tables, per-entity frames, the
resolved entity→meter_ids mapping, and the tagged multi-meter interval table.

## 54. Calendar Features, Time-of-Day Segments, External Temperature (Phase 2)

**STATUS: DECIDED**

`der/calendar_features.py` and `der/temperature.py` are both **generic**: they accept
any DataFrame with a tz-aware `DatetimeIndex` (an entity's aggregated frame, or a
meter's own `interval_df`) — they are not hard-wired to the entity model. `run_der_pipeline`
applies them automatically to every non-empty entity frame; per-meter enrichment is a
direct call the same functions on `meter_tables[meter_id]["interval_df"]`.

**Calendar features** (`add_calendar_features`, DER spec §2.4): `date`, `year`, `month`,
`day`, `day_of_year`, `hour`, `minute`, `day_of_week` (Monday=0), `day_name`,
`is_weekday`/`is_weekend` (calendar-only, holiday-independent), `season` (config
`[der.calendar].season_map`, default meteorological Northern Hemisphere), `day_type`
(`"weekday"|"weekend"|"holiday"` — `[der.calendar].holidays` overrides).

**Time-of-day segments** (`add_time_of_day_segments`, DER spec §5.1): one row per date,
`{segment}_peak_kw` for each `[der.time_of_day.segments]` window (default
morning[6,10)/midday[10,14)/afternoon[14,18)/evening[18,22)), `overnight_mean_kw` /
`nighttime_mean_kw` (alias) over hours {22,23,0..5}, `daytime_mean_kw` over hours
{6..21}. All aggregations skip NaN; vectorized via `Series.where(mask)` +
`groupby(date).max()/.mean()`.

**External temperature** (`load_temperature_data`/`merge_temperature`/`band_temperature`,
DER spec §5.2 partial — ingestion/join/banding only; the change-point regression model
family is Phase 3): loaded once per `run_der_pipeline()` call from
`[der.temperature].source` (path or DataFrame; unset = temperature-dependent analysis
degrades gracefully, no error), joined onto each entity's calendar frame via nearest-
timestamp `merge_asof` (`[der.temperature].join_tolerance_minutes`,
`.override_existing`), then banded via `pd.cut` (`[der.temperature.bands].boundaries`,
default `[32,50,65,80,90]` → `"below-32"`..`"90-above"`, NaN temperature → NaN band).

`DERResult` gained `entity_calendar_frames`, `entity_tod_frames`,
`entity_temperature_frames` (the last populated only when a temperature source is
configured).

**Caught during implementation:** `run_der_pipeline`'s original temperature-source
check (`if temp_source:`) raised on a DataFrame source (`ValueError: The truth value of
a DataFrame is ambiguous`) — any config value that may be a path *or* a DataFrame must
be checked with `is not None`, never plain truthiness. Fixed; see ADR 009.

## 55. Change-Point Regression, Demand Classification, DER Peak Events, Load-Shape Classification (Phase 3)

**STATUS: DECIDED**

**Change-point / balance-point regression** (`der/change_point.py`, DER spec §5.2 —
statistical/modeled relationship, not a causal claim): `fit_2p` (OLS), `fit_3p_cooling`/
`fit_3p_heating` (1°F-step grid search + OLS per candidate), `fit_4p`/`fit_5p` (grid
search + `scipy.optimize.lsq_linear`, slopes bounded ≥0). `select_best_change_point_model`
fits all five and picks by adjusted R² (`1-(1-R²)(n-1)/(n-p-1)`), excluding candidates
that fail their own minimum-point guard or where `n-p-1<=0`; ties go to the simpler
(lower-parameter-count) model; returns `None` if every candidate is excluded — callers
must treat that as "no model could be fit," not "temperature-independent." Functions
operate on plain `x`/`y` arrays; weekday-only filtering, daily-mean aggregation, etc.
are the caller's responsibility. See ADR 010 (including a noted `O(candidates²)` cost
for 5P's joint grid search).

**Demand classification families** (`der/demand_classification.classify_demand_families`,
§5.3): threshold (`meets_threshold_<kw>`), percentile (`top_pct_<pp>`), rank
(`top_rank_<n>`) — independent boolean columns, `[der.demand_classification]`
TOML-configured, never collapsed into one generic flag.

**Local peak/valley** (`der/local_extrema.add_local_extrema_flags`, §5.4): strict
3-point comparator (`d[i]>d[i-1] and d[i]>d[i+1]`, mirrored for valleys) on raw
`demand_kw`; boundary rows and any NaN-adjacent row default to `False`. Deliberately
separate from `events.py`'s prominence-based detection on the smoothed series.

**DER peak events** (`der/peak_events.detect_der_peak_events`, §5.5): contiguous
grouping of any boolean "meets criterion" series via `[der.peak_events].allowable_gap_intervals`
(gap-bridged, extends through intervening non-qualifying intervals),
`event_id = f"{entity_id}_{definition}_{seq:04d}"`, `duration_class` sustained/short via
`.sustained_threshold_hours`. `DERPeakEvent` — explicitly separate from `events.PeakEvent`
(different definition, different mechanism; see ADR 011). Composes with any of the
three classification families above (or any other boolean column) without coupling.

**Load-shape classification** (`der/load_shape.classify_load_shape`, §5.6): merges
per-day stats with Phase 2's `add_time_of_day_segments` output and Phase 3's local
extrema flags into independent boolean flags (`is_flat`, `is_highly_peaked`,
`has_{segment}_peak`, `is_overnight_heavy`, `is_multi_peak`, `has_sharp_peak`,
`has_sustained_high_load`, `has_peak_valley_pattern`, `is_unusual`) plus a
priority-ordered **`der_primary_shape`** (distinctly named vs. `classify_day`'s
`primary_class`; see ADR 012). `[der.load_shape]` TOML-configured thresholds.

**Caught during implementation** (see ADR 012): `bool(float("nan"))` is `True` in
Python, so a naive truthiness check on a boolean flag left `NaN` by the day-keyed
`tod_df` left-join would silently satisfy every priority-order rule. Fixed via an
explicit `_is_true(x)` helper (`x is True or x == True`) used throughout
`_primary_shape`, with a regression test constructing exactly that missing-day
scenario.

## 56. K-Means Clustering & Pattern Discovery (Phase 4)

**STATUS: DECIDED**

New dependency: `scikit-learn>=1.7.0` (`pyproject.toml`), first used here.

**Clustering** (`der/clustering.py`, DER spec §5.7/§19-20 — statistical, not causal):
`peak_normalized_series` computes DER's own §2.7 `normalized_demand`
(`demand_kw / daily_peak_demand_kw`) fresh — **not** `states.compute_normalized_demand`
(a different, baseline-subtracted quantity; same naming-collision discipline as ADR
007). `build_daily_profile_matrix` pivots complete days only into a
`(day × interval_index)` matrix. `select_k` (silhouette-driven auto-k, `max_k=8`,
`<4` complete days forces `k=1`, an unscoreable k is skipped) and
`cluster_daily_profiles` (`KMeans(random_state=42, n_init=10)`, `<2` days fails,
per-cluster `cluster_size`/`percentage_of_days`/`representative_peak`/
`within_cluster_variability`). `cluster_entity_daily_profiles` computes **both**
absolute and normalized clustering, never just one, per spec.

**Pattern discovery** (`der/patterns.py`, DER spec §5.8/§21 — heuristic/statistical,
never causal): `build_daily_summary` (per-day `is_complete_day`, `daily_energy_kwh`,
`maximum_demand_kw`, `peak_time_minutes`). `find_recurring_peak_timing` (bucketed by
`[der.patterns].peak_timing_window_minutes`, `min_occurrences` threshold,
`statistical_support` = fraction of complete days). `find_recurring_shape` (grouped by
a caller-supplied `der_primary_shape` column, excluding `insufficient_data`, same
support-fraction denominator as peak timing). `find_outlier_days` (z-score of
`daily_energy_kwh` and `maximum_demand_kw` computed **separately**, `>=5` complete days
required, `z_threshold` default 2.5).

**Shared day-completeness helper** (`der/_daily.py`): `infer_resolution_minutes`,
`expected_intervals_per_day`, `complete_day_dates` — factored out once `load_shape.py`
(Phase 3), `clustering.py`, and `patterns.py` all needed the identical "is this day
complete" logic; `load_shape.py` was refactored to import from here.

**Not wired into `run_der_pipeline`**: clustering and pattern discovery stay
standalone/directly-callable, same design choice as Phase 3's peak-events/
classification modules — K-means in particular is not cheap enough to run
unconditionally for every entity on every pipeline invocation. `patterns.py`
deliberately has no import dependency on `load_shape.py`, composing with whatever
shape-labeling source a caller supplies instead.

## 57. Meter Coincidence Analysis (Phase 5)

**STATUS: DECIDED**

**Coincidence factor** (`der/coincidence.py`, DER spec §5.9/§22 — statistical association,
not causal): `CF = coincident_group_peak_kw / sum_of_individual_meter_peaks_kw`.
CF = 1.0 means all meters peak simultaneously; CF approaching 0 means complete temporal
diversity. Both a study-period CF (one scalar over all available data) and a per-day CF
(one row per calendar date) are computed — never just one. All computed quantities are
reported as association metrics; no physical causation is implied.

**`compute_coincidence_factor(interval_df_multi, meter_ids, cfg, value_col="demand_kw")`**:
- Pivots `interval_df_multi` to a `(datetime × meter_id)` matrix for the specified meters.
- `group_demand` = `DataFrame.sum(axis=1, min_count=1)` — NaN only when all meters are
  NaN at a timestamp, consistent with Phase 1 aggregation semantics.
- `group_peak_kw` = max of `group_demand`; `coincident_peak_timestamp` = its argmax.
- `meter_peak_kw` = per-meter maximum over the study period.
- `sum_of_individual_peaks_kw` = sum of `meter_peak_kw` values.
- `CF = group_peak_kw / sum_of_individual_peaks_kw`.
- Returns `CoincidenceResult(success=False)` when fewer than `min_meters` meters are
  available or group demand is entirely NaN. CF > 1.0 is possible with uneven meter
  coverage (see ADR 015 edge-case note); callers should inspect `n_meters_reporting`.

**`compute_daily_coincidence(interval_df_multi, meter_ids, cfg, value_col="demand_kw")`**:
- Same pivot/sum/argmax logic applied per calendar date (groupby normalized date index).
- Dates where group demand is entirely NaN are **skipped** (not emitted as NaN rows).
- Columns: `date`, `coincidence_factor`, `group_peak_kw`, `sum_of_individual_peaks_kw`,
  `coincident_peak_timestamp`, `n_meters_reporting` (count of meters with ≥ 1 non-NaN
  value for that day — partial-coverage days are surfaced, not silently absorbed).
- Returns an empty DataFrame (same schema) when fewer than `min_meters` meters exist.

**`CoincidenceResult`** dataclass: `success`, `coincidence_factor`,
`group_peak_kw`, `sum_of_individual_peaks_kw`, `coincident_peak_timestamp`,
`n_meters`, `meter_peak_kw`.

**Configuration** (`[der.coincidence]`):
- `min_meters = 2` (default) — minimum meters to compute a CF. A single meter trivially
  has CF = 1.0; `min_meters = 1` enables it for completeness but produces a
  definitionally uninteresting result.

**Not wired into `run_der_pipeline`** — standalone, caller-driven (same design as Phase 3
and Phase 4 modules). Coincidence can be expensive for large portfolios and the caller
controls which entity/group pairs to evaluate.
- ADR created: adr/015-coincidence-factor.md

## 58. DER Output Layout (Phase 6)

**STATUS: DECIDED**

`der/output.py` defines the canonical set of DER output tables and their CSV
export mechanism, completing the six-phase DER integration.

**`DEROutputBundle`** — dataclass of five `pd.DataFrame` fields, all defaulting to
an empty DataFrame (never `None`). Callers check `.empty` before use.

**`build_der_output(der_result, cfg) -> DEROutputBundle`** assembles all five tables:

| Table | Granularity | Source |
|---|---|---|
| `meter_interval` | (meter, timestamp) | `DERResult.interval_df_multi` with DatetimeIndex reset to column |
| `entity_interval` | (entity, timestamp) | `entity_calendar_frames` (Phase 2) when populated, else `entity_frames` |
| `entity_daily` | (entity, date) | `build_daily_summary` + left-join of `entity_tod_frames` on `date` |
| `study_coincidence` | entity | `compute_coincidence_factor` per entity (Phase 5) |
| `daily_coincidence` | (entity, date) | `compute_daily_coincidence` per entity, stacked with `entity_id` |

Coincidence is computed inside `build_der_output` (cheap, always meaningful with
multiple meters). Clustering, load-shape classification, change-point regression,
and pattern discovery remain standalone — they are not forced on every output call.
Entities that fail the `[der.coincidence].min_meters` guard appear in
`study_coincidence` with `success=False` and NaN numeric columns rather than being
silently dropped.

**`export_der_output(bundle, cfg) -> dict[str, Path]`**: writes each non-empty table
to its configured path under `[der.output]`; creates parent directories automatically;
skips tables without a configured path or that are empty; returns `{table_name: path}`
for every table actually written.

**Configuration** (`[der.output]`, all paths absent/commented by default — DER
output is inert until populated):
- `meter_interval_csv`
- `entity_interval_csv`
- `entity_daily_csv`
- `study_coincidence_csv`
- `daily_coincidence_csv`

**Extensibility**: clustering, load-shape, and pattern results are not in the bundle
— callers that want them merge additional columns into `entity_daily` themselves
before calling `export_der_output`. The bundle fields are plain DataFrames.
- ADR created: adr/016-der-output-layout.md
- **Phase 6 completes the DER Opportunity Analysis integration (Phases 0–6).**
