"""Unit tests for Qdrant vector store schema helpers."""

from __future__ import annotations

from qdrant_client.models import Filter, MatchAny, MatchValue

from ate_rag_kb.vector_store.schema import build_filter


class TestBuildFilter:
    def test_empty_dict_returns_none(self) -> None:
        result = build_filter({})

        assert result is None

    def test_single_scalar_value(self) -> None:
        result = build_filter({"platform": "TDC"})

        assert isinstance(result, Filter)
        assert len(result.must) == 1
        assert result.must[0].key == "platform"
        assert isinstance(result.must[0].match, MatchValue)
        assert result.must[0].match.value == "TDC"

    def test_single_list_value(self) -> None:
        result = build_filter({"platform": ["TDC", "J750"]})

        assert isinstance(result, Filter)
        assert len(result.must) == 1
        assert result.must[0].key == "platform"
        assert isinstance(result.must[0].match, MatchAny)
        assert result.must[0].match.any == ["TDC", "J750"]

    def test_multiple_fields(self) -> None:
        result = build_filter({"platform": "TDC", "doc_type": "guide"})

        assert isinstance(result, Filter)
        assert len(result.must) == 2
        keys = {c.key for c in result.must}
        assert keys == {"platform", "doc_type"}

    def test_mixed_scalar_and_list_values(self) -> None:
        result = build_filter({"platform": "TDC", "doc_type": ["guide", "api"]})

        assert isinstance(result, Filter)
        assert len(result.must) == 2

        platform_cond = next(c for c in result.must if c.key == "platform")
        doctype_cond = next(c for c in result.must if c.key == "doc_type")

        assert isinstance(platform_cond.match, MatchValue)
        assert isinstance(doctype_cond.match, MatchAny)

    def test_none_input_returns_none(self) -> None:
        result = build_filter(None)

        assert result is None
