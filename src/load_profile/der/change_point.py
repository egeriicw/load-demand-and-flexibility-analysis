"""
Change-point (balance-point) regression — full ASHRAE GL14 / IPMVP model
family (DER spec §5.2): 2P, 3P-cooling, 3P-heating, 4P, 5P, plus
adjusted-R²-based model selection.

Explicitly a statistical/modeled relationship, not a causal claim (per spec).
Typically fit against daily-mean temperature vs. daily-mean demand,
weekday-only input by convention (caller's responsibility to filter — these
functions are agnostic to what ``x``/``y`` represent).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
from scipy.optimize import lsq_linear

_PARAM_COUNTS = {"2P": 2, "3P_cooling": 3, "3P_heating": 3, "4P": 4, "5P": 5}


@dataclass
class ChangePointModel:
    model_type: str  # "2P" | "3P_cooling" | "3P_heating" | "4P" | "5P"
    success: bool
    r_squared: float = float("nan")
    adjusted_r_squared: float = float("nan")
    n_points: int = 0
    params: dict[str, float] = field(default_factory=dict)
    breakpoints: list[float] = field(default_factory=list)
    method: str = ""


def _clean_pairs(x, y) -> tuple[np.ndarray, np.ndarray]:
    xc = np.asarray(x, dtype=float)
    yc = np.asarray(y, dtype=float)
    mask = np.isfinite(xc) & np.isfinite(yc)
    return xc[mask], yc[mask]


def _r_squared(y: np.ndarray, y_hat: np.ndarray) -> float:
    ss_res = float(np.sum((y - y_hat) ** 2))
    ss_tot = float(np.sum((y - y.mean()) ** 2))
    if ss_tot <= 0:
        return 0.0
    return 1.0 - ss_res / ss_tot


def _ols(design: np.ndarray, y: np.ndarray) -> np.ndarray:
    coeffs, *_ = np.linalg.lstsq(design, y, rcond=None)
    return coeffs


def _breakpoint_candidates(x: np.ndarray, step: float = 1.0) -> np.ndarray:
    """1°F-step grid over the observed range, excluding the extremes (so
    every candidate leaves at least one point on each side)."""
    lo, hi = np.floor(x.min()) + step, np.ceil(x.max())
    if hi <= lo:
        return np.array([])
    return np.arange(lo, hi, step)


def fit_2p(x, y, cfg: dict[str, Any] | None = None) -> ChangePointModel:
    """Plain OLS: base + slope·x. Minimum 4 points."""
    xc, yc = _clean_pairs(x, y)
    n = len(xc)
    if n < 4:
        return ChangePointModel(model_type="2P", success=False, n_points=n)
    design = np.column_stack([np.ones(n), xc])
    coeffs = _ols(design, yc)
    y_hat = design @ coeffs
    return ChangePointModel(
        model_type="2P", success=True, r_squared=_r_squared(yc, y_hat), n_points=n,
        params={"base": float(coeffs[0]), "slope": float(coeffs[1])}, method="ols",
    )


def fit_3p_cooling(x, y, cfg: dict[str, Any] | None = None) -> ChangePointModel:
    """baseload below breakpoint, baseload + slope·(T-bp) above. Minimum 5 points."""
    xc, yc = _clean_pairs(x, y)
    n = len(xc)
    if n < 5:
        return ChangePointModel(model_type="3P_cooling", success=False, n_points=n)

    best = None
    for bp in _breakpoint_candidates(xc):
        excess = np.maximum(xc - bp, 0.0)
        if not np.any(excess > 0):
            continue
        design = np.column_stack([np.ones(n), excess])
        coeffs = _ols(design, yc)
        y_hat = design @ coeffs
        sse = float(np.sum((yc - y_hat) ** 2))
        if best is None or sse < best[0]:
            best = (sse, bp, coeffs, y_hat)

    if best is None:
        return ChangePointModel(model_type="3P_cooling", success=False, n_points=n)
    _, bp, coeffs, y_hat = best
    return ChangePointModel(
        model_type="3P_cooling", success=True, r_squared=_r_squared(yc, y_hat), n_points=n,
        params={"baseload": float(coeffs[0]), "slope": float(coeffs[1])},
        breakpoints=[float(bp)], method="grid_search_ols",
    )


def fit_3p_heating(x, y, cfg: dict[str, Any] | None = None) -> ChangePointModel:
    """baseload + slope·(bp-T) below breakpoint, baseload above. Minimum 5 points."""
    xc, yc = _clean_pairs(x, y)
    n = len(xc)
    if n < 5:
        return ChangePointModel(model_type="3P_heating", success=False, n_points=n)

    best = None
    for bp in _breakpoint_candidates(xc):
        excess = np.maximum(bp - xc, 0.0)
        if not np.any(excess > 0):
            continue
        design = np.column_stack([np.ones(n), excess])
        coeffs = _ols(design, yc)
        y_hat = design @ coeffs
        sse = float(np.sum((yc - y_hat) ** 2))
        if best is None or sse < best[0]:
            best = (sse, bp, coeffs, y_hat)

    if best is None:
        return ChangePointModel(model_type="3P_heating", success=False, n_points=n)
    _, bp, coeffs, y_hat = best
    return ChangePointModel(
        model_type="3P_heating", success=True, r_squared=_r_squared(yc, y_hat), n_points=n,
        params={"baseload": float(coeffs[0]), "slope": float(coeffs[1])},
        breakpoints=[float(bp)], method="grid_search_ols",
    )


def fit_4p(x, y, cfg: dict[str, Any] | None = None) -> ChangePointModel:
    """Single shared breakpoint, heating slope below + cooling slope above,
    both constrained >= 0 (bounded least squares). Minimum 8 points."""
    xc, yc = _clean_pairs(x, y)
    n = len(xc)
    if n < 8:
        return ChangePointModel(model_type="4P", success=False, n_points=n)

    best = None
    for bp in _breakpoint_candidates(xc):
        heating_excess = np.maximum(bp - xc, 0.0)
        cooling_excess = np.maximum(xc - bp, 0.0)
        if not np.any(heating_excess > 0) or not np.any(cooling_excess > 0):
            continue  # degenerate: all data on one side of this candidate
        design = np.column_stack([np.ones(n), heating_excess, cooling_excess])
        result = lsq_linear(design, yc, bounds=([-np.inf, 0, 0], [np.inf, np.inf, np.inf]))
        y_hat = design @ result.x
        sse = float(np.sum((yc - y_hat) ** 2))
        if best is None or sse < best[0]:
            best = (sse, bp, result.x, y_hat)

    if best is None:
        return ChangePointModel(model_type="4P", success=False, n_points=n)
    _, bp, coeffs, y_hat = best
    base, heating_slope, cooling_slope = coeffs
    return ChangePointModel(
        model_type="4P", success=True, r_squared=_r_squared(yc, y_hat), n_points=n,
        params={
            "base": float(base), "heating_slope": float(heating_slope),
            "cooling_slope": float(cooling_slope),
        },
        breakpoints=[float(bp)], method="grid_search_bounded_lsq",
    )


def fit_5p(x, y, cfg: dict[str, Any] | None = None) -> ChangePointModel:
    """Independent heating breakpoint <= cooling breakpoint, joint grid search,
    same bounded-LS fit as 4P. Minimum 10 points, minimum 2 candidate breakpoint pairs."""
    xc, yc = _clean_pairs(x, y)
    n = len(xc)
    if n < 10:
        return ChangePointModel(model_type="5P", success=False, n_points=n)

    candidates = _breakpoint_candidates(xc)
    best = None
    n_valid_pairs = 0
    for heating_bp in candidates:
        for cooling_bp in candidates:
            if heating_bp > cooling_bp:
                continue
            heating_excess = np.maximum(heating_bp - xc, 0.0)
            cooling_excess = np.maximum(xc - cooling_bp, 0.0)
            if not np.any(heating_excess > 0) or not np.any(cooling_excess > 0):
                continue
            n_valid_pairs += 1
            design = np.column_stack([np.ones(n), heating_excess, cooling_excess])
            result = lsq_linear(design, yc, bounds=([-np.inf, 0, 0], [np.inf, np.inf, np.inf]))
            y_hat = design @ result.x
            sse = float(np.sum((yc - y_hat) ** 2))
            if best is None or sse < best[0]:
                best = (sse, heating_bp, cooling_bp, result.x, y_hat)

    if best is None or n_valid_pairs < 2:
        return ChangePointModel(model_type="5P", success=False, n_points=n)
    _, heating_bp, cooling_bp, coeffs, y_hat = best
    base, heating_slope, cooling_slope = coeffs
    return ChangePointModel(
        model_type="5P", success=True, r_squared=_r_squared(yc, y_hat), n_points=n,
        params={
            "base": float(base), "heating_slope": float(heating_slope),
            "cooling_slope": float(cooling_slope),
        },
        breakpoints=[float(heating_bp), float(cooling_bp)], method="grid_search_bounded_lsq",
    )


def select_best_change_point_model(
    x, y, cfg: dict[str, Any] | None = None
) -> ChangePointModel | None:
    """
    Fit all five model families and pick the best by adjusted R²
    (``1 - (1-R²)(n-1)/(n-p-1)``, p = each model's parameter count), which
    penalizes 4P/5P's extra parameters so a genuinely simple relationship
    isn't overfit by the richer models. Ties go to the simpler (lower-p)
    model.

    A candidate is excluded (not scored as "worse") if it failed its own
    data-sufficiency guard, or if ``n - p - 1 <= 0``. If every candidate is
    excluded, returns ``None`` — callers must treat this as "no change-point
    model could be fit," not evidence of a flat/temperature-independent load.
    """
    candidates = [
        fit_2p(x, y, cfg),
        fit_3p_cooling(x, y, cfg),
        fit_3p_heating(x, y, cfg),
        fit_4p(x, y, cfg),
        fit_5p(x, y, cfg),
    ]

    scored: list[tuple[float, int, ChangePointModel]] = []
    for model in candidates:
        if not model.success:
            continue
        p = _PARAM_COUNTS[model.model_type]
        n = model.n_points
        if n - p - 1 <= 0:
            continue
        adj_r2 = 1.0 - (1.0 - model.r_squared) * (n - 1) / (n - p - 1)
        model.adjusted_r_squared = adj_r2
        scored.append((adj_r2, -p, model))

    if not scored:
        return None

    scored.sort(key=lambda t: (t[0], t[1]), reverse=True)
    return scored[0][2]
