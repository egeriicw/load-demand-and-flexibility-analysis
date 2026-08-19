from __future__ import annotations

import numpy as np
import pandas as pd

from load_profile.der.pipeline import PORTFOLIO_ENTITY_ID, run_der_pipeline


class TestPhase2Enrichment:
    def test_entity_calendar_frames_populated(self, two_meter_cfg):
        result = run_der_pipeline(two_meter_cfg, verbose=False)
        cal = result.entity_calendar_frames[PORTFOLIO_ENTITY_ID]
        assert "season" in cal.columns
        assert "day_type" in cal.columns

    def test_entity_tod_frames_populated(self, two_meter_cfg):
        result = run_der_pipeline(two_meter_cfg, verbose=False)
        tod = result.entity_tod_frames[PORTFOLIO_ENTITY_ID]
        assert "morning_peak_kw" in tod.columns
        assert len(tod) >= 1

    def test_no_temperature_source_means_no_temperature_frames(self, two_meter_cfg):
        result = run_der_pipeline(two_meter_cfg, verbose=False)
        assert result.entity_temperature_frames == {}

    def test_temperature_source_populates_temperature_frames(self, two_meter_cfg):
        portfolio_idx = None
        # Run once without temperature to learn the portfolio's timestamp range.
        result = run_der_pipeline(two_meter_cfg, verbose=False)
        portfolio_idx = result.entity_frames[PORTFOLIO_ENTITY_ID].index

        temp_df = pd.DataFrame({
            "datetime": portfolio_idx,
            "temperature_f": np.linspace(30, 80, len(portfolio_idx)),
        })
        two_meter_cfg["der"]["temperature"]["source"] = temp_df

        result2 = run_der_pipeline(two_meter_cfg, verbose=False)
        temp_frame = result2.entity_temperature_frames[PORTFOLIO_ENTITY_ID]
        assert "temperature_f" in temp_frame.columns
        assert "temperature_band" in temp_frame.columns
        assert temp_frame["temperature_f"].notna().any()

    def test_empty_entity_skips_enrichment_without_error(self, cfg):
        result = run_der_pipeline(cfg, verbose=False)
        assert result.entity_calendar_frames == {}
        assert result.entity_tod_frames == {}
