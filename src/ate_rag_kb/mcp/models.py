"""Pydantic models for MCP tool input/output."""

from __future__ import annotations

from pydantic import BaseModel, Field


class McpChunkResult(BaseModel):
    """A single retrieved chunk with full metadata for MCP tools."""

    id: str = Field(description="Unique chunk ID (SHA256)")
    content: str = Field(description="Full chunk content")
    score: float = Field(description="Relevance score 0-1")
    chunk_type: str = Field(default="paragraph", description="Chunk type")
    doc_title: str = Field(default="", description="Document title")
    section_title: str = Field(default="", description="Section title")
    subsection_title: str = Field(default="", description="Subsection title")
    source_md: str = Field(default="", description="Source markdown file path")
    toc_path: list[str] = Field(default_factory=list, description="TOC hierarchy")
    vendor: str = Field(default="", description="ATE vendor")
    platform: str = Field(default="", description="Platform (TDC, J750, etc.)")
    software: str = Field(default="", description="Software product")
    software_release: str = Field(default="", description="Software release")
    doc_type: str = Field(default="", description="Document type")
    ecosystem: str = Field(default="", description="Ecosystem (v93000, igxl)")
    software_version: str = Field(default="", description="Software version (smt7, smt8)")
    doc_family: str = Field(default="", description="Document family (tdc, igxl_help)")
    heading_level: int = Field(default=0, description="Heading level")
    start_line: int = Field(default=0, description="Start line in source")
    end_line: int = Field(default=0, description="End line in source")
    parent_id: str | None = Field(default=None, description="Parent chunk ID")
    sibling_ids: list[str] = Field(default_factory=list, description="Sibling chunk IDs")
    child_ids: list[str] = Field(default_factory=list, description="Child chunk IDs")
    is_expanded: bool = Field(
        default=False,
        description="True if added via parent/sibling expansion",
    )


class McpCitation(BaseModel):
    """Citation mapping retrieved context to source chunks."""

    chunk_id: str
    excerpt: str = Field(description="300-char excerpt from chunk")
    source_md: str
    toc_path: list[str] = Field(default_factory=list)
    start_line: int = 0
    end_line: int = 0


class McpContextPackage(BaseModel):
    """Pre-formatted context string ready for LLM prompt injection."""

    text: str = Field(description="Concatenated chunk contents with citation markers")
    token_estimate: int = Field(description="Approximate token count")
    citation_map: list[dict] = Field(
        default_factory=list,
        description="Maps citation markers [1], [2] to chunk metadata",
    )


class McpSearchResult(BaseModel):
    """Output for ate_kb.search tool."""

    query: str
    total: int = Field(description="Number of chunks returned")
    chunks: list[McpChunkResult]
    sources: list[dict] = Field(
        default_factory=list,
        description="Unique source files ordered by relevance",
    )
    message: str = Field(
        default="",
        description="Optional block/ambiguity/clarification message",
    )


class McpResolvedScope(BaseModel):
    """Canonical retrieval scope returned to MCP callers."""

    vendor: str
    platform: str
    software: str
    software_release: str = ""


class McpAnswerContract(BaseModel):
    """Machine-readable synthesis requirements for an MCP answer."""

    answer_mode: str = Field(
        default="direct",
        description="direct, platform_comparison, or clarification",
    )
    completeness_required: bool = Field(
        default=False,
        description="True when a summary-only answer is insufficient",
    )
    resolved_scopes: list[McpResolvedScope] = Field(
        default_factory=list,
        description="Canonical retrieval scopes used for this response",
    )
    correction_notice: str = Field(
        default="",
        description="Notice when an exclusive symbol corrected the requested scope",
    )
    clarification_prompt: str = Field(
        default="",
        description="Question to ask the user when the request is ambiguous",
    )
    required_sections: list[str] = Field(
        default_factory=list,
        description="Answer sections to cover when supported by retrieved context",
    )
    coverage_topics: list[str] = Field(
        default_factory=list,
        description="Dynamically discovered content-bearing topics to inspect during synthesis",
    )
    coverage_topics_by_scope: dict[str, list[str]] = Field(
        default_factory=dict,
        description="Coverage topics grouped by canonical scope key",
    )
    synthesis_rules: list[str] = Field(
        default_factory=list,
        description="Rules the calling agent must apply when composing the final answer",
    )
    diagnostics: dict = Field(
        default_factory=dict,
        description="Retrieval coverage indicators useful for answer validation",
    )


class McpRetrieveResult(BaseModel):
    """Output for ate_kb.retrieve tool."""

    query: str
    total: int
    processing: dict = Field(
        default_factory=dict,
        description="Flags indicating which processing steps ran",
    )
    answer_contract: McpAnswerContract = Field(
        default_factory=McpAnswerContract,
        description="Machine-readable synthesis requirements for the calling agent",
    )
    chunks: list[McpChunkResult]
    context_package: McpContextPackage | None = None
    message: str = Field(
        default="",
        description="Optional block/ambiguity/clarification message",
    )


class McpAskResult(BaseModel):
    """Output for ate_kb.ask tool."""

    question: str
    answer: str = Field(
        default="",
        description="Guidance text (LLM synthesis disabled in phase 1)",
    )
    citations: list[McpCitation]
    source_files: list[str] = Field(default_factory=list)
    toc_paths: list[list[str]] = Field(default_factory=list)
    confidence: str = Field(
        default="medium",
        description="high / medium / low based on score distribution",
    )
    context_package: McpContextPackage | None = None
    message: str = Field(
        default="",
        description="Optional block/ambiguity/clarification message",
    )
    processing: dict = Field(
        default_factory=dict,
        description="Processing metadata for observability",
    )
    answer_contract: McpAnswerContract = Field(
        default_factory=McpAnswerContract,
        description="Machine-readable synthesis requirements for the calling agent",
    )


class McpRelatedResult(BaseModel):
    """Output for ate_kb.related tool."""

    chunk_id: str
    parent: McpChunkResult | None = None
    siblings: list[McpChunkResult] = Field(default_factory=list)
    children: list[McpChunkResult] = Field(default_factory=list)


class McpDocumentResult(BaseModel):
    """Output for ate_kb.get_document tool."""

    source_md: str
    total: int
    returned: int = 0
    offset: int = 0
    limit: int = 20
    has_more: bool = False
    next_offset: int | None = None
    chunks: list[McpChunkResult]
    context_package: McpContextPackage | None = None


class McpStatusResult(BaseModel):
    """Output for ate_kb.status tool."""

    status: str = Field(description="ok / degraded / unavailable")
    collection_name: str = ""
    total_chunks: int = 0
    vector_size: int = 0
    embedding_model: str = ""
    platforms: list[str] = Field(default_factory=list)
    vendors: list[str] = Field(default_factory=list)
    softwares: list[str] = Field(default_factory=list)
    software_releases: list[str] = Field(default_factory=list)
    doc_types: list[str] = Field(default_factory=list)
    ecosystems: list[str] = Field(default_factory=list)
    software_versions: list[str] = Field(default_factory=list)
    doc_families: list[str] = Field(default_factory=list)
    version: str = "0.1.0"
    resolved_scopes: list[McpResolvedScope] = Field(
        default_factory=list,
        description="Canonical retrieval scopes used for this response",
    )
    correction_notice: str = Field(
        default="",
        description="Notice when an exclusive symbol corrected the requested scope",
    )
    clarification_prompt: str = Field(
        default="",
        description="Question to ask the user when the request is ambiguous",
    )
