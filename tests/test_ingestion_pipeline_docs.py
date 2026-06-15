"""Unit tests for ingestion pipeline document ingestion."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import numpy as np
import pytest

from ate_rag_kb.ingestion.pipeline import IngestionPipeline
from ate_rag_kb.utils.config import Config


class TestIngestDocument:
    @pytest.fixture
    def pipeline(self, tmp_path: Path) -> IngestionPipeline:
        cfg = Config({
            "data": {
                "markdown_dir": str(tmp_path),
                "json_dir": str(tmp_path),
                "processed_dir": str(tmp_path / "processed"),
            }
        })
        encoder = MagicMock()
        encoder.encode.return_value = np.array([[0.1, 0.2]])
        vs = MagicMock()
        return IngestionPipeline(cfg, encoder, vs)

    def test_ingest_document_no_json(self, pipeline: IngestionPipeline, tmp_path: Path) -> None:
        md = tmp_path / "v93000" / "common.md"
        md.parent.mkdir()
        md.write_text("# Hello\n\nworld")
        chunks = pipeline.ingest_document(md)
        assert len(chunks) > 0
        pipeline.vector_store.upsert_chunks.assert_called_once()

    def test_ingest_document_with_json(self, pipeline: IngestionPipeline, tmp_path: Path) -> None:
        md = tmp_path / "v93000" / "smt7" / "test.md"
        md.parent.mkdir(parents=True)
        md.write_text("# Hello")
        json_path = tmp_path / "test.json"
        json_path.write_text('{"title": "Test"}')
        chunks = pipeline.ingest_document(md, json_path)
        assert chunks[0].doc_title == "Test"

    def test_ingest_document_sets_canonical_platform_and_doc_type(
        self, pipeline: IngestionPipeline, tmp_path: Path
    ) -> None:
        md = tmp_path / "v93000" / "common.md"
        md.parent.mkdir()
        md.write_text("content")
        chunks = pipeline.ingest_document(md, platform="TDC", doc_type="guide")
        assert chunks[0].platform == "v93000"
        assert chunks[0].doc_type == "guide"

    def test_igxl_chunks_use_j750_igxl_scope(
        self, pipeline: IngestionPipeline, tmp_path: Path
    ) -> None:
        md = tmp_path / "igxl" / "vbt" / "execSites.39.08.md"
        md.parent.mkdir(parents=True)
        md.write_text("# execSites")

        chunks = pipeline._chunk_document(md)

        assert {
            (chunk.vendor, chunk.platform, chunk.software, chunk.software_release)
            for chunk in chunks
        } == {
            ("teradyne", "j750", "igxl", "")
        }
        assert {(chunk.ecosystem, chunk.software_version) for chunk in chunks} == {("igxl", "")}

    def test_smt7_chunks_use_v93000_smt7_scope(
        self, pipeline: IngestionPipeline, tmp_path: Path
    ) -> None:
        md = tmp_path / "v93000" / "smt7" / "100096.md"
        md.parent.mkdir(parents=True)
        md.write_text("# SmarTest 7")

        chunks = pipeline._chunk_document(md)

        assert {
            (chunk.vendor, chunk.platform, chunk.software, chunk.software_release)
            for chunk in chunks
        } == {
            ("advantest", "v93000", "smt7", "")
        }
        assert {(chunk.ecosystem, chunk.software_version) for chunk in chunks} == {
            ("v93000", "smt7")
        }


class TestIngestDirectory:
    def test_ingest_directory_counts_chunks(self, tmp_path: Path) -> None:
        cfg = Config({
            "data": {
                "markdown_dir": str(tmp_path),
                "json_dir": str(tmp_path),
                "processed_dir": str(tmp_path / "processed"),
            }
        })
        encoder = MagicMock()
        encoder.encode.return_value = np.array([[0.1, 0.2]])
        vs = MagicMock()
        pipeline = IngestionPipeline(cfg, encoder, vs)
        md = tmp_path / "v93000" / "common.md"
        md.parent.mkdir()
        md.write_text("content")
        total = pipeline.ingest_directory(tmp_path)
        assert total > 0

    def test_ingest_directory_skips_failed_files(self, tmp_path: Path) -> None:
        cfg = Config({
            "data": {
                "markdown_dir": str(tmp_path),
                "json_dir": str(tmp_path),
                "processed_dir": str(tmp_path / "processed"),
            }
        })
        encoder = MagicMock()
        vs = MagicMock()
        pipeline = IngestionPipeline(cfg, encoder, vs)
        md = tmp_path / "bad.md"
        md.write_text("content")
        pipeline._chunk_document = MagicMock(side_effect=Exception("fail"))  # type: ignore[method-assign]
        total = pipeline.ingest_directory(tmp_path)
        assert total == 0

    def test_ingest_directory_with_json_dir(self, tmp_path: Path) -> None:
        cfg = Config({
            "data": {
                "markdown_dir": str(tmp_path),
                "json_dir": str(tmp_path / "json"),
                "processed_dir": str(tmp_path / "processed"),
            }
        })
        encoder = MagicMock()
        encoder.encode.return_value = np.array([[0.1, 0.2]])
        vs = MagicMock()
        pipeline = IngestionPipeline(cfg, encoder, vs)
        md = tmp_path / "v93000" / "smt7" / "doc.md"
        md.parent.mkdir(parents=True)
        md.write_text("content")
        json_dir = tmp_path / "json"
        json_dir.mkdir()
        json_path = json_dir / "v93000" / "smt7" / "doc.json"
        json_path.parent.mkdir(parents=True)
        json_path.write_text('{"title": "Doc"}')
        total = pipeline.ingest_directory(tmp_path, json_dir)
        assert total > 0

    def test_ingest_directory_builds_symbol_catalog(self, tmp_path: Path) -> None:
        cfg = Config({
            "data": {
                "markdown_dir": str(tmp_path),
                "json_dir": str(tmp_path),
                "processed_dir": str(tmp_path / "processed"),
            }
        })
        encoder = MagicMock()
        encoder.encode.return_value = np.array([[0.1, 0.2]])
        vs = MagicMock()
        pipeline = IngestionPipeline(cfg, encoder, vs)
        md = tmp_path / "igxl" / "vbt" / "execSites.39.08.md"
        md.parent.mkdir(parents=True)
        md.write_text("# SelectFirst Method")

        pipeline.ingest_directory(tmp_path)

        payload = json.loads((tmp_path / "processed" / "symbol_catalog.json").read_text())
        assert payload["owners"]["selectfirst"]["platform"] == "j750"

    def test_force_rebuild_sparse_vocab_refits_existing_encoder(self, tmp_path: Path) -> None:
        cfg = Config({"data": {"processed_dir": str(tmp_path / "processed")}})
        pipeline = IngestionPipeline(cfg, MagicMock(), MagicMock())
        pipeline.vector_store.sparse_encoder.is_fitted.return_value = True
        (tmp_path / "doc.md").write_text("Site Control")

        pipeline._ensure_sparse_vocab(tmp_path, force=True)

        pipeline.vector_store.sparse_encoder.fit.assert_called_once_with(["Site Control"])

    def test_rebuild_sparse_vocabulary_forces_refit(self, tmp_path: Path) -> None:
        cfg = Config({"data": {"processed_dir": str(tmp_path / "processed")}})
        pipeline = IngestionPipeline(cfg, MagicMock(), MagicMock())
        pipeline.vector_store.sparse_encoder.is_fitted.return_value = True
        (tmp_path / "doc.md").write_text("Site Control")

        pipeline.rebuild_sparse_vocabulary(tmp_path)

        pipeline.vector_store.sparse_encoder.fit.assert_called_once_with(["Site Control"])
