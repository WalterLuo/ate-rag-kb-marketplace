#!/usr/bin/env python3
"""Convenience script to start the FastAPI server with uvicorn."""

from __future__ import annotations

import logging
import sys
from pathlib import Path

# Ensure src is on PYTHONPATH
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import uvicorn

from ate_rag_kb.utils.config import get_config
from ate_rag_kb.utils.logging import setup_logging

logger = logging.getLogger(__name__)


def main() -> int:
    config = get_config(Path(__file__).resolve().parents[1] / "configs" / "config.yaml")
    setup_logging(config.get("logging.level", "INFO"), config.get("logging.format", "json"))

    host = config.get("api.host", "0.0.0.0")
    port = config.get("api.port", 8080)
    reload = config.get("api.reload", False)
    workers = config.get("api.workers", 1)

    logger.info("Starting uvicorn on %s:%s (workers=%s, reload=%s)", host, port, workers, reload)
    uvicorn.run(
        "ate_rag_kb.api:create_app",
        host=host,
        port=port,
        factory=True,
        reload=reload,
        workers=workers,
    )
    return 0


if __name__ == "__main__":
    try:
        code = main()
    except KeyboardInterrupt:
        logger.info("Interrupted")
        code = 130
    sys.exit(code)
