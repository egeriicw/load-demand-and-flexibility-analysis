"""DER Opportunity Analysis — multi-meter/portfolio layer built on top of the
single-meter ``load_profile`` engine. See spec/SPEC.md Part II."""

from .meters import MeterSpec, build_meter_specs, resolve_meter_groups, resolve_portfolio
from .aggregation import aggregate_entity, build_entity_frame
from .calendar_features import add_calendar_features, add_time_of_day_segments
from .temperature import band_temperature, load_temperature_data, merge_temperature
from .change_point import (
    ChangePointModel,
    fit_2p,
    fit_3p_cooling,
    fit_3p_heating,
    fit_4p,
    fit_5p,
    select_best_change_point_model,
)
from .demand_classification import classify_demand_families
from .local_extrema import add_local_extrema_flags
from .peak_events import DERPeakEvent, detect_der_peak_events
from .load_shape import classify_load_shape
from .clustering import (
    ClusteringResult,
    build_daily_profile_matrix,
    cluster_daily_profiles,
    cluster_entity_daily_profiles,
    peak_normalized_series,
    select_k,
)
from .patterns import (
    build_daily_summary,
    find_outlier_days,
    find_recurring_peak_timing,
    find_recurring_shape,
)
from .coincidence import CoincidenceResult, compute_coincidence_factor, compute_daily_coincidence
from .output import DEROutputBundle, build_der_output, export_der_output
from .pipeline import DERResult, run_der_pipeline

__all__ = [
    "MeterSpec",
    "build_meter_specs",
    "resolve_meter_groups",
    "resolve_portfolio",
    "aggregate_entity",
    "build_entity_frame",
    "add_calendar_features",
    "add_time_of_day_segments",
    "load_temperature_data",
    "merge_temperature",
    "band_temperature",
    "ChangePointModel",
    "fit_2p",
    "fit_3p_cooling",
    "fit_3p_heating",
    "fit_4p",
    "fit_5p",
    "select_best_change_point_model",
    "classify_demand_families",
    "add_local_extrema_flags",
    "DERPeakEvent",
    "detect_der_peak_events",
    "classify_load_shape",
    "ClusteringResult",
    "build_daily_profile_matrix",
    "cluster_daily_profiles",
    "cluster_entity_daily_profiles",
    "peak_normalized_series",
    "select_k",
    "build_daily_summary",
    "find_outlier_days",
    "find_recurring_peak_timing",
    "find_recurring_shape",
    "CoincidenceResult",
    "compute_coincidence_factor",
    "compute_daily_coincidence",
    "DEROutputBundle",
    "build_der_output",
    "export_der_output",
    "DERResult",
    "run_der_pipeline",
]
