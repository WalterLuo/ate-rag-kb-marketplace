"""Tests for automatic broad-concept context assembly."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

from ate_rag_kb.chunking.models import Chunk, ChunkType
from ate_rag_kb.retrieval.broad_context import BroadConceptAssembler
from ate_rag_kb.retrieval.document_graph_expander import DocumentGraphExpander
from ate_rag_kb.utils.config import Config


def _chunk(
    chunk_id: str,
    content: str,
    *,
    source_md: str,
    chunk_type: ChunkType = ChunkType.SECTION,
    doc_title: str = "",
    section_title: str = "",
) -> Chunk:
    return Chunk(
        id=chunk_id,
        content=content,
        chunk_type=chunk_type,
        source_md=source_md,
        doc_title=doc_title,
        section_title=section_title,
    )


def _store(chunks_by_source: dict[str, list[Chunk]]) -> MagicMock:
    store = MagicMock()

    def scroll(*, filters, limit):
        chunks = chunks_by_source.get(filters["source_md"], [])
        chunk_type = filters.get("chunk_type")
        if chunk_type:
            chunks = [chunk for chunk in chunks if chunk.chunk_type.value == chunk_type]
        return chunks[:limit], None

    store.scroll.side_effect = scroll
    return store


def test_broad_context_follows_forward_links_and_filters_low_utility(tmp_path: Path) -> None:
    graph = {
        "concept.md": {
            "linked_source_mds": ["states.md", "expanded.md"],
            "referenced_by_source_mds": [],
            "canonical_source_md": "concept.md",
            "content_hash": "concept",
        },
        "states.md": {
            "linked_source_mds": [],
            "referenced_by_source_mds": ["concept.md"],
            "canonical_source_md": "states.md",
            "content_hash": "states",
        },
        "expanded.md": {
            "linked_source_mds": [],
            "referenced_by_source_mds": ["concept.md"],
            "canonical_source_md": "expanded.md",
            "content_hash": "expanded",
        },
    }
    graph_path = tmp_path / "document_graph.json"
    graph_path.write_text(json.dumps(graph), encoding="utf-8")

    concept = _chunk(
        "concept-doc",
        "Site Control Window configures states and links to its subtopics.",
        source_md="concept.md",
        chunk_type=ChunkType.DOCUMENT,
        doc_title="Site Control Window",
    )
    states = _chunk(
        "states-doc",
        "Enable connects a site. Active executes the testflow. Focus selects displayed results.",
        source_md="states.md",
        chunk_type=ChunkType.DOCUMENT,
        doc_title="The states of the sites",
    )
    expanded = _chunk(
        "expanded-doc",
        "Parallel, Serial and Semi-Parallel execution use Size and Cycle settings.",
        source_md="expanded.md",
        chunk_type=ChunkType.DOCUMENT,
        doc_title="Expanded Site Control window",
    )
    image = _chunk(
        "image",
        "Image: Site Control window (site-control.png)",
        source_md="concept.md",
        chunk_type=ChunkType.IMAGE,
        section_title="Site Control Window",
    )
    functional_changes = _chunk(
        "changes",
        "Functional changes\n\nIntroduced in version 7.2.0",
        source_md="concept.md",
        section_title="Functional changes",
    )
    store = _store(
        {
            "concept.md": [concept],
            "states.md": [states],
            "expanded.md": [expanded],
        }
    )
    assembler = BroadConceptAssembler(
        Config({"retrieval": {"broad_context": {"max_tokens": 1000}}}),
        DocumentGraphExpander(graph_path=graph_path),
    )

    result, stats = assembler.assemble([concept, image, functional_changes], store)

    ids = {chunk.id for chunk in result}
    assert {"concept-doc", "states-doc", "expanded-doc"} <= ids
    assert "image" not in ids
    assert "changes" not in ids
    assert stats["broad_context_assembled"] is True
    assert stats["broad_context_discovered_source_count"] == 3
    assert stats["broad_context_added_chunk_count"] == 2
    assert stats["low_utility_chunk_count"] == 2


def test_broad_context_keeps_scope_filter_for_linked_sources(tmp_path: Path) -> None:
    graph = {
        "igxl/concept.md": {
            "linked_source_mds": ["v93000/smt7/site-control.md"],
            "referenced_by_source_mds": [],
            "canonical_source_md": "igxl/concept.md",
            "content_hash": "igxl",
        },
        "v93000/smt7/site-control.md": {
            "linked_source_mds": [],
            "referenced_by_source_mds": ["igxl/concept.md"],
            "canonical_source_md": "v93000/smt7/site-control.md",
            "content_hash": "smt7",
        },
    }
    graph_path = tmp_path / "document_graph.json"
    graph_path.write_text(json.dumps(graph), encoding="utf-8")
    igxl = _chunk(
        "igxl",
        "IG-XL serial site loop uses SelectFirst and SelectNext.",
        source_md="igxl/concept.md",
        doc_title="IG-XL Serial Site Loop",
    )
    igxl.vendor = "teradyne"
    igxl.platform = "j750"
    igxl.software = "igxl"
    smt7 = _chunk(
        "smt7",
        "SMT7 Site Control is not part of IG-XL.",
        source_md="v93000/smt7/site-control.md",
        doc_title="Site Control",
    )
    smt7.vendor = "advantest"
    smt7.platform = "v93000"
    smt7.software = "smt7"
    store = MagicMock()

    def scroll(*, filters, limit):
        if filters.get("vendor") == "teradyne":
            return [], None
        return [smt7][:limit], None

    store.scroll.side_effect = scroll
    assembler = BroadConceptAssembler(
        Config({"retrieval": {"broad_context": {"max_tokens": 1000}}}),
        DocumentGraphExpander(graph_path=graph_path),
    )

    result, _stats = assembler.assemble(
        [igxl],
        store,
        query="IG-XL 多 site 串行处理",
        filters={"vendor": "teradyne", "platform": "j750", "software": "igxl"},
    )

    assert {chunk.software for chunk in result} == {"igxl"}


def test_broad_context_uses_sections_when_document_is_too_large(tmp_path: Path) -> None:
    graph_path = tmp_path / "document_graph.json"
    graph_path.write_text(
        json.dumps(
            {
                "large.md": {
                    "linked_source_mds": [],
                    "referenced_by_source_mds": [],
                    "canonical_source_md": "large.md",
                    "content_hash": "large",
                }
            }
        ),
        encoding="utf-8",
    )
    large_document = _chunk(
        "large-doc",
        "x" * 1000,
        source_md="large.md",
        chunk_type=ChunkType.DOCUMENT,
        doc_title="Large Reference",
    )
    useful_section = _chunk(
        "section",
        "This section contains the bounded details needed for the answer.",
        source_md="large.md",
        section_title="Configuration",
    )
    assembler = BroadConceptAssembler(
        Config(
            {
                "retrieval": {
                    "broad_context": {
                        "document_max_chars": 100,
                        "max_tokens": 1000,
                    }
                }
            }
        ),
        DocumentGraphExpander(graph_path=graph_path),
    )

    result, _ = assembler.assemble(
        [useful_section],
        _store({"large.md": [large_document, useful_section]}),
    )

    ids = {chunk.id for chunk in result}
    assert "section" in ids
    assert "large-doc" not in ids


def test_broad_context_prioritizes_hub_subtopics_over_title_similar_noise(
    tmp_path: Path,
) -> None:
    graph_path = tmp_path / "document_graph.json"
    graph_path.write_text(
        json.dumps(
            {
                "hub.md": {
                    "linked_source_mds": ["states.md", "expanded.md"],
                    "referenced_by_source_mds": [],
                    "canonical_source_md": "hub.md",
                    "content_hash": "hub",
                },
                "states.md": {
                    "linked_source_mds": [],
                    "referenced_by_source_mds": ["hub.md"],
                    "canonical_source_md": "states.md",
                    "content_hash": "states",
                },
                "expanded.md": {
                    "linked_source_mds": [],
                    "referenced_by_source_mds": ["hub.md"],
                    "canonical_source_md": "expanded.md",
                    "content_hash": "expanded",
                },
                "annotations.md": {
                    "linked_source_mds": [],
                    "referenced_by_source_mds": [],
                    "canonical_source_md": "annotations.md",
                    "content_hash": "annotations",
                },
            }
        ),
        encoding="utf-8",
    )
    hub = _chunk(
        "hub",
        "Site Control Window links to the main operational subtopics.",
        source_md="hub.md",
        chunk_type=ChunkType.DOCUMENT,
        doc_title="Site Control Window",
    )
    states = _chunk(
        "states",
        "Enable, Active and Focus define the operational states.",
        source_md="states.md",
        chunk_type=ChunkType.DOCUMENT,
        doc_title="The states of the sites",
    )
    expanded = _chunk(
        "expanded",
        "Parallel, Serial and Semi-Parallel use Size and Cycle.",
        source_md="expanded.md",
        chunk_type=ChunkType.DOCUMENT,
        doc_title="Expanded Site Control window",
    )
    annotations = _chunk(
        "annotations",
        "Site Control Annotation preferences. " + "annotation " * 80,
        source_md="annotations.md",
        chunk_type=ChunkType.DOCUMENT,
        doc_title="Site Control Annotation preferences",
    )
    assembler = BroadConceptAssembler(
        Config({"retrieval": {"broad_context": {"max_tokens": 100}}}),
        DocumentGraphExpander(graph_path=graph_path),
    )

    result, _ = assembler.assemble(
        [annotations, hub],
        _store(
            {
                "hub.md": [hub],
                "states.md": [states],
                "expanded.md": [expanded],
                "annotations.md": [annotations],
            }
        ),
        query="SMT7中site control的作用是什么",
    )

    ids = {chunk.id for chunk in result}
    assert {"hub", "states", "expanded"} <= ids
    assert "annotations" not in ids
