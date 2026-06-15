"""Prompt templates and Claude Code skill schema."""

from ate_rag_kb.prompts.claude_code import CLAUDE_CODE_TOOLS, build_tool_result
from ate_rag_kb.prompts.templates import get_prompt

__all__ = ["get_prompt", "CLAUDE_CODE_TOOLS", "build_tool_result"]
