"""Building Daily Load Profile Characterization Engine."""

from .config import load_config
from .config_schema import validate_config, ConfigValidationError
from .data_ingestion import load_demand_data, validate_input, convert_units
from .time_series import regularize, assess_quality
from .baseline import estimate_baseline
from .states import detect_states
from .events import detect_start, detect_end, detect_ramps, detect_peaks
from .features import build_daily_features
from .classification import classify_day
from .visualization import plot_daily_profile
from .synthetic import generate_synthetic_day, SCENARIOS
from .pipeline import run_pipeline

__all__ = [
    "load_config",
    "validate_config",
    "ConfigValidationError",
    "load_demand_data",
    "validate_input",
    "convert_units",
    "regularize",
    "assess_quality",
    "estimate_baseline",
    "detect_states",
    "detect_start",
    "detect_end",
    "detect_ramps",
    "detect_peaks",
    "build_daily_features",
    "classify_day",
    "plot_daily_profile",
    "generate_synthetic_day",
    "SCENARIOS",
    "run_pipeline",
]
