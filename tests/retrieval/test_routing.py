"""Tests for deterministic retrieval scope routing."""

from __future__ import annotations

import pytest

from ate_rag_kb.domain.scopes import (
    ADVANTEST_V93000_SMT7,
    ADVANTEST_V93000_SMT8,
    TERADYNE_J750_IGXL,
)
from ate_rag_kb.ingestion.symbol_catalog import SymbolCatalog, SymbolOwner
from ate_rag_kb.retrieval.routing import ScopeRouter


@pytest.fixture
def catalog() -> SymbolCatalog:
    return SymbolCatalog(
        {
            "selectfirst": SymbolOwner(
                "SelectFirst",
                TERADYNE_J750_IGXL,
                ("igxl/vbt/execSites.39.08.md",),
            )
        }
    )


@pytest.fixture
def router(catalog: SymbolCatalog) -> ScopeRouter:
    return ScopeRouter(
        enabled_scopes=(TERADYNE_J750_IGXL, ADVANTEST_V93000_SMT7),
        symbol_catalog=catalog,
    )


def test_explicit_igxl_routes_only_to_j750(router: ScopeRouter) -> None:
    route = router.route("IG-XL 多 site 串行处理怎么实现？")
    assert route.answer_mode == "direct"
    assert route.scopes == (TERADYNE_J750_IGXL,)


def test_neutral_question_routes_to_two_isolated_scopes(router: ScopeRouter) -> None:
    route = router.route("多 site 串行处理怎么实现？")
    assert route.answer_mode == "platform_comparison"
    assert route.scopes == (TERADYNE_J750_IGXL, ADVANTEST_V93000_SMT7)


def test_exclusive_symbol_without_platform_routes_to_owner(router: ScopeRouter) -> None:
    route = router.route("SelectFirst 怎么用？")
    assert route.scopes == (TERADYNE_J750_IGXL,)


def test_wrong_platform_symbol_is_corrected(router: ScopeRouter) -> None:
    route = router.route("SMT7 SelectFirst 怎么用？")
    assert route.scopes == (TERADYNE_J750_IGXL,)
    assert "SelectFirst" in route.correction_notice
    assert "IG-XL" in route.correction_notice


def test_v93000_requires_version_when_smt7_and_smt8_enabled(catalog: SymbolCatalog) -> None:
    router = ScopeRouter(
        enabled_scopes=(ADVANTEST_V93000_SMT7, ADVANTEST_V93000_SMT8),
        symbol_catalog=catalog,
    )
    route = router.route("V93000 site control 怎么用？")
    assert route.answer_mode == "clarification"
    assert "SMT7" in route.clarification_prompt
    assert "SMT8" in route.clarification_prompt


def test_neutral_question_requires_platform_after_smt8_enablement(catalog: SymbolCatalog) -> None:
    router = ScopeRouter(
        enabled_scopes=(TERADYNE_J750_IGXL, ADVANTEST_V93000_SMT7, ADVANTEST_V93000_SMT8),
        symbol_catalog=catalog,
    )
    route = router.route("site control 怎么用？")
    assert route.answer_mode == "clarification"
    assert "J750" in route.clarification_prompt
    assert "V93000" in route.clarification_prompt


def test_explicit_two_software_products_return_two_scopes(router: ScopeRouter) -> None:
    route = router.route("请分别给出 IG-XL 和 SMT7 的答案")
    assert route.answer_mode == "platform_comparison"
    assert route.scopes == (TERADYNE_J750_IGXL, ADVANTEST_V93000_SMT7)


def test_follow_up_smt7_answer_routes_directly(router: ScopeRouter) -> None:
    route = router.route("我需要 SMT7 的答案")
    assert route.answer_mode == "direct"
    assert route.scopes == (ADVANTEST_V93000_SMT7,)
