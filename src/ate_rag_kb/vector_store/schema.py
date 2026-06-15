"""Qdrant collection schema setup."""

from __future__ import annotations

import logging
from typing import Any

from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    MatchAny,
    MatchText,
    MatchValue,
    PayloadSchemaType,
    SparseVectorParams,
    VectorParams,
)

logger = logging.getLogger(__name__)


def create_collection(
    client: QdrantClient,
    collection_name: str,
    vector_size: int = 1024,
    distance: Distance = Distance.COSINE,
    enable_sparse: bool = True,
) -> None:
    """Create a Qdrant collection if it does not exist."""
    collections = client.get_collections().collections
    existing = [c.name for c in collections]
    if collection_name in existing:
        logger.info("Collection '%s' already exists.", collection_name)
        return

    vectors_config: dict[str, Any] = {
        "dense": VectorParams(size=vector_size, distance=distance),
    }
    sparse_vectors_config: dict[str, Any] | None = None
    if enable_sparse:
        sparse_vectors_config = {"sparse": SparseVectorParams()}

    client.create_collection(
        collection_name=collection_name,
        vectors_config=vectors_config,
        sparse_vectors_config=sparse_vectors_config,
    )
    logger.info(
        "Created collection '%s' with vector_size=%d sparse=%s.",
        collection_name,
        vector_size,
        enable_sparse,
    )


def validate_collection_schema(
    client: QdrantClient,
    collection_name: str,
    expected_vector_size: int = 1024,
    enable_sparse: bool = True,
) -> None:
    """Validate that an existing collection has the expected named vectors.

    Raises:
        RuntimeError: If the collection is missing required named vectors
            or has an incompatible dense vector size.
    """
    info = client.get_collection(collection_name=collection_name)
    config = info.config
    vectors = config.params.vectors
    sparse_vectors = config.params.sparse_vectors

    if vectors is None or not hasattr(vectors, "get") or vectors.get("dense") is None:
        raise RuntimeError(
            f"Collection '{collection_name}' is missing the 'dense' named vector. "
            "Please rebuild the collection (e.g., run a full ingestion rebuild)."
        )

    dense_config = vectors.get("dense")
    if dense_config and dense_config.size != expected_vector_size:
        raise RuntimeError(
            f"Collection '{collection_name}' dense vector size {dense_config.size} "
            f"does not match expected {expected_vector_size}. "
            "Please rebuild the collection."
        )

    if enable_sparse and (sparse_vectors is None or sparse_vectors.get("sparse") is None):
        raise RuntimeError(
            f"Collection '{collection_name}' is missing the 'sparse' named vector. "
            "Please rebuild the collection (e.g., run a full ingestion rebuild)."
        )

    logger.info("Schema validation passed for '%s'.", collection_name)


def create_payload_indexes(
    client: QdrantClient,
    collection_name: str,
    fields: dict[str, str] | None = None,
) -> None:
    """Create payload indexes for metadata filtering."""
    if fields is None:
        fields = {
            "vendor": "keyword",
            "platform": "keyword",
            "software": "keyword",
            "software_release": "keyword",
            "doc_type": "keyword",
            "chunk_type": "keyword",
            "source_md": "text",
            "doc_title": "text",
        }

    for field_name, field_type in fields.items():
        schema_type = (
            PayloadSchemaType.KEYWORD if field_type == "keyword" else PayloadSchemaType.TEXT
        )
        try:
            client.create_payload_index(
                collection_name=collection_name,
                field_name=field_name,
                field_schema=schema_type,
            )
            logger.info("Created %s index on '%s'.", field_type, field_name)
        except Exception as exc:
            logger.warning("Index on '%s' may already exist: %s", field_name, exc)


def ensure_collection(client: QdrantClient, config: Any) -> None:
    """Idempotent collection + index setup with schema validation."""
    collection_name = config.get("vector_store.collection_name", "ate_kb")
    vector_size = config.get("schema.vector_size", 1024)
    distance_str = config.get("schema.distance", "Cosine")
    distance = getattr(Distance, distance_str.upper(), Distance.COSINE)
    enable_sparse = config.get("schema.enable_sparse_vectors", True)

    create_collection(client, collection_name, vector_size, distance, enable_sparse)
    validate_collection_schema(
        client, collection_name, expected_vector_size=vector_size, enable_sparse=enable_sparse
    )

    indexes = config.get("schema.payload_indexes", [])
    fields = {idx["field"]: idx["type"] for idx in indexes}
    create_payload_indexes(client, collection_name, fields)


def build_filter(
    filters: dict[str, Any],
    text_fields: set[str] | None = None,
) -> Filter | None:
    """Build a Qdrant Filter from a dict of field->value mappings.

    Args:
        filters: Mapping of field names to values. Lists become ``MatchAny``.
        text_fields: Optional set of field names that should use ``MatchText``
            instead of ``MatchValue`` for string values.
    """
    if not filters:
        return None
    conditions = []
    for field, value in filters.items():
        if isinstance(value, list):
            conditions.append(FieldCondition(key=field, match=MatchAny(any=value)))
        elif isinstance(value, str) and text_fields and field in text_fields:
            conditions.append(FieldCondition(key=field, match=MatchText(text=value)))
        else:
            conditions.append(FieldCondition(key=field, match=MatchValue(value=value)))
    return Filter(must=conditions) if conditions else None
