#!/usr/bin/env python3
"""Bootstrap script to generate all core ate-rag-kb modules.

DEPRECATED: This script generates the original module scaffolds and does NOT
include ecosystem/software_version/doc_family fields added in later phases.
It is kept for historical reference but should not be used to regenerate
production modules without manually adding the new metadata fields.
"""

from pathlib import Path

BASE = Path("/Users/walter_luo/Project/ate-rag-kb/src/ate_rag_kb")

FILES = {
    "embedding/__init__.py": """from ate_rag_kb.embedding.encoder import EmbeddingEncoder

__all__ = ["EmbeddingEncoder"]
""",

    "embedding/encoder.py": '''"""Embedding encoder using sentence-transformers."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import numpy as np
from sentence_transformers import SentenceTransformer

from ate_rag_kb.utils.config import Config

logger = logging.getLogger(__name__)


class EmbeddingEncoder:
    """Wrapper around sentence-transformers for ATE KB embeddings."""

    def __init__(self, config: Config | None = None) -> None:
        cfg = config or Config({})
        self.model_name: str = cfg.get("embedding.model_name", "BAAI/bge-m3")
        self.device: str = self._resolve_device(cfg.get("embedding.device", "auto"))
        self.normalize: bool = cfg.get("embedding.normalize_embeddings", True)
        self.batch_size: int = cfg.get("embedding.batch_size", 32)
        self.max_seq_length: int = cfg.get("embedding.max_seq_length", 8192)
        self.cache_dir: Path = Path(cfg.get("embedding.cache_dir", "./embeddings/cache"))
        self.query_instruction: str = cfg.get(
            "embedding.query_instruction",
            "Represent this sentence for searching relevant passages: ",
        )
        self._model: SentenceTransformer | None = None

    def _resolve_device(self, device: str) -> str:
        if device != "auto":
            return device
        import torch
        if torch.cuda.is_available():
            return "cuda"
        if torch.backends.mps.is_available():
            return "mps"
        return "cpu"

    @property
    def model(self) -> SentenceTransformer:
        if self._model is None:
            logger.info("Loading embedding model: %s on %s", self.model_name, self.device)
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            self._model = SentenceTransformer(
                self.model_name,
                device=self.device,
                cache_folder=str(self.cache_dir),
            )
            self._model.max_seq_length = self.max_seq_length
        return self._model

    def encode(self, texts: list[str], batch_size: int | None = None) -> np.ndarray:
        """Encode a list of texts into normalized embeddings."""
        if not texts:
            return np.array([])
        bs = batch_size or self.batch_size
        embeddings = self.model.encode(
            texts,
            batch_size=bs,
            normalize_embeddings=self.normalize,
            show_progress_bar=len(texts) > 100,
        )
        return np.asarray(embeddings)

    def encode_query(self, query: str) -> np.ndarray:
        """Encode a query with instruction prefix."""
        text = self.query_instruction + query
        return self.encode([text])[0]

    def encode_documents(self, documents: list[str]) -> np.ndarray:
        """Encode documents (passages)."""
        return self.encode(documents)

    @property
    def vector_size(self) -> int:
        return self.model.get_sentence_embedding_dimension()
''',

    "vector_store/__init__.py": """from ate_rag_kb.vector_store.qdrant_client import QdrantVectorStore

__all__ = ["QdrantVectorStore"]
""",

    "vector_store/schema.py": '''"""Qdrant collection schema setup."""

from __future__ import annotations

import logging
from typing import Any

from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    MatchValue,
    PayloadSchemaType,
    VectorParams,
)

logger = logging.getLogger(__name__)


def create_collection(
    client: QdrantClient,
    collection_name: str,
    vector_size: int = 1024,
    distance: Distance = Distance.COSINE,
) -> None:
    """Create a Qdrant collection if it does not exist."""
    collections = client.get_collections().collections
    existing = [c.name for c in collections]
    if collection_name in existing:
        logger.info("Collection '%s' already exists.", collection_name)
        return

    client.create_collection(
        collection_name=collection_name,
        vectors_config=VectorParams(size=vector_size, distance=distance),
    )
    logger.info("Created collection '%s' with vector_size=%d.", collection_name, vector_size)


def create_payload_indexes(
    client: QdrantClient,
    collection_name: str,
    fields: dict[str, str] | None = None,
) -> None:
    """Create payload indexes for metadata filtering."""
    if fields is None:
        fields = {
            "platform": "keyword",
            "doc_type": "keyword",
            "chunk_type": "keyword",
            "source_md": "text",
            "doc_title": "text",
        }

    for field_name, field_type in fields.items():
        schema_type = (
            PayloadSchemaType.KEYWORD
            if field_type == "keyword"
            else PayloadSchemaType.TEXT
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
    """Idempotent collection + index setup."""
    collection_name = config.get("vector_store.collection_name", "ate_kb")
    vector_size = config.get("schema.vector_size", 1024)
    distance_str = config.get("schema.distance", "Cosine")
    distance = getattr(Distance, distance_str.upper(), Distance.COSINE)

    create_collection(client, collection_name, vector_size, distance)

    indexes = config.get("schema.payload_indexes", [])
    fields = {idx["field"]: idx["type"] for idx in indexes}
    create_payload_indexes(client, collection_name, fields)


def build_filter(filters: dict[str, Any]) -> Filter | None:
    """Build a Qdrant Filter from a dict of field->value mappings."""
    if not filters:
        return None
    conditions = []
    for field, value in filters.items():
        if isinstance(value, list):
            for v in value:
                conditions.append(FieldCondition(key=field, match=MatchValue(value=v)))
        else:
            conditions.append(FieldCondition(key=field, match=MatchValue(value=value)))
    return Filter(should=conditions) if conditions else None
''',

    "vector_store/qdrant_client.py": '''"""Qdrant vector store client wrapper."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from qdrant_client import QdrantClient
from qdrant_client.models import PointStruct, ScoredPoint

from ate_rag_kb.chunking.models import Chunk
from ate_rag_kb.utils.config import Config
from ate_rag_kb.vector_store.schema import build_filter, create_collection, ensure_collection

logger = logging.getLogger(__name__)


class QdrantVectorStore:
    """Local-first Qdrant vector store for ATE KB chunks."""

    def __init__(self, config: Config | None = None) -> None:
        cfg = config or Config({})
        self.collection_name: str = cfg.get("vector_store.collection_name", "ate_kb")
        self.use_local: bool = cfg.get("vector_store.use_local", True)
        self.local_path: Path = Path(cfg.get("vector_store.local_path", "./data/qdrant_storage"))

        if self.use_local:
            self.local_path.mkdir(parents=True, exist_ok=True)
            self.client = QdrantClient(path=str(self.local_path))
            logger.info("Initialized local Qdrant at %s", self.local_path)
        else:
            host = cfg.get("vector_store.host", "localhost")
            port = cfg.get("vector_store.port", 6333)
            self.client = QdrantClient(host=host, port=port)
            logger.info("Initialized remote Qdrant at %s:%s", host, port)

        ensure_collection(self.client, cfg)

    def upsert_chunks(self, chunks: list[Chunk]) -> None:
        """Batch upsert chunks with embeddings into Qdrant."""
        if not chunks:
            return

        points: list[PointStruct] = []
        for chunk in chunks:
            if chunk.embedding is None:
                logger.warning("Chunk %s has no embedding; skipping.", chunk.id)
                continue
            points.append(
                PointStruct(
                    id=chunk.id,
                    vector=chunk.embedding,
                    payload={
                        **chunk.to_payload(),
                        "content": chunk.content,
                    },
                )
            )

        if points:
            self.client.upsert(collection_name=self.collection_name, points=points)
            logger.info("Upserted %d chunks into '%s'.", len(points), self.collection_name)

    def search(
        self,
        query_vector: list[float],
        top_k: int = 10,
        filters: dict[str, Any] | None = None,
    ) -> list[Chunk]:
        """Vector search returning Chunk objects."""
        qdrant_filter = build_filter(filters) if filters else None
        results: list[ScoredPoint] = self.client.search(
            collection_name=self.collection_name,
            query_vector=query_vector,
            limit=top_k,
            query_filter=qdrant_filter,
            with_payload=True,
        )
        return [
            Chunk.from_payload(r.id, {**r.payload, "score": r.score})
            for r in results
        ]

    def scroll(
        self,
        filters: dict[str, Any] | None = None,
        limit: int = 100,
        offset: str | None = None,
    ) -> tuple[list[Chunk], str | None]:
        """List chunks with optional filtering."""
        qdrant_filter = build_filter(filters) if filters else None
        results, next_offset = self.client.scroll(
            collection_name=self.collection_name,
            limit=limit,
            offset=offset,
            scroll_filter=qdrant_filter,
            with_payload=True,
        )
        chunks = [
            Chunk.from_payload(r.id, r.payload or {})
            for r in results
        ]
        return chunks, next_offset

    def delete_by_source(self, source_md: str) -> None:
        """Delete all chunks from a given markdown source file."""
        qdrant_filter = build_filter({"source_md": source_md})
        self.client.delete(
            collection_name=self.collection_name,
            points_selector=qdrant_filter,
        )
        logger.info("Deleted chunks for source: %s", source_md)

    def get_by_id(self, chunk_id: str) -> Chunk | None:
        """Fetch a single chunk by ID."""
        results = self.client.retrieve(
            collection_name=self.collection_name,
            ids=[chunk_id],
            with_payload=True,
        )
        if results and results[0].payload:
            return Chunk.from_payload(results[0].id, results[0].payload)
        return None

    def count(self) -> int:
        """Return total number of points in the collection."""
        return self.client.count(collection_name=self.collection_name).count
''',

    "ingestion/__init__.py": """from ate_rag_kb.ingestion.pipeline import IngestionPipeline
from ate_rag_kb.ingestion.incremental import IncrementalIngestion

__all__ = ["IngestionPipeline", "IncrementalIngestion"]
""",

    "ingestion/pipeline.py": '''"""Markdown ingestion pipeline."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from tqdm import tqdm

from ate_rag_kb.chunking.models import Chunk
from ate_rag_kb.chunking.strategies import HierarchicalChunker
from ate_rag_kb.embedding.encoder import EmbeddingEncoder
from ate_rag_kb.utils.config import Config
from ate_rag_kb.vector_store.qdrant_client import QdrantVectorStore

logger = logging.getLogger(__name__)


class IngestionPipeline:
    """Orchestrates markdown -> chunks -> embeddings -> vector store."""

    def __init__(
        self,
        config: Config,
        encoder: EmbeddingEncoder,
        vector_store: QdrantVectorStore,
        chunker: HierarchicalChunker | None = None,
    ) -> None:
        self.config = config
        self.encoder = encoder
        self.vector_store = vector_store
        self.chunker = chunker or HierarchicalChunker()

    def ingest_document(
        self,
        md_path: Path,
        json_path: Path | None = None,
        platform: str = "",
        doc_type: str = "",
    ) -> list[Chunk]:
        """Ingest a single markdown document."""
        md_text = md_path.read_text(encoding="utf-8")

        metadata: dict[str, Any] = {}
        if json_path and json_path.exists():
            metadata = json.loads(json_path.read_text(encoding="utf-8"))

        source_md = str(md_path.relative_to(self.config.get("data.markdown_dir", ".")))
        source_json = str(json_path.relative_to(self.config.get("data.json_dir", "."))) if json_path else ""

        chunks = self.chunker.chunk_document(
            md_text=md_text,
            metadata=metadata,
            source_md=source_md,
            source_json=source_json,
        )

        for chunk in chunks:
            if not chunk.platform:
                chunk.platform = platform
            if not chunk.doc_type:
                chunk.doc_type = doc_type

        texts = [c.content for c in chunks]
        embeddings = self.encoder.encode(texts)
        for chunk, emb in zip(chunks, embeddings):
            chunk.embedding = emb.tolist()

        self.vector_store.upsert_chunks(chunks)
        return chunks

    def ingest_directory(
        self,
        markdown_dir: Path,
        json_dir: Path | None = None,
    ) -> int:
        """Batch ingest all markdown files in a directory."""
        md_files = sorted(markdown_dir.rglob("*.md"))
        logger.info("Found %d markdown files in %s", len(md_files), markdown_dir)

        total_chunks = 0
        for md_path in tqdm(md_files, desc="Ingesting"):
            json_path = None
            if json_dir:
                rel = md_path.relative_to(markdown_dir)
                json_path = json_dir / rel.with_suffix(".json")

            platform = self._detect_platform(md_path)
            doc_type = self._detect_doc_type(md_path)

            try:
                chunks = self.ingest_document(md_path, json_path, platform, doc_type)
                total_chunks += len(chunks)
            except Exception as exc:
                logger.error("Failed to ingest %s: %s", md_path, exc)

        logger.info("Ingested %d chunks total.", total_chunks)
        return total_chunks

    @staticmethod
    def _detect_platform(path: Path) -> str:
        name = path.name.lower()
        if "j750" in name or "ultraflex" in name:
            return "J750"
        if "smt7" in name or "smt8" in name:
            return "SMT7"
        if "v93000" in name or "smartest" in name:
            return "V93000"
        if "tdc" in name:
            return "TDC"
        return ""

    @staticmethod
    def _detect_doc_type(path: Path) -> str:
        name = path.name.lower()
        if any(k in name for k in ["api", "reference", "command"]):
            return "api"
        if any(k in name for k in ["flow", "testflow"]):
            return "flow"
        if any(k in name for k in ["timing", "level", "pattern", "pin"]):
            return "hardware_config"
        if any(k in name for k in ["guide", "tutorial", "getting started"]):
            return "guide"
        return "reference"
''',

    "ingestion/incremental.py": '''"""Incremental ingestion with change detection."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from ate_rag_kb.ingestion.pipeline import IngestionPipeline
from ate_rag_kb.utils.config import Config

logger = logging.getLogger(__name__)

STATE_FILE = Path("./data/processed/ingestion_state.json")


class IncrementalIngestion:
    """Track file changes and only ingest new/modified documents."""

    def __init__(self, pipeline: IngestionPipeline, state_file: Path | None = None) -> None:
        self.pipeline = pipeline
        self.state_file = state_file or STATE_FILE
        self.state_file.parent.mkdir(parents=True, exist_ok=True)

    def _load_state(self) -> dict[str, float]:
        if self.state_file.exists():
            return json.loads(self.state_file.read_text(encoding="utf-8"))
        return {}

    def _save_state(self, state: dict[str, float]) -> None:
        self.state_file.write_text(json.dumps(state, indent=2), encoding="utf-8")

    def scan_for_changes(
        self,
        markdown_dir: Path,
    ) -> tuple[list[Path], list[Path]]:
        """Return (new_files, modified_files)."""
        state = self._load_state()
        new_files: list[Path] = []
        modified_files: list[Path] = []

        for md_path in markdown_dir.rglob("*.md"):
            rel = str(md_path.relative_to(markdown_dir))
            mtime = md_path.stat().st_mtime
            if rel not in state:
                new_files.append(md_path)
            elif mtime > state[rel]:
                modified_files.append(md_path)

        return new_files, modified_files

    def run_incremental(
        self,
        markdown_dir: Path,
        json_dir: Path | None = None,
    ) -> dict[str, int]:
        """Ingest only changed documents."""
        new_files, modified_files = self.scan_for_changes(markdown_dir)
        logger.info("Incremental scan: %d new, %d modified", len(new_files), len(modified_files))

        state = self._load_state()
        total_chunks = 0

        for md_path in modified_files:
            rel = str(md_path.relative_to(markdown_dir))
            self.pipeline.vector_store.delete_by_source(rel)
            logger.info("Deleted old chunks for modified file: %s", rel)

        for md_path in new_files + modified_files:
            rel = str(md_path.relative_to(markdown_dir))
            json_path = None
            if json_dir:
                json_path = json_dir / md_path.relative_to(markdown_dir).with_suffix(".json")

            platform = self.pipeline._detect_platform(md_path)
            doc_type = self.pipeline._detect_doc_type(md_path)

            try:
                chunks = self.pipeline.ingest_document(md_path, json_path, platform, doc_type)
                total_chunks += len(chunks)
                state[rel] = md_path.stat().st_mtime
            except Exception as exc:
                logger.error("Failed to ingest %s: %s", rel, exc)

        self._save_state(state)
        logger.info("Incremental ingestion complete: %d chunks.", total_chunks)
        return {"new": len(new_files), "modified": len(modified_files), "chunks": total_chunks}
''',

    "retrieval/__init__.py": """from ate_rag_kb.retrieval.hybrid import HybridRetriever
from ate_rag_kb.retrieval.compression import ContextCompressor
from ate_rag_kb.retrieval.parent_child import ParentChildExpander

__all__ = ["HybridRetriever", "ContextCompressor", "ParentChildExpander"]
""",

    "retrieval/hybrid.py": '''"""Hybrid retrieval: vector search + BM25 keyword search + fusion."""

from __future__ import annotations

import logging
from typing import Any

import numpy as np
from rank_bm25 import BM25Okapi

from ate_rag_kb.chunking.models import Chunk
from ate_rag_kb.embedding.encoder import EmbeddingEncoder
from ate_rag_kb.utils.config import Config
from ate_rag_kb.vector_store.qdrant_client import QdrantVectorStore

logger = logging.getLogger(__name__)


class HybridRetriever:
    """Combines dense vector search with sparse BM25 keyword search."""

    def __init__(
        self,
        encoder: EmbeddingEncoder,
        vector_store: QdrantVectorStore,
        config: Config | None = None,
    ) -> None:
        cfg = config or Config({})
        self.encoder = encoder
        self.vector_store = vector_store
        self.vector_top_k = cfg.get("retrieval.vector_search.top_k", 20)
        self.bm25_top_k = cfg.get("retrieval.bm25_search.top_k", 20)
        self.vector_weight = cfg.get("retrieval.hybrid.vector_weight", 0.7)
        self.bm25_weight = cfg.get("retrieval.hybrid.bm25_weight", 0.3)
        self.final_top_k = cfg.get("retrieval.hybrid.final_top_k", 10)
        self.k1 = cfg.get("retrieval.bm25_search.k1", 1.5)
        self.b = cfg.get("retrieval.bm25_search.b", 0.75)

    def retrieve(
        self,
        query: str,
        top_k: int | None = None,
        filters: dict[str, Any] | None = None,
    ) -> list[Chunk]:
        """Retrieve chunks using hybrid fusion."""
        top_k = top_k or self.final_top_k

        query_vector = self.encoder.encode_query(query)
        vector_results = self.vector_store.search(
            query_vector.tolist(),
            top_k=self.vector_top_k,
            filters=filters,
        )

        bm25_results = self._bm25_search(query, vector_results)
        fused = self._reciprocal_rank_fusion(vector_results, bm25_results)
        return fused[:top_k]

    def _bm25_search(self, query: str, candidates: list[Chunk]) -> list[Chunk]:
        if not candidates:
            return []

        tokenized_corpus = [self._tokenize(c.content) for c in candidates]
        bm25 = BM25Okapi(tokenized_corpus, k1=self.k1, b=self.b)
        scores = bm25.get_scores(self._tokenize(query))

        scored = list(zip(candidates, scores))
        scored.sort(key=lambda x: x[1], reverse=True)
        return [c for c, _ in scored[:self.bm25_top_k]]

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        return text.lower().split()

    def _reciprocal_rank_fusion(
        self,
        vector_results: list[Chunk],
        bm25_results: list[Chunk],
    ) -> list[Chunk]:
        k = 60
        scores: dict[str, float] = {}

        for rank, chunk in enumerate(vector_results):
            scores[chunk.id] = scores.get(chunk.id, 0.0) + self.vector_weight * (1.0 / (k + rank + 1))

        for rank, chunk in enumerate(bm25_results):
            scores[chunk.id] = scores.get(chunk.id, 0.0) + self.bm25_weight * (1.0 / (k + rank + 1))

        id_to_chunk = {c.id: c for c in vector_results + bm25_results}
        sorted_ids = sorted(scores.keys(), key=lambda x: scores[x], reverse=True)
        return [id_to_chunk[cid] for cid in sorted_ids if cid in id_to_chunk]
''',

    "retrieval/reranker.py": '''"""Cross-encoder reranker for retrieved chunks."""

from __future__ import annotations

import logging
from typing import Any

from sentence_transformers import CrossEncoder

from ate_rag_kb.chunking.models import Chunk
from ate_rag_kb.utils.config import Config

logger = logging.getLogger(__name__)


class Reranker:
    """Rerank query-chunk pairs using a cross-encoder."""

    def __init__(self, config: Config | None = None) -> None:
        cfg = config or Config({})
        self.model_name = cfg.get("retrieval.reranker.model_name", "BAAI/bge-reranker-v2-m3")
        self.top_k = cfg.get("retrieval.reranker.top_k", 5)
        self.batch_size = cfg.get("retrieval.reranker.batch_size", 16)
        self._model: CrossEncoder | None = None

    @property
    def model(self) -> CrossEncoder:
        if self._model is None:
            logger.info("Loading reranker: %s", self.model_name)
            self._model = CrossEncoder(self.model_name)
        return self._model

    def rerank(self, query: str, chunks: list[Chunk], top_k: int | None = None) -> list[Chunk]:
        if not chunks:
            return []

        pairs = [(query, c.content) for c in chunks]
        scores = self.model.predict(pairs, batch_size=self.batch_size, show_progress_bar=False)

        scored = list(zip(chunks, scores))
        scored.sort(key=lambda x: x[1], reverse=True)

        tk = top_k or self.top_k
        return [c for c, _ in scored[:tk]]
''',

    "retrieval/parent_child.py": '''"""Parent-child chunk expansion for context enrichment."""

from __future__ import annotations

import logging
from typing import Any

from ate_rag_kb.chunking.models import Chunk
from ate_rag_kb.utils.config import Config
from ate_rag_kb.vector_store.qdrant_client import QdrantVectorStore

logger = logging.getLogger(__name__)


class ParentChildExpander:
    """Expand retrieved chunks with parent, sibling, and child context."""

    def __init__(self, config: Config | None = None) -> None:
        cfg = config or Config({})
        self.include_parent = cfg.get("retrieval.parent_child.include_parent", True)
        self.include_siblings = cfg.get("retrieval.parent_child.include_siblings", True)
        self.include_children = cfg.get("retrieval.parent_child.include_children", False)
        self.max_siblings = cfg.get("retrieval.parent_child.max_siblings", 2)

    def expand(
        self,
        chunks: list[Chunk],
        vector_store: QdrantVectorStore,
    ) -> list[Chunk]:
        """Expand chunks with related context."""
        result_ids: set[str] = set()
        ordered: list[Chunk] = []

        for chunk in chunks:
            if chunk.id not in result_ids:
                ordered.append(chunk)
                result_ids.add(chunk.id)

            if self.include_parent and chunk.parent_id:
                parent = vector_store.get_by_id(chunk.parent_id)
                if parent and parent.id not in result_ids:
                    ordered.append(parent)
                    result_ids.add(parent.id)

            if self.include_siblings:
                for sid in chunk.sibling_ids[:self.max_siblings]:
                    if sid not in result_ids:
                        sibling = vector_store.get_by_id(sid)
                        if sibling:
                            ordered.append(sibling)
                            result_ids.add(sid)

            if self.include_children:
                for cid in chunk.child_ids:
                    if cid not in result_ids:
                        child = vector_store.get_by_id(cid)
                        if child:
                            ordered.append(child)
                            result_ids.add(cid)

        return ordered
''',

    "retrieval/compression.py": '''"""Context compression: merge, deduplicate, truncate."""

from __future__ import annotations

import logging
from typing import Any

from ate_rag_kb.chunking.models import Chunk
from ate_rag_kb.utils.config import Config

logger = logging.getLogger(__name__)


class ContextCompressor:
    """Compress a list of chunks for LLM context window."""

    def __init__(self, config: Config | None = None) -> None:
        cfg = config or Config({})
        self.merge_adjacent = cfg.get("retrieval.compression.merge_adjacent", True)
        self.remove_duplicates = cfg.get("retrieval.compression.remove_duplicates", True)
        self.max_tokens = cfg.get("retrieval.compression.max_tokens", 4000)

    def compress(self, chunks: list[Chunk]) -> list[Chunk]:
        if not chunks:
            return []

        if self.remove_duplicates:
            seen: set[str] = set()
            unique: list[Chunk] = []
            for c in chunks:
                if c.id not in seen:
                    unique.append(c)
                    seen.add(c.id)
            chunks = unique

        if self.merge_adjacent:
            chunks = self._merge_adjacent(chunks)

        result: list[Chunk] = []
        total_tokens = 0
        for chunk in chunks:
            est_tokens = len(chunk.content) // 4
            if total_tokens + est_tokens > self.max_tokens:
                remaining = self.max_tokens - total_tokens
                if remaining > 100:
                    chunk.content = chunk.content[: remaining * 4]
                    result.append(chunk)
                break
            result.append(chunk)
            total_tokens += est_tokens

        return result

    @staticmethod
    def _merge_adjacent(chunks: list[Chunk]) -> list[Chunk]:
        if not chunks:
            return []

        merged: list[Chunk] = []
        current = chunks[0]

        for nxt in chunks[1:]:
            if (
                nxt.source_md == current.source_md
                and nxt.section_title == current.section_title
                and nxt.chunk_type == current.chunk_type
                and len(current.content) + len(nxt.content) < 3000
            ):
                current.content = current.content + "\n\n" + nxt.content
                current.end_line = nxt.end_line
                current.images = current.images + [i for i in nxt.images if i not in current.images]
                current.tables = current.tables + [t for t in nxt.tables if t not in current.tables]
                current.code_blocks = current.code_blocks + [c for c in nxt.code_blocks if c not in current.code_blocks]
            else:
                merged.append(current)
                current = nxt

        merged.append(current)
        return merged
''',
}


def main() -> None:
    raise SystemExit(
        "This bootstrap script is deprecated. It generates old scaffolds without "
        "ecosystem/software_version/doc_family fields. Do not use for production."
    )


if __name__ == "__main__":
    main()
