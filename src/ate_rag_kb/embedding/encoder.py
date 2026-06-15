"""Provider-based embedding encoder for ATE KB."""

from __future__ import annotations

import logging

import numpy as np

from ate_rag_kb.embedding.providers import (
    LocalEmbeddingProvider,
    OpenAICompatibleEmbeddingProvider,
)
from ate_rag_kb.utils.config import Config

logger = logging.getLogger(__name__)

_PROVIDER_MAP = {
    "local": LocalEmbeddingProvider,
    "openai_compatible": OpenAICompatibleEmbeddingProvider,
}


class EmbeddingEncoder:
    """Wrapper that delegates encoding to a pluggable embedding provider."""

    def __init__(self, config: Config | None = None, device: str | None = None) -> None:
        cfg = config or Config({})
        provider_name: str = cfg.get("embedding.provider", "local")

        provider_cls = _PROVIDER_MAP.get(provider_name)
        if provider_cls is None:
            raise ValueError(
                f"Unknown embedding provider: {provider_name!r}. "
                f"Supported providers: {sorted(_PROVIDER_MAP)}"
            )

        if provider_name == "local":
            self._provider = provider_cls(cfg, device=device)
        else:
            self._provider = provider_cls(cfg)

        self.query_instruction: str = cfg.get(
            "embedding.query_instruction",
            "Represent this sentence for searching relevant passages: ",
        )

    @property
    def device(self) -> str:
        return getattr(self._provider, "device", "cpu")

    @property
    def model_name(self) -> str:
        return self._provider.model_name

    @property
    def vector_size(self) -> int:
        return self._provider.vector_size

    def encode(self, texts: list[str], batch_size: int | None = None) -> np.ndarray:
        """Encode a list of texts into normalized embeddings."""
        if not texts:
            return np.array([])
        bs = batch_size or getattr(self._provider, "batch_size", 32)
        normalize = getattr(self._provider, "normalize", True)
        return self._provider.encode(
            texts,
            batch_size=bs,
            normalize=normalize,
            show_progress_bar=len(texts) > 100,
        )

    def encode_query(self, query: str) -> np.ndarray:
        """Encode a query with instruction prefix."""
        text = self.query_instruction + query
        return self.encode([text])[0]

    def encode_documents(self, documents: list[str]) -> np.ndarray:
        """Encode documents (passages)."""
        return self.encode(documents)
