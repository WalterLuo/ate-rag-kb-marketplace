"""Unit tests for API server factory."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from ate_rag_kb.api.server import _build_retriever
from ate_rag_kb.utils.config import Config


class TestBuildRetriever:
    def test_returns_pipeline_when_available(self) -> None:
        cfg = Config({})
        with patch("ate_rag_kb.retrieval.pipeline.RetrievalPipeline") as mock_cls:
            instance = MagicMock()
            mock_cls.return_value = instance
            result = _build_retriever(cfg)
            assert result is instance

    def test_returns_none_when_unavailable(self) -> None:
        cfg = Config({})
        with patch("ate_rag_kb.retrieval.pipeline.RetrievalPipeline", side_effect=ImportError("no")):
            result = _build_retriever(cfg)
            assert result is None
