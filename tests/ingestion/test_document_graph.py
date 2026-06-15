"""Tests for document graph link parsing and graph building."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ate_rag_kb.ingestion.document_graph import DocumentGraphBuilder, MarkdownLinkParser


class TestMarkdownLinkParser:
    def test_extracts_internal_htm_links(self) -> None:
        text = (
            "1. [The states of the sites](100096.htm \"tooltip\")\n"
            "2. [Expanded Site Control](100119.htm)\n"
            "3. [External link](https://example.com)\n"
            "4. ![image](assets/img.png)\n"
            '5. <a href="100324.htm">Allow parallel</a>\n'
        )
        links = MarkdownLinkParser.extract_links(text)
        assert sorted(links) == ["100096.htm", "100119.htm", "100324.htm"]

    def test_ignores_images(self) -> None:
        text = "![diagram](images/fig1.png) and [real link](20264.htm)"
        links = MarkdownLinkParser.extract_links(text)
        assert links == ["20264.htm"]

    def test_ignores_external_urls(self) -> None:
        text = (
            "[ext1](https://example.com/page.htm) "
            "[ext2](http://internal.org/doc.html) "
            "[local](21615.htm)"
        )
        links = MarkdownLinkParser.extract_links(text)
        assert links == ["21615.htm"]

    def test_ignores_assets_paths(self) -> None:
        text = (
            "[asset](../assets/file.pdf) "
            "[asset2](assets/image.gif) "
            "[valid](42588.htm)"
        )
        links = MarkdownLinkParser.extract_links(text)
        assert links == ["42588.htm"]

    def test_extracts_html_extension(self) -> None:
        text = "[Page](concept.html) and [Other](ref.htm)"
        links = MarkdownLinkParser.extract_links(text)
        assert sorted(links) == ["concept.html", "ref.htm"]

    def test_no_duplicates(self) -> None:
        text = "[A](100118.htm) [B](100118.htm)"
        links = MarkdownLinkParser.extract_links(text)
        assert links == ["100118.htm"]

    def test_empty_text(self) -> None:
        assert MarkdownLinkParser.extract_links("") == []

    def test_extracts_internal_md_links(self) -> None:
        text = (
            "[SelectNext](execSites.39.09.md)\n"
            "[InSerialLoop](execSites.39.05.md)\n"
        )
        links = MarkdownLinkParser.extract_links(text)
        assert sorted(links) == ["execSites.39.05.md", "execSites.39.09.md"]

    def test_extracts_mixed_htm_and_md_links(self) -> None:
        text = (
            "[A](100118.htm)\n"
            "[B](execSites.39.09.md)\n"
            "[C](ref.html)\n"
        )
        links = MarkdownLinkParser.extract_links(text)
        assert sorted(links) == ["100118.htm", "execSites.39.09.md", "ref.html"]

    def test_ignores_external_md_urls(self) -> None:
        text = (
            "[ext](https://example.com/doc.md) "
            "[local](igxl/vbt/execSites.39.09.md)"
        )
        links = MarkdownLinkParser.extract_links(text)
        assert links == ["igxl/vbt/execSites.39.09.md"]

    def test_ignores_md_images(self) -> None:
        text = "![diagram](images/fig1.md) and [real link](content.md)"
        links = MarkdownLinkParser.extract_links(text)
        assert links == ["content.md"]

    def test_extracts_md_links_with_fragment_or_query(self) -> None:
        text = (
            "[Fragment](execSites.39.09.md#selectnext) "
            "[Query](execSites.39.10.md?view=full)"
        )
        links = MarkdownLinkParser.extract_links(text)
        assert links == ["execSites.39.09.md", "execSites.39.10.md"]

    def test_extracts_raw_html_md_links(self) -> None:
        text = '<a href="execSites.39.09.md">SelectNext</a>'
        links = MarkdownLinkParser.extract_links(text)
        assert links == ["execSites.39.09.md"]

class TestDocumentGraphBuilder:
    @pytest.fixture
    def temp_dirs(self, tmp_path: Path) -> tuple[Path, Path]:
        markdown_dir = tmp_path / "markdown"
        json_dir = tmp_path / "json"
        markdown_dir.mkdir()
        json_dir.mkdir()
        return markdown_dir, json_dir

    def _write_doc(
        self,
        markdown_dir: Path,
        json_dir: Path,
        rel_path: str,
        md_content: str,
        source_html: str,
    ) -> None:
        md_path = markdown_dir / rel_path
        md_path.parent.mkdir(parents=True, exist_ok=True)
        md_path.write_text(md_content, encoding="utf-8")

        json_path = json_dir / rel_path.replace(".md", ".json")
        json_path.parent.mkdir(parents=True, exist_ok=True)
        meta = {
            "title": rel_path,
            "source_html": source_html,
            "markdown_path": f"markdown/{rel_path}",
            "content": md_content,
        }
        json_path.write_text(json.dumps(meta), encoding="utf-8")

    def test_builds_forward_links(self, temp_dirs: tuple[Path, Path]) -> None:
        md_dir, json_dir = temp_dirs
        self._write_doc(md_dir, json_dir, "v93000/smt7/100118.md", "# A\n[Link](100096.htm)", "100118.htm")
        self._write_doc(md_dir, json_dir, "v93000/smt7/100096.md", "# B\nContent", "100096.htm")

        builder = DocumentGraphBuilder(markdown_dir=md_dir, json_dir=json_dir)
        graph = builder.build()

        assert graph["v93000/smt7/100118.md"]["linked_source_mds"] == ["v93000/smt7/100096.md"]
        assert graph["v93000/smt7/100096.md"]["linked_source_mds"] == []

    def test_builds_back_references(self, temp_dirs: tuple[Path, Path]) -> None:
        md_dir, json_dir = temp_dirs
        self._write_doc(md_dir, json_dir, "a.md", "[To B](b.htm)", "a.htm")
        self._write_doc(md_dir, json_dir, "b.md", "Content", "b.htm")

        builder = DocumentGraphBuilder(markdown_dir=md_dir, json_dir=json_dir)
        graph = builder.build()

        assert graph["b.md"]["referenced_by_source_mds"] == ["a.md"]

    def test_canonical_for_variant(self, temp_dirs: tuple[Path, Path]) -> None:
        md_dir, json_dir = temp_dirs
        self._write_doc(md_dir, json_dir, "v93000/smt7/21615.md", "# Main", "21615.htm")
        self._write_doc(md_dir, json_dir, "v93000/smt7/21615_2.md", "# Variant", "21615_2.htm")

        builder = DocumentGraphBuilder(markdown_dir=md_dir, json_dir=json_dir)
        graph = builder.build()

        assert graph["v93000/smt7/21615.md"]["canonical_source_md"] == "v93000/smt7/21615.md"
        assert graph["v93000/smt7/21615_2.md"]["canonical_source_md"] == "v93000/smt7/21615.md"

    def test_content_hash_unique(self, temp_dirs: tuple[Path, Path]) -> None:
        md_dir, json_dir = temp_dirs
        self._write_doc(md_dir, json_dir, "a.md", "Hello", "a.htm")
        self._write_doc(md_dir, json_dir, "b.md", "World", "b.htm")

        builder = DocumentGraphBuilder(markdown_dir=md_dir, json_dir=json_dir)
        graph = builder.build()

        assert graph["a.md"]["content_hash"] != graph["b.md"]["content_hash"]

    def test_missing_target_href_ignored(self, temp_dirs: tuple[Path, Path]) -> None:
        md_dir, json_dir = temp_dirs
        self._write_doc(md_dir, json_dir, "a.md", "[Missing](999999.htm)", "a.htm")

        builder = DocumentGraphBuilder(markdown_dir=md_dir, json_dir=json_dir)
        graph = builder.build()

        assert graph["a.md"]["linked_source_mds"] == []

    def test_builds_forward_md_links(self, temp_dirs: tuple[Path, Path]) -> None:
        md_dir, json_dir = temp_dirs
        self._write_doc(
            md_dir, json_dir, "igxl/vbt/execSites.39.08.md",
            "# SelectFirst\n[SelectNext](execSites.39.09.md)",
            "execSites.39.08.htm",
        )
        self._write_doc(
            md_dir, json_dir, "igxl/vbt/execSites.39.09.md",
            "# SelectNext\nContent",
            "execSites.39.09.htm",
        )

        builder = DocumentGraphBuilder(markdown_dir=md_dir, json_dir=json_dir)
        graph = builder.build()

        assert graph["igxl/vbt/execSites.39.08.md"]["linked_source_mds"] == [
            "igxl/vbt/execSites.39.09.md"
        ]
        assert graph["igxl/vbt/execSites.39.09.md"]["linked_source_mds"] == []

    def test_builds_md_back_references(self, temp_dirs: tuple[Path, Path]) -> None:
        md_dir, json_dir = temp_dirs
        self._write_doc(
            md_dir, json_dir, "igxl/vbt/a.md",
            "[To B](b.md)",
            "a.htm",
        )
        self._write_doc(
            md_dir, json_dir, "igxl/vbt/b.md",
            "Content",
            "b.htm",
        )

        builder = DocumentGraphBuilder(markdown_dir=md_dir, json_dir=json_dir)
        graph = builder.build()

        assert graph["igxl/vbt/b.md"]["referenced_by_source_mds"] == ["igxl/vbt/a.md"]

    def test_md_relative_path_resolution(self, temp_dirs: tuple[Path, Path]) -> None:
        md_dir, json_dir = temp_dirs
        self._write_doc(
            md_dir, json_dir, "igxl/vbt/execSites.39.08.md",
            "# A\n[Up](../overview.md)",
            "execSites.39.08.htm",
        )
        self._write_doc(
            md_dir, json_dir, "igxl/overview.md",
            "# Overview",
            "overview.htm",
        )

        builder = DocumentGraphBuilder(markdown_dir=md_dir, json_dir=json_dir)
        graph = builder.build()

        assert graph["igxl/vbt/execSites.39.08.md"]["linked_source_mds"] == ["igxl/overview.md"]

    def test_md_missing_target_ignored(self, temp_dirs: tuple[Path, Path]) -> None:
        md_dir, json_dir = temp_dirs
        self._write_doc(
            md_dir, json_dir, "igxl/vbt/a.md",
            "[Missing](nonexistent.md)",
            "a.htm",
        )

        builder = DocumentGraphBuilder(markdown_dir=md_dir, json_dir=json_dir)
        graph = builder.build()

        assert graph["igxl/vbt/a.md"]["linked_source_mds"] == []

    def test_save_and_load(self, temp_dirs: tuple[Path, Path]) -> None:
        md_dir, json_dir = temp_dirs
        self._write_doc(md_dir, json_dir, "a.md", "[To B](b.htm)", "a.htm")
        self._write_doc(md_dir, json_dir, "b.md", "Content", "b.htm")

        builder = DocumentGraphBuilder(markdown_dir=md_dir, json_dir=json_dir)
        graph = builder.build()
        output_path = md_dir.parent / "document_graph.json"
        builder.save(output_path)

        loaded = DocumentGraphBuilder.load(output_path)
        assert loaded == graph
