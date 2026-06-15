"""Reranker provider implementations for Reranker."""

from __future__ import annotations

import hashlib
import logging
import os
from collections import OrderedDict
from pathlib import Path
from typing import Any

import httpx
import numpy as np

from ate_rag_kb.utils.config import Config

logger = logging.getLogger(__name__)

_OFFLINE_ENV_VARS = ("HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE")

# HTTP status codes that indicate transient server issues
_TRANSIENT_STATUS_CODES = {429, 503, 504}


class _RerankCache:
    """Simple bounded LRU cache for rerank scoring results.

    Keyed by query + model + stable document digests.
    Does NOT cache API keys or full document text.
    """

    def __init__(self, max_size: int = 64) -> None:
        self._max_size = max_size
        self._cache: OrderedDict[str, np.ndarray] = OrderedDict()

    def get(self, key: str) -> np.ndarray | None:
        if key in self._cache:
            self._cache.move_to_end(key)
            return self._cache[key]
        return None

    def put(self, key: str, scores: np.ndarray) -> None:
        if key in self._cache:
            self._cache.move_to_end(key)
        self._cache[key] = scores
        while len(self._cache) > self._max_size:
            self._cache.popitem(last=False)

    def clear(self) -> None:
        self._cache.clear()

    @property
    def size(self) -> int:
        return len(self._cache)


def _build_cache_key(query: str, model_name: str, documents: list[str]) -> str:
    """Build a stable cache key from query, model, and document digests."""
    parts = [query, model_name]
    for doc in documents:
        parts.append(hashlib.sha256(doc.encode("utf-8")).hexdigest()[:16])
    joined = "|".join(parts)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()


class LocalRerankerProvider:
    """Local CrossEncoder reranker provider."""

    def __init__(self, config: Config) -> None:
        cfg = config
        self.model_name: str = cfg.get(
            "retrieval.reranker.model_name", "BAAI/bge-reranker-v2-m3"
        )
        self.batch_size: int = cfg.get("retrieval.reranker.batch_size", 16)
        requested_device = cfg.get("retrieval.reranker.device", "cpu")
        self.device: str = self._resolve_device(requested_device)
        self.cache_dir: Path = self._resolve_cache_dir(
            cfg.get("embedding.cache_dir", "./embeddings/cache")
        )
        self.local_files_only: bool = cfg.get("embedding.local_files_only", True)
        self._model: Any = None

    @staticmethod
    def _resolve_device(device: str) -> str:
        if device != "auto":
            return device
        import torch

        if torch.cuda.is_available():
            return "cuda"
        if torch.backends.mps.is_available():
            return "mps"
        return "cpu"

    @staticmethod
    def _resolve_cache_dir(cache_dir: str | Path) -> Path:
        path = Path(cache_dir).expanduser()
        if path.is_absolute():
            return path
        project_root = Path(__file__).resolve().parents[3]
        return project_root / path

    def _apply_network_mode(self) -> None:
        if self.local_files_only:
            for key in _OFFLINE_ENV_VARS:
                os.environ[key] = "1"
            os.environ.pop("HF_ENDPOINT", None)
            return

        for key in _OFFLINE_ENV_VARS:
            os.environ.pop(key, None)

    def _resolve_local_model_path(self) -> str:
        """Resolve a huggingface_hub cache entry to a local snapshot path."""
        if not self.local_files_only:
            return self.model_name

        safe_name = self.model_name.replace("/", "--")
        cache_entry = self.cache_dir / f"models--{safe_name}"
        snapshots_dir = cache_entry / "snapshots"

        if not snapshots_dir.exists():
            raise FileNotFoundError(
                f"Local model cache not found for {self.model_name} at {cache_entry}. "
                "Download the model with local_files_only=false, or unpack the offline "
                "model cache under embeddings/cache."
            )

        for snapshot in sorted(snapshots_dir.iterdir()):
            if snapshot.is_dir() and (snapshot / "config.json").exists():
                logger.info("Using local snapshot: %s", snapshot)
                return str(snapshot)

        raise FileNotFoundError(
            f"Local model cache not found for {self.model_name}: no valid snapshot with "
            f"config.json exists under {snapshots_dir}. Re-download or unpack the model cache."
        )

    @property
    def model(self) -> Any:
        from sentence_transformers import CrossEncoder

        if self._model is None:
            logger.info("Loading reranker: %s on %s", self.model_name, self.device)
            self._apply_network_mode()
            model_path = self._resolve_local_model_path()
            self._model = CrossEncoder(
                model_path,
                device=self.device,
                local_files_only=self.local_files_only,
                cache_folder=str(self.cache_dir),
            )
        return self._model

    def predict(
        self,
        pairs: list[tuple[str, str]],
        batch_size: int,
        show_progress_bar: bool = False,
    ) -> np.ndarray:
        scores = self.model.predict(pairs, batch_size=batch_size, show_progress_bar=show_progress_bar)
        return np.asarray(scores)


class HttpRerankerProvider:
    """HTTP rerank provider for SiliconFlow-style /v1/rerank APIs."""

    def __init__(self, config: Config) -> None:
        cfg = config
        self.model_name: str = cfg.get(
            "retrieval.reranker.model_name", "BAAI/bge-reranker-v2-m3"
        )
        self.base_url: str = cfg.get(
            "retrieval.reranker.api.base_url", "https://api.siliconflow.cn/v1"
        )
        self.api_key_env: str = cfg.get(
            "retrieval.reranker.api.api_key_env", "SILICONFLOW_API_KEY"
        )
        self.timeout_seconds: int = cfg.get("retrieval.reranker.api.timeout_seconds", 30)
        self.top_n: int = cfg.get("retrieval.reranker.api.top_n", 32)
        self.max_chunks_per_doc: int | None = cfg.get(
            "retrieval.reranker.api.max_chunks_per_doc", None
        )
        self.overlap_tokens: int | None = cfg.get(
            "retrieval.reranker.api.overlap_tokens", None
        )
        self._cache = _RerankCache(max_size=64)

    def _get_api_key(self) -> str:
        api_key = os.environ.get(self.api_key_env, "")
        if not api_key:
            raise ValueError(
                f"Reranker API key not found. Set the {self.api_key_env} "
                f"environment variable to your API key."
            )
        return api_key

    def predict(
        self,
        pairs: list[tuple[str, str]],
        batch_size: int,
        show_progress_bar: bool = False,
    ) -> np.ndarray:
        """Score query-document pairs via the HTTP rerank API.

        Returns a numpy array of scores aligned with the input pairs order.
        Documents not returned by the API get a very low score (-1000.0).
        """
        api_key = self._get_api_key()
        query = pairs[0][0] if pairs else ""
        documents = [doc for _, doc in pairs]

        # Check cache
        cache_key = _build_cache_key(query, self.model_name, documents)
        cached = self._cache.get(cache_key)
        if cached is not None:
            logger.debug("Rerank cache hit for query (%d docs)", len(documents))
            return cached

        effective_top_n = min(self.top_n, len(documents))

        # Build request payload with optional fields
        payload: dict[str, Any] = {
            "model": self.model_name,
            "query": query,
            "documents": documents,
            "top_n": effective_top_n,
            "return_documents": False,
        }
        if self.max_chunks_per_doc is not None:
            payload["max_chunks_per_doc"] = self.max_chunks_per_doc
        if self.overlap_tokens is not None:
            payload["overlap_tokens"] = self.overlap_tokens

        response = httpx.post(
            f"{self.base_url}/rerank",
            json=payload,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            timeout=httpx.Timeout(
                connect=10.0,
                read=float(self.timeout_seconds),
                write=10.0,
                pool=10.0,
            ),
        )

        if response.status_code != 200:
            status = response.status_code
            body = response.text[:500]
            if status in _TRANSIENT_STATUS_CODES:
                label = {429: "Rate limited", 503: "Service unavailable", 504: "Gateway timeout"}
                raise RuntimeError(
                    f"Reranker API {label.get(status, 'transient error')} "
                    f"(HTTP {status}). Retry later. Response: {body}"
                )
            raise RuntimeError(
                f"Reranker API request failed (HTTP {status}): {body}"
            )

        data = response.json()
        results = data.get("results", [])

        # Build score array aligned with input order
        scores = np.full(len(pairs), -1000.0)
        for result in results:
            idx = result.get("index", -1)
            score = result.get("relevance_score", -1000.0)
            if 0 <= idx < len(pairs):
                scores[idx] = score

        # Cache the result
        self._cache.put(cache_key, scores.copy())

        return scores
