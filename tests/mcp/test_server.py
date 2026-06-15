"""Protocol-level integration tests for the MCP server."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from ate_rag_kb.mcp.server import McpServerApp, run_mcp_server
from ate_rag_kb.mcp.tools import TOOL_SCHEMAS
from ate_rag_kb.utils.config import Config

pytest.importorskip("mcp")


@pytest.fixture
def mock_config():
    return Config({"vector_store": {"collection_name": "test_kb"}})


@pytest.fixture
def app(mock_config):
    with patch("ate_rag_kb.mcp.server.RetrievalPipeline") as mock_pipeline_cls, \
         patch("ate_rag_kb.mcp.server.McpToolHandler") as mock_handler_cls:
        mock_pipeline = AsyncMock()
        mock_pipeline_cls.return_value = mock_pipeline
        mock_handler = AsyncMock()
        mock_handler_cls.return_value = mock_handler
        yield McpServerApp(mock_config), mock_pipeline, mock_handler


class TestMcpServerProtocol:
    @pytest.mark.asyncio
    async def test_list_tools_returns_all_tools(self, app):
        mcp_app, _pipeline, _handler = app
        from mcp import types

        # NOTE: Coupled to mcp SDK internal API (request_handlers dict).
        # If upgrading the SDK breaks this, switch to testing via public interfaces.
        list_tools_handler = mcp_app._server.request_handlers[types.ListToolsRequest]
        result = await list_tools_handler(None)

        assert result is not None
        tools = result.root.tools
        assert len(tools) == len(TOOL_SCHEMAS)
        tool_names = {t.name for t in tools}
        expected = {
            "ate_kb.search",
            "ate_kb.retrieve",
            "ate_kb.ask",
            "ate_kb.related",
            "ate_kb.get_document",
            "ate_kb.status",
        }
        assert tool_names == expected

    @pytest.mark.asyncio
    async def test_call_tool_search(self, app):
        mcp_app, _pipeline, handler = app
        from mcp import types

        handler.handle_search = AsyncMock(return_value=AsyncMock(model_dump_json=lambda indent: '{"query": "test"}'))

        call_tool_handler = mcp_app._server.request_handlers[types.CallToolRequest]
        req = types.CallToolRequest(params=types.CallToolRequestParams(name="ate_kb.search", arguments={"query": "test"}))
        result = await call_tool_handler(req)

        handler.handle_search.assert_awaited_once_with({"query": "test"})
        assert len(result.root.content) == 1

    @pytest.mark.asyncio
    async def test_call_tool_retrieve(self, app):
        mcp_app, _pipeline, handler = app
        from mcp import types

        handler.handle_retrieve = AsyncMock(return_value=AsyncMock(model_dump_json=lambda indent: '{"query": "test"}'))

        call_tool_handler = mcp_app._server.request_handlers[types.CallToolRequest]
        req = types.CallToolRequest(params=types.CallToolRequestParams(name="ate_kb.retrieve", arguments={"query": "test"}))
        result = await call_tool_handler(req)

        handler.handle_retrieve.assert_awaited_once_with({"query": "test"})
        assert len(result.root.content) == 1

    @pytest.mark.asyncio
    async def test_call_tool_ask(self, app):
        mcp_app, _pipeline, handler = app
        from mcp import types

        handler.handle_ask = AsyncMock(return_value=AsyncMock(model_dump_json=lambda indent: '{"question": "test"}'))

        call_tool_handler = mcp_app._server.request_handlers[types.CallToolRequest]
        req = types.CallToolRequest(params=types.CallToolRequestParams(name="ate_kb.ask", arguments={"question": "test"}))
        result = await call_tool_handler(req)

        handler.handle_ask.assert_awaited_once_with({"question": "test"})
        assert len(result.root.content) == 1

    @pytest.mark.asyncio
    async def test_call_tool_related(self, app):
        mcp_app, _pipeline, handler = app
        from mcp import types

        handler.handle_related = AsyncMock(return_value=AsyncMock(model_dump_json=lambda indent: '{"chunk_id": "c1"}'))

        call_tool_handler = mcp_app._server.request_handlers[types.CallToolRequest]
        req = types.CallToolRequest(params=types.CallToolRequestParams(name="ate_kb.related", arguments={"chunk_id": "c1"}))
        result = await call_tool_handler(req)

        handler.handle_related.assert_awaited_once_with({"chunk_id": "c1"})
        assert len(result.root.content) == 1

    @pytest.mark.asyncio
    async def test_call_tool_get_document(self, app):
        mcp_app, _pipeline, handler = app
        from mcp import types

        handler.handle_get_document = AsyncMock(return_value=AsyncMock(model_dump_json=lambda indent: '{"source_md": "doc.md"}'))

        call_tool_handler = mcp_app._server.request_handlers[types.CallToolRequest]
        req = types.CallToolRequest(params=types.CallToolRequestParams(name="ate_kb.get_document", arguments={"source_md": "doc.md"}))
        result = await call_tool_handler(req)

        handler.handle_get_document.assert_awaited_once_with({"source_md": "doc.md"})
        assert len(result.root.content) == 1

    @pytest.mark.asyncio
    async def test_call_tool_status(self, app):
        mcp_app, _pipeline, handler = app
        from mcp import types

        handler.handle_status = AsyncMock(return_value=AsyncMock(model_dump_json=lambda indent: '{"status": "ok"}'))

        call_tool_handler = mcp_app._server.request_handlers[types.CallToolRequest]
        req = types.CallToolRequest(params=types.CallToolRequestParams(name="ate_kb.status", arguments={}))
        result = await call_tool_handler(req)

        handler.handle_status.assert_awaited_once_with({})
        assert len(result.root.content) == 1

    @pytest.mark.asyncio
    async def test_call_tool_unknown_tool(self, app):
        mcp_app, _pipeline, handler = app
        from mcp import types

        call_tool_handler = mcp_app._server.request_handlers[types.CallToolRequest]
        req = types.CallToolRequest(params=types.CallToolRequestParams(name="ate_kb.unknown", arguments={}))
        result = await call_tool_handler(req)

        content = result.root.content[0].text
        assert "Unknown tool" in content
        handler.handle_search.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_call_tool_exception_handling(self, app):
        mcp_app, _pipeline, handler = app
        from mcp import types

        handler.handle_search = AsyncMock(side_effect=RuntimeError("boom"))

        call_tool_handler = mcp_app._server.request_handlers[types.CallToolRequest]
        req = types.CallToolRequest(params=types.CallToolRequestParams(name="ate_kb.search", arguments={"query": "test"}))
        result = await call_tool_handler(req)

        content = result.root.content[0].text
        assert "Tool execution failed" in content
        assert "boom" in content


class TestRunMcpServer:
    @pytest.mark.asyncio
    async def test_run_mcp_server_starts_transport(self, mock_config):
        with patch("ate_rag_kb.mcp.server.McpServerApp") as mock_app_cls:
            mock_app = AsyncMock()
            mock_app_cls.return_value = mock_app

            await run_mcp_server(mock_config)

            mock_app_cls.assert_called_once_with(mock_config)
            mock_app.run.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_run_mcp_server_import_error(self, mock_config):
        with (
            patch("ate_rag_kb.mcp.server.McpServerApp", side_effect=ImportError("no mcp")),
            pytest.raises(ImportError, match="no mcp"),
        ):
            await run_mcp_server(mock_config)
