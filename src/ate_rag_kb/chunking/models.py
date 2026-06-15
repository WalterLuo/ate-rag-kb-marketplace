"""Chunk data models."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ChunkType(str, Enum):
    """Types of chunks for ATE technical documentation."""

    DOCUMENT = "document"
    SECTION = "section"
    SUBSECTION = "subsection"
    CODE_BLOCK = "code_block"
    TABLE = "table"
    IMAGE = "image"
    PARAGRAPH = "paragraph"
    LIST = "list"


@dataclass
class Chunk:
    """A single chunk of content with rich metadata for ATE RAG."""

    id: str
    content: str
    chunk_type: ChunkType

    # Source tracking
    doc_title: str = ""
    section_title: str = ""
    subsection_title: str = ""
    source_md: str = ""  # relative path to markdown file
    source_json: str = ""  # relative path to json metadata
    source_html: str = ""  # original html file name (e.g. 147893.htm)

    # TOC hierarchy
    toc_path: list[str] = field(default_factory=list)
    toc_parent_href: str = ""  # parent document href from toc_tree
    toc_child_hrefs: list[str] = field(default_factory=list)  # child doc hrefs from toc_tree

    # Position
    heading_level: int = 0
    start_line: int = 0
    end_line: int = 0

    # Canonical ATE metadata
    vendor: str = ""  # teradyne, advantest
    platform: str = ""  # j750, v93000
    software: str = ""  # igxl, smt7, smt8
    software_release: str = ""

    # ATE-specific metadata
    doc_type: str = ""  # reference, guide, api, flow
    tags: list[str] = field(default_factory=list)

    # Legacy compatibility metadata
    ecosystem: str = ""  # v93000, igxl
    software_version: str = ""  # smt7, smt8
    doc_family: str = ""  # tdc, igxl_help
    release_version: str = ""  # e.g. 2024.1

    # Media
    images: list[dict] = field(default_factory=list)  # [{"path": "", "alt": "", "caption": ""}]
    tables: list[dict] = field(default_factory=list)  # [{"headers": [], "rows": []}]
    code_blocks: list[dict] = field(default_factory=list)  # [{"language": "", "code": ""}]

    # Parent-child relationships
    parent_id: str | None = None
    sibling_ids: list[str] = field(default_factory=list)
    child_ids: list[str] = field(default_factory=list)

    # Embedding
    embedding: list[float] | None = None

    # Search metadata (not stored in vector DB)
    score: float = 0.0

    def to_payload(self) -> dict[str, Any]:
        """Convert to Qdrant-compatible payload dict."""
        return {
            "doc_title": self.doc_title,
            "section_title": self.section_title,
            "subsection_title": self.subsection_title,
            "source_md": self.source_md,
            "source_json": self.source_json,
            "source_html": self.source_html,
            "toc_path": self.toc_path,
            "toc_parent_href": self.toc_parent_href,
            "toc_child_hrefs": self.toc_child_hrefs,
            "chunk_type": self.chunk_type.value,
            "heading_level": self.heading_level,
            "start_line": self.start_line,
            "end_line": self.end_line,
            "vendor": self.vendor,
            "platform": self.platform,
            "software": self.software,
            "software_release": self.software_release,
            "doc_type": self.doc_type,
            "tags": self.tags,
            "ecosystem": self.ecosystem,
            "software_version": self.software_version,
            "doc_family": self.doc_family,
            "release_version": self.release_version,
            "images": self.images,
            "tables": self.tables,
            "code_blocks": self.code_blocks,
            "parent_id": self.parent_id,
            "sibling_ids": self.sibling_ids,
            "child_ids": self.child_ids,
        }

    @classmethod
    def from_payload(cls, chunk_id: str, payload: dict[str, Any]) -> Chunk:
        """Reconstruct from Qdrant payload."""
        return cls(
            id=chunk_id,
            content=payload.get("content", ""),
            chunk_type=ChunkType(payload.get("chunk_type", "paragraph")),
            doc_title=payload.get("doc_title", ""),
            section_title=payload.get("section_title", ""),
            subsection_title=payload.get("subsection_title", ""),
            source_md=payload.get("source_md", ""),
            source_json=payload.get("source_json", ""),
            source_html=payload.get("source_html", ""),
            toc_path=payload.get("toc_path", []),
            toc_parent_href=payload.get("toc_parent_href", ""),
            toc_child_hrefs=payload.get("toc_child_hrefs", []),
            heading_level=payload.get("heading_level", 0),
            start_line=payload.get("start_line", 0),
            end_line=payload.get("end_line", 0),
            vendor=payload.get("vendor", ""),
            platform=payload.get("platform", ""),
            software=payload.get("software", ""),
            software_release=payload.get("software_release", ""),
            doc_type=payload.get("doc_type", ""),
            tags=payload.get("tags", []),
            ecosystem=payload.get("ecosystem", ""),
            software_version=payload.get("software_version", ""),
            doc_family=payload.get("doc_family", ""),
            release_version=payload.get("release_version", ""),
            images=payload.get("images", []),
            tables=payload.get("tables", []),
            code_blocks=payload.get("code_blocks", []),
            parent_id=payload.get("parent_id"),
            sibling_ids=payload.get("sibling_ids", []),
            child_ids=payload.get("child_ids", []),
            score=payload.get("score", 0.0),
        )
