"""Embedding provider implementations for EmbeddingEncoder."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

import httpx
import numpy as np

from ate_rag_kb.utils.config import Config

logger = logging.getLogger(__name__)

_OFFLINE_ENV_VARS = ("HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE")


class LocalEmbeddingProvider:
    """Local sentence-transformers embedding provider."""

    def __init__(self, config: Config, device: str | None = None) -> None:
        cfg = config
        self.model_name: str = cfg.get("embedding.model_name", "BAAI/bge-m3")
        requested_device = device or cfg.get("embedding.device", "auto")
        self.device: str = self._resolve_device(requested_device)
        self.normalize: bool = cfg.get("embedding.normalize_embeddings", True)
        self.batch_size: int = cfg.get("embedding.batch_size", 32)
        self.max_seq_length: int = cfg.get("embedding.max_seq_length", 8192)
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
        from sentence_transformers import SentenceTransformer

        if self._model is None:
            logger.info("Loading embedding model: %s on %s", self.model_name, self.device)
            self._apply_network_mode()
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            model_path = self._resolve_local_model_path()
            self._model = SentenceTransformer(
                model_path,
                device=self.device,
                cache_folder=str(self.cache_dir),
                local_files_only=self.local_files_only,
            )
            self._model.max_seq_length = self.max_seq_length
        return self._model

    @property
    def vector_size(self) -> int:
        return self.model.get_sentence_embedding_dimension()

    def encode(
        self,
        texts: list[str],
        batch_size: int,
        normalize: bool,
        show_progress_bar: bool = False,
    ) -> np.ndarray:
        embeddings = self.model.encode(
            texts,
            batch_size=batch_size,
            normalize_embeddings=normalize,
            show_progress_bar=show_progress_bar,
        )
        return np.asarray(embeddings)


class OpenAICompatibleEmbeddingProvider:
    """OpenAI-compatible HTTP embedding provider (e.g. SiliconFlow)."""

    def __init__(self, config: Config) -> None:
        cfg = config
        self.model_name: str = cfg.get("embedding.model_name", "BAAI/bge-m3")
        self.base_url: str = cfg.get(
            "embedding.api.base_url", "https://api.siliconflow.cn/v1"
        )
        self.api_key_env: str = cfg.get(
            "embedding.api.api_key_env", "SILICONFLOW_API_KEY"
        )
        self.timeout_seconds: int = cfg.get("embedding.api.timeout_seconds", 60)
        self._vector_size: int | None = cfg.get("schema.vector_size", None)
        self.normalize: bool = cfg.get("embedding.normalize_embeddings", True)

    def _get_api_key(self) -> str:
        api_key = os.environ.get(self.api_key_env, "")
        if not api_key:
            raise ValueError(
                f"Embedding API key not found. Set the {self.api_key_env} "
                f"environment variable to your API key."
            )
        return api_key

    @property
    def vector_size(self) -> int:
        if self._vector_size is not None:
            return self._vector_size
        raise ValueError(
            "schema.vector_size must be set in config when using the "
            "openai_compatible embedding provider."
        )

    def encode(
        self,
        texts: list[str],
        batch_size: int,
        normalize: bool,
        show_progress_bar: bool = False,
    ) -> np.ndarray:
        api_key = self._get_api_key()
        all_embeddings: list[list[float]] = []

        for start in range(0, len(texts), batch_size):
            batch = texts[start : start + batch_size]
            response = httpx.post(
                f"{self.base_url}/embeddings",
                json={"model": self.model_name, "input": batch},
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                timeout=self.timeout_seconds,
            )
            if response.status_code != 200:
                raise RuntimeError(
                    f"Embedding API request failed (HTTP {response.status_code}): "
                    f"{response.text[:500]}"
                )

            data = response.json()
            sorted_data = sorted(data["data"], key=lambda item: item["index"])
            batch_embeddings = [item["embedding"] for item in sorted_data]

            expected_size = self._vector_size
            for embedding in batch_embeddings:
                if expected_size and len(embedding) != expected_size:
                    raise ValueError(
                        f"Embedding dimension mismatch: expected {expected_size}, "
                        f"got {len(embedding)} from {self.model_name}."
                    )
            all_embeddings.extend(batch_embeddings)

        return np.array(all_embeddings)
