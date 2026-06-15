"""Claude Code skill schema and tool result builder."""

from __future__ import annotations

from typing import Any

# ---------------------------------------------------------------------------
# Tool definitions for Claude Code integration
# ---------------------------------------------------------------------------

CLAUDE_CODE_TOOLS: list[dict[str, Any]] = [
    {
        "name": "ask_tdc",
        "description": (
            "Ask a question about TDC/SmarTest documentation, test program development, "
            "or ATE platform configuration. Returns relevant documentation passages with citations."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The question or topic to search for in TDC/SmarTest docs.",
                },
                "top_k": {
                    "type": "integer",
                    "default": 5,
                    "description": "Maximum number of documentation chunks to return.",
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "find_flow",
        "description": (
            "Find test flow documentation, including flow syntax, flow graph construction, "
            "sequencing rules, and best practices for ATE test programs."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query for test flow topics.",
                },
                "top_k": {
                    "type": "integer",
                    "default": 5,
                    "description": "Maximum number of documentation chunks to return.",
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "find_api",
        "description": (
            "Find API reference documentation for ATE system control, data acquisition, "
            "and programmatic interfaces. Covers function signatures, parameters, and usage examples."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "API name, function, or topic to search for.",
                },
                "top_k": {
                    "type": "integer",
                    "default": 5,
                    "description": "Maximum number of documentation chunks to return.",
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "find_timing",
        "description": (
            "Find timing configuration documentation, including edge definitions, "
            "timing sets, period calculations, and waveform programming for ATE platforms."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query for timing configuration topics.",
                },
                "top_k": {
                    "type": "integer",
                    "default": 5,
                    "description": "Maximum number of documentation chunks to return.",
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "find_pattern",
        "description": (
            "Find pattern programming documentation, including pattern syntax, vector formats, "
            "pattern compression, and pattern-to-tester mapping for ATE platforms."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query for pattern programming topics.",
                },
                "top_k": {
                    "type": "integer",
                    "default": 5,
                    "description": "Maximum number of documentation chunks to return.",
                },
            },
            "required": ["query"],
        },
    },
]


def build_tool_result(tool_name: str, query: str, chunks: list[dict[str, Any]]) -> dict[str, Any]:
    """Format retrieved chunks into a Claude Code tool result.

    Args:
        tool_name: Name of the tool that was invoked.
        query: Original query string.
        chunks: List of chunk dictionaries (e.g., from the API response).

    Returns:
        A structured result dict suitable for Claude Code consumption.
    """
    formatted_chunks = []
    for idx, chunk in enumerate(chunks, start=1):
        formatted_chunks.append(
            {
                "index": idx,
                "content": chunk.get("content", ""),
                "source": chunk.get("source_md", ""),
                "toc_path": chunk.get("toc_path", []),
                "score": chunk.get("score", 0.0),
                "excerpt": chunk.get("content", "")[:300],
            }
        )

    return {
        "tool": tool_name,
        "query": query,
        "chunks": formatted_chunks,
        "total": len(formatted_chunks),
    }
