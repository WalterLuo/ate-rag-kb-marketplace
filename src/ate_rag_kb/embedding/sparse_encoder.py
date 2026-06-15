"""TF-IDF sparse vector encoder for Qdrant sparse retrieval.

Tokenizes text with support for mixed Chinese/English content,
builds a vocabulary from the full corpus with IDF weighting,
and encodes chunks/queries as (indices, values) pairs.
"""

from __future__ import annotations

import json
import logging
import re
from collections import Counter
from math import log
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_MAX_VOCAB = 50000

# Tokenizer regex:
# - Keep alphanumeric sequences (including internal underscores, hyphens, dots)
# - Keep CJK characters as individual tokens
# - Split on ASCII and full-width punctuation/whitespace
_TOKEN_RE = re.compile(
    r"[a-z0-9]+(?:[_.\-][a-z0-9]+)*|[一-鿿]",
    re.IGNORECASE,
)


class SparseVectorEncoder:
    """Sparse vector encoder with corpus IDF weighting.

    Vocabulary is built once from the training corpus and persisted to
    ``vocab_path`` so that query-time tokenization uses the same indices
    and IDF weights.
    """

    def __init__(
        self,
        vocab_path: Path | None = None,
        max_vocab_size: int = DEFAULT_MAX_VOCAB,
    ) -> None:
        self.vocab_path = vocab_path
        self.max_vocab_size = max_vocab_size
        self._vocab: dict[str, dict[str, Any]] = {}
        if vocab_path and vocab_path.exists():
            self._load_vocab()

    # ------------------------------------------------------------------
    # Vocabulary management
    # ------------------------------------------------------------------

    def fit(self, texts: list[str]) -> None:
        """Build vocabulary with IDF weighting from *texts* and persist."""
        document_count = len(texts)
        token_counter: Counter[str] = Counter()
        doc_frequency: Counter[str] = Counter()

        for text in texts:
            tokens = self._tokenize(text)
            token_counter.update(tokens)
            unique_tokens = set(tokens)
            doc_frequency.update(unique_tokens)

        most_common = token_counter.most_common(self.max_vocab_size)
        self._vocab = {}
        for idx, (term, _) in enumerate(most_common):
            df = doc_frequency.get(term, 1)
            idf = log(document_count / df) + 1.0
            self._vocab[term] = {"index": idx, "idf": round(idf, 6)}

        logger.info(
            "Built sparse vocab with %d terms (sample: %s)",
            len(self._vocab),
            [t for t, _ in most_common[:5]],
        )
        self._save_vocab()

    def _save_vocab(self) -> None:
        if self.vocab_path is None:
            return
        self.vocab_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "format_version": 2,
            "vocab_size": len(self._vocab),
            "vocab": self._vocab,
        }
        self.vocab_path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        logger.info("Saved sparse vocab to %s", self.vocab_path)

    def _load_vocab(self) -> None:
        if self.vocab_path is None or not self.vocab_path.exists():
            return
        raw = json.loads(self.vocab_path.read_text(encoding="utf-8"))

        # Detect legacy flat format {"term": index}
        if isinstance(raw, dict) and raw.get("format_version") != 2:
            # Check if values are plain integers (legacy format)
            sample_values = list(raw.values())[:10]
            if sample_values and all(isinstance(v, int) for v in sample_values):
                raise RuntimeError(
                    f"Legacy sparse vocab format detected at {self.vocab_path}. "
                    "Please rebuild the sparse vocabulary (e.g., run a full ingestion)."
                )

        vocab_data = raw.get("vocab", raw) if isinstance(raw, dict) else raw
        self._vocab = vocab_data
        logger.info(
            "Loaded sparse vocab with %d terms from %s",
            len(self._vocab),
            self.vocab_path,
        )

    @property
    def vocab_size(self) -> int:
        return len(self._vocab)

    def is_fitted(self) -> bool:
        return len(self._vocab) > 0

    # ------------------------------------------------------------------
    # Encoding
    # ------------------------------------------------------------------

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        """Tokenize text preserving technical terms and CJK characters."""
        return [m.group(0).lower() for m in _TOKEN_RE.finditer(text)]

    def encode(self, text: str) -> tuple[list[int], list[float]]:
        """Return sparse vector as (indices, values).

        If no tokens match the vocabulary, returns empty vectors ([], [])
        instead of a dummy zero vector.
        """
        if not self._vocab:
            logger.warning("SparseVectorEncoder.encode called before fit; returning empty vector.")
            return [], []

        tokens = self._tokenize(text)
        counter: Counter[str] = Counter(tokens)

        indices: list[int] = []
        values: list[float] = []
        for token, count in counter.items():
            entry = self._vocab.get(token)
            if entry is not None:
                idx = entry["index"] if isinstance(entry, dict) else entry
                idf = entry.get("idf", 1.0) if isinstance(entry, dict) else 1.0
                indices.append(idx)
                values.append(float(count) * idf)

        if not indices:
            return [], []

        # Sort by index for deterministic serialization
        paired = sorted(zip(indices, values, strict=False))
        return [i for i, _ in paired], [v for _, v in paired]

    def encode_batch(self, texts: list[str]) -> list[tuple[list[int], list[float]]]:
        """Batch encode texts."""
        return [self.encode(t) for t in texts]

    def to_dict(self) -> dict[str, Any]:
        return {
            "vocab_size": self.vocab_size,
            "max_vocab_size": self.max_vocab_size,
            "vocab_path": str(self.vocab_path) if self.vocab_path else None,
        }
