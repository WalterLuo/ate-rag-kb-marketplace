"""Unit tests for RetrievalPipeline search_enriched and retrieve_enriched."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ate_rag_kb.chunking.models import Chunk, ChunkType
from ate_rag_kb.domain.scopes import TERADYNE_J750_IGXL
from ate_rag_kb.retrieval.pipeline import RetrievalPipeline
from ate_rag_kb.retrieval.planner import RetrievalPlanner
from ate_rag_kb.utils.config import Config


class TestSearchEnriched:
    @pytest.fixture
    def pipeline(self) -> RetrievalPipeline:
        config = Config(
            {
                "retrieval": {
                    "planner": {
                        "title_boost_factor": 0.15,
                        "context_enrichment_enabled": True,
                        "enrichment_budget": 3,
                    },
                    "vector_search": {"top_k": 20},
                    "bm25_search": {"enabled": True, "top_k": 20},
                    "hybrid": {
                        "enabled": True,
                        "vector_weight": 0.7,
                        "bm25_weight": 0.3,
                        "final_top_k": 10,
                    },
                    "reranker": {"enabled": True, "top_k": 5},
                    "parent_child": {
                        "enabled": True,
                        "include_parent": True,
                        "include_siblings": True,
                    },
                    "compression": {"enabled": True, "max_tokens": 4000},
                },
                "embedding": {"model_name": "test"},
                "schema": {"vector_size": 1024},
            }
        )
        with patch("ate_rag_kb.retrieval.pipeline.QdrantVectorStore"):
            pipeline = RetrievalPipeline(config)
        pipeline.hybrid = MagicMock()  # type: ignore[misc]
        pipeline.vector_store = MagicMock()  # type: ignore[misc]
        pipeline.reranker = MagicMock()  # type: ignore[misc]
        pipeline.reranker.top_k = 5
        pipeline.reranker.broad_candidate_top_k = 16
        pipeline.reranker.broad_final_top_k = 10
        pipeline.reranker.broad_max_sources = 8
        pipeline.expander = MagicMock()  # type: ignore[misc]
        pipeline.compressor = MagicMock()  # type: ignore[misc]
        pipeline.graph_expander = MagicMock()  # type: ignore[misc]
        pipeline.graph_expander.expand = MagicMock(return_value=([], {}))
        return pipeline

    def _make_chunk(
        self,
        chunk_id: str = "c1",
        chunk_type: ChunkType = ChunkType.PARAGRAPH,
        content: str = "test",
        source_md: str = "doc.md",
        score: float = 0.9,
        parent_id: str | None = None,
    ) -> Chunk:
        return Chunk(
            id=chunk_id,
            content=content,
            chunk_type=chunk_type,
            source_md=source_md,
            score=score,
            parent_id=parent_id,
        )

    @pytest.mark.asyncio
    async def test_enrichment_not_truncated_by_top_k(
        self, pipeline: RetrievalPipeline
    ) -> None:
        """When top_k=3 and all 3 hits are edge chunks, document chunk should still appear."""
        hits = [
            self._make_chunk(
                "e1", ChunkType.PARAGRAPH, source_md="doc.md", score=0.9, parent_id="p1"
            ),
            self._make_chunk(
                "e2", ChunkType.PARAGRAPH, source_md="doc.md", score=0.85, parent_id="p1"
            ),
            self._make_chunk(
                "e3", ChunkType.PARAGRAPH, source_md="doc.md", score=0.8, parent_id="p1"
            ),
        ]
        parent = self._make_chunk("p1", ChunkType.SECTION, source_md="doc.md", score=0.5)
        doc_chunk = self._make_chunk("d1", ChunkType.DOCUMENT, source_md="doc.md", score=0.5)

        pipeline.hybrid.retrieve = MagicMock(return_value=hits)
        pipeline.vector_store.get_by_ids = MagicMock(return_value=[parent])
        pipeline.vector_store.scroll = MagicMock(return_value=([doc_chunk], None))

        planner = RetrievalPlanner(pipeline.config)
        plan = planner.plan("test query")

        results = await pipeline.search_enriched(query="test", plan=plan, top_k=3)

        ids = [c.id for c, _ in results]
        assert "e1" in ids
        assert "e2" in ids
        assert "e3" in ids
        # Enrichment chunks should be present (parent or document)
        assert "p1" in ids or "d1" in ids
        # Total should be at least top_k, but not unbounded
        assert len(results) <= 3 + 3  # top_k + enrichment_budget

    @pytest.mark.asyncio
    async def test_primary_hits_preserved_before_enrichment(
        self, pipeline: RetrievalPipeline
    ) -> None:
        """Primary hits should keep their relative ordering before enrichment chunks."""
        hits = [
            self._make_chunk("e1", ChunkType.PARAGRAPH, score=0.9, parent_id="p1"),
            self._make_chunk("e2", ChunkType.PARAGRAPH, score=0.85, parent_id="p1"),
        ]
        parent = self._make_chunk("p1", ChunkType.SECTION, score=0.5)

        pipeline.hybrid.retrieve = MagicMock(return_value=hits)
        pipeline.vector_store.get_by_ids = MagicMock(return_value=[parent])
        pipeline.vector_store.scroll = MagicMock(return_value=([], None))

        planner = RetrievalPlanner(pipeline.config)
        plan = planner.plan("test")

        results = await pipeline.search_enriched(query="test", plan=plan, top_k=2)

        ids = [c.id for c, _ in results]
        assert ids[0] == "e1"
        assert ids[1] == "e2"
        if len(ids) > 2:
            assert ids[2] == "p1"

    @pytest.mark.asyncio
    async def test_retrieve_enriched_uses_search_enriched(
        self, pipeline: RetrievalPipeline
    ) -> None:
        """retrieve_enriched should delegate to search_enriched for phase 1."""
        chunk = self._make_chunk("c1", score=0.9)

        pipeline.hybrid.retrieve = MagicMock(return_value=[chunk])
        pipeline.reranker.rerank = MagicMock(return_value=[chunk])
        pipeline.expander.expand = MagicMock(return_value=[chunk])
        pipeline.compressor.compress = MagicMock(return_value=[chunk])

        planner = RetrievalPlanner(pipeline.config)
        plan = planner.plan("test")

        results = await pipeline.retrieve_enriched(
            query="test",
            plan=plan,
            top_k=5,
            rerank=True,
            expand_parents=True,
            expand_siblings=False,
            compress=True,
        )

        assert len(results) == 1
        assert results[0][0].id == "c1"
        pipeline.reranker.rerank.assert_called_once()
        pipeline.expander.expand.assert_called_once()
        pipeline.compressor.compress.assert_called_once()

    @pytest.mark.asyncio
    async def test_retrieve_enriched_falls_back_when_reranker_fails(
        self, pipeline: RetrievalPipeline
    ) -> None:
        """Transient reranker failures should not fail the whole retrieval."""
        chunk = self._make_chunk("c1", score=0.9)

        pipeline.hybrid.retrieve = MagicMock(return_value=[chunk])
        pipeline.graph_expander.expand = MagicMock(return_value=([chunk], {}))
        pipeline.reranker.rerank = MagicMock(side_effect=RuntimeError("rate limited"))
        pipeline.expander.expand = MagicMock(side_effect=lambda chunks, *_args, **_kwargs: chunks)
        pipeline.compressor.compress = MagicMock(side_effect=lambda chunks, **_kwargs: chunks)

        planner = RetrievalPlanner(pipeline.config)
        results = await pipeline.retrieve_enriched(
            query="test",
            plan=planner.plan("test"),
            top_k=5,
            rerank=True,
            expand_parents=True,
            expand_siblings=False,
            compress=True,
        )

        assert [result[0].id for result in results] == ["c1"]
        assert pipeline._last_retrieval_stats["reranker_fallback_used"] is True
        assert pipeline._last_retrieval_stats["reranker_error_type"] == "RuntimeError"
        assert "rate limited" in pipeline._last_retrieval_stats["reranker_error"]

    @pytest.mark.asyncio
    async def test_retrieve_enriched_can_disable_reranker_fallback(
        self, pipeline: RetrievalPipeline
    ) -> None:
        """Operators can keep fail-fast reranking behavior when desired."""
        chunk = self._make_chunk("c1", score=0.9)
        pipeline.reranker_fallback_on_error = False

        pipeline.hybrid.retrieve = MagicMock(return_value=[chunk])
        pipeline.graph_expander.expand = MagicMock(return_value=([chunk], {}))
        pipeline.reranker.rerank = MagicMock(side_effect=RuntimeError("rate limited"))

        planner = RetrievalPlanner(pipeline.config)
        with pytest.raises(RuntimeError, match="rate limited"):
            await pipeline.retrieve_enriched(
                query="test",
                plan=planner.plan("test"),
                top_k=5,
                rerank=True,
                expand_parents=False,
                expand_siblings=False,
                compress=False,
            )

    @pytest.mark.asyncio
    async def test_retrieve_enriched_preserves_exact_title_matches_after_rerank(
        self, pipeline: RetrievalPipeline
    ) -> None:
        """Planner title matches should survive cross-encoder reranking."""
        select_first = self._make_chunk(
            "select_first",
            ChunkType.DOCUMENT,
            content="# SelectFirst\nThis method initializes a serial loop to the first site.",
            source_md="igxl/vbt/execSites.39.08.md",
            score=0.95,
        )
        select_first.doc_title = "SelectFirst"
        select_next = self._make_chunk(
            "select_next",
            ChunkType.DOCUMENT,
            content="# SelectNext\nThis method selects the next site in a serial loop.",
            source_md="igxl/vbt/execSites.39.09.md",
            score=0.94,
        )
        select_next.doc_title = "SelectNext"
        noisy = [
            self._make_chunk(
                f"noise{i}",
                ChunkType.PARAGRAPH,
                content="IG-XL includes SelectSitesFirstFan and SelectSitesNextFan methods.",
                source_md=f"igxl/vbt/noise{i}.md",
                score=0.99 - i * 0.01,
            )
            for i in range(5)
        ]
        candidates = noisy + [select_first, select_next]
        for candidate in candidates:
            candidate.vendor = "teradyne"
            candidate.platform = "j750"
            candidate.software = "igxl"

        pipeline.hybrid.retrieve = MagicMock(return_value=candidates)
        pipeline.graph_expander.expand = MagicMock(return_value=(candidates, {}))
        pipeline.reranker.rerank = MagicMock(return_value=noisy[:5])
        pipeline.expander.expand = MagicMock(side_effect=lambda chunks, *_args, **_kwargs: chunks)
        pipeline.compressor.compress = MagicMock(side_effect=lambda chunks, **_kwargs: chunks)

        planner = RetrievalPlanner(pipeline.config)
        query = "IG-XL 多 site 串行处理怎么实现？"
        plan = planner.plan(query, scope=TERADYNE_J750_IGXL)

        results = await pipeline.retrieve_enriched(
            query=query,
            plan=plan,
            top_k=5,
            rerank=True,
            expand_parents=True,
            expand_siblings=False,
            compress=True,
            scope=TERADYNE_J750_IGXL,
        )

        rerank_query = pipeline.reranker.rerank.call_args.args[0]
        assert "SelectFirst" in rerank_query
        assert "SelectNext" in rerank_query

        source_mds = {chunk.source_md for chunk, _score in results}
        assert "igxl/vbt/execSites.39.08.md" in source_mds
        assert "igxl/vbt/execSites.39.09.md" in source_mds
        assert pipeline._last_retrieval_stats["title_match_preserved_chunk_count"] == 2

    @pytest.mark.asyncio
    async def test_retrieve_scope_applies_scope_filters_and_drops_cross_scope(
        self, pipeline: RetrievalPipeline
    ) -> None:
        igxl = self._make_chunk("igxl", source_md="igxl/doc.md")
        igxl.vendor = "teradyne"
        igxl.platform = "j750"
        igxl.software = "igxl"
        smt7 = self._make_chunk("smt7", source_md="v93000/smt7/doc.md")
        smt7.vendor = "advantest"
        smt7.platform = "v93000"
        smt7.software = "smt7"
        pipeline.retrieve_enriched = AsyncMock(return_value=[(igxl, 0.9), (smt7, 0.8)])  # type: ignore[method-assign]
        pipeline._last_retrieval_stats = {}

        planner = RetrievalPlanner(pipeline.config)
        result = await pipeline.retrieve_scope(
            query="SelectFirst 怎么用？",
            plan=planner.plan("SelectFirst 怎么用？", scope=TERADYNE_J750_IGXL),
            scope=TERADYNE_J750_IGXL,
            top_k=5,
            user_filters={"software": "smt7"},
            rerank=True,
            expand_parents=True,
            expand_siblings=True,
            compress=True,
        )

        filters = pipeline.retrieve_enriched.call_args.kwargs["filters"]
        assert filters["vendor"] == "teradyne"
        assert filters["platform"] == "j750"
        assert filters["software"] == "igxl"
        assert [chunk.id for chunk, _score in result.chunks] == ["igxl"]
        assert result.processing["cross_scope_dropped_chunk_count"] == 1

    @pytest.mark.asyncio
    async def test_search_enriched_preserves_hybrid_stats(
        self, pipeline: RetrievalPipeline
    ) -> None:
        chunk = self._make_chunk("c1")
        pipeline.hybrid.retrieve = MagicMock(return_value=[chunk])
        pipeline.hybrid._last_retrieval_stats = {
            "dense_candidate_count": 4,
            "sparse_candidate_count": 2,
            "fused_candidate_count": 5,
            "sparse_search_used": True,
            "legacy_bm25_fallback_used": False,
        }
        planner = RetrievalPlanner(pipeline.config)

        await pipeline.search_enriched(query="test", plan=planner.plan("test"))

        assert pipeline._last_retrieval_stats["dense_candidate_count"] == 4
        assert pipeline._last_retrieval_stats["sparse_candidate_count"] == 2
        assert pipeline._last_retrieval_stats["fused_candidate_count"] == 5
        assert pipeline._last_retrieval_stats["sparse_search_used"] is True

    @pytest.mark.asyncio
    async def test_retrieve_narrow_query_uses_default_rerank_top_k(
        self, pipeline: RetrievalPipeline
    ) -> None:
        """Narrow query should call rerank with is_broad_concept=False."""
        chunks = [
            self._make_chunk(f"c{i}", source_md="doc.md", score=0.9 - i * 0.05)
            for i in range(10)
        ]
        pipeline.hybrid.retrieve = MagicMock(return_value=chunks)
        pipeline.graph_expander.expand = MagicMock(return_value=(chunks, {}))
        pipeline.reranker.rerank = MagicMock(return_value=chunks[:5])
        pipeline.expander.expand = MagicMock(return_value=chunks[:5])
        pipeline.compressor.compress = MagicMock(return_value=chunks[:5])

        results = await pipeline.retrieve(
            query="narrow query",
            is_broad_concept=False,
            rerank=True,
        )

        pipeline.reranker.rerank.assert_called_once()
        call_kwargs = pipeline.reranker.rerank.call_args.kwargs
        assert call_kwargs.get("is_broad_concept") is False
        assert len(results) == 5

    @pytest.mark.asyncio
    async def test_retrieve_broad_concept_uses_source_diverse_rerank(
        self, pipeline: RetrievalPipeline
    ) -> None:
        """Broad query should call rerank with is_broad_concept=True."""
        chunks = [
            self._make_chunk("a1", source_md="a.md", score=0.99),
            self._make_chunk("a2", source_md="a.md", score=0.98),
            self._make_chunk("b1", source_md="b.md", score=0.80),
            self._make_chunk("c1", source_md="c.md", score=0.70),
            self._make_chunk("d1", source_md="d.md", score=0.60),
        ]
        pipeline.hybrid.retrieve = MagicMock(return_value=chunks[:2])
        pipeline.graph_expander.expand = MagicMock(return_value=(chunks, {}))
        # Simulate source-diverse selection returning a1, b1, c1, d1
        pipeline.reranker.rerank = MagicMock(return_value=[chunks[0], chunks[2], chunks[3], chunks[4]])
        pipeline.expander.expand = MagicMock(return_value=[chunks[0], chunks[2], chunks[3], chunks[4]])
        pipeline.compressor.compress = MagicMock(return_value=[chunks[0], chunks[2], chunks[3], chunks[4]])

        results = await pipeline.retrieve(
            query="broad concept query",
            is_broad_concept=True,
            rerank=True,
        )

        pipeline.reranker.rerank.assert_called_once()
        call_kwargs = pipeline.reranker.rerank.call_args.kwargs
        assert call_kwargs.get("is_broad_concept") is True
        source_mds = {c.source_md for c, _ in results if c.source_md}
        assert len(source_mds) >= 3

    @pytest.mark.asyncio
    async def test_retrieve_broad_concept_preserves_graph_expanded_sources(
        self, pipeline: RetrievalPipeline
    ) -> None:
        """Broad query should not let a single source monopolize all top slots."""
        # Simulate many high-score chunks from the same source crowding out graph-expanded sources
        crowded = [
            self._make_chunk(f"crowd{i}", source_md="dominant.md", score=0.99 - i * 0.01)
            for i in range(8)
        ]
        expanded = [
            self._make_chunk("expanded_324", source_md="100324.md", score=0.70),
            self._make_chunk("expanded_264", source_md="20264.md", score=0.65),
            self._make_chunk("expanded_615", source_md="21615.md", score=0.60),
        ]
        all_chunks = crowded + expanded

        pipeline.hybrid.retrieve = MagicMock(return_value=crowded[:2])
        pipeline.graph_expander.expand = MagicMock(return_value=(all_chunks, {
            "expanded_source_count": 3,
            "expanded_chunk_count": 3,
        }))
        # Simulate broad rerank + source-diverse: keep some expanded chunks
        diverse = crowded[:1] + expanded
        pipeline.reranker.rerank = MagicMock(return_value=diverse)
        pipeline.expander.expand = MagicMock(return_value=diverse)
        pipeline.compressor.compress = MagicMock(return_value=diverse)

        results = await pipeline.retrieve(
            query="site control broad",
            is_broad_concept=True,
            rerank=True,
        )

        source_mds = {c.source_md for c, _ in results}
        assert "100324.md" in source_mds
        assert "20264.md" in source_mds
        assert "21615.md" in source_mds

    @pytest.mark.asyncio
    async def test_retrieve_stats_include_diversity_counts(
        self, pipeline: RetrievalPipeline
    ) -> None:
        """Processing stats should expose post-rerank and post-diversity counts."""
        chunks = [
            self._make_chunk("a1", source_md="a.md", score=0.99),
            self._make_chunk("b1", source_md="b.md", score=0.80),
            self._make_chunk("c1", source_md="c.md", score=0.70),
        ]
        pipeline.hybrid.retrieve = MagicMock(return_value=chunks)
        pipeline.graph_expander.expand = MagicMock(return_value=(chunks, {
            "expanded_source_count": 2,
            "expanded_chunk_count": 2,
        }))
        pipeline.reranker.rerank = MagicMock(return_value=chunks)
        pipeline.expander.expand = MagicMock(return_value=chunks)
        pipeline.compressor.compress = MagicMock(return_value=chunks)
        pipeline.reranker.broad_candidate_top_k = 16
        pipeline.reranker.top_k = 5

        # Broad concept: post_rerank should reflect candidate pool, post_diversity should reflect final
        await pipeline.retrieve(query="test", is_broad_concept=True, rerank=True)
        stats = pipeline._last_retrieval_stats
        assert stats["post_rerank_candidate_count"] == 3  # min(3, 16)
        assert stats["post_diversity_candidate_count"] == 3
        assert stats["post_rerank_source_count"] == 3
        assert stats["post_diversity_source_count"] == 3

        # Narrow query: post_rerank should reflect top_k truncation
        await pipeline.retrieve(query="test", is_broad_concept=False, rerank=True)
        stats = pipeline._last_retrieval_stats
        assert stats["post_rerank_candidate_count"] == 3  # min(3, 5)
        assert stats["post_diversity_candidate_count"] == 3
        assert stats["final_context_source_count"] == 3
        assert stats["final_context_token_estimate"] > 0
