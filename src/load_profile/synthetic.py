"""
Synthetic daily load-profile generator for algorithm testing and validation.

Each scenario produces a pandas DataFrame with columns:
    datetime  (tz-aware),  demand_kw

Scenarios map to the 20 test cases in the specification.
Expected behaviour is documented alongside each generator so test assertions
can be written from the function's docstring.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# Core builder
# ---------------------------------------------------------------------------

def _make_index(
    date: str = "2024-01-15",
    tz: str = "America/Chicago",
    resolution_minutes: float = 15.0,
) -> pd.DatetimeIndex:
    start = pd.Timestamp(date, tz=tz)
    end   = start + pd.Timedelta(hours=24) - pd.Timedelta(minutes=resolution_minutes)
    return pd.date_range(start, end, freq=f"{resolution_minutes}min", tz=tz)


def _frame(index: pd.DatetimeIndex, demand: np.ndarray) -> pd.DataFrame:
    return pd.DataFrame({"datetime": index, "demand_kw": demand}).set_index("datetime")


def _ramp(n: int, v_start: float, v_end: float) -> np.ndarray:
    return np.linspace(v_start, v_end, n)


def _noise(n: int, sigma: float = 5.0, seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return rng.normal(0, sigma, n)


# ---------------------------------------------------------------------------
# Scenario functions
# ---------------------------------------------------------------------------

def generate_synthetic_day(
    scenario: str,
    date: str = "2024-01-15",
    tz: str = "America/Chicago",
    resolution_minutes: float = 15.0,
) -> tuple[pd.DataFrame, dict]:
    """
    Generate a synthetic day and its expected-behaviour dictionary.

    Parameters
    ----------
    scenario : str
        One of the scenario names listed in SCENARIOS below.
    date, tz, resolution_minutes : as described above.

    Returns
    -------
    (DataFrame, expected)
        DataFrame has a tz-aware DatetimeIndex named ``datetime`` and a
        ``demand_kw`` column.
        ``expected`` is a dict of expected analytical results for assertions.
    """
    fn = SCENARIOS.get(scenario)
    if fn is None:
        raise ValueError(
            f"Unknown scenario '{scenario}'. Available: {sorted(SCENARIOS)}"
        )
    return fn(date=date, tz=tz, resolution_minutes=resolution_minutes)


# ---------------------------------------------------------------------------
# Individual scenarios
# ---------------------------------------------------------------------------

def _scenario_flat_continuous(date, tz, resolution_minutes):
    """
    1. Flat/continuous load — demand is essentially constant all day.
    Expected: is_continuous_operation=True, no credible start/end detected.
    """
    idx = _make_index(date, tz, resolution_minutes)
    n   = len(idx)
    demand = np.full(n, 500.0) + _noise(n, 8)
    return _frame(idx, demand), {
        "is_continuous_operation": True,
        "primary_class": "CONTINUOUS",
        "probable_start_time": None,
        "probable_end_time": None,
    }


def _scenario_classic_morning_startup(date, tz, resolution_minutes):
    """
    2. Classic morning startup — low overnight, sharp ramp ~07:00, sustained operation.
    Expected: MORNING_START class, start ~07:00, rapid_start attribute.
    """
    idx  = _make_index(date, tz, resolution_minutes)
    n    = len(idx)
    res  = resolution_minutes
    d    = np.full(n, 50.0)  # overnight baseline

    start_int = int(7 * 60 / res)
    ramp_ints = int(30  / res)  # 30-min sharp ramp
    end_int   = int(18 * 60 / res)
    shut_ints = int(30  / res)

    d[start_int : start_int + ramp_ints] = _ramp(ramp_ints, 50, 450)
    d[start_int + ramp_ints : end_int]   = 450.0
    d[end_int : end_int + shut_ints]     = _ramp(shut_ints, 450, 50)
    d[end_int + shut_ints :]             = 50.0
    d += _noise(n, 5)

    return _frame(idx, d), {
        "is_continuous_operation": False,
        "primary_class": "MORNING_START",
        "start_hour_approx": 7.0,
        "end_hour_approx": 18.0,
        "attributes_include": ["rapid_start"],
    }


def _scenario_gradual_startup(date, tz, resolution_minutes):
    """
    3. Gradual startup — demand climbs steadily from 06:00 to 10:00 before levelling.
    Expected: MORNING_START or EARLY_START, is_gradual=True for start event.
    """
    idx  = _make_index(date, tz, resolution_minutes)
    n    = len(idx)
    res  = resolution_minutes
    d    = np.full(n, 60.0)

    start_int = int(6 * 60 / res)
    ramp_ints = int(4 * 60 / res)  # 4-hour gradual ramp
    end_int   = int(19 * 60 / res)
    shut_ints = int(60  / res)

    d[start_int : start_int + ramp_ints] = _ramp(ramp_ints, 60, 420)
    d[start_int + ramp_ints : end_int]   = 420.0
    d[end_int : end_int + shut_ints]     = _ramp(shut_ints, 420, 60)
    d[end_int + shut_ints :]             = 60.0
    d += _noise(n, 8)

    return _frame(idx, d), {
        "is_continuous_operation": False,
        "start_is_gradual": True,
        "attributes_include": ["gradual_start"],
    }


def _scenario_sharp_startup(date, tz, resolution_minutes):
    """
    4. Sharp startup — single 15-min interval ramp, very high ramp rate.
    Expected: rapid_start attribute, startup_ramp_kw_per_hr > 50.
    """
    idx  = _make_index(date, tz, resolution_minutes)
    n    = len(idx)
    res  = resolution_minutes
    d    = np.full(n, 40.0)

    t = int(8 * 60 / res)
    d[t]     = 400.0
    d[t + 1 : int(17 * 60 / res)] = 400.0
    d[int(17 * 60 / res):] = 40.0
    d += _noise(n, 5)

    return _frame(idx, d), {
        "attributes_include": ["rapid_start"],
        "startup_ramp_kw_per_hr_min": 50.0,
    }


def _scenario_broad_peak(date, tz, resolution_minutes):
    """
    5. Broad peak — high demand sustained for 6+ hours.
    Expected: broad_peak attribute, peak_width_80_hours >= 3.0.
    """
    idx  = _make_index(date, tz, resolution_minutes)
    n    = len(idx)
    res  = resolution_minutes
    d    = np.full(n, 60.0)

    d[int(9*60/res) : int(17*60/res)] = 500.0
    d += _noise(n, 6)
    return _frame(idx, d), {
        "attributes_include": ["broad_peak"],
        "peak_width_80_hours_min": 3.0,
    }


def _scenario_narrow_peak(date, tz, resolution_minutes):
    """
    6. Narrow/sharp peak — brief high-demand spike, rapid return to lower level.
    Expected: sharp_peak attribute.
    """
    idx  = _make_index(date, tz, resolution_minutes)
    n    = len(idx)
    res  = resolution_minutes
    d    = np.full(n, 200.0)

    t = int(12 * 60 / res)
    spike_dur = int(45 / res)
    d[t : t + spike_dur] = 600.0
    d += _noise(n, 5)
    return _frame(idx, d), {
        "attributes_include": ["sharp_peak"],
        "peak_width_80_hours_max": 1.0,
    }


def _scenario_two_shift(date, tz, resolution_minutes):
    """
    7. Two-shift operation — two distinct OPERATING periods separated by a midday break.
    Expected: multiple_operating_periods attribute, operating_period_count=2.
    """
    idx  = _make_index(date, tz, resolution_minutes)
    n    = len(idx)
    res  = resolution_minutes
    d    = np.full(n, 50.0)

    # Morning shift
    d[int(6*60/res)  : int(12*60/res)] = 400.0
    # Afternoon shift
    d[int(14*60/res) : int(22*60/res)] = 400.0
    d += _noise(n, 5)
    return _frame(idx, d), {
        "attributes_include": ["multiple_operating_periods"],
        "operating_period_count": 2,
    }


def _scenario_247_operation(date, tz, resolution_minutes):
    """
    8. 24/7 operation — never goes below operating threshold.
    Expected: CONTINUOUS classification.
    """
    idx = _make_index(date, tz, resolution_minutes)
    n   = len(idx)
    d   = np.full(n, 480.0) + _noise(n, 20, seed=8)
    return _frame(idx, d), {
        "is_continuous_operation": True,
        "primary_class": "CONTINUOUS",
    }


def _scenario_demand_spike(date, tz, resolution_minutes):
    """
    9. Isolated demand spike — single-interval extreme value.
    Expected: peak event detected at spike location; spike may not influence normalization baseline.
    """
    idx  = _make_index(date, tz, resolution_minutes)
    n    = len(idx)
    res  = resolution_minutes
    d    = np.full(n, 200.0)
    d[int(9*60/res)  : int(17*60/res)] = 350.0
    spike_t = int(12 * 60 / res)
    d[spike_t] = 900.0  # single interval spike
    d += _noise(n, 5)
    return _frame(idx, d), {
        "peak_kw_min": 850.0,
    }


def _scenario_multi_stage_startup(date, tz, resolution_minutes):
    """
    10. Multi-stage startup — demand ramps in two distinct steps before reaching peak.
    Expected: multiple UP ramps during startup, gradual overall start.
    """
    idx  = _make_index(date, tz, resolution_minutes)
    n    = len(idx)
    res  = resolution_minutes
    d    = np.full(n, 50.0)

    # Stage 1: 06:00–07:00
    d[int(6*60/res) : int(7*60/res)] = _ramp(int(60/res), 50, 200)
    # Plateau: 07:00–08:00
    d[int(7*60/res) : int(8*60/res)] = 200.0
    # Stage 2: 08:00–09:00
    d[int(8*60/res) : int(9*60/res)] = _ramp(int(60/res), 200, 450)
    d[int(9*60/res) : int(17*60/res)] = 450.0
    d[int(17*60/res):] = 50.0
    d += _noise(n, 5)
    return _frame(idx, d), {
        "up_ramp_count_min": 2,
    }


def _scenario_gradual_shutdown(date, tz, resolution_minutes):
    """
    11. Gradual shutdown — extended ramp-down over 3 hours.
    Expected: end_is_gradual=True, shutdown_duration_hours >= 2.
    """
    idx  = _make_index(date, tz, resolution_minutes)
    n    = len(idx)
    res  = resolution_minutes
    d    = np.full(n, 50.0)

    d[int(7*60/res)  : int(16*60/res)] = 400.0
    d[int(16*60/res) : int(19*60/res)] = _ramp(int(3*60/res), 400, 50)
    d += _noise(n, 5)
    return _frame(idx, d), {
        "end_is_gradual": True,
        "shutdown_duration_hours_min": 2.0,
    }


def _scenario_abrupt_shutdown(date, tz, resolution_minutes):
    """
    12. Abrupt shutdown — demand drops to baseline in a single interval.
    Expected: rapid_shutdown attribute.
    """
    idx  = _make_index(date, tz, resolution_minutes)
    n    = len(idx)
    res  = resolution_minutes
    d    = np.full(n, 50.0)

    d[int(7*60/res) : int(17*60/res)] = 420.0
    d[int(17*60/res)] = 50.0
    d += _noise(n, 5)
    return _frame(idx, d), {
        "attributes_include": ["rapid_shutdown"],
    }


def _scenario_multiple_peaks(date, tz, resolution_minutes):
    """
    13. Multiple distinct peaks — two separated high-demand events.
    Expected: secondary_peak_count >= 1, multiple_peaks attribute.
    """
    idx  = _make_index(date, tz, resolution_minutes)
    n    = len(idx)
    res  = resolution_minutes
    d    = np.full(n, 100.0)

    d[int(9*60/res)  : int(11*60/res)] = 500.0  # Peak 1
    d[int(14*60/res) : int(16*60/res)] = 480.0  # Peak 2
    d += _noise(n, 8)
    return _frame(idx, d), {
        "attributes_include": ["multiple_peaks"],
        "secondary_peak_count_min": 1,
    }


def _scenario_missing_data(date, tz, resolution_minutes):
    """
    14. Missing-data scenario — a 2-hour gap in the middle of the day.
    Expected: data quality flags present; interpolation fraction > 0.
    """
    idx  = _make_index(date, tz, resolution_minutes)
    n    = len(idx)
    res  = resolution_minutes
    d    = np.full(n, 50.0, dtype=float)

    d[int(7*60/res)  : int(17*60/res)] = 400.0
    # 2-hour gap at midday
    d[int(11*60/res) : int(13*60/res)] = np.nan
    d += np.where(np.isnan(d), 0, _noise(n, 5))
    return _frame(idx, d), {
        "has_missing_data": True,
        "longest_missing_gap_minutes_min": 100.0,  # just under 2 hr
    }


def _scenario_interpolated_gaps(date, tz, resolution_minutes):
    """
    15. Interpolated gaps — short gaps (<60 min) that will be linearly interpolated.
    Expected: interpolation_fraction > 0; interpolated values flagged in provenance.
    """
    idx  = _make_index(date, tz, resolution_minutes)
    n    = len(idx)
    res  = resolution_minutes
    d    = np.full(n, 50.0, dtype=float)

    d[int(7*60/res)  : int(17*60/res)] = 400.0
    # 30-min gap — should be interpolated
    d[int(12*60/res) : int(12*60/res) + int(30/res)] = np.nan
    return _frame(idx, d), {
        "interpolation_fraction_min": 0.01,
    }


def _scenario_irregular_data(date, tz, resolution_minutes):
    """
    16. Irregular data — some intervals are doubled, others skipped.
    Expected: irregular_interval_count > 0 in validation report.
    """
    idx  = _make_index(date, tz, resolution_minutes)
    n    = len(idx)
    d    = np.full(n, 300.0) + _noise(n, 10, seed=16)
    df   = _frame(idx, d)
    # Remove a few rows and duplicate one to create irregularity
    drop_pos = [20, 21, 22]
    df = df.drop(df.index[drop_pos])
    dup = df.iloc[[15]]
    df  = pd.concat([df, dup]).sort_index()
    return df, {
        "has_irregular_timestamps": True,
    }


def _scenario_dst_spring(date, tz, resolution_minutes):
    """
    17a. DST spring-forward — day has fewer intervals (e.g. 92 for 15-min data).
    Expected: expected_intervals < 96 for 15-min data.
    """
    # 2024-03-10 is spring forward in US Central
    dst_date = "2024-03-10"
    idx  = _make_index(dst_date, tz, resolution_minutes)
    n    = len(idx)
    d    = np.full(n, 50.0)
    res = resolution_minutes
    d[int(7*60/res) : int(16*60/res)] = 350.0
    d += _noise(n, 5, seed=17)
    return _frame(idx, d), {
        "expected_intervals_less_than": 96 * (15 / resolution_minutes),
        "date": dst_date,
    }


def _scenario_dst_fall(date, tz, resolution_minutes):
    """
    17b. DST fall-back — day has more intervals (e.g. 100 for 15-min data).
    Expected: expected_intervals > 96 for 15-min data.
    """
    dst_date = "2024-11-03"
    idx  = _make_index(dst_date, tz, resolution_minutes)
    n    = len(idx)
    d    = np.full(n, 50.0)
    d[int(7*60/resolution_minutes) : int(16*60/resolution_minutes)] = 350.0
    d += _noise(n, 5, seed=18)
    return _frame(idx, d), {
        "expected_intervals_greater_than": 96 * (15 / resolution_minutes),
        "date": dst_date,
    }


def _scenario_short_operating_period(date, tz, resolution_minutes):
    """
    18. Very short operating period — 45-min occupancy.
    Expected: short_operating_duration attribute, operating_period_count=1.
    """
    idx  = _make_index(date, tz, resolution_minutes)
    n    = len(idx)
    res  = resolution_minutes
    d    = np.full(n, 40.0)

    t    = int(12 * 60 / res)
    dur  = int(45 / res)
    d[t : t + dur] = 300.0
    d += _noise(n, 5, seed=19)
    return _frame(idx, d), {
        "attributes_include": ["short_operating_duration"],
        "total_operating_duration_hours_max": 2.0,
    }


def _scenario_minimal_variation(date, tz, resolution_minutes):
    """
    19. Minimal daily variation — slight variation, nearly flat.
    Expected: MINIMAL_LOAD or CONTINUOUS classification.
    """
    idx = _make_index(date, tz, resolution_minutes)
    n   = len(idx)
    d   = np.full(n, 200.0) + _noise(n, 2, seed=19)
    return _frame(idx, d), {
        "primary_class_in": ["CONTINUOUS", "MINIMAL_LOAD"],
    }


def _scenario_highly_variable(date, tz, resolution_minutes):
    """
    20. Highly variable operation — demand fluctuates widely throughout the day.
    Expected: high_intraday_variability attribute, cv >= 0.30.
    """
    idx = _make_index(date, tz, resolution_minutes)
    n   = len(idx)
    rng = np.random.default_rng(20)
    d   = 200.0 + rng.normal(0, 80, n).clip(-150, 350)
    d   = d.clip(10)
    return _frame(idx, d), {
        "attributes_include": ["high_intraday_variability"],
        "cv_min": 0.30,
    }


# ---------------------------------------------------------------------------
# Scenario registry
# ---------------------------------------------------------------------------

SCENARIOS: dict[str, callable] = {
    "flat_continuous":          _scenario_flat_continuous,
    "classic_morning_startup":  _scenario_classic_morning_startup,
    "gradual_startup":          _scenario_gradual_startup,
    "sharp_startup":            _scenario_sharp_startup,
    "broad_peak":               _scenario_broad_peak,
    "narrow_peak":              _scenario_narrow_peak,
    "two_shift":                _scenario_two_shift,
    "247_operation":            _scenario_247_operation,
    "demand_spike":             _scenario_demand_spike,
    "multi_stage_startup":      _scenario_multi_stage_startup,
    "gradual_shutdown":         _scenario_gradual_shutdown,
    "abrupt_shutdown":          _scenario_abrupt_shutdown,
    "multiple_peaks":           _scenario_multiple_peaks,
    "missing_data":             _scenario_missing_data,
    "interpolated_gaps":        _scenario_interpolated_gaps,
    "irregular_data":           _scenario_irregular_data,
    "dst_spring":               _scenario_dst_spring,
    "dst_fall":                 _scenario_dst_fall,
    "short_operating_period":   _scenario_short_operating_period,
    "minimal_variation":        _scenario_minimal_variation,
    "highly_variable":          _scenario_highly_variable,
}
