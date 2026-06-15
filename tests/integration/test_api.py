"""Integration tests for FastAPI endpoints."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from ate_rag_kb.api.server import create_app
from ate_rag_kb.chunking.models import Chunk, ChunkType
from ate_rag_kb.domain.scopes import (
    ADVANTEST_V93000_SMT7,
    ADVANTEST_V93000_SMT8,
    TERADYNE_J750_IGXL,
)
from ate_rag_kb.ingestion.symbol_catalog import SymbolCatalog
from ate_rag_kb.retrieval.coordinator import RetrievalCoordinator
from ate_rag_kb.retrieval.pipeline import ScopedPipelineResult
from ate_rag_kb.retrieval.planner import RetrievalPlanner
from ate_rag_kb.retrieval.routing import ScopeRouter
from ate_rag_kb.utils.config import Config


@pytest.fixture
def mock_retriever() -> AsyncMock:
    retriever = AsyncMock()
    retriever.search.return_value = [
        (
            Chunk(
                id="c1",
                content="Test content",
                chunk_type=ChunkType.PARAGRAPH,
                doc_title="Doc",
                source_md="doc.md",
                score=0.95,
            ),
            0.95,
        )
    ]
    retriever.retrieve.return_value = [
        (
            Chunk(
                id="c1",
                content="Test content",
                chunk_type=ChunkType.PARAGRAPH,
                doc_title="Doc",
                source_md="doc.md",
                score=0.95,
            ),
            0.95,
        )
    ]
    retriever.get_related.return_value = {
        "parent": Chunk(id="p1", content="Parent", chunk_type=ChunkType.SECTION),
        "siblings": [],
        "children": [],
    }
    retriever.get_document.return_value = [
        Chunk(id="c1", content="Test", chunk_type=ChunkType.PARAGRAPH, source_md="doc.md"),
    ]
    retriever.get_document_page.return_value = {
        "chunks": [
            Chunk(id="c1", content="Test", chunk_type=ChunkType.PARAGRAPH, source_md="doc.md"),
        ],
        "total": 1,
        "returned": 1,
        "has_more": False,
        "next_offset": None,
    }
    return retriever


@pytest.fixture
def client(mock_retriever: AsyncMock) -> TestClient:
    config = Config({"logging": {"level": "INFO", "format": "json"}})
    app = create_app(config)

    from ate_rag_kb.api.routes import set_coordinator, set_planner, set_retriever
    from ate_rag_kb.retrieval.planner import RetrievalPlanner

    set_coordinator(None)
    set_retriever(mock_retriever)
    set_planner(RetrievalPlanner(config))
    return TestClient(app)


def _coordinated_client(include_smt8: bool = False) -> tuple[TestClient, AsyncMock]:
    config = Config({"logging": {"level": "INFO", "format": "json"}})
    app = create_app(config)
    pipeline = AsyncMock()
    scopes = [TERADYNE_J750_IGXL, ADVANTEST_V93000_SMT7]
    if include_smt8:
        scopes.append(ADVANTEST_V93000_SMT8)

    async def retrieve_scope(**kwargs):
        scope = kwargs["scope"]
        chunk = Chunk(
            id=scope.key.replace("/", "-"),
            content=f"{scope.key} content",
            chunk_type=ChunkType.PARAGRAPH,
            source_md=f"{scope.platform}/{scope.software}/doc.md",
            doc_title=f"{scope.platform} {scope.software}",
            vendor=scope.vendor,
            platform=scope.platform,
            software=scope.software,
        )
        return ScopedPipelineResult(chunks=[(chunk, 0.9)], processing={})

    pipeline.retrieve_scope = AsyncMock(side_effect=retrieve_scope)
    pipeline.search_scope = AsyncMock(side_effect=retrieve_scope)
    coordinator = RetrievalCoordinator(
        ScopeRouter(tuple(scopes), SymbolCatalog.empty()),
        RetrievalPlanner(Config({})),
        pipeline,
    )
    from ate_rag_kb.api.routes import set_coordinator, set_planner, set_retriever

    set_retriever(pipeline)
    set_planner(RetrievalPlanner(config))
    set_coordinator(coordinator)
    return TestClient(app), pipeline


class TestHealth:
    def test_health_endpoint(self, client: TestClient) -> None:
        response = client.get("/health")

        assert response.status_code == 200
        assert response.json() == {"status": "ok"}

    def test_ready_endpoint_when_retriever_configured(self, client: TestClient) -> None:
        response = client.get("/ready")

        assert response.status_code == 200
        assert response.json() == {"status": "ok"}

    def test_ready_endpoint_returns_503_without_retriever(self) -> None:
        config = Config({"logging": {"level": "INFO", "format": "json"}})
        with patch("ate_rag_kb.api.server._build_retriever", return_value=None):
            app = create_app(config)
            from ate_rag_kb.api.routes import set_coordinator, set_planner, set_retriever

            set_coordinator(None)
            set_planner(None)
            set_retriever(None)

            client = TestClient(app)
            response = client.get("/ready")

        assert response.status_code == 503
        assert response.json()["detail"] == "Retrieval backend not initialized"


class TestSearch:
    def test_search_returns_chunks(self, client: TestClient) -> None:
        response = client.post("/api/v1/search", json={"query": "test query"})

        assert response.status_code == 200
        data = response.json()
        assert data["query"] == "test query"
        assert len(data["chunks"]) == 1
        assert data["chunks"][0]["id"] == "c1"

    def test_search_with_filters(self, client: TestClient) -> None:
        response = client.post(
            "/api/v1/search",
            json={"query": "test", "filters": {"platform": "TDC"}},
        )

        assert response.status_code == 200

    def test_search_rejects_empty_query(self, client: TestClient) -> None:
        response = client.post("/api/v1/search", json={"query": ""})

        assert response.status_code == 422

    def test_search_returns_coordinated_scopes(self) -> None:
        client, pipeline = _coordinated_client()

        response = client.post("/api/v1/search", json={"query": "多 site 串行处理怎么实现？"})

        assert response.status_code == 200
        data = response.json()
        assert data["answer_mode"] == "platform_comparison"
        assert data["resolved_scopes"] == [
            {"vendor": "teradyne", "platform": "j750", "software": "igxl", "software_release": ""},
            {"vendor": "advantest", "platform": "v93000", "software": "smt7", "software_release": ""},
        ]
        assert pipeline.search_scope.call_count == 2


class TestRetrieve:
    def test_retrieve_with_expansion(self, client: TestClient) -> None:
        response = client.post(
            "/api/v1/retrieve",
            json={
                "query": "test",
                "expand_parents": True,
                "expand_siblings": True,
                "rerank": True,
                "compress": True,
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["reranked"] is True
        assert data["expanded"] is True
        assert data["compressed"] is True

    def test_retrieve_marks_not_reranked_when_fallback_used(
        self, client: TestClient, mock_retriever: AsyncMock
    ) -> None:
        mock_retriever._last_retrieval_stats = {"reranker_fallback_used": True}

        response = client.post(
            "/api/v1/retrieve",
            json={"query": "test", "rerank": True},
        )

        assert response.status_code == 200
        assert response.json()["reranked"] is False

    def test_coordinated_retrieve_marks_not_reranked_when_fallback_used(self) -> None:
        client, pipeline = _coordinated_client()

        async def retrieve_scope(**kwargs):
            scope = kwargs["scope"]
            chunk = Chunk(
                id=scope.key.replace("/", "-"),
                content=f"{scope.key} content",
                chunk_type=ChunkType.PARAGRAPH,
                source_md=f"{scope.platform}/{scope.software}/doc.md",
                doc_title=f"{scope.platform} {scope.software}",
                vendor=scope.vendor,
                platform=scope.platform,
                software=scope.software,
            )
            return ScopedPipelineResult(
                chunks=[(chunk, 0.9)],
                processing={"reranker_fallback_used": True},
            )

        pipeline.retrieve_scope.side_effect = retrieve_scope

        response = client.post(
            "/api/v1/retrieve",
            json={"query": "多 site 串行处理怎么实现？", "rerank": True},
        )

        assert response.status_code == 200
        assert response.json()["reranked"] is False

    def test_retrieve_rejects_empty_query(self, client: TestClient) -> None:
        response = client.post("/api/v1/retrieve", json={"query": ""})

        assert response.status_code == 422


class TestAsk:
    def test_ask_returns_citations(self, client: TestClient) -> None:
        response = client.post(
            "/api/v1/ask",
            json={"question": "What is TDC?"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["question"] == "What is TDC?"
        assert len(data["citations"]) == 1
        assert data["citations"][0]["chunk_id"] == "c1"

    def test_ask_rejects_empty_question(self, client: TestClient) -> None:
        response = client.post("/api/v1/ask", json={"question": ""})

        assert response.status_code == 422

    def test_ask_returns_clarification_without_chunks(self) -> None:
        client, pipeline = _coordinated_client(include_smt8=True)

        response = client.post("/api/v1/ask", json={"question": "V93000 site control 怎么用？"})

        assert response.status_code == 200
        data = response.json()
        assert data["answer_mode"] == "clarification"
        assert "SMT7" in data["clarification_prompt"]
        assert "SMT8" in data["clarification_prompt"]
        assert data["chunks"] == []
        pipeline.retrieve_scope.assert_not_called()


class TestRelated:
    def test_related_returns_parent(self, client: TestClient) -> None:
        response = client.post("/api/v1/related", json={"chunk_id": "c1"})

        assert response.status_code == 200
        data = response.json()
        assert data["chunk_id"] == "c1"
        assert data["parent"]["id"] == "p1"

    def test_related_rejects_empty_chunk_id(self, client: TestClient) -> None:
        response = client.post("/api/v1/related", json={"chunk_id": ""})

        assert response.status_code == 422


class TestDocument:
    def test_get_document_returns_chunks(self, client: TestClient) -> None:
        response = client.get("/api/v1/document/doc.md")

        assert response.status_code == 200
        data = response.json()
        assert data["source_md"] == "doc.md"
        assert len(data["chunks"]) == 1

    def test_get_document_accepts_source_paths_and_paginates(
        self, client: TestClient, mock_retriever: AsyncMock
    ) -> None:
        chunk = Chunk(
            id="c2",
            content="Paged",
            chunk_type=ChunkType.PARAGRAPH,
            source_md="v93000/smt7/100096.md",
        )
        mock_retriever.get_document_page.return_value = {
            "chunks": [chunk],
            "total": 12,
            "returned": 1,
            "has_more": True,
            "next_offset": 2,
        }

        response = client.get("/api/v1/document/v93000/smt7/100096.md?limit=1&offset=1")

        assert response.status_code == 200
        data = response.json()
        assert data["source_md"] == "v93000/smt7/100096.md"
        assert data["total"] == 12
        assert data["returned"] == 1
        assert data["offset"] == 1
        assert data["limit"] == 1
        assert data["has_more"] is True
        assert data["next_offset"] == 2
        assert data["chunks"][0]["id"] == "c2"
        mock_retriever.get_document_page.assert_awaited_with(
            "v93000/smt7/100096.md",
            limit=1,
            offset=1,
        )
