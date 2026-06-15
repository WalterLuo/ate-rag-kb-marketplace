"""Pydantic models for API requests and responses."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ChunkResult(BaseModel):
    """A single retrieved chunk with metadata."""

    id: str
    content: str
    score: float = Field(description="Relevance score (0-1)")
    chunk_type: str = "paragraph"
    doc_title: str = ""
    section_title: str = ""
    subsection_title: str = ""
    source_md: str = ""
    toc_path: list[str] = Field(default_factory=list)
    vendor: str = ""
    platform: str = ""
    software: str = ""
    software_release: str = ""
    doc_type: str = ""
    tags: list[str] = Field(default_factory=list)
    ecosystem: str = ""
    software_version: str = ""
    doc_family: str = ""
    heading_level: int = 0
    start_line: int = 0
    end_line: int = 0
    parent_id: str | None = None
    sibling_ids: list[str] = Field(default_factory=list)
    child_ids: list[str] = Field(default_factory=list)
    images: list[dict] = Field(default_factory=list)
    tables: list[dict] = Field(default_factory=list)
    code_blocks: list[dict] = Field(default_factory=list)


class SearchRequest(BaseModel):
    """Request body for semantic search."""

    query: str = Field(..., min_length=1, description="Search query string")
    top_k: int = Field(default=10, ge=1, le=100, description="Number of results to return")
    filters: dict[str, Any] = Field(
        default_factory=dict,
        description="Optional metadata filters (e.g. platform, doc_type)",
    )


class ResolvedScope(BaseModel):
    """Canonical retrieval scope used by HTTP retrieval endpoints."""

    vendor: str
    platform: str
    software: str
    software_release: str = ""


class SearchResponse(BaseModel):
    """Response for semantic search."""

    query: str
    chunks: list[ChunkResult]
    total: int = Field(description="Total number of chunks returned")
    answer_mode: str = "direct"
    resolved_scopes: list[ResolvedScope] = Field(default_factory=list)
    correction_notice: str = ""
    clarification_prompt: str = ""
    message: str = Field(
        default="",
        description="Optional block/ambiguity/clarification message",
    )
    timing: dict[str, float] = Field(
        default_factory=dict,
        description="Step-by-step execution timing in milliseconds",
    )


class RetrieveRequest(BaseModel):
    """Request body for advanced retrieval with expansion and reranking."""

    query: str = Field(..., min_length=1, description="Search query string")
    top_k: int = Field(default=10, ge=1, le=100, description="Number of results to return")
    filters: dict[str, Any] = Field(
        default_factory=dict,
        description="Optional metadata filters",
    )
    expand_parents: bool = Field(default=True, description="Include parent chunks")
    expand_siblings: bool = Field(default=True, description="Include sibling chunks")
    rerank: bool = Field(default=True, description="Apply cross-encoder reranking")
    compress: bool = Field(default=True, description="Merge adjacent and remove duplicates")


class RetrieveResponse(BaseModel):
    """Response for advanced retrieval."""

    query: str
    chunks: list[ChunkResult]
    total: int
    reranked: bool
    expanded: bool
    compressed: bool
    answer_mode: str = "direct"
    resolved_scopes: list[ResolvedScope] = Field(default_factory=list)
    correction_notice: str = ""
    clarification_prompt: str = ""
    message: str = Field(
        default="",
        description="Optional block/ambiguity/clarification message",
    )
    timing: dict[str, float] = Field(
        default_factory=dict,
        description="Step-by-step execution timing in milliseconds",
    )


class AskRequest(BaseModel):
    """Request body for agent-friendly Q&A."""

    question: str = Field(..., min_length=1, description="User question")
    context: str = Field(default="", description="Optional additional context")
    top_k: int = Field(default=8, ge=1, le=50, description="Max chunks to retrieve")
    filters: dict[str, Any] = Field(default_factory=dict)


class Citation(BaseModel):
    """Citation mapping answer text to source chunks."""

    chunk_id: str
    excerpt: str
    source_md: str
    toc_path: list[str] = Field(default_factory=list)
    start_line: int = 0
    end_line: int = 0


class AskResponse(BaseModel):
    """Agent-friendly response with structured citations."""

    question: str
    chunks: list[ChunkResult]
    citations: list[Citation] = Field(
        default_factory=list,
        description="Citations linking answer to source chunks",
    )
    toc_paths: list[list[str]] = Field(
        default_factory=list,
        description="Unique TOC paths found in retrieved chunks",
    )
    source_files: list[str] = Field(
        default_factory=list,
        description="Unique source markdown files",
    )
    answer_mode: str = "direct"
    resolved_scopes: list[ResolvedScope] = Field(default_factory=list)
    correction_notice: str = ""
    clarification_prompt: str = ""
    message: str = Field(
        default="",
        description="Optional block/ambiguity/clarification message",
    )
    timing: dict[str, float] = Field(
        default_factory=dict,
        description="Step-by-step execution timing in milliseconds",
    )


class RelatedRequest(BaseModel):
    """Request body for finding related chunks."""

    chunk_id: str = Field(..., min_length=1, description="Chunk ID to find relations for")


class RelatedResponse(BaseModel):
    """Response with parent and sibling chunks."""

    chunk_id: str
    parent: ChunkResult | None = None
    siblings: list[ChunkResult] = Field(default_factory=list)
    children: list[ChunkResult] = Field(default_factory=list)


class DocumentResponse(BaseModel):
    """Response returning all chunks for a source markdown file."""

    source_md: str
    chunks: list[ChunkResult]
    total: int
    returned: int = 0
    offset: int = 0
    limit: int = 20
    has_more: bool = False
    next_offset: int | None = None
