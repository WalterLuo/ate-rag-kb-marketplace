"""Unit tests for MCP tool handlers."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from ate_rag_kb.chunking.models import Chunk, ChunkType
from ate_rag_kb.domain.scopes import (
    ADVANTEST_V93000_SMT7,
    ADVANTEST_V93000_SMT8,
    TERADYNE_J750_IGXL,
)
from ate_rag_kb.ingestion.symbol_catalog import SymbolCatalog
from ate_rag_kb.mcp.tools import McpToolHandler
from ate_rag_kb.retrieval.coordinator import RetrievalCoordinator
from ate_rag_kb.retrieval.document_graph_expander import DocumentGraphExpander
from ate_rag_kb.retrieval.pipeline import RetrievalPipeline, ScopedPipelineResult
from ate_rag_kb.retrieval.planner import RetrievalPlanner
from ate_rag_kb.retrieval.routing import ScopeRouter
from ate_rag_kb.utils.config import Config


class TestMcpToolHandler:
    @pytest.fixture
    def handler(self) -> McpToolHandler:
        pipeline = AsyncMock()
        pipeline.config = Config({"documents": {"igxl": {"enabled": True}}})
        pipeline._last_retrieval_stats = {}
        return McpToolHandler(pipeline)

    def _make_handler(self) -> McpToolHandler:
        pipeline = AsyncMock()
        pipeline.config = Config({"documents": {"igxl": {"enabled": True}}})
        pipeline._last_retrieval_stats = {}
        return McpToolHandler(pipeline)

    def _make_coordinated_handler(
        self,
        *,
        include_smt8: bool = False,
    ) -> tuple[McpToolHandler, MagicMock]:
        pipeline = MagicMock()
        pipeline.config = Config({})
        enabled_scopes = [TERADYNE_J750_IGXL, ADVANTEST_V93000_SMT7]
        if include_smt8:
            enabled_scopes.append(ADVANTEST_V93000_SMT8)

        async def retrieve_scope(**kwargs):
            scope = kwargs["scope"]
            chunk = self._make_chunk(
                chunk_id=scope.key.replace("/", "-"),
                source_md=f"{scope.platform}/{scope.software}/doc.md",
                doc_title=f"{scope.platform} {scope.software}",
                section_title="Scoped Section",
                platform=scope.platform,
            )
            chunk.vendor = scope.vendor
            chunk.platform = scope.platform
            chunk.software = scope.software
            chunk.software_release = scope.software_release
            return ScopedPipelineResult(
                chunks=[(chunk, 0.9)],
                processing={
                    "coverage_topics": [f"{scope.key} topic"],
                    "cross_scope_dropped_chunk_count": 0,
                },
            )

        pipeline.retrieve_scope = AsyncMock(side_effect=retrieve_scope)
        pipeline.search_scope = AsyncMock(side_effect=retrieve_scope)
        router = ScopeRouter(tuple(enabled_scopes), SymbolCatalog.empty())
        coordinator = RetrievalCoordinator(router, RetrievalPlanner(Config({})), pipeline)
        return McpToolHandler(pipeline, coordinator=coordinator), pipeline

    def _make_chunk(
        self,
        chunk_id: str = "c1",
        content: str = "test content",
        score: float = 0.9,
        source_md: str = "doc.md",
        doc_title: str = "Doc Title",
        section_title: str = "Section",
        platform: str = "TDC",
        start_line: int = 10,
        end_line: int = 20,
    ) -> Chunk:
        return Chunk(
            id=chunk_id,
            content=content,
            chunk_type=ChunkType.PARAGRAPH,
            source_md=source_md,
            doc_title=doc_title,
            section_title=section_title,
            platform=platform,
            start_line=start_line,
            end_line=end_line,
            score=score,
        )

    @pytest.mark.asyncio
    async def test_handle_search(self, handler: McpToolHandler) -> None:
        chunk = self._make_chunk()
        handler.pipeline.search_enriched = AsyncMock(return_value=[(chunk, 0.9)])

        result = await handler.handle_search({"query": "test"})

        assert result.query == "test"
        assert result.total == 1
        assert result.chunks[0].id == "c1"
        assert result.chunks[0].source_md == "doc.md"
        assert result.chunks[0].doc_title == "Doc Title"
        assert result.chunks[0].section_title == "Section"
        assert result.chunks[0].start_line == 10
        assert result.chunks[0].end_line == 20
        assert len(result.sources) == 1
        assert result.sources[0]["source_md"] == "doc.md"

    @pytest.mark.asyncio
    async def test_handle_retrieve(self, handler: McpToolHandler) -> None:
        chunk = self._make_chunk()
        handler.pipeline.retrieve_enriched = AsyncMock(return_value=[(chunk, 0.85)])

        result = await handler.handle_retrieve({"query": "test"})

        assert result.query == "test"
        assert result.total == 1
        assert result.processing["reranked"] is True
        assert result.processing["expanded"] is True
        assert result.processing["compressed"] is True
        assert result.context_package is not None
        assert len(result.context_package.citation_map) == 1
        assert result.context_package.citation_map[0]["source_md"] == "doc.md"
        assert result.answer_contract.answer_mode == "direct"
        assert result.answer_contract.completeness_required is False

    @pytest.mark.asyncio
    async def test_handle_retrieve_reports_reranker_fallback(
        self, handler: McpToolHandler
    ) -> None:
        chunk = self._make_chunk()
        handler.pipeline.retrieve_enriched = AsyncMock(return_value=[(chunk, 0.85)])
        handler.pipeline._last_retrieval_stats = {
            "reranker_fallback_used": True,
            "reranker_error_type": "RuntimeError",
            "reranker_error": "rate limited",
        }

        result = await handler.handle_retrieve({"query": "test"})

        assert result.processing["reranker_fallback_used"] is True
        assert result.processing["reranker_error_type"] == "RuntimeError"
        assert result.processing["reranker_error"] == "rate limited"
        assert result.processing["reranked"] is False

    @pytest.mark.asyncio
    async def test_handle_retrieve_returns_broad_answer_contract(
        self, handler: McpToolHandler
    ) -> None:
        chunk = self._make_chunk()
        handler.pipeline.retrieve_enriched = AsyncMock(return_value=[(chunk, 0.85)])
        handler.pipeline._last_retrieval_stats = {
            "broad_context_assembled": True,
            "coverage_topics": ["The states of the sites", "Allow parallel flag"],
            "final_context_source_count": 4,
            "final_context_token_estimate": 3200,
        }

        result = await handler.handle_retrieve(
            {"query": "SMT7中site control的作用是什么"}
        )

        assert result.answer_contract.answer_mode == "broad_concept"
        assert result.answer_contract.completeness_required is True
        assert result.answer_contract.coverage_topics == [
            "The states of the sites",
            "Allow parallel flag",
        ]
        assert result.answer_contract.diagnostics["coverage_topic_count"] == 2
        assert result.answer_contract.diagnostics["final_context_source_count"] == 4

    @pytest.mark.asyncio
    async def test_handle_retrieve_job_list_enriched(self) -> None:
        handler = self._make_handler()
        job_list_127 = self._make_chunk(
            chunk_id="jl127",
            source_md="igxl/datatool/DTSheets.11.127.md",
            doc_title="Job List Sheet",
            section_title="Job List Sheet Overview",
            platform="J750",
        )
        job_list_128 = self._make_chunk(
            chunk_id="jl128",
            source_md="igxl/datatool/DTSheets.11.128.md",
            doc_title="Job List Sheet",
            section_title="Job List Sheet Details",
            platform="J750",
        )
        handler.pipeline.retrieve_enriched = AsyncMock(
            return_value=[(job_list_127, 0.95), (job_list_128, 0.9)]
        )

        result = await handler.handle_retrieve(
            {"query": "在 ig-xl 中 job list 有什么用"}
        )

        source_mds = [chunk.source_md for chunk in result.chunks]
        assert "igxl/datatool/DTSheets.11.127.md" in source_mds
        assert "igxl/datatool/DTSheets.11.128.md" in source_mds

    @pytest.mark.asyncio
    async def test_handle_ask(self, handler: McpToolHandler) -> None:
        c1 = self._make_chunk(chunk_id="c1", score=0.95)
        c2 = self._make_chunk(chunk_id="c2", score=0.7)
        c3 = self._make_chunk(chunk_id="c3", score=0.6)
        handler.pipeline.retrieve_enriched = AsyncMock(
            return_value=[(c1, 0.95), (c2, 0.7), (c3, 0.6)]
        )

        result = await handler.handle_ask({"question": "how to test?"})

        assert result.question == "how to test?"
        assert result.confidence == "high"
        assert len(result.citations) == 3
        assert result.citations[0].chunk_id == "c1"
        assert result.citations[0].source_md == "doc.md"
        assert result.source_files == ["doc.md"]
        assert result.context_package is not None

    @pytest.mark.asyncio
    async def test_ask_returns_isolated_context_sections(self) -> None:
        handler, pipeline = self._make_coordinated_handler()

        result = await handler.handle_ask({"question": "多 site 串行处理怎么实现？"})

        assert result.answer_contract.answer_mode == "platform_comparison"
        assert [
            scope.model_dump(exclude_defaults=True)
            for scope in result.answer_contract.resolved_scopes
        ] == [
            {"vendor": "teradyne", "platform": "j750", "software": "igxl"},
            {"vendor": "advantest", "platform": "v93000", "software": "smt7"},
        ]
        assert set(result.answer_contract.coverage_topics_by_scope) == {
            "j750/igxl",
            "v93000/smt7",
        }
        assert result.context_package is not None
        assert "## J750 / IGXL" in result.context_package.text
        assert "## V93000 / SMT7" in result.context_package.text
        assert pipeline.retrieve_scope.call_count == 2

    @pytest.mark.asyncio
    async def test_ask_returns_clarification_without_flat_context(self) -> None:
        handler, pipeline = self._make_coordinated_handler(include_smt8=True)

        result = await handler.handle_ask({"question": "V93000 site control 怎么用？"})

        assert result.answer_contract.answer_mode == "clarification"
        assert "SMT7" in result.answer_contract.clarification_prompt
        assert "SMT8" in result.answer_contract.clarification_prompt
        assert result.context_package is None
        pipeline.retrieve_scope.assert_not_called()

    @pytest.mark.asyncio
    async def test_handle_ask_low_confidence(self, handler: McpToolHandler) -> None:
        chunk = self._make_chunk(score=0.3)
        handler.pipeline.retrieve_enriched = AsyncMock(return_value=[(chunk, 0.3)])

        result = await handler.handle_ask({"question": "vague?"})

        assert result.confidence == "low"

    @pytest.mark.asyncio
    async def test_handle_ask_returns_site_control_graph_sources_without_hints(
        self, tmp_path: Path
    ) -> None:
        graph = {
            "100118.md": {
                "linked_source_mds": [],
                "referenced_by_source_mds": ["100324.md"],
                "canonical_source_md": "100118.md",
                "content_hash": "100118",
            },
            "100324.md": {
                "linked_source_mds": ["21615.md", "20264.md"],
                "referenced_by_source_mds": [],
                "canonical_source_md": "100324.md",
                "content_hash": "100324",
            },
            "21615.md": {
                "linked_source_mds": [],
                "referenced_by_source_mds": [],
                "canonical_source_md": "21615.md",
                "content_hash": "21615",
            },
            "20264.md": {
                "linked_source_mds": [],
                "referenced_by_source_mds": [],
                "canonical_source_md": "20264.md",
                "content_hash": "20264",
            },
        }
        graph_path = tmp_path / "document_graph.json"
        graph_path.write_text(json.dumps(graph), encoding="utf-8")
        chunks_by_source = {
            "100324.md": [self._make_chunk("100324", source_md="100324.md")],
            "21615.md": [self._make_chunk("21615", source_md="21615.md")],
            "20264.md": [self._make_chunk("20264", source_md="20264.md")],
        }
        store = MagicMock()

        def scroll(*, filters, limit):
            chunks = chunks_by_source.get(filters["source_md"], [])
            return chunks[:limit], None

        store.scroll = scroll
        pipeline = RetrievalPipeline.__new__(RetrievalPipeline)
        pipeline.config = Config(
            {"retrieval": {"planner": {"context_enrichment_enabled": False}}}
        )
        pipeline.vector_store = store
        pipeline.hybrid = MagicMock()
        pipeline.hybrid.retrieve.return_value = [
            self._make_chunk("100118", source_md="100118.md")
        ]
        pipeline.hybrid._last_retrieval_stats = {
            "dense_candidate_count": 1,
            "sparse_candidate_count": 0,
            "fused_candidate_count": 1,
            "sparse_search_used": False,
            "legacy_bm25_fallback_used": False,
        }
        pipeline.graph_expander = DocumentGraphExpander(graph_path=graph_path)
        pipeline.reranker = MagicMock()
        pipeline.reranker.top_k = 5
        pipeline.reranker.broad_candidate_top_k = 16
        pipeline.reranker.broad_final_top_k = 10
        pipeline.reranker.broad_max_sources = 8
        pipeline.reranker.rerank.side_effect = lambda _query, chunks, **kwargs: chunks
        pipeline.expander = MagicMock()
        pipeline.expander.expand.side_effect = lambda chunks, *_args, **_kwargs: chunks
        pipeline.compressor = MagicMock()
        pipeline.compressor.compress.side_effect = lambda chunks: chunks
        pipeline._last_retrieval_stats = {}
        handler = McpToolHandler(pipeline)

        result = await handler.handle_ask({"question": "Site Control 有什么用？"})

        assert {"100118.md", "100324.md", "21615.md", "20264.md"} <= set(
            result.source_files
        )
        assert result.processing["graph_expanded_source_count"] == 3
        assert result.answer_contract.answer_mode == "broad_concept"
        assert result.answer_contract.completeness_required is True
        assert "A short overview alone is insufficient." in result.answer
        assert any(
            "Do not return only a short overview" in rule
            for rule in result.answer_contract.synthesis_rules
        )

    @pytest.mark.asyncio
    async def test_handle_get_document(self, handler: McpToolHandler) -> None:
        chunk = self._make_chunk()
        handler.pipeline.get_document_page = AsyncMock(
            return_value={
                "chunks": [chunk],
                "total": 1,
                "returned": 1,
                "has_more": False,
                "next_offset": None,
            }
        )

        result = await handler.handle_get_document({"source_md": "doc.md"})

        assert result.source_md == "doc.md"
        assert result.total == 1
        assert result.returned == 1
        assert result.offset == 0
        assert result.limit == 20
        assert result.has_more is False
        assert result.next_offset is None
        assert result.chunks[0].id == "c1"
        assert result.context_package is not None
        handler.pipeline.get_document_page.assert_awaited_once_with("doc.md", limit=20, offset=0)

    @pytest.mark.asyncio
    async def test_handle_get_document_pagination_limit(self, handler: McpToolHandler) -> None:
        chunks = [self._make_chunk(chunk_id=f"c{i}") for i in range(5)]
        handler.pipeline.get_document_page = AsyncMock(
            return_value={
                "chunks": chunks[:2],
                "total": 5,
                "returned": 2,
                "has_more": True,
                "next_offset": 2,
            }
        )

        result = await handler.handle_get_document({"source_md": "doc.md", "limit": 2})

        assert result.total == 5
        assert result.returned == 2
        assert result.limit == 2
        assert result.has_more is True
        assert result.next_offset == 2
        assert [c.id for c in result.chunks] == ["c0", "c1"]

    @pytest.mark.asyncio
    async def test_handle_get_document_pagination_offset(self, handler: McpToolHandler) -> None:
        chunks = [self._make_chunk(chunk_id=f"c{i}") for i in range(5)]
        handler.pipeline.get_document_page = AsyncMock(
            return_value={
                "chunks": chunks[2:4],
                "total": 5,
                "returned": 2,
                "has_more": True,
                "next_offset": 4,
            }
        )

        result = await handler.handle_get_document({"source_md": "doc.md", "limit": 2, "offset": 2})

        assert result.total == 5
        assert result.returned == 2
        assert result.offset == 2
        assert result.has_more is True
        assert result.next_offset == 4
        assert [c.id for c in result.chunks] == ["c2", "c3"]

    @pytest.mark.asyncio
    async def test_handle_get_document_pagination_last_page(self, handler: McpToolHandler) -> None:
        chunks = [self._make_chunk(chunk_id=f"c{i}") for i in range(3)]
        handler.pipeline.get_document_page = AsyncMock(
            return_value={
                "chunks": chunks[2:],
                "total": 3,
                "returned": 1,
                "has_more": False,
                "next_offset": None,
            }
        )

        result = await handler.handle_get_document({"source_md": "doc.md", "limit": 2, "offset": 2})

        assert result.total == 3
        assert result.returned == 1
        assert result.offset == 2
        assert result.has_more is False
        assert result.next_offset is None
        assert [c.id for c in result.chunks] == ["c2"]

    @pytest.mark.asyncio
    async def test_handle_get_document_max_tokens(self, handler: McpToolHandler) -> None:
        chunks = [self._make_chunk(chunk_id=f"c{i}", content="x" * 400) for i in range(10)]
        handler.pipeline.get_document_page = AsyncMock(
            return_value={
                "chunks": chunks,
                "total": 10,
                "returned": 10,
                "has_more": False,
                "next_offset": None,
            }
        )

        result = await handler.handle_get_document({"source_md": "doc.md", "max_tokens": 500})

        assert result.total == 10
        assert result.context_package is not None
        # build_context_package stops after exceeding max_tokens, so the estimate
        # may slightly overshoot one chunk; verify not all 10 chunks were included.
        assert result.context_package.token_estimate < 1200
        assert len(result.context_package.citation_map) < 10

    @pytest.mark.asyncio
    async def test_handle_related(self, handler: McpToolHandler) -> None:
        parent = self._make_chunk(chunk_id="p1", content="parent")
        sibling1 = self._make_chunk(chunk_id="s1", content="sibling1")
        sibling2 = self._make_chunk(chunk_id="s2", content="sibling2")
        sibling3 = self._make_chunk(chunk_id="s3", content="sibling3")
        handler.pipeline.get_related = AsyncMock(
            return_value={"parent": parent, "siblings": [sibling1, sibling2, sibling3], "children": []}
        )

        result = await handler.handle_related({"chunk_id": "c1"})

        assert result.chunk_id == "c1"
        assert result.parent is not None
        assert result.parent.id == "p1"
        assert len(result.siblings) == 2
        assert result.siblings[0].id == "s1"
        assert result.siblings[1].id == "s2"
        assert len(result.children) == 0

    @pytest.mark.asyncio
    async def test_handle_related_max_siblings_1(self, handler: McpToolHandler) -> None:
        s1 = self._make_chunk(chunk_id="s1")
        s2 = self._make_chunk(chunk_id="s2")
        s3 = self._make_chunk(chunk_id="s3")
        handler.pipeline.get_related = AsyncMock(
            return_value={"parent": None, "siblings": [s1, s2, s3], "children": []}
        )

        result = await handler.handle_related({"chunk_id": "c1", "max_siblings": 1})

        assert len(result.siblings) == 1
        assert result.siblings[0].id == "s1"

    @pytest.mark.asyncio
    async def test_handle_related_max_siblings_0(self, handler: McpToolHandler) -> None:
        s1 = self._make_chunk(chunk_id="s1")
        s2 = self._make_chunk(chunk_id="s2")
        handler.pipeline.get_related = AsyncMock(
            return_value={"parent": None, "siblings": [s1, s2], "children": []}
        )

        result = await handler.handle_related({"chunk_id": "c1", "max_siblings": 0})

        assert len(result.siblings) == 0

    @pytest.mark.asyncio
    async def test_handle_related_no_siblings(self, handler: McpToolHandler) -> None:
        s1 = self._make_chunk(chunk_id="s1")
        s2 = self._make_chunk(chunk_id="s2")
        handler.pipeline.get_related = AsyncMock(
            return_value={"parent": None, "siblings": [s1, s2], "children": []}
        )

        result = await handler.handle_related({"chunk_id": "c1", "include_siblings": False})

        assert len(result.siblings) == 0

    @pytest.mark.asyncio
    async def test_handle_status(self, handler: McpToolHandler) -> None:
        handler.pipeline.collection_stats = AsyncMock(
            return_value={
                "collection_name": "ate_kb",
                "total_chunks": 100,
                "vector_size": 1024,
                "embedding_model": "bge-m3",
                "platforms": ["TDC"],
                "doc_types": ["reference"],
            }
        )

        result = await handler.handle_status({})

        assert result.status == "ok"
        assert result.collection_name == "ate_kb"
        assert result.total_chunks == 100
        assert result.vector_size == 1024
        assert result.platforms == ["TDC"]

    @pytest.mark.asyncio
    async def test_handle_status_degraded(self, handler: McpToolHandler) -> None:
        handler.pipeline.collection_stats = AsyncMock(side_effect=RuntimeError("fail"))

        result = await handler.handle_status({})

        assert result.status == "degraded"

    # -----------------------------------------------------------------------
    # Ecosystem filtering
    # -----------------------------------------------------------------------

    def test_is_smt7_or_v93000_chunk_detects_numeric_and_prefix_docs(self) -> None:
        smt7_prefixed = self._make_chunk(source_md="smt7/pattern/119474.md")
        v93000_smt7_prefixed = self._make_chunk(source_md="v93000/smt7/119474.md")
        v93000_prefixed = self._make_chunk(source_md="v93000/timing/levels.md")
        numeric_only = self._make_chunk(source_md="119474.md")
        numeric_variant = self._make_chunk(source_md="119474_2.md")
        igxl_doc = self._make_chunk(source_md="igxl/patterntool/PTVectorsEditing.4.21.md")

        assert McpToolHandler._is_smt7_or_v93000_chunk(smt7_prefixed) is True
        assert McpToolHandler._is_smt7_or_v93000_chunk(v93000_smt7_prefixed) is True
        assert McpToolHandler._is_smt7_or_v93000_chunk(v93000_prefixed) is True
        assert McpToolHandler._is_smt7_or_v93000_chunk(numeric_only) is True
        assert McpToolHandler._is_smt7_or_v93000_chunk(numeric_variant) is True
        assert McpToolHandler._is_smt7_or_v93000_chunk(igxl_doc) is False

    # -----------------------------------------------------------------------
    # Planner-driven retrieval & bidirectional ecosystem filtering
    # -----------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_handle_ask_job_list_chinese(self) -> None:
        handler = self._make_handler()
        job_list_127 = self._make_chunk(
            chunk_id="jl127",
            source_md="igxl/datatool/DTSheets.11.127.md",
            doc_title="Job List Sheet",
            section_title="Job List Sheet Overview",
            platform="J750",
        )
        job_list_128 = self._make_chunk(
            chunk_id="jl128",
            source_md="igxl/datatool/DTSheets.11.128.md",
            doc_title="Job List Sheet",
            section_title="Job List Sheet Details",
            platform="J750",
        )
        numeric_contam = self._make_chunk(
            chunk_id="smt7",
            source_md="v93000/smt7/119474.md",
            doc_title="SMT7 Pattern",
            platform="SMT7",
        )
        handler.pipeline.retrieve_enriched = AsyncMock(
            return_value=[
                (job_list_127, 0.95),
                (job_list_128, 0.9),
                (numeric_contam, 0.85),
            ]
        )

        result = await handler.handle_ask(
            {"question": "在 ig-xl 中 job list 有什么用"}
        )

        source_mds = result.source_files
        assert "igxl/datatool/DTSheets.11.127.md" in source_mds
        assert "igxl/datatool/DTSheets.11.128.md" in source_mds
        assert "v93000/smt7/119474.md" not in source_mds

    @pytest.mark.asyncio
    async def test_handle_ask_job_list_glossary(self) -> None:
        handler = self._make_handler()
        job_list = self._make_chunk(
            chunk_id="jl",
            source_md="igxl/datatool/DTSheets.11.127.md",
            doc_title="Job List Sheet",
            platform="J750",
        )
        handler.pipeline.retrieve_enriched = AsyncMock(
            return_value=[(job_list, 0.95)]
        )

        result = await handler.handle_ask({"question": "作业列表有什么用"})

        assert "igxl/datatool/DTSheets.11.127.md" in result.source_files

    @pytest.mark.asyncio
    async def test_handle_ask_preserves_enrichment_beyond_top_k(self) -> None:
        handler = self._make_handler()
        primary = [
            self._make_chunk(chunk_id=f"p{i}", source_md=f"igxl/doc{i}.md", platform="J750")
            for i in range(3)
        ]
        doc_context = self._make_chunk(
            chunk_id="doc",
            source_md="igxl/datatool/DTSheets.11.127.md",
            doc_title="Job List Sheet",
            platform="J750",
        )
        handler.pipeline.retrieve_enriched = AsyncMock(
            return_value=[(chunk, 0.9 - i * 0.1) for i, chunk in enumerate(primary)]
            + [(doc_context, 0.5)]
        )

        result = await handler.handle_ask(
            {"question": "在 ig-xl 中 job list 有什么用", "top_k": 3}
        )

        assert len(result.citations) == 4
        assert "igxl/datatool/DTSheets.11.127.md" in result.source_files

    @pytest.mark.asyncio
    async def test_handle_ask_smt7_array_not_contaminated(self) -> None:
        handler = self._make_handler()
        smt7_array = self._make_chunk(
            chunk_id="smt7_array",
            source_md="smt7/programming/arrays.md",
            doc_title="SMT7 Arrays",
            platform="SMT7",
        )
        igxl_array = self._make_chunk(
            chunk_id="igxl_array",
            source_md="igxl/patternlanguage/plarrays.1.01.md",
            doc_title="IG-XL Arrays",
            platform="J750",
        )
        handler.pipeline.retrieve_enriched = AsyncMock(
            return_value=[(smt7_array, 0.9), (igxl_array, 0.85)]
        )

        result = await handler.handle_ask({"question": "SMT7 ARRAY"})

        source_mds = result.source_files
        assert "smt7/programming/arrays.md" in source_mds
        assert "igxl/patternlanguage/plarrays.1.01.md" not in source_mds

    @pytest.mark.asyncio
    async def test_handle_ask_tdc_recognized_as_v93000(self) -> None:
        handler = self._make_handler()
        tdc_doc = self._make_chunk(
            chunk_id="tdc",
            source_md="v93000/smt7/119474.md",
            doc_title="TDC Flow Creator",
            platform="TDC",
        )
        igxl_doc = self._make_chunk(
            chunk_id="igxl",
            source_md="igxl/datatool/dtribbon.03.10.md",
            doc_title="DataTool Ribbon",
            platform="J750",
        )
        handler.pipeline.retrieve_enriched = AsyncMock(
            return_value=[(tdc_doc, 0.9), (igxl_doc, 0.85)]
        )

        result = await handler.handle_ask({"question": "TDC 中如何查看文档"})

        source_mds = result.source_files
        assert "v93000/smt7/119474.md" in source_mds
        assert "igxl/datatool/dtribbon.03.10.md" not in source_mds

    @pytest.mark.asyncio
    async def test_bidirectional_filter_v93000_excludes_igxl(self) -> None:
        handler = self._make_handler()
        v93000_doc = self._make_chunk(
            chunk_id="v93000",
            source_md="v93000/timing/levels.md",
            doc_title="V93000 Levels",
            platform="V93000",
        )
        igxl_doc = self._make_chunk(
            chunk_id="igxl",
            source_md="igxl/patterntool/PTVectorsEditing.4.21.md",
            doc_title="Pattern Tool",
            platform="J750",
        )
        handler.pipeline.retrieve_enriched = AsyncMock(
            return_value=[(v93000_doc, 0.9), (igxl_doc, 0.85)]
        )

        result = await handler.handle_ask({"question": "v93000 levels"})

        source_mds = result.source_files
        assert "v93000/timing/levels.md" in source_mds
        assert "igxl/patterntool/PTVectorsEditing.4.21.md" not in source_mds

    @pytest.mark.asyncio
    async def test_handle_ask_processing_shows_diversity_stages(self) -> None:
        """MCP processing should distinguish graph, rerank, diversity, and final counts."""
        handler = self._make_handler()
        c1 = self._make_chunk(chunk_id="c1", source_md="a.md", score=0.95)
        c2 = self._make_chunk(chunk_id="c2", source_md="b.md", score=0.85)
        handler.pipeline.retrieve_enriched = AsyncMock(
            return_value=[(c1, 0.95), (c2, 0.85)]
        )
        handler.pipeline._last_retrieval_stats = {
            "dense_candidate_count": 10,
            "sparse_candidate_count": 10,
            "fused_candidate_count": 20,
            "graph_expanded_source_count": 5,
            "graph_expanded_chunk_count": 15,
            "post_rerank_candidate_count": 16,
            "post_rerank_source_count": 8,
            "post_diversity_candidate_count": 10,
            "post_diversity_source_count": 8,
            "final_context_source_count": 7,
            "final_context_token_estimate": 3200,
            "reranked_candidate_count": 16,
        }

        result = await handler.handle_ask({"question": "test?"})

        proc = result.processing
        assert proc["graph_expanded_source_count"] == 5
        assert proc["graph_expanded_chunk_count"] == 15
        assert proc["post_rerank_candidate_count"] == 16
        assert proc["post_rerank_source_count"] == 8
        assert proc["post_diversity_candidate_count"] == 10
        assert proc["post_diversity_source_count"] == 8
        assert proc["final_context_source_count"] == 7
        assert proc["final_context_token_estimate"] == 3200
        # reranked_candidate_count should reflect rerank stage, not final count
        assert proc["reranked_candidate_count"] == 16
