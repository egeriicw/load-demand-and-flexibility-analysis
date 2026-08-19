from __future__ import annotations

from load_profile.der.pipeline import PORTFOLIO_ENTITY_ID, run_der_pipeline


class TestRunDerPipeline:
    def test_no_meters_configured_is_inert(self, cfg):
        result = run_der_pipeline(cfg, verbose=False)
        assert result.meter_tables == {}
        assert result.entity_frames[PORTFOLIO_ENTITY_ID].empty

    def test_runs_per_meter_pipeline_for_each_configured_meter(self, two_meter_cfg):
        result = run_der_pipeline(two_meter_cfg, verbose=False)
        assert set(result.meter_tables) == {"M1", "M2"}
        for table in result.meter_tables.values():
            assert set(table.keys()) == {"interval_df", "daily_df", "ramp_df", "peak_df"}

    def test_portfolio_entity_present_even_without_groups(self, two_meter_cfg):
        result = run_der_pipeline(two_meter_cfg, verbose=False)
        assert PORTFOLIO_ENTITY_ID in result.entity_frames
        assert result.entity_meter_ids[PORTFOLIO_ENTITY_ID] == ["M1", "M2"]

    def test_group_entity_frame_matches_resolved_members(self, grouped_cfg):
        result = run_der_pipeline(grouped_cfg, verbose=False)
        assert result.entity_meter_ids["building_a"] == ["M1", "M2"]
        assert "building_a" in result.entity_frames
        # Portfolio excludes M3 per grouped_cfg fixture
        assert result.entity_meter_ids[PORTFOLIO_ENTITY_ID] == ["M1", "M2"]

    def test_interval_df_multi_tagged_with_meter_id(self, two_meter_cfg):
        result = run_der_pipeline(two_meter_cfg, verbose=False)
        assert set(result.interval_df_multi["meter_id"].unique()) == {"M1", "M2"}

    def test_portfolio_demand_is_sum_of_constituent_meters_same_timestamp(self, two_meter_cfg):
        result = run_der_pipeline(two_meter_cfg, verbose=False)
        m1 = result.meter_tables["M1"]["interval_df"]["demand_kw"]
        m2 = result.meter_tables["M2"]["interval_df"]["demand_kw"]
        portfolio = result.entity_frames[PORTFOLIO_ENTITY_ID]["demand_kw"]
        common_ts = m1.index.intersection(m2.index).intersection(portfolio.index)
        assert len(common_ts) > 0
        for ts in common_ts[:5]:
            assert portfolio.loc[ts] == m1.loc[ts] + m2.loc[ts]
