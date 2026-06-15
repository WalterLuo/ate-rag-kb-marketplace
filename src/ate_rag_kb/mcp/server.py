"""MCP server for ATE RAG Knowledge Base.

Provides stdio transport for agent-native integration with Claude Code,
OpenClaw, Codex, and Cursor.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel

from ate_rag_kb.mcp.tools import TOOL_SCHEMAS, McpToolHandler
from ate_rag_kb.retrieval.coordinator import build_retrieval_coordinator
from ate_rag_kb.retrieval.pipeline import RetrievalPipeline
from ate_rag_kb.utils.config import Config

if TYPE_CHECKING:
    from mcp.server import Server

logger = logging.getLogger(__name__)

_TOOL_DESCRIPTIONS: dict[str, str] = {
    "ate_kb.search": (
        "Exploratory semantic search over the ATE knowledge base. "
        "Use for topic discovery or locating relevant source files; for "
        "answering specific ATE technical questions, prefer ate_kb.retrieve "
        "or ate_kb.ask."
    ),
    "ate_kb.retrieve": (
        "Default MCP tool for answering specific ATE technical questions. "
        "Uses hybrid search, reranking, parent-child expansion, and compression. "
        "Use this before CLI search, shell grep/rg, or raw markdown reads."
    ),
    "ate_kb.ask": (
        "Default MCP tool for direct ATE Q&A with citations and confidence "
        "scoring. Returns a grounded context package for agent synthesis. "
        "Use this before CLI search, shell grep/rg, or raw markdown reads."
    ),
    "ate_kb.related": (
        "Get parent, sibling, and child chunks for a given chunk ID. "
        "Use when a retrieved passage needs broader context."
    ),
    "ate_kb.get_document": (
        "Retrieve all chunks for a source markdown file. "
        "Use after ate_kb.retrieve or ate_kb.ask identifies a relevant "
        "source_md and full-document context is needed."
    ),
    "ate_kb.status": (
        "Check knowledge base health and collection statistics. "
        "Use to verify the KB is available before querying."
    ),
}


def _build_error_response(message: str, suggestion: str) -> dict[str, Any]:
    return {"error": message, "suggestion": suggestion}


class McpServerApp:
    """MCP server application with registered tool handlers."""

    def __init__(self, config: Config) -> None:
        self.pipeline = RetrievalPipeline(config)
        self.coordinator = build_retrieval_coordinator(config, self.pipeline)
        self.handler = McpToolHandler(self.pipeline, coordinator=self.coordinator)
        self._server: Server = self._create_server()

    def _create_server(self) -> Server:
        from mcp import types
        from mcp.server import Server

        server = Server("ate-kb")

        @server.list_tools()
        async def handle_list_tools() -> list[Any]:
            tools: list[Any] = []
            for name, schema in TOOL_SCHEMAS.items():
                tools.append(
                    types.Tool(
                        name=name,
                        description=_TOOL_DESCRIPTIONS.get(name, ""),
                        inputSchema=schema,
                    )
                )
            return tools

        @server.call_tool()
        async def handle_call_tool(
            name: str, arguments: dict | None
        ) -> list[Any]:
            args = arguments or {}
            logger.info("MCP tool call: %s", name)

            try:
                result: BaseModel
                if name == "ate_kb.search":
                    result = await self.handler.handle_search(args)
                elif name == "ate_kb.retrieve":
                    result = await self.handler.handle_retrieve(args)
                elif name == "ate_kb.ask":
                    result = await self.handler.handle_ask(args)
                elif name == "ate_kb.related":
                    result = await self.handler.handle_related(args)
                elif name == "ate_kb.get_document":
                    result = await self.handler.handle_get_document(args)
                elif name == "ate_kb.status":
                    result = await self.handler.handle_status(args)
                else:
                    error_payload = _build_error_response(
                        f"Unknown tool: {name}",
                        "Use ate_kb.search, ate_kb.retrieve, ate_kb.ask, "
                        "ate_kb.related, ate_kb.get_document, or ate_kb.status",
                    )
                    return [types.TextContent(type="text", text=json.dumps(error_payload, indent=2))]

                return [types.TextContent(type="text", text=result.model_dump_json(indent=2))]

            except Exception as exc:
                logger.exception("MCP tool %s failed", name)
                error_payload = _build_error_response(
                    f"Tool execution failed: {exc}",
                    "Check that Qdrant is running and documents are ingested.",
                )
                return [types.TextContent(type="text", text=json.dumps(error_payload, indent=2))]

        return server

    async def run(self) -> None:
        """Start the stdio transport and block until closed."""
        from mcp.server.stdio import stdio_server

        async with stdio_server() as (read_stream, write_stream):
            logger.info("MCP server starting (stdio transport)")
            await self._server.run(
                read_stream,
                write_stream,
                self._server.create_initialization_options(),
            )


async def run_mcp_server(config: Config) -> None:
    """Run the MCP server with stdio transport.

    This function blocks until the input stream is closed.
    """
    app = McpServerApp(config)
    await app.run()
