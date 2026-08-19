# ADR 001 — Baseline Estimation Method

**Date:** 2026-08-18  
**Status:** DECIDED (parameters provisional)  
**Spec sections:** 7, 9  
**Open questions addressed:** Q8, Q13–Q19

## Context

The baseline is one of the most consequential design decisions because startup/end detection depends on it. Four candidate methods were considered:

- A: Absolute minimum (lowest observed value)
- B: Lowest sustained demand (lowest level persisting ≥ X minutes)
- C: Low-demand percentile (e.g. median of lowest 10%)
- D: Hybrid — identify a sustained low-demand region, then compute a representative statistic within it

## Decision

**Use Method D (hybrid lowest-sustained-demand).**

Algorithm:
1. Compute the 10th percentile of the day's demand as the low-demand threshold
2. Find all intervals at or below that threshold
3. Identify the longest contiguous run of those intervals
4. If the run lasts ≥ 60 minutes, its median is the baseline
5. If no run qualifies, fall back to the 10th percentile of the full day (continuous-operation path)

Baseline is a single scalar per day.

## Rationale

- Method A is sensitive to single-point anomalies
- Method B requires defining "sustained" — Method D does so explicitly
- Method C ignores whether the low-demand intervals are contiguous
- Method D captures the concept of a genuine inactive period, not just occasional low readings

## Provisional parameters (to be confirmed)

| Parameter | Value | Question |
|---|---|---|
| `low_demand_percentile` | 10 | Q15 |
| `min_persistence_minutes` | 60 | Q13, Q14 |
| Representative statistic | median | Q16 |
| Baseline is scalar per day | yes | Q17 |
| Continuous-operation criterion | range/mean < 0.15 | Q18 |

## Consequences

- Baseline will be stable for typical commercial/industrial buildings (long overnight period)
- May be less stable for buildings with variable overnight loads
- Continuous-operation buildings will use the fallback percentile; their `is_continuous_operation` flag will be True
