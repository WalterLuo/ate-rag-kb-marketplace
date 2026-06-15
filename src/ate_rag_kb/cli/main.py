"""Command-line interface for ATE RAG Knowledge Base."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
from pathlib import Path

from ate_rag_kb.utils.config import get_config
from ate_rag_kb.utils.logging import setup_logging

logger = logging.getLogger(__name__)


def _config_path() -> Path:
    env_path = os.environ.get("CONFIG_PATH")
    if env_path:
        path = Path(env_path)
        if not path.exists():
            raise FileNotFoundError(
                f"CONFIG_PATH is set to '{env_path}' but the file does not exist. "
                "Please verify the path or unset CONFIG_PATH to use the default."
            )
        return path

    default = Path(__file__).resolve().parents[3] / "configs" / "config.yaml"
    if not default.exists():
        raise FileNotFoundError(
            f"Default config not found at {default}. "
            "Please run from the project root or set CONFIG_PATH."
        )
    return default


def _load_json_if_exists(path: Path) -> dict | None:
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return None


async def _cmd_ingest(args: argparse.Namespace) -> int:
    config = get_config(_config_path())
    setup_logging(config.get("logging.level", "INFO"), config.get("logging.format", "json"))

    try:
        from ate_rag_kb.embedding.encoder import EmbeddingEncoder
        from ate_rag_kb.ingestion.pipeline import IngestionPipeline
        from ate_rag_kb.vector_store.qdrant_client import QdrantVectorStore
    except Exception as exc:
        logger.error("Ingestion pipeline not available: %s", exc)
        return 1

    raw_dir = Path(config.get("data.raw_dir", "./data/raw"))
    markdown_dir = Path(args.dir)
    json_dir = raw_dir / "json" if (raw_dir / "json").exists() else None

    toc_tree = _load_json_if_exists(raw_dir / "toc_tree.json")
    href_map = _load_json_if_exists(raw_dir / "href_map.json")

    ingest_device = config.get("embedding.ingest_device", "cpu")
    encoder = EmbeddingEncoder(config, device=ingest_device)
    # Preload model to fail fast on loading errors
    _ = encoder.vector_size
    logger.info("Embedding model ready: %s on %s", encoder.model_name, encoder.device)

    vector_store = QdrantVectorStore(
        config,
        allow_incompatible_schema=True,
    )
    pipeline = IngestionPipeline(
        config, encoder, vector_store,
        toc_tree=toc_tree,
        href_map=href_map,
    )

    if args.incremental:
        from ate_rag_kb.ingestion.incremental import IncrementalIngestion, _get_state_file

        state_file = _get_state_file(config)
        incremental = IncrementalIngestion(pipeline, state_file=state_file)

        if not vector_store.schema_compatible or incremental.needs_full_rebuild():
            logger.warning(
                "Profile mismatch or first run detected. Clearing collection and performing full re-ingest."
            )
            pipeline.vector_store.clear_collection()
            if incremental.state_file.exists():
                incremental.state_file.unlink()
            pipeline.rebuild_sparse_vocabulary(markdown_dir)

        stats = incremental.run_incremental(markdown_dir, json_dir=json_dir)
        logger.info("Incremental ingestion: %s", stats)
    else:
        from ate_rag_kb.ingestion.incremental import IncrementalIngestion, _get_state_file

        pipeline.vector_store.clear_collection()
        pipeline.rebuild_sparse_vocabulary(markdown_dir)
        total = pipeline.ingest_directory(markdown_dir, json_dir=json_dir)
        IncrementalIngestion(
            pipeline,
            state_file=_get_state_file(config),
        ).mark_all_files_current(markdown_dir)
        logger.info("Ingested %d chunks", total)
    return 0


async def _cmd_search(args: argparse.Namespace) -> int:
    config = get_config(_config_path())
    setup_logging(config.get("logging.level", "INFO"), config.get("logging.format", "json"))

    try:
        from ate_rag_kb.retrieval.pipeline import RetrievalPipeline
    except Exception as exc:
        logger.error("Retrieval pipeline not available: %s", exc)
        return 1

    retriever = RetrievalPipeline(config)
    results = await retriever.search(query=args.query, top_k=args.top_k)

    output = []
    for chunk, score in results:
        output.append(
            {
                "id": chunk.id,
                "score": round(score, 4),
                "source": chunk.source_md,
                "content": chunk.content[:300],
            }
        )
    print(json.dumps(output, indent=2, ensure_ascii=False))
    return 0


async def _cmd_serve(args: argparse.Namespace) -> int:
    import uvicorn

    config = get_config(_config_path())
    setup_logging(config.get("logging.level", "INFO"), config.get("logging.format", "json"))

    host = args.host or config.get("api.host", "0.0.0.0")
    port = args.port or config.get("api.port", 8080)

    logger.info("Starting server on %s:%s", host, port)
    uvicorn.run(
        "ate_rag_kb.api:create_app",
        host=host,
        port=port,
        factory=True,
        reload=config.get("api.reload", False),
        workers=config.get("api.workers", 1),
    )
    return 0


async def _cmd_status(_args: argparse.Namespace) -> int:
    config = get_config(_config_path())
    setup_logging(config.get("logging.level", "INFO"), config.get("logging.format", "json"))

    try:
        from ate_rag_kb.retrieval.pipeline import RetrievalPipeline
    except Exception as exc:
        logger.error("Retrieval pipeline not available: %s", exc)
        return 1

    retriever = RetrievalPipeline(config)
    stats = await retriever.collection_stats()
    print(json.dumps(stats, indent=2, ensure_ascii=False))
    return 0


async def _cmd_mcp(_args: argparse.Namespace) -> int:
    config = get_config(_config_path())
    setup_logging(config.get("logging.level", "INFO"), config.get("logging.format", "json"))

    try:
        from ate_rag_kb.mcp.server import run_mcp_server
    except ImportError as exc:
        logger.error("MCP server not available: %s", exc)
        return 1

    logger.info("Starting MCP server (stdio transport)")
    await run_mcp_server(config)
    return 0


async def _async_main() -> int:
    parser = argparse.ArgumentParser(
        prog="ate-rag-kb",
        description="ATE RAG Knowledge Base CLI",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # ingest
    ingest_parser = subparsers.add_parser("ingest", help="Run document ingestion")
    ingest_parser.add_argument("--dir", required=True, help="Directory to ingest")
    ingest_parser.add_argument(
        "--incremental",
        action="store_true",
        help="Only ingest new or changed files",
    )
    ingest_parser.set_defaults(func=_cmd_ingest)

    # search
    search_parser = subparsers.add_parser("search", help="Search the knowledge base")
    search_parser.add_argument("query", help="Search query string")
    search_parser.add_argument("--top-k", type=int, default=10, help="Number of results")
    search_parser.set_defaults(func=_cmd_search)

    # serve
    serve_parser = subparsers.add_parser("serve", help="Start the API server")
    serve_parser.add_argument("--host", default=None, help="Bind host")
    serve_parser.add_argument("--port", type=int, default=None, help="Bind port")
    serve_parser.set_defaults(func=_cmd_serve)

    # status
    status_parser = subparsers.add_parser("status", help="Show collection statistics")
    status_parser.set_defaults(func=_cmd_status)

    # mcp
    mcp_parser = subparsers.add_parser("mcp", help="Start MCP server (stdio transport)")
    mcp_parser.set_defaults(func=_cmd_mcp)

    args = parser.parse_args()
    return await args.func(args)


def main() -> None:
    """Synchronous entry point."""
    try:
        exit_code = asyncio.run(_async_main())
    except KeyboardInterrupt:
        logger.info("Interrupted")
        exit_code = 130
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
