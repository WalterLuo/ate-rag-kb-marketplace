"""Unit tests for provider-based embedding encoder."""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from ate_rag_kb.embedding.encoder import EmbeddingEncoder
from ate_rag_kb.utils.config import Config


class TestEmbeddingEncoder:
    @pytest.fixture
    def encoder(self) -> EmbeddingEncoder:
        cfg = Config({"embedding": {"device": "cpu"}})
        with patch("sentence_transformers.SentenceTransformer"):
            yield EmbeddingEncoder(cfg)

    def test_default_config(self, encoder: EmbeddingEncoder) -> None:
        assert encoder.model_name == "BAAI/bge-m3"
        assert encoder.device == "cpu"

    def test_default_provider_is_local(self) -> None:
        cfg = Config({"embedding": {"device": "cpu"}})
        with patch("sentence_transformers.SentenceTransformer"):
            encoder = EmbeddingEncoder(cfg)
        assert encoder.model_name == "BAAI/bge-m3"

    def test_model_name_env_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """EmbeddingEncoder.model_name must reflect the env-var-expanded model name."""
        monkeypatch.setenv("ATE_KB_EMBEDDING_MODEL", "vendor/custom-embedding")
        cfg = Config(
            {
                "embedding": {
                    "model_name": "${ATE_KB_EMBEDDING_MODEL:-BAAI/bge-m3}",
                    "device": "cpu",
                }
            }
        )
        with patch("sentence_transformers.SentenceTransformer"):
            encoder = EmbeddingEncoder(cfg)
        assert encoder.model_name == "vendor/custom-embedding"

    def test_encode_empty_list(self, encoder: EmbeddingEncoder) -> None:
        result = encoder.encode([])
        assert result.size == 0

    def test_encode_query(self, encoder: EmbeddingEncoder) -> None:
        mock_provider = encoder._provider
        mock_provider.model.encode.return_value = np.array([[0.1, 0.2]])
        emb = encoder.encode_query("test")
        assert isinstance(emb, np.ndarray)
        assert emb.shape == (2,)

    def test_encode_documents(self, encoder: EmbeddingEncoder) -> None:
        mock_provider = encoder._provider
        mock_provider.model.encode.return_value = np.array([[0.1, 0.2], [0.3, 0.4]])
        emb = encoder.encode_documents(["a", "b"])
        assert emb.shape == (2, 2)

    def test_vector_size(self, encoder: EmbeddingEncoder) -> None:
        mock_provider = encoder._provider
        mock_provider.model.get_sentence_embedding_dimension.return_value = 1024
        assert encoder.vector_size == 1024

    def test_unknown_provider_raises_value_error(self) -> None:
        cfg = Config({"embedding": {"provider": "nonexistent", "device": "cpu"}})
        with pytest.raises(ValueError, match="Unknown embedding provider"):
            EmbeddingEncoder(cfg)

    def test_online_mode_does_not_force_offline_environment(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path
    ) -> None:
        monkeypatch.setenv("HF_HUB_OFFLINE", "1")
        monkeypatch.setenv("TRANSFORMERS_OFFLINE", "1")
        cfg = Config(
            {
                "embedding": {
                    "device": "cpu",
                    "cache_dir": str(tmp_path),
                    "local_files_only": False,
                }
            }
        )

        with patch("sentence_transformers.SentenceTransformer") as mock_cls:
            encoder = EmbeddingEncoder(cfg)
            _ = encoder._provider.model

        assert "HF_HUB_OFFLINE" not in os.environ
        assert "TRANSFORMERS_OFFLINE" not in os.environ
        mock_cls.assert_called_once()
        assert mock_cls.call_args.kwargs["local_files_only"] is False

    def test_offline_mode_raises_clear_error_when_cache_missing(self, tmp_path) -> None:
        cfg = Config(
            {
                "embedding": {
                    "model_name": "BAAI/bge-m3",
                    "device": "cpu",
                    "cache_dir": str(tmp_path),
                    "local_files_only": True,
                }
            }
        )
        encoder = EmbeddingEncoder(cfg)

        with pytest.raises(FileNotFoundError, match="Local model cache not found"):
            _ = encoder._provider.model

    def test_embedding_query_device_defaults_to_cpu_and_ingest_device_independent(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("ATE_KB_QUERY_DEVICE", "cpu")
        monkeypatch.setenv("ATE_KB_INGEST_DEVICE", "mps")
        cfg = Config(
            {
                "embedding": {
                    "device": "${ATE_KB_QUERY_DEVICE:-cpu}",
                    "ingest_device": "${ATE_KB_INGEST_DEVICE:-auto}",
                }
            }
        )
        assert cfg.get("embedding.device") == "cpu"
        assert cfg.get("embedding.ingest_device") == "mps"


class TestOpenAICompatibleProvider:
    """Tests for the openai_compatible embedding provider."""

    def test_encode_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TEST_API_KEY", "test-key-123")
        cfg = Config(
            {
                "embedding": {
                    "provider": "openai_compatible",
                    "model_name": "BAAI/bge-m3",
                    "api": {
                        "base_url": "https://api.example.com/v1",
                        "api_key_env": "TEST_API_KEY",
                        "timeout_seconds": 30,
                    },
                },
                "schema": {"vector_size": 4},
            }
        )

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": [
                {"embedding": [0.1, 0.2, 0.3, 0.4], "index": 0},
                {"embedding": [0.5, 0.6, 0.7, 0.8], "index": 1},
            ]
        }

        with patch("ate_rag_kb.embedding.providers.httpx.post", return_value=mock_response) as mock_post:
            encoder = EmbeddingEncoder(cfg)
            result = encoder.encode(["hello", "world"])

        assert result.shape == (2, 4)
        mock_post.assert_called_once()
        call_kwargs = mock_post.call_args
        assert call_kwargs.kwargs["headers"]["Authorization"] == "Bearer test-key-123"

    def test_encode_missing_api_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("MISSING_KEY", raising=False)
        cfg = Config(
            {
                "embedding": {
                    "provider": "openai_compatible",
                    "model_name": "BAAI/bge-m3",
                    "api": {
                        "base_url": "https://api.example.com/v1",
                        "api_key_env": "MISSING_KEY",
                        "timeout_seconds": 30,
                    },
                },
                "schema": {"vector_size": 4},
            }
        )

        encoder = EmbeddingEncoder(cfg)
        with pytest.raises(ValueError, match="API key not found"):
            encoder.encode(["hello"])

    def test_encode_http_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TEST_API_KEY", "test-key-123")
        cfg = Config(
            {
                "embedding": {
                    "provider": "openai_compatible",
                    "model_name": "BAAI/bge-m3",
                    "api": {
                        "base_url": "https://api.example.com/v1",
                        "api_key_env": "TEST_API_KEY",
                        "timeout_seconds": 30,
                    },
                },
                "schema": {"vector_size": 4},
            }
        )

        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.text = "Internal Server Error"

        with patch("ate_rag_kb.embedding.providers.httpx.post", return_value=mock_response):
            encoder = EmbeddingEncoder(cfg)
            with pytest.raises(RuntimeError, match="HTTP 500"):
                encoder.encode(["hello"])

    def test_encode_dimension_mismatch(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TEST_API_KEY", "test-key-123")
        cfg = Config(
            {
                "embedding": {
                    "provider": "openai_compatible",
                    "model_name": "BAAI/bge-m3",
                    "api": {
                        "base_url": "https://api.example.com/v1",
                        "api_key_env": "TEST_API_KEY",
                        "timeout_seconds": 30,
                    },
                },
                "schema": {"vector_size": 4},
            }
        )

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": [
                {"embedding": [0.1, 0.2], "index": 0},
            ]
        }

        with patch("ate_rag_kb.embedding.providers.httpx.post", return_value=mock_response):
            encoder = EmbeddingEncoder(cfg)
            with pytest.raises(ValueError, match="dimension mismatch"):
                encoder.encode(["hello"])

    def test_encode_batches_multiple_requests(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TEST_API_KEY", "test-key-123")
        cfg = Config(
            {
                "embedding": {
                    "provider": "openai_compatible",
                    "model_name": "BAAI/bge-m3",
                    "batch_size": 2,
                    "api": {
                        "base_url": "https://api.example.com/v1",
                        "api_key_env": "TEST_API_KEY",
                        "timeout_seconds": 30,
                    },
                },
                "schema": {"vector_size": 2},
            }
        )

        call_index = 0

        def mock_post(url, **kwargs):
            nonlocal call_index
            inputs = kwargs["json"]["input"]
            resp = MagicMock()
            resp.status_code = 200
            resp.json.return_value = {
                "data": [
                    {"embedding": [float(call_index * len(inputs) + i), 0.0], "index": i}
                    for i in range(len(inputs))
                ]
            }
            call_index += 1
            return resp

        with patch("ate_rag_kb.embedding.providers.httpx.post", side_effect=mock_post):
            encoder = EmbeddingEncoder(cfg)
            result = encoder.encode(["a", "b", "c"])

        assert result.shape == (3, 2)

    def test_vector_size_from_config(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TEST_API_KEY", "test-key")
        cfg = Config(
            {
                "embedding": {
                    "provider": "openai_compatible",
                    "model_name": "BAAI/bge-m3",
                    "api": {
                        "base_url": "https://api.example.com/v1",
                        "api_key_env": "TEST_API_KEY",
                        "timeout_seconds": 30,
                    },
                },
                "schema": {"vector_size": 1024},
            }
        )
        encoder = EmbeddingEncoder(cfg)
        assert encoder.vector_size == 1024
