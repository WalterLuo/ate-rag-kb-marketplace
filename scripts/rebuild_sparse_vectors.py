"""Rebuild sparse vectors for all points in a Qdrant collection.

Reads every point's content, re-encodes with the current SparseVectorEncoder,
and updates the sparse vector in-place.  Does NOT re-chunk or re-embed.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

# Allow running from project root without installing the package
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from qdrant_client.models import PointVectors, SparseVector

from ate_rag_kb.utils.config import get_config
from ate_rag_kb.vector_store.qdrant_client import QdrantVectorStore

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


def main() -> int:
    config = get_config()
    store = QdrantVectorStore(config)
    encoder = store.sparse_encoder

    if not encoder.is_fitted():
        logger.error("Sparse encoder is not fitted. Run full ingestion first.")
        return 1

    collection = store.collection_name
    client = store.client
    total = client.count(collection_name=collection).count
    logger.info("Collection %s has %d points. Rebuilding sparse vectors...", collection, total)

    offset: str | None = None
    processed = 0
    batch_size = 500

    while True:
        results, offset = client.scroll(
            collection_name=collection,
            limit=batch_size,
            offset=offset,
            with_payload=["content"],
            with_vectors=["sparse"],
        )
        if not results:
            break

        updates: list[PointVectors] = []
        for point in results:
            content = (point.payload or {}).get("content", "")
            indices, values = encoder.encode(content)
            if not indices:
                continue
            updates.append(
                PointVectors(
                    id=point.id,
                    vector={"sparse": SparseVector(indices=indices, values=values)},
                )
            )

        if updates:
            client.update_vectors(collection_name=collection, points=updates)

        processed += len(results)
        logger.info("Processed %d / %d points (updated %d vectors)", processed, total, len(updates))

        if offset is None:
            break

    logger.info("Sparse vector rebuild complete. %d points processed.", processed)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
