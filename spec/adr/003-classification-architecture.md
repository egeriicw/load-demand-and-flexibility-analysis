# ADR 003 — Classification Architecture

**Date:** 2026-08-18  
**Status:** DECIDED (taxonomy provisional)  
**Spec sections:** 37, 38, 39  
**Open questions addressed:** Q88, Q89, Q93

## Context

Options considered:
1. Single composite classification label with no sub-structure
2. One primary class + independent boolean attributes
3. Machine-learning model
4. Hierarchical class tree

## Decision

**Use one primary class (mutually exclusive) plus an independent list of boolean attributes.**

Example output:
```python
{
  "primary_class": "MORNING_START",
  "attributes": ["rapid_start", "long_operating_duration", "broad_peak"],
  "classification_confidence": 0.87
}
```

All rules are driven by thresholds in the TOML configuration file. No machine learning in V1.

## Rationale

- Single composite labels collapse too much information
- ML requires labelled data and is a black box — unacceptable for an explainable diagnostic tool
- One primary class + attributes provides a clean, extensible structure
- TOML-configurable rules allow calibration to different building types without code changes
- Attributes are independent, so multiple can be true simultaneously without conflict

## Primary class taxonomy (provisional)

```
CONTINUOUS, EARLY_START, MORNING_START, MIDDAY_START, EVENING_START,
NO_CLEAR_START, MINIMAL_LOAD, UNKNOWN
```

Primary class is determined by start timing. If no start is detected, the operating-period presence determines whether to use NO_CLEAR_START or UNKNOWN.

## Attribute list (provisional)

```
rapid_start, gradual_start, rapid_shutdown, gradual_shutdown,
long_operating_duration, short_operating_duration,
broad_peak, sharp_peak, high_peak_concentration,
multiple_operating_periods, multiple_peaks, high_intraday_variability
```

## Consequences

- Classification can be queried at the primary-class level (coarse) or attribute level (fine)
- New attributes can be added without changing existing outputs
- V2 could add a sub-class layer (e.g. MORNING_START_BROAD) without breaking V1 consumers
- The taxonomy may need extension when real building data reveals profile types not anticipated here
