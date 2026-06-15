"""CLI ingestion regression tests."""

from __future__ import annotations

import argparse
from unittest.mock import MagicMock, patch

import pytest

from ate_rag_kb.cli.main import _cmd_ingest
from ate_rag_kb.utils.config import Config


@pytest.mark.asyncio
async def test_incremental_ingest_opens_store_in_rebuild_mode(tmp_path) -> None:
    markdown_dir = tmp_path / "markdown"
    markdown_dir.mkdir()
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    config = Config(
        {
            "data": {
                "raw_dir": str(raw_dir),
                "processed_dir": str(tmp_path / "processed"),
            }
        }
    )
    vector_store = MagicMock()
    pipeline = MagicMock(vector_store=vector_store)
    incremental = MagicMock()
    incremental.needs_full_rebuild.return_value = False
    incremental.run_incremental.return_value = {}

    with (
        patch("ate_rag_kb.cli.main.get_config", return_value=config),
        patch("ate_rag_kb.cli.main.setup_logging"),
        patch("ate_rag_kb.embedding.encoder.EmbeddingEncoder") as encoder_cls,
        patch(
            "ate_rag_kb.vector_store.qdrant_client.QdrantVectorStore",
            return_value=vector_store,
        ) as store_cls,
        patch(
            "ate_rag_kb.ingestion.pipeline.IngestionPipeline",
            return_value=pipeline,
        ),
        patch(
            "ate_rag_kb.ingestion.incremental.IncrementalIngestion",
            return_value=incremental,
        ),
        patch(
            "ate_rag_kb.ingestion.incremental._get_state_file",
            return_value=tmp_path / "state.json",
        ),
    ):
        encoder_cls.return_value.vector_size = 1024
        result = await _cmd_ingest(
            argparse.Namespace(dir=str(markdown_dir), incremental=True)
        )

    assert result == 0
    store_cls.assert_called_once_with(config, allow_incompatible_schema=True)


@pytest.mark.asyncio
async def test_full_ingest_clears_store_and_rebuilds_sparse_vocab(tmp_path) -> None:
    markdown_dir = tmp_path / "markdown"
    markdown_dir.mkdir()
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    config = Config(
        {
            "data": {
                "raw_dir": str(raw_dir),
                "processed_dir": str(tmp_path / "processed"),
            }
        }
    )
    vector_store = MagicMock()
    pipeline = MagicMock(vector_store=vector_store)
    pipeline.ingest_directory.return_value = 3
    incremental = MagicMock()

    with (
        patch("ate_rag_kb.cli.main.get_config", return_value=config),
        patch("ate_rag_kb.cli.main.setup_logging"),
        patch("ate_rag_kb.embedding.encoder.EmbeddingEncoder") as encoder_cls,
        patch(
            "ate_rag_kb.vector_store.qdrant_client.QdrantVectorStore",
            return_value=vector_store,
        ) as store_cls,
        patch(
            "ate_rag_kb.ingestion.pipeline.IngestionPipeline",
            return_value=pipeline,
        ),
        patch(
            "ate_rag_kb.ingestion.incremental.IncrementalIngestion",
            return_value=incremental,
        ),
        patch(
            "ate_rag_kb.ingestion.incremental._get_state_file",
            return_value=tmp_path / "state.json",
        ),
    ):
        encoder_cls.return_value.vector_size = 1024
        result = await _cmd_ingest(
            argparse.Namespace(dir=str(markdown_dir), incremental=False)
        )

    assert result == 0
    store_cls.assert_called_once_with(config, allow_incompatible_schema=True)
    vector_store.clear_collection.assert_called_once_with()
    pipeline.rebuild_sparse_vocabulary.assert_called_once_with(markdown_dir)
    pipeline.ingest_directory.assert_called_once_with(markdown_dir, json_dir=None)
    incremental.mark_all_files_current.assert_called_once_with(markdown_dir)
