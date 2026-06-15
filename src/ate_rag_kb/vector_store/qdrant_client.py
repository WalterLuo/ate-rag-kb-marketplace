"""Qdrant vector store client wrapper."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

# Prevent httpx from routing localhost traffic through a system proxy.
_no_proxy = os.environ.get("NO_PROXY", "")
os.environ["NO_PROXY"] = ",".join(filter(None, [*_no_proxy.split(","), "localhost", "127.0.0.1"]))

from qdrant_client import QdrantClient  # noqa: E402
from qdrant_client.models import PointStruct, SparseVector  # noqa: E402

from ate_rag_kb.chunking.models import Chunk  # noqa: E402
from ate_rag_kb.embedding.sparse_encoder import SparseVectorEncoder  # noqa: E402
from ate_rag_kb.utils.config import Config  # noqa: E402
from ate_rag_kb.vector_store.schema import (  # noqa: E402
    build_filter,
    ensure_collection,
)

logger = logging.getLogger(__name__)

_LOCAL_MODE_DEPRECATED = (
    "Local Qdrant mode is no longer supported. "
    "Use server mode (docker compose up -d qdrant) instead. "
    "See README.md for migration instructions."
)


class QdrantVectorStore:
    """Server-mode Qdrant vector store for ATE KB chunks."""

    def __init__(
        self,
        config: Config | None = None,
        *,
        allow_incompatible_schema: bool = False,
    ) -> None:
        cfg = config or Config({})
        self.config = cfg
        self.collection_name: str = cfg.get("vector_store.collection_name", "ate_kb")
        self.upsert_batch_size: int = cfg.get("vector_store.upsert_batch_size", 128)
        self.enable_sparse_vectors: bool = cfg.get("schema.enable_sparse_vectors", True)
        self.schema_compatible = True
        mode: str | None = cfg.get("vector_store.mode")
        url: str | None = cfg.get("vector_store.url")
        use_local: bool = cfg.get("vector_store.use_local", False)

        # Local mode is deprecated and raises
        if mode == "local" or (mode is None and use_local):
            raise RuntimeError(_LOCAL_MODE_DEPRECATED)

        if mode == "server" or mode is None:
            if url:
                self.client = QdrantClient(url=url)
                logger.info("Initialized Qdrant server at %s", url)
            else:
                host = cfg.get("vector_store.host", "localhost")
                port = cfg.get("vector_store.port", 6333)
                self.client = QdrantClient(host=host, port=port)
                logger.info("Initialized remote Qdrant at %s:%s", host, port)
        else:
            raise ValueError(f"Invalid vector_store.mode: {mode}. Use 'server'.")

        try:
            ensure_collection(self.client, cfg)
        except RuntimeError as exc:
            if not allow_incompatible_schema:
                raise
            self.schema_compatible = False
            logger.warning(
                "Loaded incompatible collection '%s' for rebuild only: %s",
                self.collection_name,
                exc,
            )

        vocab_path = Path(cfg.get("data.processed_dir", "./data/processed")) / "sparse_vocab.json"
        if not self.enable_sparse_vectors:
            self.sparse_encoder = SparseVectorEncoder()
            self.sparse_encoder.vocab_path = vocab_path
            return
        try:
            self.sparse_encoder = SparseVectorEncoder(vocab_path=vocab_path)
        except RuntimeError as exc:
            if not allow_incompatible_schema:
                raise
            self.schema_compatible = False
            logger.warning("Loaded incompatible sparse vocabulary for rebuild only: %s", exc)
            self.sparse_encoder = SparseVectorEncoder()
            self.sparse_encoder.vocab_path = vocab_path

    def clear_collection(self) -> None:
        """Delete and recreate the collection to clear all points and indexes."""
        try:
            self.client.delete_collection(collection_name=self.collection_name)
            logger.info("Deleted collection '%s'.", self.collection_name)
        except Exception:
            logger.warning(
                "Collection '%s' did not exist; nothing to delete.", self.collection_name
            )

        ensure_collection(self.client, self.config)
        self.schema_compatible = True
        logger.info("Recreated collection '%s' with schema.", self.collection_name)

    def upsert_chunks(self, chunks: list[Chunk]) -> None:
        """Batch upsert chunks with dense + sparse vectors into Qdrant."""
        if not chunks:
            return
        if self.enable_sparse_vectors and not self.sparse_encoder.is_fitted():
            raise RuntimeError(
                "Cannot upsert sparse vectors before the sparse vocabulary is fitted. "
                "Run a full ingestion rebuild first."
            )

        points: list[PointStruct] = []
        for chunk in chunks:
            if chunk.embedding is None:
                logger.warning("Chunk %s has no embedding; skipping.", chunk.id)
                continue
            vectors: dict[str, Any] = {"dense": chunk.embedding}
            if self.enable_sparse_vectors:
                sparse_indices, sparse_values = self.sparse_encoder.encode(chunk.content)
                vectors["sparse"] = SparseVector(
                    indices=sparse_indices,
                    values=sparse_values,
                )
            points.append(
                PointStruct(
                    id=chunk.id,
                    vector=vectors,
                    payload={
                        **chunk.to_payload(),
                        "content": chunk.content,
                    },
                )
            )

        for start in range(0, len(points), self.upsert_batch_size):
            batch = points[start : start + self.upsert_batch_size]
            self.client.upsert(collection_name=self.collection_name, points=batch)
            logger.info("Upserted %d chunks into '%s'.", len(batch), self.collection_name)

    def search(
        self,
        query_vector: list[float],
        top_k: int = 10,
        filters: dict[str, Any] | None = None,
    ) -> list[Chunk]:
        """Dense vector search returning Chunk objects."""
        qdrant_filter = build_filter(filters) if filters else None
        response = self.client.query_points(
            collection_name=self.collection_name,
            query=query_vector,
            using="dense",
            limit=top_k,
            query_filter=qdrant_filter,
            with_payload=True,
        )
        return [
            Chunk.from_payload(r.id, {**(r.payload or {}), "score": r.score})
            for r in response.points
        ]

    def sparse_search(
        self,
        query_text: str,
        top_k: int = 10,
        filters: dict[str, Any] | None = None,
    ) -> list[Chunk]:
        """Sparse vector search returning Chunk objects."""
        if not self.enable_sparse_vectors:
            return []
        indices, values = self.sparse_encoder.encode(query_text)
        if not indices:
            logger.debug("Empty sparse query for '%s'; skipping sparse search.", query_text)
            return []
        qdrant_filter = build_filter(filters) if filters else None
        response = self.client.query_points(
            collection_name=self.collection_name,
            query=SparseVector(indices=indices, values=values),
            using="sparse",
            limit=top_k,
            query_filter=qdrant_filter,
            with_payload=True,
        )
        return [
            Chunk.from_payload(r.id, {**(r.payload or {}), "score": r.score})
            for r in response.points
        ]

    def scroll(
        self,
        filters: dict[str, Any] | None = None,
        limit: int = 100,
        offset: str | None = None,
    ) -> tuple[list[Chunk], str | None]:
        """List chunks with optional filtering."""
        qdrant_filter = build_filter(filters) if filters else None
        results, next_offset = self.client.scroll(
            collection_name=self.collection_name,
            limit=limit,
            offset=offset,
            scroll_filter=qdrant_filter,
            with_payload=True,
        )
        chunks = [Chunk.from_payload(r.id, r.payload or {}) for r in results]
        return chunks, next_offset

    def delete_by_source(self, source_md: str) -> None:
        """Delete all chunks from a given markdown source file."""
        qdrant_filter = build_filter({"source_md": source_md})
        self.client.delete(
            collection_name=self.collection_name,
            points_selector=qdrant_filter,
        )
        logger.info("Deleted chunks for source: %s", source_md)

    def get_by_id(self, chunk_id: str) -> Chunk | None:
        """Fetch a single chunk by ID."""
        results = self.client.retrieve(
            collection_name=self.collection_name,
            ids=[chunk_id],
            with_payload=True,
        )
        if results and results[0].payload:
            return Chunk.from_payload(results[0].id, results[0].payload)
        return None

    def get_by_ids(self, chunk_ids: list[str]) -> list[Chunk | None]:
        """Fetch multiple chunks by ID in a single round-trip."""
        if not chunk_ids:
            return []
        deduped_ids = list(dict.fromkeys(chunk_ids))
        results = self.client.retrieve(
            collection_name=self.collection_name,
            ids=deduped_ids,
            with_payload=True,
        )
        id_to_chunk = {
            r.id: Chunk.from_payload(r.id, r.payload or {}) for r in results if r.payload
        }
        return [id_to_chunk.get(cid) for cid in chunk_ids]

    def count(self, filters: dict[str, Any] | None = None) -> int:
        """Return total number of points in the collection."""
        qdrant_filter = build_filter(filters) if filters else None
        return self.client.count(
            collection_name=self.collection_name,
            count_filter=qdrant_filter,
        ).count
