"""Unit tests for RetrievalPlanner."""

from __future__ import annotations

import pytest

from ate_rag_kb.domain.scopes import TERADYNE_J750_IGXL
from ate_rag_kb.retrieval.planner import RetrievalPlanner
from ate_rag_kb.utils.config import Config


class TestRetrievalPlanner:
    @pytest.fixture
    def planner(self) -> RetrievalPlanner:
        return RetrievalPlanner()

    # -------------------------------------------------------------------
    # Ecosystem detection
    # -------------------------------------------------------------------

    def test_detect_ecosystem_igxl(self, planner: RetrievalPlanner) -> None:
        plan = planner.plan("ig-xl job list")
        assert plan.ecosystem == "igxl"
        assert plan.is_igxl_query is True

    def test_detect_ecosystem_v93000(self, planner: RetrievalPlanner) -> None:
        plan = planner.plan("v93000 timing configuration")
        assert plan.ecosystem == "v93000"
        assert plan.is_v93000_smt7_query is True

    def test_detect_ecosystem_smt7(self, planner: RetrievalPlanner) -> None:
        plan = planner.plan("smt7 array handling")
        assert plan.ecosystem == "v93000"

    def test_detect_ecosystem_tdc(self, planner: RetrievalPlanner) -> None:
        plan = planner.plan("tdc flow creator usage")
        assert plan.ecosystem == "v93000"

    def test_detect_ecosystem_neutral(self, planner: RetrievalPlanner) -> None:
        plan = planner.plan("how does testing work in general")
        assert plan.ecosystem is None

    def test_uses_resolved_scope_when_provided(self, planner: RetrievalPlanner) -> None:
        plan = planner.plan("多 site 串行处理怎么实现？", scope=TERADYNE_J750_IGXL)
        assert plan.ecosystem == "igxl"
        assert plan.doc_family == "igxl_help"

    def test_non_igxl_terms_override_igxl(self, planner: RetrievalPlanner) -> None:
        # "v93000" should win even if "pattern tool" is an IG-XL term
        plan = planner.plan("v93000 pattern tool")
        assert plan.ecosystem == "v93000"

    # -------------------------------------------------------------------
    # Doc family detection
    # -------------------------------------------------------------------

    def test_detect_doc_family_tdc(self, planner: RetrievalPlanner) -> None:
        plan = planner.plan("tdc test development center")
        assert plan.doc_family == "tdc"
        assert plan.ecosystem == "v93000"

    def test_detect_doc_family_igxl_help(self, planner: RetrievalPlanner) -> None:
        plan = planner.plan("datatool pin map configuration")
        assert plan.doc_family == "igxl_help"
        assert plan.ecosystem == "igxl"

    def test_detect_doc_family_smt7_help(self, planner: RetrievalPlanner) -> None:
        plan = planner.plan("smt7 online help")
        assert plan.doc_family == "smt7_help"
        assert plan.ecosystem == "v93000"

    def test_detect_doc_family_v93000_manual(self, planner: RetrievalPlanner) -> None:
        plan = planner.plan("v93000 hardware manual")
        assert plan.doc_family == "v93000_manual"
        assert plan.ecosystem == "v93000"

    # -------------------------------------------------------------------
    # Glossary expansion
    # -------------------------------------------------------------------

    def test_expand_glossary_job_list(self, planner: RetrievalPlanner) -> None:
        plan = planner.plan("作业列表有什么用")
        assert "Job List Sheet" in plan.enhanced_query

    def test_expand_glossary_array(self, planner: RetrievalPlanner) -> None:
        plan = planner.plan("数组的作用")
        assert "ARRAY" in plan.enhanced_query

    def test_igxl_serial_site_loop_expands_api_terms(self, planner: RetrievalPlanner) -> None:
        plan = planner.plan("IG-XL 多 site 串行处理怎么实现？", scope=TERADYNE_J750_IGXL)
        assert "SelectFirst" in plan.enhanced_query
        assert "SelectNext" in plan.enhanced_query
        assert "loopDone" in plan.enhanced_query
        assert "FastSiteLoop" in plan.enhanced_query

    def test_no_expansion_for_unknown_query(self, planner: RetrievalPlanner) -> None:
        plan = planner.plan("random unrelated query")
        assert plan.enhanced_query == "random unrelated query"

    # -------------------------------------------------------------------
    # Title match terms
    # -------------------------------------------------------------------

    def test_extract_title_match_terms_job_list(self, planner: RetrievalPlanner) -> None:
        plan = planner.plan("Job List Sheet usage")
        assert "job list sheet" in plan.title_match_terms

    def test_extract_title_match_terms_with_glossary(self, planner: RetrievalPlanner) -> None:
        plan = planner.plan("作业列表")
        assert "job list sheet" in plan.title_match_terms

    # -------------------------------------------------------------------
    # Filter inference
    # -------------------------------------------------------------------

    def test_infer_filters_igxl(self, planner: RetrievalPlanner) -> None:
        plan = planner.plan("ig-xl pattern tool")
        assert plan.inferred_filters is None

    def test_infer_filters_smt7(self, planner: RetrievalPlanner) -> None:
        plan = planner.plan("smt7 timing")
        assert plan.inferred_filters == {"ecosystem": "v93000", "software_version": ["smt7", ""]}

    def test_infer_filters_smt8(self, planner: RetrievalPlanner) -> None:
        plan = planner.plan("smt8 timing")
        assert plan.inferred_filters == {"ecosystem": "v93000", "software_version": ["smt8", ""]}

    def test_infer_filters_v93000(self, planner: RetrievalPlanner) -> None:
        plan = planner.plan("v93000 levels")
        assert plan.inferred_filters == {"ecosystem": "v93000"}

    def test_infer_filters_tdc(self, planner: RetrievalPlanner) -> None:
        plan = planner.plan("tdc module creation")
        assert plan.inferred_filters == {"ecosystem": "v93000", "doc_family": "tdc"}

    def test_infer_filters_neutral(self, planner: RetrievalPlanner) -> None:
        plan = planner.plan("general testing question")
        assert plan.inferred_filters is None

    def test_infer_filters_v93000_ecosystem_no_specific_platform(
        self, planner: RetrievalPlanner
    ) -> None:
        plan = planner.plan("flextest timing")
        assert plan.ecosystem == "v93000"
        assert plan.inferred_filters == {"ecosystem": "v93000"}

    # -------------------------------------------------------------------
    # TDC logical mapping
    # -------------------------------------------------------------------

    def test_tdc_mapped_to_v93000_ecosystem(self, planner: RetrievalPlanner) -> None:
        plan = planner.plan("tdc how to view documents")
        assert plan.ecosystem == "v93000"
        assert plan.doc_family == "tdc"

    # -------------------------------------------------------------------
    # Regression: weak terms must not force TDC doc_family
    # -------------------------------------------------------------------

    def test_site_control_query_not_forced_tdc(self, planner: RetrievalPlanner) -> None:
        """Site Control contains 'test suite' which is a weak TDC term."""
        plan = planner.plan("SmarTest 7 中 test suite 的 Site Control 都有什么用处？")
        assert plan.doc_family != "tdc"
        assert plan.ecosystem == "v93000"

    def test_site_control_usage_question_is_broad(self, planner: RetrievalPlanner) -> None:
        plan = planner.plan("Site Control 有什么用？")

        assert plan.is_broad_concept is True

    def test_module_query_not_forced_tdc(self, planner: RetrievalPlanner) -> None:
        """'module' alone must not trigger TDC doc_family filter."""
        plan = planner.plan("how to configure a module")
        assert plan.doc_family != "tdc"

    def test_flow_creator_query_not_forced_tdc(self, planner: RetrievalPlanner) -> None:
        """'flow creator' alone must not trigger TDC doc_family filter."""
        plan = planner.plan("flow creator basics")
        assert plan.doc_family != "tdc"

    def test_tdc_viewer_query_still_detected(self, planner: RetrievalPlanner) -> None:
        """Strong TDC terms must still correctly set doc_family."""
        plan = planner.plan("tdc viewer 如何使用")
        assert plan.doc_family == "tdc"
        assert plan.ecosystem == "v93000"

    def test_test_development_center_query_still_detected(self, planner: RetrievalPlanner) -> None:
        plan = planner.plan("test development center overview")
        assert plan.doc_family == "tdc"
        assert plan.ecosystem == "v93000"

    # -------------------------------------------------------------------
    # Glossary ecosystem / doc_family backfill
    # -------------------------------------------------------------------

    def test_glossary_backfills_igxl_ecosystem(self, planner: RetrievalPlanner) -> None:
        plan = planner.plan("作业列表有什么用")
        assert plan.ecosystem == "igxl"
        assert plan.doc_family == "igxl_help"

    def test_glossary_backfills_tdc_ecosystem(self, planner: RetrievalPlanner) -> None:
        plan = planner.plan("TDC 文档怎么查看")
        assert plan.ecosystem == "v93000"
        assert plan.doc_family == "tdc"

    def test_explicit_platform_wins_over_glossary(self, planner: RetrievalPlanner) -> None:
        plan = planner.plan("SMT7 job list")
        assert plan.ecosystem == "v93000"
        assert plan.doc_family != "igxl_help"
        assert "Job List Sheet" not in plan.enhanced_query
        assert "DataTool Job List" not in plan.enhanced_query

    # -------------------------------------------------------------------
    # Block detection
    # -------------------------------------------------------------------

    def test_blocks_igxl_when_disabled(self) -> None:
        planner = RetrievalPlanner(Config({"documents": {"igxl": {"enabled": False}}}))
        plan = planner.plan("ig-xl job list")
        assert plan.is_blocked is True
        assert "not enabled" in (plan.block_reason or "").lower()

    def test_allows_igxl_when_enabled(self) -> None:
        planner = RetrievalPlanner(Config({"documents": {"igxl": {"enabled": True}}}))
        plan = planner.plan("ig-xl job list")
        assert plan.is_blocked is False

    # -------------------------------------------------------------------
    # Ambiguity detection
    # -------------------------------------------------------------------

    def test_ambiguous_when_both_smt7_smt8_enabled_and_vague(self) -> None:
        planner = RetrievalPlanner(
            Config(
                {
                    "documents": {
                        "v93000": {
                            "enabled_software_versions": ["smt7", "smt8"],
                            "ambiguity_policy": "ask_when_multiple",
                        }
                    }
                }
            )
        )
        plan = planner.plan("smartest timing configuration")
        assert plan.is_ambiguous is True
        assert plan.clarification_prompt is not None
        assert "smt7" in plan.clarification_prompt.lower() or "smt8" in plan.clarification_prompt.lower()

    def test_not_ambiguous_when_specific_version_mentioned(self) -> None:
        planner = RetrievalPlanner(
            Config(
                {
                    "documents": {
                        "v93000": {
                            "enabled_software_versions": ["smt7", "smt8"],
                            "ambiguity_policy": "ask_when_multiple",
                        }
                    }
                }
            )
        )
        plan = planner.plan("smt7 timing configuration")
        assert plan.is_ambiguous is False

    def test_not_ambiguous_when_only_one_version_enabled(self) -> None:
        planner = RetrievalPlanner(
            Config(
                {
                    "documents": {
                        "v93000": {
                            "enabled_software_versions": ["smt7"],
                            "ambiguity_policy": "ask_when_multiple",
                        }
                    }
                }
            )
        )
        plan = planner.plan("smartest timing configuration")
        assert plan.is_ambiguous is False
