"""DER Opportunity Analysis — multi-meter/portfolio layer built on top of the
single-meter ``load_profile`` engine. See spec/SPEC.md Part II."""

from .meters import MeterSpec, build_meter_specs, resolve_meter_groups, resolve_portfolio
from .aggregation import aggregate_entity, build_entity_frame
from .calendar_features import add_calendar_features, add_time_of_day_segments
from .temperature import band_temperature, load_temperature_data, merge_temperature
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
    "DERResult",
    "run_der_pipeline",
]
