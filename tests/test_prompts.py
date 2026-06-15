"""Unit tests for prompt templates."""

from __future__ import annotations

import pytest

from ate_rag_kb.prompts.claude_code import CLAUDE_CODE_TOOLS, build_tool_result
from ate_rag_kb.prompts.templates import get_prompt


class TestGetPrompt:
    def test_ate_system_prompt(self) -> None:
        prompt = get_prompt("ate_system")

        assert "ATE" in prompt
        assert "test engineer" in prompt.lower()

    def test_retrieval_prompt_with_substitution(self) -> None:
        prompt = get_prompt("retrieval", context="Some context", question="What is TDC?")

        assert "Some context" in prompt
        assert "What is TDC?" in prompt

    def test_query_expansion_prompt(self) -> None:
        prompt = get_prompt("query_expansion", query="timing setup")

        assert "timing setup" in prompt

    def test_unknown_prompt_raises_key_error(self) -> None:
        with pytest.raises(KeyError):
            get_prompt("nonexistent")


class TestClaudeCodeTools:
    def test_tools_list_length(self) -> None:
        assert len(CLAUDE_CODE_TOOLS) == 5

    def test_tools_have_required_fields(self) -> None:
        for tool in CLAUDE_CODE_TOOLS:
            assert "name" in tool
            assert "description" in tool
            assert "parameters" in tool

    def test_build_tool_result(self) -> None:
        chunks = [
            {"content": "Hello", "source_md": "doc.md", "toc_path": ["A"], "score": 0.9}
        ]
        result = build_tool_result("ask_tdc", "query", chunks)

        assert result["tool"] == "ask_tdc"
        assert result["query"] == "query"
        assert result["total"] == 1
        assert result["chunks"][0]["index"] == 1
