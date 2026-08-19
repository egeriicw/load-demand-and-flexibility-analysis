"""
Diagnostic visualizations for a single daily load profile.

Observed vs. interpolated demand are always visually distinct.
All annotations (baseline, threshold, events) are layered on top.
"""

from __future__ import annotations

from typing import Any

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np
import pandas as pd

from .events import StartEvent, EndEvent, RampEvent, PeakEvent


def plot_daily_profile(
    date: str,
    df_day: pd.DataFrame,
    series_smooth: pd.Series,
    norm_demand: pd.Series,
    states: pd.Series,
    baseline_result: dict[str, Any],
    start_event: StartEvent | None,
    end_event: EndEvent | None,
    ramp_events: list[RampEvent],
    peak_events: list[PeakEvent],
    operating_periods: list[dict],
    features: dict[str, Any],
    classification: dict[str, Any],
    cfg: dict[str, Any],
    figsize: tuple[float, float] | None = None,
    dpi: int | None = None,
) -> plt.Figure:
    """
    Produce a multi-panel diagnostic plot for one calendar day.

    Panel 1 (top): Raw & smoothed demand with all analytical overlays.
    Panel 2 (bottom): Normalised demand with breadth thresholds.

    Returns
    -------
    matplotlib Figure (caller is responsible for plt.show() or savefig())
    """
    viz_cfg = cfg.get("visualization", {})
    fw  = figsize[0] if figsize else viz_cfg.get("figsize_w", 14)
    fh  = figsize[1] if figsize else viz_cfg.get("figsize_h", 8)
    dpi = dpi or viz_cfg.get("dpi", 120)

    c_obs   = viz_cfg.get("color_observed",     "#2c7bb6")
    c_interp = viz_cfg.get("color_interpolated", "#d7191c")
    c_bl    = viz_cfg.get("color_baseline",      "#1a9641")
    c_thr   = viz_cfg.get("color_threshold",     "#fdae61")
    c_pk    = viz_cfg.get("color_peak",          "#d62728")

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(fw, fh), dpi=dpi,
                                    sharex=True, gridspec_kw={"height_ratios": [3, 1]})

    # ── Panel 1: absolute demand ──────────────────────────────────────────
    _plot_demand(ax1, df_day, series_smooth, c_obs, c_interp)
    _plot_baseline_lines(ax1, baseline_result, cfg, c_bl, c_thr)
    _plot_operating_periods(ax1, operating_periods)
    _plot_start_end(ax1, start_event, end_event)
    _plot_ramps(ax1, ramp_events)
    _plot_peaks(ax1, peak_events, c_pk)

    ax1.set_ylabel("Demand (kW)")
    ax1.set_title(
        f"{date}  |  {classification['primary_class']}"
        f"  |  conf: {classification['classification_confidence']:.2f}"
        f"  |  attrs: {', '.join(classification['attributes']) or 'none'}"
    )
    ax1.legend(loc="upper right", fontsize=8, ncol=3)
    ax1.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))

    # ── Panel 2: normalised demand ────────────────────────────────────────
    _plot_normalised(ax2, norm_demand, cfg, c_obs)

    ax2.set_ylabel("Norm demand (0–1)")
    ax2.set_xlabel("Time")
    ax2.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))

    fig.tight_layout()
    return fig


# ---------------------------------------------------------------------------
# Plot helpers
# ---------------------------------------------------------------------------

def _plot_demand(
    ax: plt.Axes,
    df_day: pd.DataFrame,
    series_smooth: pd.Series,
    c_obs: str,
    c_interp: str,
) -> None:
    obs_mask   = df_day["is_observed"].fillna(False)
    interp_mask = df_day["is_interpolated"].fillna(False)

    idx = df_day.index

    # Observed segments
    obs_series   = df_day["demand_kw"].where(obs_mask)
    interp_series = df_day["demand_kw"].where(interp_mask)

    ax.plot(idx, df_day["demand_kw"],  color=c_obs,    lw=1.0, alpha=0.4, label="_raw")
    ax.plot(idx, obs_series,           color=c_obs,    lw=1.5, label="Observed",    zorder=3)
    ax.plot(idx, interp_series,        color=c_interp, lw=1.5, linestyle="--",
            label="Interpolated", zorder=3)

    if "analysis_demand_kw" in df_day.columns:
        ax.plot(idx, df_day["analysis_demand_kw"], color="black", lw=1.0,
                alpha=0.6, linestyle=":", label="Smoothed")
    elif series_smooth is not None:
        ax.plot(series_smooth.index, series_smooth.values, color="black",
                lw=1.0, alpha=0.6, linestyle=":", label="Smoothed")


def _plot_baseline_lines(
    ax: plt.Axes,
    baseline_result: dict[str, Any],
    cfg: dict[str, Any],
    c_bl: str,
    c_thr: str,
) -> None:
    bl_kw  = baseline_result.get("baseline_kw")
    pk_kw  = baseline_result.get("peak_kw")

    if bl_kw is None or np.isnan(bl_kw):
        return

    ax.axhline(bl_kw, color=c_bl, lw=1.2, linestyle="--", label=f"Baseline ({bl_kw:.0f} kW)")

    op_range = baseline_result.get("operating_range_kw", 0) or 0
    alpha_e = cfg.get("operating_threshold", {}).get("alpha_entry", 0.20)
    alpha_x = cfg.get("operating_threshold", {}).get("alpha_exit",  0.15)

    thr_entry = bl_kw + alpha_e * op_range
    thr_exit  = bl_kw + alpha_x * op_range

    ax.axhline(thr_entry, color=c_thr, lw=1.0, linestyle="-.",
               label=f"Op entry ({thr_entry:.0f} kW)")
    ax.axhline(thr_exit,  color=c_thr, lw=0.8, linestyle=":",
               label=f"Op exit ({thr_exit:.0f} kW)")

    if pk_kw and not np.isnan(pk_kw):
        ax.axhline(pk_kw, color="#888888", lw=0.7, linestyle=":",
                   label=f"Peak ({pk_kw:.0f} kW)")


def _plot_operating_periods(ax: plt.Axes, periods: list[dict]) -> None:
    for i, p in enumerate(periods):
        ax.axvspan(p["start"], p["end"], alpha=0.08, color="steelblue",
                   label="Operating" if i == 0 else "_")


def _plot_start_end(
    ax: plt.Axes,
    start_event: StartEvent | None,
    end_event: EndEvent | None,
) -> None:
    if start_event:
        ax.axvline(start_event.transition_time, color="green", lw=1.5,
                   linestyle="-", label=f"Start ({start_event.transition_time.strftime('%H:%M')})")
        ax.axvline(start_event.threshold_crossing_time, color="green", lw=0.8,
                   linestyle=":", label="_start_cross")

    if end_event:
        ax.axvline(end_event.transition_time, color="red", lw=1.5,
                   linestyle="-", label=f"End ({end_event.transition_time.strftime('%H:%M')})")
        ax.axvline(end_event.threshold_crossing_time, color="red", lw=0.8,
                   linestyle=":", label="_end_cross")


def _plot_ramps(ax: plt.Axes, ramp_events: list[RampEvent]) -> None:
    for i, r in enumerate(ramp_events):
        color  = "#2ca02c" if r.event_type == "UP" else "#e377c2"
        label  = f"Ramp {r.event_type}" if i == 0 else "_"
        ax.annotate(
            "",
            xy=(r.end_time, r.end_kw),
            xytext=(r.start_time, r.start_kw),
            arrowprops=dict(arrowstyle="->", color=color, lw=1.2),
        )


def _plot_peaks(ax: plt.Axes, peak_events: list[PeakEvent], c_pk: str) -> None:
    for p in peak_events:
        marker = "*" if p.rank == 1 else "^"
        size   = 150 if p.rank == 1 else 80
        label  = "Primary peak" if p.rank == 1 else (f"Peak {p.rank}" if p.rank == 2 else "_")
        ax.scatter(p.peak_time, p.peak_kw, marker=marker, color=c_pk, s=size,
                   zorder=5, label=label)
        ax.annotate(
            f"{p.peak_kw:.0f} kW",
            xy=(p.peak_time, p.peak_kw),
            xytext=(5, 5), textcoords="offset points",
            fontsize=7, color=c_pk,
        )


def _plot_normalised(
    ax: plt.Axes,
    norm_demand: pd.Series,
    cfg: dict[str, Any],
    c_obs: str,
) -> None:
    ax.plot(norm_demand.index, norm_demand.values, color=c_obs, lw=1.2)
    ax.axhline(0, color="black", lw=0.5)
    ax.axhline(1, color="#888888", lw=0.5, linestyle="--")

    breadth_cfg = cfg.get("breadth", {})
    for thr in breadth_cfg.get("operating_thresholds", [0.20, 0.40, 0.60, 0.80, 0.90]):
        ax.axhline(thr, color="orange", lw=0.5, linestyle=":", alpha=0.7)
    for thr in breadth_cfg.get("peak_thresholds", [0.70, 0.80, 0.90]):
        ax.axhline(thr, color="red", lw=0.5, linestyle=":", alpha=0.5)

    ax.set_ylim(-0.1, 1.2)
    ax.fill_between(norm_demand.index, 0, norm_demand.values.clip(0, None),
                    alpha=0.15, color=c_obs)


def plot_population_summary(
    daily_df: pd.DataFrame,
    cfg: dict[str, Any],
) -> plt.Figure:
    """
    High-level population summary showing class distribution and key metric distributions.
    """
    viz_cfg = cfg.get("visualization", {})
    fig, axes = plt.subplots(2, 2, figsize=(14, 8), dpi=viz_cfg.get("dpi", 120))
    fig.suptitle("Population-Level Daily Load Profile Summary", fontsize=13)

    # Class distribution
    if "primary_class" in daily_df.columns:
        vc = daily_df["primary_class"].value_counts()
        axes[0, 0].bar(vc.index, vc.values, color="steelblue")
        axes[0, 0].set_title("Primary Classification Distribution")
        axes[0, 0].set_xlabel("Class")
        axes[0, 0].set_ylabel("Count")
        axes[0, 0].tick_params(axis="x", rotation=30)

    # Start time distribution
    if "probable_start_time" in daily_df.columns:
        start_hours = daily_df["probable_start_time"].dropna().apply(
            lambda s: pd.Timestamp(s).hour + pd.Timestamp(s).minute / 60
        )
        axes[0, 1].hist(start_hours, bins=24, color="green", alpha=0.7)
        axes[0, 1].set_title("Start Time Distribution")
        axes[0, 1].set_xlabel("Hour of Day")
        axes[0, 1].set_ylabel("Days")

    # Operating duration
    if "total_operating_duration_hours" in daily_df.columns:
        axes[1, 0].hist(daily_df["total_operating_duration_hours"].dropna(), bins=20,
                        color="steelblue", alpha=0.7)
        axes[1, 0].set_title("Operating Duration (hours)")
        axes[1, 0].set_xlabel("Hours")
        axes[1, 0].set_ylabel("Days")

    # Peak kW distribution
    if "peak_kw" in daily_df.columns:
        axes[1, 1].hist(daily_df["peak_kw"].dropna(), bins=20,
                        color="tomato", alpha=0.7)
        axes[1, 1].set_title("Daily Peak Demand (kW)")
        axes[1, 1].set_xlabel("kW")
        axes[1, 1].set_ylabel("Days")

    fig.tight_layout()
    return fig
