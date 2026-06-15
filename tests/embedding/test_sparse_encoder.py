"""Tests for SparseVectorEncoder."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ate_rag_kb.embedding.sparse_encoder import SparseVectorEncoder


class TestTokenizer:
    def test_tokenize_english_lowercase(self) -> None:
        tokens = SparseVectorEncoder._tokenize("Site Control")
        assert tokens == ["site", "control"]

    def test_tokenize_chinese_punctuation(self) -> None:
        tokens = SparseVectorEncoder._tokenize("如何使用 Site Control？")
        assert "site" in tokens
        assert "control" in tokens
        assert "如何" not in tokens  # CJK not matched by our regex

    def test_tokenize_mixed_text(self) -> None:
        tokens = SparseVectorEncoder._tokenize("Test ARRAY_x handling in SMT7.")
        assert "test" in tokens
        assert "array_x" in tokens
        assert "handling" in tokens
        assert "smt7" in tokens

    def test_tokenize_technical_terms(self) -> None:
        tokens = SparseVectorEncoder._tokenize("pin_config.v2 data-set")
        assert "pin_config.v2" in tokens
        assert "data-set" in tokens

    def test_tokenize_fullwidth_punctuation(self) -> None:
        tokens = SparseVectorEncoder._tokenize("测试（test）data、config")
        assert "test" in tokens
        assert "data" in tokens
        assert "config" in tokens


class TestEncode:
    def test_encode_returns_empty_for_unknown_query(self) -> None:
        encoder = SparseVectorEncoder()
        encoder.fit(["hello world", "foo bar"])

        indices, values = encoder.encode("xyz123unknown")
        assert indices == []
        assert values == []

    def test_encode_returns_empty_when_not_fitted(self) -> None:
        encoder = SparseVectorEncoder()
        indices, values = encoder.encode("hello")
        assert indices == []
        assert values == []

    def test_encode_matches_known_tokens(self) -> None:
        encoder = SparseVectorEncoder()
        encoder.fit(["hello world", "hello earth"])

        indices, values = encoder.encode("hello")
        assert len(indices) == 1
        assert len(values) == 1
        assert values[0] > 0

    def test_encode_applies_idf_weighting(self) -> None:
        encoder = SparseVectorEncoder()
        encoder.fit([
            "hello world foo",
            "hello world bar",
            "hello world baz",
        ])

        # "hello" appears in all docs -> low IDF
        # "foo" appears in 1 doc -> high IDF
        hello_idx = encoder._vocab["hello"]["index"]
        foo_idx = encoder._vocab["foo"]["index"]

        hello_idf = encoder._vocab["hello"]["idf"]
        foo_idf = encoder._vocab["foo"]["idf"]

        assert foo_idf > hello_idf

        indices, values = encoder.encode("hello foo")
        hello_val = values[indices.index(hello_idx)]
        foo_val = values[indices.index(foo_idx)]
        assert foo_val > hello_val

    def test_site_control_query(self) -> None:
        encoder = SparseVectorEncoder()
        encoder.fit([
            "site control overview",
            "site configuration panel",
            "control flow settings",
        ])

        indices, values = encoder.encode("Site Control")
        assert len(indices) == 2
        assert len(values) == 2

        indices2, values2 = encoder.encode("如何使用 Site Control？")
        assert len(indices2) == 2
        assert len(values2) == 2


class TestVocabPersistence:
    def test_save_and_load_vocab_with_idf(self, tmp_path: Path) -> None:
        vocab_path = tmp_path / "sparse_vocab.json"
        encoder = SparseVectorEncoder(vocab_path=vocab_path)
        encoder.fit(["hello world", "hello earth"])

        assert vocab_path.exists()
        raw = json.loads(vocab_path.read_text(encoding="utf-8"))
        assert raw.get("format_version") == 2
        assert "vocab" in raw
        assert raw["vocab"]["hello"]["idf"] > 0

        encoder2 = SparseVectorEncoder(vocab_path=vocab_path)
        assert encoder2.is_fitted()
        assert encoder2.vocab_size == encoder.vocab_size

        indices, values = encoder2.encode("hello")
        assert len(indices) == 1
        assert len(values) == 1

    def test_legacy_vocab_format_raises(self, tmp_path: Path) -> None:
        vocab_path = tmp_path / "sparse_vocab.json"
        # Write legacy format
        vocab_path.write_text(
            json.dumps({"hello": 0, "world": 1}),
            encoding="utf-8",
        )

        with pytest.raises(RuntimeError, match="Legacy sparse vocab format detected"):
            SparseVectorEncoder(vocab_path=vocab_path)

    def test_empty_vocab_loads_without_error(self, tmp_path: Path) -> None:
        vocab_path = tmp_path / "sparse_vocab.json"
        vocab_path.write_text(json.dumps({}), encoding="utf-8")

        encoder = SparseVectorEncoder(vocab_path=vocab_path)
        assert not encoder.is_fitted()
