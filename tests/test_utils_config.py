"""Unit tests for configuration utilities."""

from __future__ import annotations

import pytest

from ate_rag_kb.utils.config import Config, get_config, reload_config


class TestConfig:
    def test_get_with_dot_notation(self) -> None:
        data = {"embedding": {"model_name": "BAAI/bge-m3", "batch_size": 32}}
        config = Config(data)

        assert config.get("embedding.model_name") == "BAAI/bge-m3"
        assert config.get("embedding.batch_size") == 32

    def test_get_returns_default_when_key_missing(self) -> None:
        config = Config({})

        assert config.get("missing.key", "default") == "default"
        assert config.get("missing.key") is None

    def test_get_returns_default_for_partial_path(self) -> None:
        config = Config({"embedding": {"model_name": "bge-m3"}})

        assert config.get("embedding.missing_key", 42) == 42

    def test_getitem_raises_key_error_when_missing(self) -> None:
        config = Config({})

        with pytest.raises(KeyError):
            _ = config["nonexistent.key"]

    def test_section_returns_subconfig(self) -> None:
        data = {"retrieval": {"top_k": 10, "enabled": True}}
        config = Config(data)
        sub = config.section("retrieval")

        assert isinstance(sub, Config)
        assert sub.get("top_k") == 10
        assert sub.get("enabled") is True

    def test_to_dict_returns_copy(self) -> None:
        data = {"a": 1}
        config = Config(data)
        d = config.to_dict()

        d["a"] = 99
        assert config.get("a") == 1

    def test_get_top_level_key(self) -> None:
        config = Config({"level": "INFO"})

        assert config.get("level") == "INFO"

    def test_get_expands_environment_variable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ATE_KB_MODEL_CACHE", "/tmp/ate-models")
        config = Config({"embedding": {"cache_dir": "${ATE_KB_MODEL_CACHE}"}})

        assert config.get("embedding.cache_dir") == "/tmp/ate-models"

    def test_get_expands_environment_variable_with_default(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("ATE_KB_MODEL_CACHE", raising=False)
        config = Config({"embedding": {"cache_dir": "${ATE_KB_MODEL_CACHE:-./embeddings/cache}"}})

        assert config.get("embedding.cache_dir") == "./embeddings/cache"

    def test_embedding_model_name_env_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Embedding model name must be switchable via ATE_KB_EMBEDDING_MODEL."""
        monkeypatch.setenv("ATE_KB_EMBEDDING_MODEL", "vendor/custom-embedding")
        config = Config(
            {"embedding": {"model_name": "${ATE_KB_EMBEDDING_MODEL:-BAAI/bge-m3}"}}
        )

        assert config.get("embedding.model_name") == "vendor/custom-embedding"

    def test_embedding_model_name_default_when_no_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Embedding model name falls back to default when env var is unset."""
        monkeypatch.delenv("ATE_KB_EMBEDDING_MODEL", raising=False)
        config = Config(
            {"embedding": {"model_name": "${ATE_KB_EMBEDDING_MODEL:-BAAI/bge-m3}"}}
        )

        assert config.get("embedding.model_name") == "BAAI/bge-m3"

    def test_reranker_model_name_env_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Reranker model name must be switchable via ATE_KB_RERANKER_MODEL."""
        monkeypatch.setenv("ATE_KB_RERANKER_MODEL", "vendor/custom-reranker")
        config = Config(
            {
                "retrieval": {
                    "reranker": {
                        "model_name": "${ATE_KB_RERANKER_MODEL:-BAAI/bge-reranker-v2-m3}"
                    }
                }
            }
        )

        assert config.get("retrieval.reranker.model_name") == "vendor/custom-reranker"

    def test_reranker_model_name_default_when_no_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Reranker model name falls back to default when env var is unset."""
        monkeypatch.delenv("ATE_KB_RERANKER_MODEL", raising=False)
        config = Config(
            {
                "retrieval": {
                    "reranker": {
                        "model_name": "${ATE_KB_RERANKER_MODEL:-BAAI/bge-reranker-v2-m3}"
                    }
                }
            }
        )

        assert config.get("retrieval.reranker.model_name") == "BAAI/bge-reranker-v2-m3"


class TestGetConfig:
    def test_get_config_returns_same_instance_on_subsequent_calls(self) -> None:
        reload_config()
        c1 = get_config()
        c2 = get_config()

        assert c1 is c2

    def test_reload_config_returns_new_instance(self) -> None:
        reload_config()
        c1 = get_config()
        c2 = reload_config()

        assert c1 is not c2
