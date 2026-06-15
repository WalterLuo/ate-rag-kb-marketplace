"""MCP tool definitions and handlers for ATE RAG Knowledge Base.

Each tool reuses the existing RetrievalPipeline and returns structured
JSON that agents can consume directly.
"""

from __future__ import annotations

import logging
from typing import Any

from ate_rag_kb.chunking.models import Chunk
from ate_rag_kb.mcp.context_builder import (
    _chunk_to_mcp,
    build_context_package,
    build_scoped_context_package,
    build_sources_summary,
    compute_confidence,
)
from ate_rag_kb.mcp.models import (
    McpAnswerContract,
    McpAskResult,
    McpCitation,
    McpDocumentResult,
    McpRelatedResult,
    McpResolvedScope,
    McpRetrieveResult,
    McpSearchResult,
    McpStatusResult,
)
from ate_rag_kb.retrieval.coordinator import (
    CoordinatedRetrievalResult,
    RetrievalCoordinator,
)
from ate_rag_kb.retrieval.pipeline import RetrievalPipeline
from ate_rag_kb.retrieval.planner import RetrievalPlan, RetrievalPlanner
from ate_rag_kb.utils.timing import StepTimer

logger = logging.getLogger(__name__)

_BROAD_REQUIRED_SECTIONS = [
    "Core concept and purpose",
    "Related windows, flags, commands, APIs, or configuration fields",
    "Common usage scenarios",
    "Execution behavior and examples",
    "Limitations, warnings, and best practices",
]

_BROAD_SYNTHESIS_RULES = [
    "Do not return only a short overview when content-bearing subtopics are available.",
    "Cover each applicable coverage topic, or briefly state why it is outside the answer scope.",
    "Cite source_md and section_title for each answer section.",
    "Mark unsupported or unverified details as not confirmed by the KB.",
]

# ---------------------------------------------------------------------------
# Tool schemas (JSON Schema for MCP discovery)
# ---------------------------------------------------------------------------

_SEARCH_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "query": {
            "type": "string",
            "description": (
                "Search query. Use natural language, not keywords. "
                "Example: 'How to configure drive edge in timing set'"
            ),
        },
        "top_k": {
            "type": "integer",
            "default": 10,
            "minimum": 1,
            "maximum": 50,
            "description": "Maximum number of chunks to return",
        },
        "filters": {
            "type": "object",
            "default": {},
            "description": (
                "Optional metadata filters. Supported: platform, doc_type, chunk_type, tags"
            ),
        },
    },
    "required": ["query"],
}

_RETRIEVE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "query": {
            "type": "string",
            "description": "Search query in natural language",
        },
        "top_k": {
            "type": "integer",
            "default": 10,
            "minimum": 1,
            "maximum": 50,
            "description": "Number of results after all processing",
        },
        "filters": {
            "type": "object",
            "default": {},
            "description": "Same filter schema as ate_kb.search",
        },
        "rerank": {
            "type": "boolean",
            "default": True,
            "description": "Apply cross-encoder reranking (slower, more accurate)",
        },
        "expand_parents": {
            "type": "boolean",
            "default": True,
            "description": "Include parent section chunks for context",
        },
        "expand_siblings": {
            "type": "boolean",
            "default": True,
            "description": "Include sibling chunks (adjacent sections)",
        },
        "compress": {
            "type": "boolean",
            "default": True,
            "description": "Merge adjacent chunks and remove duplicates",
        },
        "max_tokens": {
            "type": "integer",
            "default": 4000,
            "minimum": 500,
            "maximum": 16000,
            "description": "Approximate token budget for returned content",
        },
    },
    "required": ["query"],
}

_ASK_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "question": {
            "type": "string",
            "description": "The question to answer",
        },
        "top_k": {
            "type": "integer",
            "default": 8,
            "minimum": 1,
            "maximum": 50,
        },
        "filters": {
            "type": "object",
            "default": {},
            "description": "Same filter schema as ate_kb.search",
        },
        "include_context_package": {
            "type": "boolean",
            "default": True,
            "description": "Include full context package for agent's own reasoning",
        },
    },
    "required": ["question"],
}

_RELATED_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "chunk_id": {
            "type": "string",
            "description": "The chunk ID to find relations for",
        },
        "include_parent": {
            "type": "boolean",
            "default": True,
        },
        "include_siblings": {
            "type": "boolean",
            "default": True,
        },
        "include_children": {
            "type": "boolean",
            "default": False,
        },
        "max_siblings": {
            "type": "integer",
            "default": 2,
            "minimum": 0,
            "maximum": 10,
        },
    },
    "required": ["chunk_id"],
}

_GET_DOCUMENT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "source_md": {
            "type": "string",
            "description": "Source markdown file name (e.g., '118727.md')",
        },
        "limit": {
            "type": "integer",
            "default": 20,
            "minimum": 1,
            "maximum": 100,
            "description": "Maximum number of chunks to return",
        },
        "offset": {
            "type": "integer",
            "default": 0,
            "minimum": 0,
            "description": "Offset from which to start returning chunks",
        },
        "max_tokens": {
            "type": "integer",
            "default": 4000,
            "minimum": 500,
            "maximum": 16000,
            "description": "Approximate token budget for context_package",
        },
    },
    "required": ["source_md"],
}

_STATUS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {},
    "required": [],
}

TOOL_SCHEMAS: dict[str, dict[str, Any]] = {
    "ate_kb.search": _SEARCH_SCHEMA,
    "ate_kb.retrieve": _RETRIEVE_SCHEMA,
    "ate_kb.ask": _ASK_SCHEMA,
    "ate_kb.related": _RELATED_SCHEMA,
    "ate_kb.get_document": _GET_DOCUMENT_SCHEMA,
    "ate_kb.status": _STATUS_SCHEMA,
}

# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------


class McpToolHandler:
    """Wraps RetrievalPipeline methods as MCP tool handlers."""

    def __init__(
        self,
        pipeline: RetrievalPipeline,
        coordinator: RetrievalCoordinator | None = None,
    ) -> None:
        self.pipeline = pipeline
        self.planner = RetrievalPlanner(pipeline.config)
        self.coordinator = coordinator

    @staticmethod
    def _merge_filters(
        inferred: dict[str, Any] | None,
        user: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        """Merge inferred filters with user-provided filters (user wins)."""
        if not inferred and not user:
            return None
        merged = dict(inferred or {})
        if user:
            merged.update(user)
        return merged if merged else None

    @staticmethod
    def _apply_ecosystem_filter(
        query: str,
        results: list[tuple[Chunk, float]],
        plan: RetrievalPlan,
    ) -> list[tuple[Chunk, float]]:
        """Bidirectional ecosystem contamination filtering."""
        if plan.ecosystem == "igxl":
            return [
                (c, s)
                for c, s in results
                if c.ecosystem != "v93000"
                and not McpToolHandler._is_smt7_or_v93000_chunk(c)
                and (c.platform != "TDC" or c.source_md.lower().startswith("igxl/"))
            ]
        if plan.ecosystem == "v93000":
            return [
                (c, s)
                for c, s in results
                if c.ecosystem != "igxl"
                and not c.source_md.lower().startswith("igxl/")
                and c.platform != "J750"
            ]
        return results

    def _result_limit_with_enrichment(
        self,
        query: str,
        top_k: int,
        *,
        is_broad_concept: bool = False,
    ) -> int:
        """Allow bounded enrichment beyond top_k."""
        del query
        enrichment_budget = self.pipeline.config.get("retrieval.planner.enrichment_budget", 3)
        limit = top_k + enrichment_budget
        if is_broad_concept:
            return max(
                limit,
                self.pipeline.config.get("retrieval.broad_context.max_chunks", 16),
            )
        return limit

    def _context_token_budget(
        self,
        plan: RetrievalPlan,
        requested: int | None = None,
    ) -> int:
        if requested is not None:
            return requested
        if plan.is_broad_concept:
            return self.pipeline.config.get("retrieval.broad_context.max_tokens", 9000)
        return 4000

    @staticmethod
    def _broad_processing(stats: dict[str, Any]) -> dict[str, Any]:
        return {
            "broad_context_assembled": stats.get("broad_context_assembled", False),
            "broad_context_seed_source_count": stats.get(
                "broad_context_seed_source_count", 0
            ),
            "broad_context_discovered_source_count": stats.get(
                "broad_context_discovered_source_count", 0
            ),
            "broad_context_added_chunk_count": stats.get(
                "broad_context_added_chunk_count", 0
            ),
            "broad_context_source_count": stats.get("broad_context_source_count", 0),
            "broad_context_token_estimate": stats.get(
                "broad_context_token_estimate", 0
            ),
            "low_utility_rerank_candidate_count": stats.get(
                "low_utility_rerank_candidate_count", 0
            ),
            "low_utility_chunk_count": stats.get("low_utility_chunk_count", 0),
            "coverage_topics": stats.get("coverage_topics", []),
        }

    @staticmethod
    def _rerank_processing(stats: dict[str, Any], requested: bool) -> dict[str, Any]:
        fallback_used = stats.get("reranker_fallback_used", False)
        return {
            "reranked": bool(requested and not fallback_used),
            "reranker_fallback_used": fallback_used,
            "reranker_error_type": stats.get("reranker_error_type", ""),
            "reranker_error": stats.get("reranker_error", ""),
        }

    @staticmethod
    def _answer_contract(
        plan: RetrievalPlan,
        processing_info: dict[str, Any],
    ) -> McpAnswerContract:
        """Return explicit synthesis requirements for the calling agent."""
        if not plan.is_broad_concept:
            return McpAnswerContract()

        coverage_topics = processing_info.get("coverage_topics", [])
        return McpAnswerContract(
            answer_mode="broad_concept",
            completeness_required=True,
            required_sections=list(_BROAD_REQUIRED_SECTIONS),
            coverage_topics=list(coverage_topics),
            synthesis_rules=list(_BROAD_SYNTHESIS_RULES),
            diagnostics={
                "broad_context_assembled": processing_info.get(
                    "broad_context_assembled", False
                ),
                "coverage_topic_count": len(coverage_topics),
                "final_context_source_count": processing_info.get(
                    "final_context_source_count", 0
                ),
                "final_context_token_estimate": processing_info.get(
                    "final_context_token_estimate", 0
                ),
            },
        )

    @staticmethod
    def _scope_to_mcp(scope: Any) -> McpResolvedScope:
        return McpResolvedScope(
            vendor=scope.vendor,
            platform=scope.platform,
            software=scope.software,
            software_release=scope.software_release,
        )

    @staticmethod
    def _flatten_coordinated(
        result: CoordinatedRetrievalResult,
    ) -> list[tuple[Chunk, float]]:
        return [
            (chunk, score)
            for group in result.groups
            for chunk, score in group.chunks
        ]

    @staticmethod
    def _coordinated_processing(result: CoordinatedRetrievalResult) -> dict[str, Any]:
        return {
            "processing_by_scope": result.processing_by_scope,
            "cross_scope_dropped_chunk_count": result.cross_scope_dropped_chunk_count,
            "final_source_files_by_scope": {
                group.scope.key: sorted(
                    {chunk.source_md for chunk, _score in group.chunks if chunk.source_md}
                )
                for group in result.groups
            },
        }

    @staticmethod
    def _coordinated_answer_contract(
        result: CoordinatedRetrievalResult,
    ) -> McpAnswerContract:
        coverage_by_scope = {
            group.scope.key: list(group.processing.get("coverage_topics", []))
            for group in result.groups
        }
        completeness_required = any(coverage_by_scope.values())
        flat_coverage = (
            next(iter(coverage_by_scope.values()))
            if len(coverage_by_scope) == 1
            else []
        )
        return McpAnswerContract(
            answer_mode=result.answer_mode,
            completeness_required=completeness_required,
            resolved_scopes=[McpToolHandler._scope_to_mcp(group.scope) for group in result.groups],
            correction_notice=result.correction_notice,
            clarification_prompt=result.clarification_prompt,
            required_sections=list(_BROAD_REQUIRED_SECTIONS) if completeness_required else [],
            coverage_topics=list(flat_coverage),
            coverage_topics_by_scope=coverage_by_scope,
            synthesis_rules=list(_BROAD_SYNTHESIS_RULES) if completeness_required else [],
            diagnostics={
                **McpToolHandler._coordinated_processing(result),
                "coverage_topic_count_by_scope": {
                    key: len(value) for key, value in coverage_by_scope.items()
                },
            },
        )

    @staticmethod
    def _coordinated_answer_guidance(contract: McpAnswerContract) -> str:
        if contract.answer_mode == "clarification":
            return contract.clarification_prompt
        base = (
            "Use the provided scoped context package and citations to synthesize an answer. "
            "Keep each resolved scope isolated and cite source_md and section_title for every claim."
        )
        if contract.answer_mode == "platform_comparison":
            base += " Provide separate sections for each resolved scope."
        if contract.completeness_required:
            base += " This question requires complete coverage of the scoped coverage topics."
        return base

    @staticmethod
    def _is_smt7_or_v93000_chunk(chunk: Chunk) -> bool:
        sm = chunk.source_md.lower()
        if sm.startswith(("v93000/", "smt7/", "smt8/")):
            return True
        basename = sm.split("/")[-1]
        name_part = basename.split(".")[0]
        if name_part.isdigit():
            return True
        return "_" in name_part and name_part.split("_")[0].isdigit()

    async def handle_search(self, args: dict[str, Any]) -> McpSearchResult:
        """Handle ate_kb.search."""
        if self.coordinator is not None:
            return await self._handle_search_coordinated(args)

        query = args["query"]
        top_k = args.get("top_k", 10)
        user_filters = args.get("filters") or None

        plan = self.planner.plan(query)

        if plan.is_blocked:
            return McpSearchResult(
                query=query, total=0, chunks=[], sources=[], message=plan.block_reason or ""
            )
        if plan.is_ambiguous:
            return McpSearchResult(
                query=query, total=0, chunks=[], sources=[], message=plan.clarification_prompt or ""
            )

        filters = self._merge_filters(plan.inferred_filters, user_filters)

        results: list[tuple[Chunk, float]] = await self.pipeline.search_enriched(
            query=query,
            plan=plan,
            top_k=top_k,
            filters=filters,
        )
        results = self._apply_ecosystem_filter(query, results, plan)
        max_results = self._result_limit_with_enrichment(
            query, top_k, is_broad_concept=plan.is_broad_concept
        )
        results = results[:max_results]

        chunks = [_chunk_to_mcp(chunk, score) for chunk, score in results]
        sources = build_sources_summary(chunks)

        return McpSearchResult(
            query=query,
            total=len(chunks),
            chunks=chunks,
            sources=sources,
        )

    async def _handle_search_coordinated(self, args: dict[str, Any]) -> McpSearchResult:
        query = args["query"]
        result = await self.coordinator.search(
            query,
            top_k=args.get("top_k", 10),
            filters=args.get("filters") or None,
        )
        if result.answer_mode == "clarification":
            return McpSearchResult(
                query=query,
                total=0,
                chunks=[],
                sources=[],
                message=result.clarification_prompt,
            )
        flat = self._flatten_coordinated(result)
        chunks = [_chunk_to_mcp(chunk, score) for chunk, score in flat]
        return McpSearchResult(
            query=query,
            total=len(chunks),
            chunks=chunks,
            sources=build_sources_summary(chunks),
            message=result.correction_notice,
        )

    async def handle_retrieve(self, args: dict[str, Any]) -> McpRetrieveResult:
        """Handle ate_kb.retrieve."""
        if self.coordinator is not None:
            return await self._handle_retrieve_coordinated(args)

        timer = StepTimer()
        with timer.step("total"):
            query = args["query"]
            top_k = args.get("top_k", 10)
            user_filters = args.get("filters") or None
            rerank = args.get("rerank", True)
            expand_parents = args.get("expand_parents", True)
            expand_siblings = args.get("expand_siblings", True)
            compress = args.get("compress", True)
            requested_max_tokens = args.get("max_tokens")

            plan = self.planner.plan(query)

            if plan.is_blocked:
                return McpRetrieveResult(
                    query=query,
                    total=0,
                    chunks=[],
                    context_package=None,
                    message=plan.block_reason or "",
                )
            if plan.is_ambiguous:
                return McpRetrieveResult(
                    query=query,
                    total=0,
                    chunks=[],
                    context_package=None,
                    message=plan.clarification_prompt or "",
                )

            filters = self._merge_filters(plan.inferred_filters, user_filters)

            results: list[tuple[Chunk, float]] = await self.pipeline.retrieve_enriched(
                query=plan.enhanced_query,
                plan=plan,
                top_k=top_k * 2,
                filters=filters,
                expand_parents=expand_parents,
                expand_siblings=expand_siblings,
                rerank=rerank,
                compress=compress,
            )
            results = self._apply_ecosystem_filter(query, results, plan)
            max_results = self._result_limit_with_enrichment(
                query, top_k, is_broad_concept=plan.is_broad_concept
            )
            results = results[:max_results]
            chunks = [_chunk_to_mcp(chunk, score) for chunk, score in results]
            max_tokens = self._context_token_budget(plan, requested_max_tokens)
            context_package = build_context_package(results, max_tokens=max_tokens)

            stats = self.pipeline._last_retrieval_stats
            processing_info = {
                "planner_inferred_filters": plan.inferred_filters,
                "dense_candidate_count": stats.get("dense_candidate_count", len(results)),
                "sparse_candidate_count": stats.get("sparse_candidate_count", 0),
                "fused_candidate_count": stats.get("fused_candidate_count", len(results)),
                "sparse_search_used": stats.get("sparse_search_used", False),
                "legacy_bm25_fallback_used": stats.get("legacy_bm25_fallback_used", False),
                "graph_expanded_source_count": stats.get("graph_expanded_source_count", 0),
                "graph_expanded_chunk_count": stats.get("graph_expanded_chunk_count", 0),
                "post_rerank_candidate_count": stats.get("post_rerank_candidate_count", 0),
                "post_rerank_source_count": stats.get("post_rerank_source_count", 0),
                "post_diversity_candidate_count": stats.get("post_diversity_candidate_count", 0),
                "post_diversity_source_count": stats.get("post_diversity_source_count", 0),
                "final_context_source_count": stats.get("final_context_source_count", 0),
                "final_context_token_estimate": stats.get("final_context_token_estimate", 0),
                "reranked_candidate_count": stats.get("reranked_candidate_count", len(results) if rerank else 0),
                "final_source_files": sorted({c.source_md for c in chunks if c.source_md}),
                **self._broad_processing(stats),
                **self._rerank_processing(stats, rerank),
                "expanded": expand_parents or expand_siblings,
                "compressed": compress,
                **timer.to_dict(),
            }

            return McpRetrieveResult(
                query=query,
                total=len(chunks),
                processing=processing_info,
                answer_contract=self._answer_contract(plan, processing_info),
                chunks=chunks,
                context_package=context_package,
            )

        query = args["query"]
        top_k = args.get("top_k", 10)
        user_filters = args.get("filters") or None
        rerank = args.get("rerank", True)
        expand_parents = args.get("expand_parents", True)
        expand_siblings = args.get("expand_siblings", True)
        compress = args.get("compress", True)
        requested_max_tokens = args.get("max_tokens")

        plan = self.planner.plan(query)

        if plan.is_blocked:
            return McpRetrieveResult(
                query=query,
                total=0,
                chunks=[],
                context_package=None,
                message=plan.block_reason or "",
            )
        if plan.is_ambiguous:
            return McpRetrieveResult(
                query=query,
                total=0,
                chunks=[],
                context_package=None,
                message=plan.clarification_prompt or "",
            )

        filters = self._merge_filters(plan.inferred_filters, user_filters)

        results: list[tuple[Chunk, float]] = await self.pipeline.retrieve_enriched(
            query=plan.enhanced_query,
            plan=plan,
            top_k=top_k * 2,
            filters=filters,
            expand_parents=expand_parents,
            expand_siblings=expand_siblings,
            rerank=rerank,
            compress=compress,
        )
        results = self._apply_ecosystem_filter(query, results, plan)
        max_results = self._result_limit_with_enrichment(
            query, top_k, is_broad_concept=plan.is_broad_concept
        )
        results = results[:max_results]
        chunks = [_chunk_to_mcp(chunk, score) for chunk, score in results]
        max_tokens = self._context_token_budget(plan, requested_max_tokens)
        context_package = build_context_package(results, max_tokens=max_tokens)

        stats = self.pipeline._last_retrieval_stats
        processing_info = {
            "planner_inferred_filters": plan.inferred_filters,
            "dense_candidate_count": stats.get("dense_candidate_count", len(results)),
            "sparse_candidate_count": stats.get("sparse_candidate_count", 0),
            "fused_candidate_count": stats.get("fused_candidate_count", len(results)),
            "sparse_search_used": stats.get("sparse_search_used", False),
            "legacy_bm25_fallback_used": stats.get("legacy_bm25_fallback_used", False),
            "graph_expanded_source_count": stats.get("graph_expanded_source_count", 0),
            "graph_expanded_chunk_count": stats.get("graph_expanded_chunk_count", 0),
            "post_rerank_candidate_count": stats.get("post_rerank_candidate_count", 0),
            "post_rerank_source_count": stats.get("post_rerank_source_count", 0),
            "post_diversity_candidate_count": stats.get("post_diversity_candidate_count", 0),
            "post_diversity_source_count": stats.get("post_diversity_source_count", 0),
            "final_context_source_count": stats.get("final_context_source_count", 0),
            "final_context_token_estimate": stats.get("final_context_token_estimate", 0),
            "reranked_candidate_count": stats.get("reranked_candidate_count", len(results) if rerank else 0),
            "final_source_files": sorted({c.source_md for c in chunks if c.source_md}),
            **self._broad_processing(stats),
            **self._rerank_processing(stats, rerank),
            "expanded": expand_parents or expand_siblings,
            "compressed": compress,
        }

        return McpRetrieveResult(
            query=query,
            total=len(chunks),
            processing=processing_info,
            answer_contract=self._answer_contract(plan, processing_info),
            chunks=chunks,
            context_package=context_package,
        )

    async def _handle_retrieve_coordinated(self, args: dict[str, Any]) -> McpRetrieveResult:
        query = args["query"]
        result = await self.coordinator.retrieve(
            query,
            top_k=args.get("top_k", 10),
            filters=args.get("filters") or None,
            rerank=args.get("rerank", True),
            expand_parents=args.get("expand_parents", True),
            expand_siblings=args.get("expand_siblings", True),
            compress=args.get("compress", True),
        )
        contract = self._coordinated_answer_contract(result)
        if result.answer_mode == "clarification":
            return McpRetrieveResult(
                query=query,
                total=0,
                processing=self._coordinated_processing(result),
                answer_contract=contract,
                chunks=[],
                context_package=None,
                message=result.clarification_prompt,
            )

        flat = self._flatten_coordinated(result)
        chunks = [_chunk_to_mcp(chunk, score) for chunk, score in flat]
        context_package = build_scoped_context_package(
            [(group.scope, group.chunks) for group in result.groups],
            max_tokens=args.get("max_tokens", 4000),
        )
        return McpRetrieveResult(
            query=query,
            total=len(chunks),
            processing=self._coordinated_processing(result),
            answer_contract=contract,
            chunks=chunks,
            context_package=context_package,
            message=result.correction_notice,
        )

    async def handle_ask(self, args: dict[str, Any]) -> McpAskResult:
        """Handle ate_kb.ask.

        Phase 1: No LLM synthesis. Returns grounded context package + citations.
        """
        if self.coordinator is not None:
            return await self._handle_ask_coordinated(args)

        timer = StepTimer()
        with timer.step("total"):
            question = args["question"]
            top_k = args.get("top_k", 8)
            user_filters = args.get("filters") or None
            include_context = args.get("include_context_package", True)

            plan = self.planner.plan(question)

            if plan.is_blocked:
                return McpAskResult(
                    question=question,
                    answer=plan.block_reason or "",
                    citations=[],
                    source_files=[],
                    toc_paths=[],
                    confidence="low",
                    context_package=None,
                    message=plan.block_reason or "",
                )
            if plan.is_ambiguous:
                return McpAskResult(
                    question=question,
                    answer=plan.clarification_prompt or "",
                    citations=[],
                    source_files=[],
                    toc_paths=[],
                    confidence="low",
                    context_package=None,
                    message=plan.clarification_prompt or "",
                )

            filters = self._merge_filters(plan.inferred_filters, user_filters)

            results: list[tuple[Chunk, float]] = await self.pipeline.retrieve_enriched(
                query=plan.enhanced_query,
                plan=plan,
                top_k=top_k * 2,
                filters=filters,
                expand_parents=True,
                expand_siblings=True,
                rerank=True,
                compress=True,
            )
            results = self._apply_ecosystem_filter(question, results, plan)
            max_results = self._result_limit_with_enrichment(
                question, top_k, is_broad_concept=plan.is_broad_concept
            )
            results = results[:max_results]
            chunks = [_chunk_to_mcp(chunk, score) for chunk, score in results]

            citations = [
                McpCitation(
                    chunk_id=chunk.id,
                    excerpt=chunk.content[:300],
                    source_md=chunk.source_md,
                    toc_path=chunk.toc_path,
                    start_line=chunk.start_line,
                    end_line=chunk.end_line,
                )
                for chunk in chunks
            ]

            toc_paths = sorted({tuple(c.toc_path) for c in chunks if c.toc_path})
            source_files = sorted({c.source_md for c in chunks if c.source_md})
            confidence = compute_confidence(chunks)

            context_package = None
            if include_context:
                context_package = build_context_package(
                    results,
                    max_tokens=self._context_token_budget(plan),
                )

            stats = self.pipeline._last_retrieval_stats
            processing_info = {
                "planner_inferred_filters": plan.inferred_filters,
                "dense_candidate_count": stats.get("dense_candidate_count", len(results)),
                "sparse_candidate_count": stats.get("sparse_candidate_count", 0),
                "fused_candidate_count": stats.get("fused_candidate_count", len(results)),
                "sparse_search_used": stats.get("sparse_search_used", False),
                "legacy_bm25_fallback_used": stats.get("legacy_bm25_fallback_used", False),
                "graph_expanded_source_count": stats.get("graph_expanded_source_count", 0),
                "graph_expanded_chunk_count": stats.get("graph_expanded_chunk_count", 0),
                "post_rerank_candidate_count": stats.get("post_rerank_candidate_count", 0),
                "post_rerank_source_count": stats.get("post_rerank_source_count", 0),
                "post_diversity_candidate_count": stats.get("post_diversity_candidate_count", 0),
                "post_diversity_source_count": stats.get("post_diversity_source_count", 0),
                "final_context_source_count": stats.get("final_context_source_count", 0),
                "final_context_token_estimate": stats.get("final_context_token_estimate", 0),
                "reranked_candidate_count": stats.get("reranked_candidate_count", len(results)),
                "final_source_files": source_files,
                **self._broad_processing(stats),
                **self._rerank_processing(stats, True),
                "expanded": True,
                "compressed": True,
                **timer.to_dict(),
            }

            answer_contract = self._answer_contract(plan, processing_info)
            return McpAskResult(
                question=question,
                answer=self._answer_guidance(plan, answer_contract),
                citations=citations,
                source_files=list(source_files),
                toc_paths=[list(tp) for tp in toc_paths],
                confidence=confidence,
                context_package=context_package,
                processing=processing_info,
                answer_contract=answer_contract,
            )

    async def _handle_ask_coordinated(self, args: dict[str, Any]) -> McpAskResult:
        question = args["question"]
        include_context = args.get("include_context_package", True)
        result = await self.coordinator.retrieve(
            question,
            top_k=args.get("top_k", 8),
            filters=args.get("filters") or None,
            expand_parents=True,
            expand_siblings=True,
            rerank=True,
            compress=True,
        )
        contract = self._coordinated_answer_contract(result)
        if result.answer_mode == "clarification":
            return McpAskResult(
                question=question,
                answer=contract.clarification_prompt,
                citations=[],
                source_files=[],
                toc_paths=[],
                confidence="low",
                context_package=None,
                message=contract.clarification_prompt,
                processing=self._coordinated_processing(result),
                answer_contract=contract,
            )

        flat = self._flatten_coordinated(result)
        chunks = [_chunk_to_mcp(chunk, score) for chunk, score in flat]
        citations = [
            McpCitation(
                chunk_id=chunk.id,
                excerpt=chunk.content[:300],
                source_md=chunk.source_md,
                toc_path=chunk.toc_path,
                start_line=chunk.start_line,
                end_line=chunk.end_line,
            )
            for chunk in chunks
        ]
        context_package = None
        if include_context:
            context_package = build_scoped_context_package(
                [(group.scope, group.chunks) for group in result.groups],
                max_tokens=4000,
            )
        toc_paths = sorted({tuple(c.toc_path) for c in chunks if c.toc_path})
        source_files = sorted({c.source_md for c in chunks if c.source_md})
        return McpAskResult(
            question=question,
            answer=self._coordinated_answer_guidance(contract),
            citations=citations,
            source_files=list(source_files),
            toc_paths=[list(tp) for tp in toc_paths],
            confidence=compute_confidence(chunks),
            context_package=context_package,
            message=result.correction_notice,
            processing=self._coordinated_processing(result),
            answer_contract=contract,
        )

    @staticmethod
    def _answer_guidance(
        plan: RetrievalPlan,
        answer_contract: McpAnswerContract,
    ) -> str:
        base = (
            "Use the provided context package and citations to synthesize an answer. "
            "Always cite source_md and section_title for every claim."
        )
        if not plan.is_broad_concept:
            return base
        return (
            f"{base} This is a broad-concept question: provide a comprehensive answer using "
            "the assembled context. A short overview alone is insufficient. Follow the "
            f"answer_contract, inspect all {len(answer_contract.coverage_topics)} discovered "
            "coverage_topics, and cover the core "
            "purpose, discovered subtopics, execution behavior, examples, limitations, "
            "warnings, and best practices when supported. Explicitly mark details that are "
            "not confirmed by the KB."
        )

    async def handle_related(self, args: dict[str, Any]) -> McpRelatedResult:
        """Handle ate_kb.related."""
        chunk_id = args["chunk_id"]
        include_parent = args.get("include_parent", True)
        include_siblings = args.get("include_siblings", True)
        include_children = args.get("include_children", False)
        max_siblings = args.get("max_siblings", 2)

        relations = await self.pipeline.get_related(chunk_id)

        parent = None
        if include_parent and relations.get("parent"):
            parent = _chunk_to_mcp(relations["parent"], score=1.0)

        siblings: list[Any] = []
        if include_siblings:
            siblings = [
                _chunk_to_mcp(chunk, score=1.0)
                for chunk in relations.get("siblings", [])[:max_siblings]
            ]
        children = [
            _chunk_to_mcp(chunk, score=1.0)
            for chunk in relations.get("children", [])
            if include_children
        ]

        return McpRelatedResult(
            chunk_id=chunk_id,
            parent=parent,
            siblings=siblings,
            children=children,
        )

    async def handle_get_document(self, args: dict[str, Any]) -> McpDocumentResult:
        """Handle ate_kb.get_document with pagination."""
        source_md = args["source_md"]
        limit = args.get("limit", 20)
        offset = args.get("offset", 0)
        max_tokens = args.get("max_tokens", 4000)

        page = await self.pipeline.get_document_page(source_md, limit=limit, offset=offset)
        paginated = page["chunks"]
        results = [_chunk_to_mcp(chunk, score=1.0) for chunk in paginated]

        context_package = None
        if results:
            context_package = build_context_package(
                [(c, 1.0) for c in paginated], max_tokens=max_tokens
            )

        return McpDocumentResult(
            source_md=source_md,
            total=page["total"],
            returned=page["returned"],
            offset=offset,
            limit=limit,
            has_more=page["has_more"],
            next_offset=page["next_offset"],
            chunks=results,
            context_package=context_package,
        )

    async def handle_status(self, _args: dict[str, Any]) -> McpStatusResult:
        """Handle ate_kb.status."""
        try:
            stats = await self.pipeline.collection_stats()
            return McpStatusResult(
                status="ok",
                collection_name=stats.get("collection_name", ""),
                total_chunks=stats.get("total_chunks", 0),
                vector_size=stats.get("vector_size", 0),
                embedding_model=stats.get("embedding_model", ""),
                platforms=stats.get("platforms", []),
                doc_types=stats.get("doc_types", []),
                ecosystems=stats.get("ecosystems", []),
                software_versions=stats.get("software_versions", []),
                doc_families=stats.get("doc_families", []),
                version="0.1.0",
            )
        except Exception as exc:
            logger.error("Status check failed: %s", exc)
            return McpStatusResult(status="degraded")
