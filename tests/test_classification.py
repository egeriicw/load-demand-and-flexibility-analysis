from __future__ import annotations

from load_profile.classification import (
    CLASS_CONTINUOUS,
    CLASS_EARLY_START,
    CLASS_EVENING_START,
    CLASS_MIDDAY_START,
    CLASS_MINIMAL_LOAD,
    CLASS_MORNING_START,
    CLASS_NO_CLEAR_START,
    CLASS_UNKNOWN,
    classify_day,
)


def _base_features(**overrides):
    feat = {
        "is_continuous_operation": False,
        "minimum_kw": 50.0,
        "maximum_kw": 450.0,
        "probable_start_time": None,
        "total_operating_duration_hours": 0.0,
        "dq_completeness_fraction": 1.0,
        "start_confidence": None,
        "end_confidence": None,
        "startup_ramp_kw_per_hr": None,
        "start_is_gradual": None,
        "shutdown_ramp_kw_per_hr": None,
        "end_is_gradual": None,
        "peak_width_80_hours": None,
        "peak_concentration_1hr": None,
        "operating_period_count": 0,
        "secondary_peak_count": 0,
        "cv": None,
    }
    feat.update(overrides)
    return feat


class TestClassifyDayPrimaryClass:
    def test_continuous_operation(self, cfg):
        feat = _base_features(is_continuous_operation=True)
        result = classify_day(feat, cfg)
        assert result["primary_class"] == CLASS_CONTINUOUS

    def test_minimal_load_when_range_small(self, cfg):
        feat = _base_features(minimum_kw=100.0, maximum_kw=102.0)
        result = classify_day(feat, cfg)
        assert result["primary_class"] == CLASS_MINIMAL_LOAD

    def test_early_start(self, cfg):
        feat = _base_features(
            minimum_kw=50.0, maximum_kw=450.0,
            probable_start_time="2024-01-15T04:30:00-06:00",
        )
        result = classify_day(feat, cfg)
        assert result["primary_class"] == CLASS_EARLY_START

    def test_morning_start(self, cfg):
        feat = _base_features(
            minimum_kw=50.0, maximum_kw=450.0,
            probable_start_time="2024-01-15T07:30:00-06:00",
        )
        result = classify_day(feat, cfg)
        assert result["primary_class"] == CLASS_MORNING_START

    def test_midday_start(self, cfg):
        feat = _base_features(
            minimum_kw=50.0, maximum_kw=450.0,
            probable_start_time="2024-01-15T11:00:00-06:00",
        )
        result = classify_day(feat, cfg)
        assert result["primary_class"] == CLASS_MIDDAY_START

    def test_evening_start(self, cfg):
        feat = _base_features(
            minimum_kw=50.0, maximum_kw=450.0,
            probable_start_time="2024-01-15T16:00:00-06:00",
        )
        result = classify_day(feat, cfg)
        assert result["primary_class"] == CLASS_EVENING_START

    def test_no_clear_start_when_operated_without_start_event(self, cfg):
        feat = _base_features(
            minimum_kw=50.0, maximum_kw=450.0,
            probable_start_time=None,
            total_operating_duration_hours=5.0,
        )
        result = classify_day(feat, cfg)
        assert result["primary_class"] == CLASS_NO_CLEAR_START

    def test_unknown_when_no_information(self, cfg):
        feat = _base_features(
            minimum_kw=50.0, maximum_kw=450.0,
            probable_start_time=None,
            total_operating_duration_hours=0.0,
        )
        result = classify_day(feat, cfg)
        assert result["primary_class"] == CLASS_UNKNOWN


class TestClassifyDayAttributes:
    def test_rapid_start_attribute(self, cfg):
        feat = _base_features(
            minimum_kw=50.0, maximum_kw=450.0,
            probable_start_time="2024-01-15T07:00:00-06:00",
            startup_ramp_kw_per_hr=100.0,
        )
        result = classify_day(feat, cfg)
        assert "rapid_start" in result["attributes"]

    def test_gradual_start_attribute(self, cfg):
        feat = _base_features(
            minimum_kw=50.0, maximum_kw=450.0,
            probable_start_time="2024-01-15T07:00:00-06:00",
            startup_ramp_kw_per_hr=10.0,
            start_is_gradual=True,
        )
        result = classify_day(feat, cfg)
        assert "gradual_start" in result["attributes"]

    def test_long_operating_duration_attribute(self, cfg):
        feat = _base_features(
            minimum_kw=50.0, maximum_kw=450.0,
            probable_start_time="2024-01-15T06:00:00-06:00",
            total_operating_duration_hours=12.0,
        )
        result = classify_day(feat, cfg)
        assert "long_operating_duration" in result["attributes"]

    def test_short_operating_duration_attribute(self, cfg):
        feat = _base_features(
            minimum_kw=50.0, maximum_kw=450.0,
            probable_start_time="2024-01-15T06:00:00-06:00",
            total_operating_duration_hours=1.0,
        )
        result = classify_day(feat, cfg)
        assert "short_operating_duration" in result["attributes"]

    def test_broad_peak_attribute(self, cfg):
        feat = _base_features(
            minimum_kw=50.0, maximum_kw=450.0,
            probable_start_time="2024-01-15T06:00:00-06:00",
            peak_width_80_hours=4.0,
        )
        result = classify_day(feat, cfg)
        assert "broad_peak" in result["attributes"]

    def test_sharp_peak_attribute(self, cfg):
        feat = _base_features(
            minimum_kw=50.0, maximum_kw=450.0,
            probable_start_time="2024-01-15T06:00:00-06:00",
            peak_width_80_hours=0.5,
        )
        result = classify_day(feat, cfg)
        assert "sharp_peak" in result["attributes"]

    def test_multiple_operating_periods_attribute(self, cfg):
        feat = _base_features(
            minimum_kw=50.0, maximum_kw=450.0,
            probable_start_time="2024-01-15T06:00:00-06:00",
            operating_period_count=2,
        )
        result = classify_day(feat, cfg)
        assert "multiple_operating_periods" in result["attributes"]

    def test_multiple_peaks_attribute(self, cfg):
        feat = _base_features(
            minimum_kw=50.0, maximum_kw=450.0,
            probable_start_time="2024-01-15T06:00:00-06:00",
            secondary_peak_count=2,
        )
        result = classify_day(feat, cfg)
        assert "multiple_peaks" in result["attributes"]

    def test_high_intraday_variability_attribute(self, cfg):
        feat = _base_features(
            minimum_kw=50.0, maximum_kw=450.0,
            probable_start_time="2024-01-15T06:00:00-06:00",
            cv=0.5,
        )
        result = classify_day(feat, cfg)
        assert "high_intraday_variability" in result["attributes"]

    def test_high_peak_concentration_attribute(self, cfg):
        feat = _base_features(
            minimum_kw=50.0, maximum_kw=450.0,
            probable_start_time="2024-01-15T06:00:00-06:00",
            peak_concentration_1hr=0.5,
        )
        result = classify_day(feat, cfg)
        assert "high_peak_concentration" in result["attributes"]


class TestClassificationConfidence:
    def test_confidence_bounded_0_1(self, cfg):
        feat = _base_features(
            minimum_kw=50.0, maximum_kw=450.0,
            probable_start_time="2024-01-15T06:00:00-06:00",
            dq_completeness_fraction=1.0,
            start_confidence=1.0,
            end_confidence=1.0,
        )
        result = classify_day(feat, cfg)
        assert 0.0 <= result["classification_confidence"] <= 1.0

    def test_confidence_reduced_for_unknown_class(self, cfg):
        feat_known = _base_features(
            minimum_kw=50.0, maximum_kw=450.0,
            probable_start_time="2024-01-15T06:00:00-06:00",
            dq_completeness_fraction=1.0,
            start_confidence=0.8,
            end_confidence=0.8,
        )
        feat_unknown = _base_features(
            minimum_kw=50.0, maximum_kw=450.0,
            probable_start_time=None,
            total_operating_duration_hours=0.0,
            dq_completeness_fraction=1.0,
        )
        conf_known = classify_day(feat_known, cfg)["classification_confidence"]
        conf_unknown = classify_day(feat_unknown, cfg)["classification_confidence"]
        assert conf_unknown < conf_known

    def test_notes_present(self, cfg):
        feat = _base_features(is_continuous_operation=True)
        result = classify_day(feat, cfg)
        assert isinstance(result["classification_notes"], str)
        assert len(result["classification_notes"]) > 0
