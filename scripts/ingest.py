#!/usr/bin/env python3
"""Convenience script to run document ingestion.

NOTE: This script always performs a FULL ingest and bypasses incremental
state tracking. For incremental ingestion (only new/changed files), use:
    uv run -m ate_rag_kb.cli.main ingest --dir <dir> --incremental
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from pathlib import Path

# Ensure src is on PYTHONPATH
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ate_rag_kb.embedding.encoder import EmbeddingEncoder
from ate_rag_kb.ingestion.pipeline import IngestionPipeline
from ate_rag_kb.utils.config import get_config
from ate_rag_kb.utils.logging import setup_logging
from ate_rag_kb.vector_store.qdrant_client import QdrantVectorStore

logger = logging.getLogger(__name__)


def _load_json_if_exists(path: Path) -> dict | None:
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return None


async def main() -> int:
    config = get_config(Path(__file__).resolve().parents[1] / "configs" / "config.yaml")
    setup_logging(config.get("logging.level", "INFO"), config.get("logging.format", "json"))

    raw_dir = Path(config.get("data.raw_dir", "./data/raw"))
    markdown_dir = raw_dir / "markdown"
    json_dir = raw_dir / "json" if (raw_dir / "json").exists() else None

    toc_tree = _load_json_if_exists(raw_dir / "toc_tree.json")
    href_map = _load_json_if_exists(raw_dir / "href_map.json")

    encoder = EmbeddingEncoder(config)
    vector_store = QdrantVectorStore(config)
    pipeline = IngestionPipeline(
        config, encoder, vector_store,
        toc_tree=toc_tree,
        href_map=href_map,
    )

    total = pipeline.ingest_directory(markdown_dir, json_dir=json_dir)
    logger.info("Ingestion complete: %d chunks", total)
    return 0


if __name__ == "__main__":
    try:
        code = asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Interrupted")
        code = 130
    sys.exit(code)
