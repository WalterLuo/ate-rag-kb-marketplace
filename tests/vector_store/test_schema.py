"""Tests for Qdrant collection schema creation and validation."""

from __future__ import annotations

import pytest
from qdrant_client import QdrantClient

from ate_rag_kb.vector_store.schema import (
    create_collection,
    create_payload_indexes,
    ensure_collection,
    validate_collection_schema,
)


class TestCreateCollection:
    def test_create_collection_with_dense_and_sparse(self) -> None:
        client = QdrantClient(":memory:")
        create_collection(client, "test_dense_sparse", vector_size=128, enable_sparse=True)

        info = client.get_collection("test_dense_sparse")
        assert info.config.params.vectors is not None
        assert info.config.params.vectors.get("dense") is not None
        assert info.config.params.vectors.get("dense").size == 128
        assert info.config.params.sparse_vectors is not None
        assert info.config.params.sparse_vectors.get("sparse") is not None

    def test_create_collection_dense_only(self) -> None:
        client = QdrantClient(":memory:")
        create_collection(client, "test_dense_only", vector_size=256, enable_sparse=False)

        info = client.get_collection("test_dense_only")
        assert info.config.params.vectors is not None
        assert info.config.params.vectors.get("dense") is not None
        assert info.config.params.vectors.get("dense").size == 256
        assert info.config.params.sparse_vectors is None

    def test_create_collection_idempotent(self) -> None:
        client = QdrantClient(":memory:")
        create_collection(client, "test_idempotent", vector_size=64, enable_sparse=True)
        create_collection(client, "test_idempotent", vector_size=64, enable_sparse=True)

        info = client.get_collection("test_idempotent")
        assert info.config.params.vectors.get("dense").size == 64


class TestValidateCollectionSchema:
    def test_validate_passes_for_correct_schema(self) -> None:
        client = QdrantClient(":memory:")
        create_collection(client, "test_ok", vector_size=128, enable_sparse=True)

        validate_collection_schema(client, "test_ok", expected_vector_size=128, enable_sparse=True)

    def test_validate_fails_when_dense_missing(self) -> None:
        client = QdrantClient(":memory:")
        # Create collection with old-style unnamed vector (no "dense" named vector)
        client.create_collection(
            collection_name="test_no_dense",
            vectors_config={"size": 128, "distance": "Cosine"},
        )

        with pytest.raises(RuntimeError, match="missing the 'dense' named vector"):
            validate_collection_schema(client, "test_no_dense", expected_vector_size=128, enable_sparse=True)

    def test_validate_fails_when_sparse_missing_but_expected(self) -> None:
        client = QdrantClient(":memory:")
        create_collection(client, "test_no_sparse", vector_size=128, enable_sparse=False)

        with pytest.raises(RuntimeError, match="missing the 'sparse' named vector"):
            validate_collection_schema(client, "test_no_sparse", expected_vector_size=128, enable_sparse=True)

    def test_validate_passes_when_sparse_not_expected(self) -> None:
        client = QdrantClient(":memory:")
        create_collection(client, "test_sparse_disabled", vector_size=128, enable_sparse=False)

        validate_collection_schema(client, "test_sparse_disabled", expected_vector_size=128, enable_sparse=False)

    def test_validate_fails_on_vector_size_mismatch(self) -> None:
        client = QdrantClient(":memory:")
        create_collection(client, "test_size_mismatch", vector_size=128, enable_sparse=True)

        with pytest.raises(RuntimeError, match="dense vector size 128 does not match expected 256"):
            validate_collection_schema(client, "test_size_mismatch", expected_vector_size=256, enable_sparse=True)


class TestEnsureCollection:
    def test_ensure_collection_creates_with_sparse(self) -> None:
        from ate_rag_kb.utils.config import Config

        client = QdrantClient(":memory:")
        cfg = Config({
            "vector_store": {"collection_name": "ensure_test"},
            "schema": {"vector_size": 128, "enable_sparse_vectors": True, "payload_indexes": []},
        })
        ensure_collection(client, cfg)

        info = client.get_collection("ensure_test")
        assert info.config.params.vectors.get("dense").size == 128
        assert info.config.params.sparse_vectors.get("sparse") is not None

    def test_ensure_collection_validates_existing(self) -> None:
        from ate_rag_kb.utils.config import Config

        client = QdrantClient(":memory:")
        # Create with old-style schema (no named dense vector)
        client.create_collection(
            collection_name="ensure_validate",
            vectors_config={"size": 128, "distance": "Cosine"},
        )

        cfg = Config({
            "vector_store": {"collection_name": "ensure_validate"},
            "schema": {"vector_size": 128, "enable_sparse_vectors": True, "payload_indexes": []},
        })

        with pytest.raises(RuntimeError, match="missing the 'dense' named vector"):
            ensure_collection(client, cfg)


class TestCreatePayloadIndexes:
    def test_default_indexes_include_canonical_metadata(self) -> None:
        indexed_fields: set[str] = set()

        class RecordingClient:
            def create_payload_index(self, **kwargs: object) -> None:
                indexed_fields.add(str(kwargs["field_name"]))

        create_payload_indexes(RecordingClient(), "test_payload_indexes")

        assert {"vendor", "platform", "software", "software_release"} <= indexed_fields
