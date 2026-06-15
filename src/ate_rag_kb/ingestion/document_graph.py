"""Cross-document link graph builder for ATE KB ingestion.

Parses internal ``.htm`` / ``.html`` and ``.md`` links from Markdown content,
resolves them to ``source_md`` paths via JSON metadata or relative-path
resolution, builds forward / backward references, and handles ``_2`` variant
documents.
"""

from __future__ import annotations

import hashlib
import json
import logging
import posixpath
import re
from pathlib import Path, PurePosixPath
from typing import Any

logger = logging.getLogger(__name__)

# Regex for markdown links: [text](href "optional tooltip")
# Negative lookbehind (?<!!) excludes image syntax: ![alt](url)
_MD_LINK_RE = re.compile(
    r"(?<!!)\[([^\]]+)\]\(([^)#?\s\"]+\.(?:md|html?))(?:[?#][^)\s\"]*)?(?:\s+\"[^\"]*\")?\)",
    re.IGNORECASE,
)

# Regex for raw <a href="..."> tags
_HTML_A_RE = re.compile(
    r'<a\s+[^>]*href="([^"#?]+(?:\.md|\.html?))(?:[?#][^"]*)?"[^>]*>',
    re.IGNORECASE,
)


def _is_internal_href(href: str) -> bool:
    """Return True for local ``.htm`` / ``.html`` / ``.md`` paths that should be tracked."""
    href_lower = href.lower()
    # Skip external URLs
    if href_lower.startswith(("http://", "https://", "ftp://", "mailto:")):
        return False
    # Skip image / asset paths
    if "/assets/" in href_lower or href_lower.startswith("assets/"):
        return False
    if href_lower.startswith("../assets/"):
        return False
    # Track .htm, .html, and .md internal links
    return (
        href_lower.endswith(".htm")
        or href_lower.endswith(".html")
        or href_lower.endswith(".md")
    )


class MarkdownLinkParser:
    """Extract internal documentation links from Markdown text."""

    @staticmethod
    def extract_links(md_text: str) -> list[str]:
        """Return deduplicated list of internal ``.htm`` / ``.html`` hrefs."""
        seen: set[str] = set()
        results: list[str] = []

        for match in _MD_LINK_RE.finditer(md_text):
            href = match.group(2)
            if _is_internal_href(href) and href not in seen:
                seen.add(href)
                results.append(href)

        for match in _HTML_A_RE.finditer(md_text):
            href = match.group(1)
            if _is_internal_href(href) and href not in seen:
                seen.add(href)
                results.append(href)

        return results


class DocumentGraphBuilder:
    """Build a cross-document link graph from all Markdown + JSON metadata."""

    def __init__(
        self,
        markdown_dir: Path,
        json_dir: Path | None = None,
    ) -> None:
        self.markdown_dir = markdown_dir
        self.json_dir = json_dir
        # source_html -> source_md mapping, built from JSON metadata
        self._html_to_md: dict[str, str] = {}
        # source_md -> source_html mapping
        self._md_to_html: dict[str, str] = {}
        # variant detection: base_name (without _2) -> canonical source_md
        self._canonical_map: dict[str, str] = {}

    def _build_html_index(self) -> None:
        """Index all source_html -> source_md mappings from JSON metadata."""
        if self.json_dir is None:
            return

        for json_path in self.json_dir.rglob("*.json"):
            try:
                meta = json.loads(json_path.read_text(encoding="utf-8"))
            except Exception:
                continue

            source_html = meta.get("source_html", "")
            markdown_path = meta.get("markdown_path", "")
            if not source_html or not markdown_path:
                continue

            # Derive source_md from markdown_path (e.g. "markdown/v93000/smt7/100118.md")
            # We want the relative path under markdown_dir
            rel_md = markdown_path
            if rel_md.startswith("markdown/"):
                rel_md = rel_md[len("markdown/") :]

            self._html_to_md[source_html] = rel_md
            self._md_to_html[rel_md] = source_html

        # Second pass: establish canonical mapping
        for source_html, source_md in self._html_to_md.items():
            base = self._base_href(source_html)
            if base in self._html_to_md:
                self._canonical_map[source_md] = self._html_to_md[base]
            else:
                self._canonical_map[source_md] = source_md

    @staticmethod
    def _base_href(href: str) -> str:
        """Return base href without ``_2`` / ``_3`` etc suffixes.

        Examples:
            ``21615_2.htm`` -> ``21615.htm``
            ``100096.htm``  -> ``100096.htm``
        """
        # Match pattern like 21615_2.htm -> 21615.htm
        m = re.match(r"^(.+)_(\d+)\.html?$", href, re.IGNORECASE)
        if m:
            return f"{m.group(1)}.htm"
        return href

    def _resolve_href(self, current_source_md: str, href: str) -> str | None:
        """Map an internal href to its ``source_md`` path.

        Examples:
            ``execSites.39.09.md`` from ``igxl/vbt/execSites.39.08.md`` -> ``igxl/vbt/execSites.39.09.md``
            ``../overview.md`` from ``igxl/vbt/a.md`` -> ``igxl/overview.md``
        """
        href_path = PurePosixPath(href)
        current_parent = PurePosixPath(current_source_md).parent

        if href_path.suffix.lower() == ".md":
            candidate = posixpath.normpath(str(current_parent / href_path))
            if (self.markdown_dir / candidate).exists():
                return candidate
            return None

        relative_html = posixpath.normpath(str(current_parent / href_path))
        return self._html_to_md.get(href) or self._html_to_md.get(relative_html)

    def build(self) -> dict[str, Any]:
        """Build and return the document graph.

        Returns a dict keyed by ``source_md`` with values:
            ``linked_source_mds``: list[str]
            ``referenced_by_source_mds``: list[str]
            ``canonical_source_md``: str
            ``content_hash``: str
            ``source_html``: str
        """
        self._build_html_index()

        # Collect all existing source_md paths first for existence checks
        all_source_mds: set[str] = set()
        for md_path in self.markdown_dir.rglob("*.md"):
            rel_md = str(md_path.relative_to(self.markdown_dir))
            all_source_mds.add(rel_md)

        # First pass: collect forward links and metadata per document
        raw_graph: dict[str, dict[str, Any]] = {}

        for md_path in self.markdown_dir.rglob("*.md"):
            rel_md = str(md_path.relative_to(self.markdown_dir))
            md_text = md_path.read_text(encoding="utf-8")
            content_hash = hashlib.sha256(md_text.encode("utf-8")).hexdigest()[:32]

            links = MarkdownLinkParser.extract_links(md_text)
            linked_mds: list[str] = []
            for href in links:
                target_md = self._resolve_href(rel_md, href)
                if target_md and target_md != rel_md and target_md in all_source_mds:
                    linked_mds.append(target_md)

            canonical = self._canonical_map.get(rel_md, rel_md)
            source_html = self._md_to_html.get(rel_md, "")

            raw_graph[rel_md] = {
                "source_html": source_html,
                "linked_source_mds": linked_mds,
                "referenced_by_source_mds": [],
                "canonical_source_md": canonical,
                "content_hash": content_hash,
            }

        # Second pass: build back-references
        for source_md, node in raw_graph.items():
            for linked in node["linked_source_mds"]:
                if (
                    linked in raw_graph
                    and source_md not in raw_graph[linked]["referenced_by_source_mds"]
                ):
                    raw_graph[linked]["referenced_by_source_mds"].append(source_md)

        return raw_graph

    def save(self, path: Path) -> None:
        """Persist the built graph to *path*."""
        graph = self.build()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(graph, indent=2), encoding="utf-8")
        logger.info("Saved document graph with %d nodes to %s", len(graph), path)

    @staticmethod
    def load(path: Path) -> dict[str, Any]:
        """Load a previously saved graph from *path*."""
        return json.loads(path.read_text(encoding="utf-8"))
