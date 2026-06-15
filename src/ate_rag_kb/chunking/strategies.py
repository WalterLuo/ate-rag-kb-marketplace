"""Hierarchical chunking strategy for ATE technical documentation."""

from __future__ import annotations

import hashlib
import re
from typing import Any

from ate_rag_kb.chunking.models import Chunk, ChunkType
from ate_rag_kb.utils.config import Config


class HierarchicalChunker:
    """Split markdown documents into hierarchical chunks with rich metadata."""

    # Regex patterns
    _HEADING_RE = re.compile(r"^(#{1,4})\s+(.+)$", re.MULTILINE)
    _CODE_BLOCK_RE = re.compile(r"```(\w+)?\n(.*?)```", re.DOTALL)
    _TABLE_RE = re.compile(r"(\|[^\n]+\|\n\|[-:\s|]+\|\n(?:\|[^\n]+\|\n?)+)")
    _IMAGE_RE = re.compile(r"!\[(.*?)\]\((.+?)\)")
    _PARAGRAPH_RE = re.compile(r"\n\s*\n")

    def __init__(self, config: Config | None = None) -> None:
        cfg = config or Config({})
        strategies = cfg.get("chunking.strategies", {})
        self._limits: dict[ChunkType, dict[str, Any]] = {
            ChunkType.DOCUMENT: strategies.get("document", {}),
            ChunkType.SECTION: strategies.get("section", {}),
            ChunkType.SUBSECTION: strategies.get("subsection", {}),
            ChunkType.CODE_BLOCK: strategies.get("code_block", {}),
            ChunkType.TABLE: strategies.get("table", {}),
            ChunkType.PARAGRAPH: strategies.get("paragraph", {}),
        }
        section_max = self._limits.get(ChunkType.SECTION, {}).get("max_length", 4000)
        self._para_threshold = cfg.get("chunking.paragraph_threshold", max(800, section_max // 5))

    def _get_limit(self, chunk_type: ChunkType) -> tuple[int, int]:
        """Return (max_length, overlap) for a chunk type."""
        limits = self._limits.get(chunk_type, {})
        defaults: dict[ChunkType, tuple[int, int]] = {
            ChunkType.DOCUMENT: (8000, 200),
            ChunkType.SECTION: (4000, 100),
            ChunkType.SUBSECTION: (2000, 50),
            ChunkType.CODE_BLOCK: (1500, 0),
            ChunkType.TABLE: (3000, 0),
            ChunkType.PARAGRAPH: (4000, 100),
        }
        default_max, default_overlap = defaults.get(chunk_type, (4000, 100))
        return limits.get("max_length", default_max), limits.get("overlap", default_overlap)

    @staticmethod
    def _truncate_content(content: str, max_length: int) -> str:
        """Truncate content at max_length, preferring paragraph boundary."""
        if len(content) <= max_length:
            return content
        truncated = content[:max_length]
        para_break = truncated.rfind("\n\n")
        if para_break > max_length * 0.8:
            return truncated[:para_break]
        return truncated

    def chunk(self, text: str, metadata: dict[str, Any]) -> list[Chunk]:
        """Chunk markdown text into a hierarchical list of Chunk objects.

        Args:
            text: Raw markdown content.
            metadata: Document-level metadata (source_md, doc_title, platform, etc.)

        Returns:
            List of Chunk objects with parent/sibling/child relationships.
        """
        lines = text.splitlines()
        chunks: list[Chunk] = []

        # Extract special elements first so we can reference them
        code_blocks = self._extract_code_blocks(text)
        tables = self._extract_tables(text)
        images = self._extract_images(text)

        # Split by headings to build hierarchy
        heading_sections = self._split_by_headings(text, lines)

        # Create document-level root chunk
        doc_chunk = self._create_document_chunk(text, metadata)
        chunks.append(doc_chunk)

        # Track last chunk at each heading level for parent linking
        level_chunks: dict[int, Chunk] = {0: doc_chunk}

        for section in heading_sections:
            chunk = self._create_heading_chunk(section, metadata, doc_chunk.id)
            chunks.append(chunk)
            level_chunks[section["level"]] = chunk

            # Link parent
            parent = self._find_parent(level_chunks, section["level"])
            if parent is not None:
                chunk.parent_id = parent.id
                parent.child_ids = [*parent.child_ids, chunk.id]

            # Paragraph-level chunks for long sections
            if len(section["body"]) > self._para_threshold:
                para_chunks = self._chunk_paragraphs(
                    section["body"], chunk, metadata, section
                )
                for pc in para_chunks:
                    pc.parent_id = chunk.id
                    chunk.child_ids = [*chunk.child_ids, pc.id]
                chunks.extend(para_chunks)

            # Dedicated code block chunks inside this section
            section_code = self._filter_code_blocks(code_blocks, section["start_line"], section["end_line"])
            for cb in section_code:
                cb_chunk = self._create_code_block_chunk(cb, chunk, metadata)
                cb_chunk.parent_id = chunk.id
                chunk.child_ids = [*chunk.child_ids, cb_chunk.id]
                chunks.append(cb_chunk)

            # Dedicated table chunks inside this section
            section_tables = self._filter_tables(tables, section["start_line"], section["end_line"])
            for tbl in section_tables:
                tbl_chunk = self._create_table_chunk(tbl, chunk, metadata)
                tbl_chunk.parent_id = chunk.id
                chunk.child_ids = [*chunk.child_ids, tbl_chunk.id]
                chunks.append(tbl_chunk)

            # Image chunks inside this section
            section_images = self._filter_images(images, section["start_line"], section["end_line"])
            for img in section_images:
                img_chunk = self._create_image_chunk(img, chunk, metadata)
                img_chunk.parent_id = chunk.id
                chunk.child_ids = [*chunk.child_ids, img_chunk.id]
                chunks.append(img_chunk)

        # Link siblings at each level
        self._link_siblings(chunks)

        return chunks

    # ------------------------------------------------------------------
    # Extraction helpers
    # ------------------------------------------------------------------

    def _extract_headings(self, text: str) -> list[dict[str, Any]]:
        """Extract all headings with line numbers."""
        headings = []
        for match in self._HEADING_RE.finditer(text):
            level = len(match.group(1))
            title = match.group(2).strip()
            line_num = text[: match.start()].count("\n")
            headings.append({"level": level, "title": title, "line": line_num})
        return headings

    def _extract_code_blocks(self, text: str) -> list[dict[str, Any]]:
        """Extract fenced code blocks with language and line numbers."""
        blocks = []
        for match in self._CODE_BLOCK_RE.finditer(text):
            language = (match.group(1) or "").strip()
            code = match.group(2)
            start_line = text[: match.start()].count("\n")
            end_line = text[: match.end()].count("\n")
            blocks.append({
                "language": language,
                "code": code,
                "start_line": start_line,
                "end_line": end_line,
            })
        return blocks

    def _extract_tables(self, text: str) -> list[dict[str, Any]]:
        """Extract markdown tables with headers and rows."""
        tables = []
        for match in self._TABLE_RE.finditer(text):
            raw = match.group(1)
            lines = [ln.strip() for ln in raw.strip().splitlines() if ln.strip()]
            if len(lines) < 2:
                continue
            headers = [c.strip() for c in lines[0].split("|") if c.strip()]
            rows = []
            for row_line in lines[2:]:
                cells = [c.strip() for c in row_line.split("|") if c.strip()]
                rows.append(cells)
            start_line = text[: match.start()].count("\n")
            end_line = text[: match.end()].count("\n")
            tables.append({
                "headers": headers,
                "rows": rows,
                "raw": raw,
                "start_line": start_line,
                "end_line": end_line,
            })
        return tables

    def _extract_images(self, text: str) -> list[dict[str, Any]]:
        """Extract markdown image references."""
        images = []
        for match in self._IMAGE_RE.finditer(text):
            alt = match.group(1)
            path = match.group(2)
            start_line = text[: match.start()].count("\n")
            end_line = text[: match.end()].count("\n")
            images.append({
                "alt": alt,
                "path": path,
                "start_line": start_line,
                "end_line": end_line,
            })
        return images

    # ------------------------------------------------------------------
    # Splitting helpers
    # ------------------------------------------------------------------

    def _split_by_headings(self, text: str, lines: list[str]) -> list[dict[str, Any]]:
        """Split text into sections delimited by h1-h4 headings."""
        headings = self._extract_headings(text)
        if not headings:
            return [
                {
                    "level": 1,
                    "title": "",
                    "body": text,
                    "start_line": 0,
                    "end_line": len(lines) - 1,
                }
            ]

        sections = []
        for i, h in enumerate(headings):
            start_line = h["line"]
            end_line = (
                headings[i + 1]["line"] - 1
                if i + 1 < len(headings)
                else len(lines) - 1
            )
            body_lines = lines[start_line : end_line + 1]
            # Remove heading line from body
            body = "\n".join(body_lines[1:]) if body_lines else ""
            sections.append(
                {
                    "level": h["level"],
                    "title": h["title"],
                    "body": body,
                    "start_line": start_line,
                    "end_line": end_line,
                }
            )
        return sections

    def _chunk_paragraphs(
        self,
        body: str,
        parent_chunk: Chunk,
        metadata: dict[str, Any],
        section: dict[str, Any],
    ) -> list[Chunk]:
        """Split a long section body into paragraph-level chunks."""
        paragraphs = [p.strip() for p in self._PARAGRAPH_RE.split(body) if p.strip()]
        para_chunks: list[Chunk] = []
        for idx, para in enumerate(paragraphs):
            chunk_id = self._make_id(
                metadata.get("source_md", ""),
                section["title"],
                f"para-{idx}",
                para,
            )
            para_chunks.append(
                Chunk(
                    id=chunk_id,
                    content=para,
                    chunk_type=ChunkType.PARAGRAPH,
                    doc_title=metadata.get("doc_title", ""),
                    section_title=section["title"] if section["level"] <= 2 else parent_chunk.section_title,
                    subsection_title=section["title"] if section["level"] > 2 else "",
                    source_md=metadata.get("source_md", ""),
                    source_json=metadata.get("source_json", ""),
                    source_html=metadata.get("source_html", ""),
                    toc_path=[*parent_chunk.toc_path],
                    toc_parent_href=metadata.get("toc_parent_href", ""),
                    toc_child_hrefs=metadata.get("toc_child_hrefs", []),
                    heading_level=section["level"],
                    start_line=section["start_line"],
                    end_line=section["end_line"],
                    platform=metadata.get("platform", ""),
                    doc_type=metadata.get("doc_type", ""),
                    tags=metadata.get("tags", []),
                    ecosystem=metadata.get("ecosystem", ""),
                    software_version=metadata.get("software_version", ""),
                    doc_family=metadata.get("doc_family", ""),
                    release_version=metadata.get("release_version", ""),
                    parent_id=parent_chunk.id,
                )
            )
        return para_chunks

    # ------------------------------------------------------------------
    # Relationship helpers
    # ------------------------------------------------------------------

    def _find_parent(
        self, level_chunks: dict[int, Chunk], current_level: int
    ) -> Chunk | None:
        """Find the nearest parent chunk at a lower heading level."""
        for level in range(current_level - 1, -1, -1):
            if level in level_chunks:
                return level_chunks[level]
        return None

    def _link_siblings(self, chunks: list[Chunk]) -> None:
        """Populate sibling_ids for chunks that share the same parent."""
        parent_map: dict[str, list[Chunk]] = {}
        for chunk in chunks:
            pid = chunk.parent_id
            if pid is not None:
                parent_map.setdefault(pid, []).append(chunk)

        for siblings in parent_map.values():
            ids = [c.id for c in siblings]
            for chunk in siblings:
                chunk.sibling_ids = [sid for sid in ids if sid != chunk.id]

    # ------------------------------------------------------------------
    # Filter helpers
    # ------------------------------------------------------------------

    def _filter_images(
        self, images: list[dict[str, Any]], start_line: int, end_line: int
    ) -> list[dict[str, Any]]:
        """Return images that fall within the given line range."""
        return [
            img
            for img in images
            if start_line <= img["start_line"] <= end_line
        ]

    def _filter_tables(
        self, tables: list[dict[str, Any]], start_line: int, end_line: int
    ) -> list[dict[str, Any]]:
        """Return tables that fall within the given line range."""
        return [
            tbl
            for tbl in tables
            if start_line <= tbl["start_line"] <= end_line
        ]

    def _filter_code_blocks(
        self, blocks: list[dict[str, Any]], start_line: int, end_line: int
    ) -> list[dict[str, Any]]:
        """Return code blocks that fall within the given line range."""
        return [
            cb
            for cb in blocks
            if start_line <= cb["start_line"] <= end_line
        ]

    # ------------------------------------------------------------------
    # Conversion helpers
    # ------------------------------------------------------------------

    def _table_to_text(self, table: dict[str, Any]) -> str:
        """Convert a parsed table into a plain-text representation."""
        headers = " | ".join(table["headers"])
        rows = [" | ".join(row) for row in table["rows"]]
        return f"Table:\n{headers}\n" + "\n".join(rows)

    # ------------------------------------------------------------------
    # Chunk factories
    # ------------------------------------------------------------------

    def _base_toc_path(self, metadata: dict[str, Any]) -> list[str]:
        """Return the base TOC path from metadata, falling back to doc_title."""
        return metadata.get("toc_path", [metadata.get("doc_title", "")]) or [metadata.get("doc_title", "")]

    def _create_document_chunk(self, text: str, metadata: dict[str, Any]) -> Chunk:
        """Create the top-level DOCUMENT chunk."""
        chunk_id = self._make_id(
            metadata.get("source_md", ""), metadata.get("doc_title", ""), "doc", text[:200]
        )
        max_len, _ = self._get_limit(ChunkType.DOCUMENT)
        content = self._truncate_content(text, max_len)
        return Chunk(
            id=chunk_id,
            content=content,
            chunk_type=ChunkType.DOCUMENT,
            doc_title=metadata.get("doc_title", ""),
            source_md=metadata.get("source_md", ""),
            source_json=metadata.get("source_json", ""),
            source_html=metadata.get("source_html", ""),
            toc_path=self._base_toc_path(metadata),
            toc_parent_href=metadata.get("toc_parent_href", ""),
            toc_child_hrefs=metadata.get("toc_child_hrefs", []),
            heading_level=0,
            platform=metadata.get("platform", ""),
            doc_type=metadata.get("doc_type", ""),
            tags=metadata.get("tags", []),
            ecosystem=metadata.get("ecosystem", ""),
            software_version=metadata.get("software_version", ""),
            doc_family=metadata.get("doc_family", ""),
            release_version=metadata.get("release_version", ""),
        )

    def _create_heading_chunk(
        self, section: dict[str, Any], metadata: dict[str, Any], doc_id: str
    ) -> Chunk:
        """Create a SECTION or SUBSECTION chunk from a heading split."""
        level = section["level"]
        chunk_type = ChunkType.SECTION if level <= 2 else ChunkType.SUBSECTION
        chunk_id = self._make_id(
            metadata.get("source_md", ""),
            section["title"],
            f"h{level}",
            section["body"][:200],
        )
        base_path = self._base_toc_path(metadata)
        raw_content = f"{section['title']}\n\n{section['body']}".strip()
        max_len, _ = self._get_limit(chunk_type)
        content = self._truncate_content(raw_content, max_len)
        return Chunk(
            id=chunk_id,
            content=content,
            chunk_type=chunk_type,
            doc_title=metadata.get("doc_title", ""),
            section_title=section["title"] if level <= 2 else "",
            subsection_title=section["title"] if level > 2 else "",
            source_md=metadata.get("source_md", ""),
            source_json=metadata.get("source_json", ""),
            source_html=metadata.get("source_html", ""),
            toc_path=[*base_path, section["title"]],
            toc_parent_href=metadata.get("toc_parent_href", ""),
            toc_child_hrefs=metadata.get("toc_child_hrefs", []),
            heading_level=level,
            start_line=section["start_line"],
            end_line=section["end_line"],
            platform=metadata.get("platform", ""),
            doc_type=metadata.get("doc_type", ""),
            tags=metadata.get("tags", []),
            ecosystem=metadata.get("ecosystem", ""),
            software_version=metadata.get("software_version", ""),
            doc_family=metadata.get("doc_family", ""),
            release_version=metadata.get("release_version", ""),
            parent_id=doc_id,
        )

    def _create_code_block_chunk(
        self, cb: dict[str, Any], parent: Chunk, metadata: dict[str, Any]
    ) -> Chunk:
        """Create a CODE_BLOCK chunk."""
        chunk_id = self._make_id(
            metadata.get("source_md", ""), parent.section_title, "code", cb["code"][:200]
        )
        return Chunk(
            id=chunk_id,
            content=cb["code"],
            chunk_type=ChunkType.CODE_BLOCK,
            doc_title=metadata.get("doc_title", ""),
            section_title=parent.section_title,
            subsection_title=parent.subsection_title,
            source_md=metadata.get("source_md", ""),
            source_json=metadata.get("source_json", ""),
            source_html=metadata.get("source_html", ""),
            toc_path=[*parent.toc_path],
            toc_parent_href=metadata.get("toc_parent_href", ""),
            toc_child_hrefs=metadata.get("toc_child_hrefs", []),
            heading_level=parent.heading_level,
            start_line=cb["start_line"],
            end_line=cb["end_line"],
            platform=metadata.get("platform", ""),
            doc_type=metadata.get("doc_type", ""),
            tags=metadata.get("tags", []),
            ecosystem=metadata.get("ecosystem", ""),
            software_version=metadata.get("software_version", ""),
            doc_family=metadata.get("doc_family", ""),
            release_version=metadata.get("release_version", ""),
            code_blocks=[{"language": cb["language"], "code": cb["code"]}],
            parent_id=parent.id,
        )

    def _create_table_chunk(
        self, tbl: dict[str, Any], parent: Chunk, metadata: dict[str, Any]
    ) -> Chunk:
        """Create a TABLE chunk."""
        chunk_id = self._make_id(
            metadata.get("source_md", ""), parent.section_title, "table", tbl["raw"][:200]
        )
        return Chunk(
            id=chunk_id,
            content=self._table_to_text(tbl),
            chunk_type=ChunkType.TABLE,
            doc_title=metadata.get("doc_title", ""),
            section_title=parent.section_title,
            subsection_title=parent.subsection_title,
            source_md=metadata.get("source_md", ""),
            source_json=metadata.get("source_json", ""),
            source_html=metadata.get("source_html", ""),
            toc_path=[*parent.toc_path],
            toc_parent_href=metadata.get("toc_parent_href", ""),
            toc_child_hrefs=metadata.get("toc_child_hrefs", []),
            heading_level=parent.heading_level,
            start_line=tbl["start_line"],
            end_line=tbl["end_line"],
            platform=metadata.get("platform", ""),
            doc_type=metadata.get("doc_type", ""),
            tags=metadata.get("tags", []),
            ecosystem=metadata.get("ecosystem", ""),
            software_version=metadata.get("software_version", ""),
            doc_family=metadata.get("doc_family", ""),
            release_version=metadata.get("release_version", ""),
            tables=[{"headers": tbl["headers"], "rows": tbl["rows"]}],
            parent_id=parent.id,
        )

    def _create_image_chunk(
        self, img: dict[str, Any], parent: Chunk, metadata: dict[str, Any]
    ) -> Chunk:
        """Create an IMAGE chunk."""
        chunk_id = self._make_id(
            metadata.get("source_md", ""), parent.section_title, "img", img["path"]
        )
        return Chunk(
            id=chunk_id,
            content=f"Image: {img['alt']} ({img['path']})",
            chunk_type=ChunkType.IMAGE,
            doc_title=metadata.get("doc_title", ""),
            section_title=parent.section_title,
            subsection_title=parent.subsection_title,
            source_md=metadata.get("source_md", ""),
            source_json=metadata.get("source_json", ""),
            source_html=metadata.get("source_html", ""),
            toc_path=[*parent.toc_path],
            toc_parent_href=metadata.get("toc_parent_href", ""),
            toc_child_hrefs=metadata.get("toc_child_hrefs", []),
            heading_level=parent.heading_level,
            start_line=img["start_line"],
            end_line=img["end_line"],
            platform=metadata.get("platform", ""),
            doc_type=metadata.get("doc_type", ""),
            tags=metadata.get("tags", []),
            ecosystem=metadata.get("ecosystem", ""),
            software_version=metadata.get("software_version", ""),
            doc_family=metadata.get("doc_family", ""),
            release_version=metadata.get("release_version", ""),
            images=[{"path": img["path"], "alt": img["alt"], "caption": ""}],
            parent_id=parent.id,
        )

    # ------------------------------------------------------------------
    # ID generation
    # ------------------------------------------------------------------

    def _make_id(self, source_md: str, title: str, suffix: str, content_snippet: str) -> str:
        """Deterministic SHA256-based chunk ID."""
        raw = f"{source_md}::{title}::{suffix}::{content_snippet}".encode()
        return hashlib.sha256(raw).hexdigest()[:32]
