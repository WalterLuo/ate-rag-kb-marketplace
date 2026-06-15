"""Unit tests for domain glossary."""

from __future__ import annotations

import pytest

from ate_rag_kb.retrieval.glossary import (
    ATE_GLOSSARY,
    expand_query,
    match_glossary,
)


class TestMatchGlossary:
    def test_match_job_list_chinese(self) -> None:
        matched = match_glossary("作业列表有什么用")
        assert len(matched) == 1
        assert "Job List Sheet" in matched[0].expansions

    def test_match_job_list_english(self) -> None:
        matched = match_glossary("How does Job List work")
        assert len(matched) == 1
        assert "Job List Sheet" in matched[0].expansions

    def test_match_array_chinese(self) -> None:
        matched = match_glossary("数组在代码中的作用")
        assert len(matched) == 1
        assert "ARRAY" in matched[0].expansions

    def test_match_spooling_chinese(self) -> None:
        matched = match_glossary("离线控制状态")
        assert len(matched) == 1
        assert "spooling" in matched[0].expansions

    def test_match_multiple_glossary_entries(self) -> None:
        # "job list" + "array" should both match
        matched = match_glossary("Job List 和 ARRAY 的区别")
        assert len(matched) == 2

    def test_no_match(self) -> None:
        matched = match_glossary("random unrelated query")
        assert len(matched) == 0


class TestExpandQuery:
    def test_expand_job_list(self) -> None:
        enhanced = expand_query("作业列表有什么用")
        assert "Job List Sheet" in enhanced
        assert "DataTool Job List" in enhanced

    def test_expand_array(self) -> None:
        enhanced = expand_query("数组的作用")
        assert "ARRAY" in enhanced
        assert "ARRAY_x" in enhanced

    def test_no_expansion(self) -> None:
        original = "random query"
        enhanced = expand_query(original)
        assert enhanced == original

    def test_unique_expansions(self) -> None:
        # If multiple entries share expansions, they should be deduplicated
        enhanced = expand_query("Job List 和 job list")
        # "Job List Sheet" should appear only once
        assert enhanced.count("Job List Sheet") == 1


class TestGlossaryEntry:
    def test_entry_is_frozen(self) -> None:
        entry = ATE_GLOSSARY[0]
        with pytest.raises(AttributeError):
            entry.cn_terms = ("new term",)  # type: ignore[misc]
