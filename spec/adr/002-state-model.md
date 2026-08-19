# ADR 002 — Demand State Model

**Date:** 2026-08-18  
**Status:** DECIDED (threshold parameters provisional)  
**Spec sections:** 12, 13, 14, 15  
**Open questions addressed:** Q24, Q25, Q29

## Context

The spec considered two options for the state taxonomy:
- A granular model: BASELINE / LOW_LOAD / OPERATING / HIGH_LOAD / PEAK / TRANSITION_UP / TRANSITION_DOWN
- A simple two-state model: BASELINE / OPERATING

## Decision

**Use a two-state model: BASELINE and OPERATING.**

A third pseudo-state `UNKNOWN` is used for NaN-demand intervals.

Rich behavior (gradual vs. sharp transitions, multiple peaks, peakiness) is derived from the continuous normalized demand series rather than from discrete state labels.

## Hysteresis

Separate entry and exit thresholds are used:

```
T_entry = baseline + alpha_entry * (peak - baseline)   [default: 20%]
T_exit  = baseline + alpha_exit  * (peak - baseline)   [default: 15%]
```

## State persistence

A state change is not recognized unless it persists for ≥ 30 minutes (configurable). This prevents transient noise from creating spurious transitions.

## Rationale

- The granular model adds complexity without corresponding clarity in V1
- The two-state model is interpretable and directly maps to the building's operating/inactive distinction
- Hysteresis handles noisy data near the threshold without special-case logic
- Persistence enforcement handles short excursions

## Provisional parameters (to be confirmed)

| Parameter | Value | Question |
|---|---|---|
| `alpha_entry` | 0.20 | Q26, Q27 |
| `alpha_exit` | 0.15 | Q28, Q30 |
| `min_state_persistence_minutes` | 30 | Q31 |

## Consequences

- Operating periods may be slightly shorter or longer than visual inspection would suggest, depending on threshold calibration
- Buildings with very noisy demand near the threshold may produce ambiguous state series
- V2 could add HIGH_LOAD / PEAK states without breaking the V1 feature schema
