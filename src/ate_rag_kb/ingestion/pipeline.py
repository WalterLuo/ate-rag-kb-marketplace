"""Markdown ingestion pipeline."""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

from tqdm import tqdm

from ate_rag_kb.chunking.models import Chunk
from ate_rag_kb.chunking.strategies import HierarchicalChunker
from ate_rag_kb.domain.scopes import TERADYNE_J750_IGXL, RetrievalScope
from ate_rag_kb.embedding.encoder import EmbeddingEncoder
from ate_rag_kb.ingestion.document_graph import DocumentGraphBuilder
from ate_rag_kb.ingestion.symbol_catalog import SymbolCatalogBuilder
from ate_rag_kb.utils.config import Config
from ate_rag_kb.utils.scope import DocumentScope
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
        toc_tree: dict[str, Any] | None = None,
        href_map: dict[str, Any] | None = None,
    ) -> None:
        self.config = config
        self.encoder = encoder
        self.vector_store = vector_store
        self.chunker = chunker or HierarchicalChunker(config)
        self._href_to_node = self._build_href_index(toc_tree)
        self._href_to_abs_path = self._build_abs_path_index(href_map)

    @staticmethod
    def _build_href_index(tree: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
        """Build a flat href -> node_info index from nested toc_tree."""
        if not tree:
            return {}
        index: dict[str, dict[str, Any]] = {}

        def walk(node: dict[str, Any], parent_href: str | None = None) -> None:
            href = node.get("href", "")
            if href:
                index[href] = {
                    "label": node.get("label", ""),
                    "parent_href": parent_href,
                    "child_hrefs": [
                        c.get("href", "") for c in node.get("children", []) if c.get("href")
                    ],
                }
            for child in node.get("children", []):
                walk(child, href)

        walk(tree)
        return index

    @staticmethod
    def _build_abs_path_index(href_map: dict[str, Any] | None) -> dict[str, str]:
        """Build href -> absolute source path index from href_map."""
        if not href_map:
            return {}
        index: dict[str, str] = {}
        for abs_path, node in href_map.items():
            href = node.get("href", "")
            if href:
                index[href] = abs_path
        return index

    def _chunk_document(
        self,
        md_path: Path,
        json_path: Path | None = None,
        platform: str = "",
        doc_type: str = "",
    ) -> list[Chunk]:
        """Read and chunk a markdown document without embedding."""
        md_text = md_path.read_text(encoding="utf-8")

        metadata: dict[str, Any] = {}
        if json_path and json_path.exists():
            doc_meta = json.loads(json_path.read_text(encoding="utf-8"))
            # Flatten key fields from per-document JSON
            metadata["doc_title"] = doc_meta.get("title", "")
            metadata["toc_path"] = doc_meta.get("toc_path", [])
            metadata["source_html"] = doc_meta.get("source_html", "")
            metadata["images"] = doc_meta.get("images", [])
            # Merge remaining fields for downstream use
            for key, value in doc_meta.items():
                if key not in metadata:
                    metadata[key] = value

        source_md = str(md_path.relative_to(self.config.get("data.markdown_dir", ".")))
        source_json = (
            str(json_path.relative_to(self.config.get("data.json_dir", "."))) if json_path else ""
        )

        metadata["source_md"] = source_md
        metadata["source_json"] = source_json

        # Detect canonical scope and preserve compatibility metadata.
        scope = self._detect_scope(source_md, metadata.get("doc_title", ""), metadata)
        vendor = scope.vendor if scope else ""
        canonical_platform = scope.platform if scope else ""
        software = scope.software if scope else ""
        software_release = scope.software_release if scope else ""
        ecosystem = (
            "igxl" if software == "igxl" else "v93000" if canonical_platform == "v93000" else ""
        )
        software_version = software if software in {"smt7", "smt8"} else ""
        doc_family = self._detect_doc_family(source_md, metadata.get("doc_title", ""), metadata)

        metadata["vendor"] = vendor
        metadata["platform"] = canonical_platform
        metadata["software"] = software
        metadata["software_release"] = software_release
        metadata["ecosystem"] = ecosystem
        metadata["software_version"] = software_version
        metadata["doc_family"] = doc_family

        # Skip documents outside enabled scope
        if not DocumentScope(self.config).should_ingest_scope(md_path, scope):
            return []

        # Derive platform tags from source path for downstream filtering
        if "tags" not in metadata:
            metadata["tags"] = []
        if source_md.startswith("igxl/") and "ig-xl" not in metadata["tags"]:
            metadata["tags"].append("ig-xl")
        elif source_md.startswith("v93000/smt7/"):
            if "v93000" not in metadata["tags"]:
                metadata["tags"].append("v93000")
            if "smt7" not in metadata["tags"]:
                metadata["tags"].append("smt7")
        elif source_md.startswith("v93000/smt8/"):
            if "v93000" not in metadata["tags"]:
                metadata["tags"].append("v93000")
            if "smt8" not in metadata["tags"]:
                metadata["tags"].append("smt8")
        elif source_md.startswith("smt7/") and "smt7" not in metadata["tags"]:
            metadata["tags"].append("smt7")
        elif source_md.startswith("v93000/") and "v93000" not in metadata["tags"]:
            metadata["tags"].append("v93000")
        elif source_md.startswith("tdc/") and "tdc" not in metadata["tags"]:
            metadata["tags"].append("tdc")

        # Enrich with toc_tree parent/child relationships
        source_html = metadata.get("source_html", "")
        if source_html and self._href_to_node:
            node_info = self._href_to_node.get(source_html)
            if node_info:
                metadata["toc_parent_href"] = node_info.get("parent_href", "")
                metadata["toc_child_hrefs"] = node_info.get("child_hrefs", [])
                logger.debug(
                    "TOC enrichment for %s: parent=%s children=%d",
                    source_html,
                    node_info.get("parent_href"),
                    len(node_info.get("child_hrefs", [])),
                )

        # Source trace via href_map (available in metadata for API layer)
        if source_html and self._href_to_abs_path:
            abs_path = self._href_to_abs_path.get(source_html)
            if abs_path:
                metadata["source_html_path"] = abs_path

        chunks = self.chunker.chunk(
            text=md_text,
            metadata=metadata,
        )

        # Keep the platform argument for legacy callers; canonical scope wins for ingested docs.
        for chunk in chunks:
            chunk.vendor = vendor
            chunk.platform = canonical_platform
            chunk.software = software
            chunk.software_release = software_release
            if not chunk.doc_type:
                chunk.doc_type = doc_type

        return chunks

    def _embed_and_upsert(self, chunks: list[Chunk]) -> None:
        """Compute embeddings and upsert chunks into the vector store."""
        if not chunks:
            return
        try:
            texts = [c.content for c in chunks]
            embeddings = self.encoder.encode(texts)
            for chunk, emb in zip(chunks, embeddings, strict=False):
                chunk.embedding = emb.tolist()
            self.vector_store.upsert_chunks(chunks)
        except RuntimeError as exc:
            message = str(exc).lower()
            is_memory_error = any(
                marker in message
                for marker in [
                    "invalid buffer size",
                    "out of memory",
                    "mps backend out of memory",
                ]
            )
            if not is_memory_error or len(chunks) == 1:
                raise

            midpoint = len(chunks) // 2
            logger.warning(
                "Embedding batch of %d chunks exceeded device memory; retrying as %d + %d.",
                len(chunks),
                midpoint,
                len(chunks) - midpoint,
            )
            self._embed_and_upsert(chunks[:midpoint])
            self._embed_and_upsert(chunks[midpoint:])

    def ingest_document(
        self,
        md_path: Path,
        json_path: Path | None = None,
        platform: str = "",
        doc_type: str = "",
    ) -> list[Chunk]:
        """Ingest a single markdown document."""
        chunks = self._chunk_document(md_path, json_path, platform, doc_type)
        self._embed_and_upsert(chunks)
        return chunks

    def _ensure_sparse_vocab(self, markdown_dir: Path, *, force: bool = False) -> None:
        """Fit sparse encoder vocabulary from all markdown files when needed."""
        if not getattr(self.vector_store, "enable_sparse_vectors", True):
            return
        if self.vector_store.sparse_encoder.is_fitted() and not force:
            return
        md_files = sorted(markdown_dir.rglob("*.md"))
        texts: list[str] = []
        for md_path in md_files:
            try:
                texts.append(md_path.read_text(encoding="utf-8"))
            except Exception:
                continue
        if texts:
            self.vector_store.sparse_encoder.fit(texts)
            logger.info("Fitted sparse vocab from %d documents", len(texts))

    def rebuild_sparse_vocabulary(self, markdown_dir: Path) -> None:
        """Rebuild the persisted sparse vocabulary from the current corpus."""
        self._ensure_sparse_vocab(markdown_dir, force=True)

    def _build_document_graph(
        self,
        markdown_dir: Path,
        json_dir: Path | None = None,
    ) -> None:
        """Build and persist cross-document link graph."""
        try:
            graph_builder = DocumentGraphBuilder(
                markdown_dir=markdown_dir,
                json_dir=json_dir,
            )
            processed_dir = Path(self.config.get("data.processed_dir", "./data/processed"))
            processed_dir.mkdir(parents=True, exist_ok=True)
            graph_builder.save(processed_dir / "document_graph.json")
            logger.info("Built document graph")
        except Exception as exc:
            logger.warning("Failed to build document graph: %s", exc)

    def _build_symbol_catalog(
        self,
        markdown_dir: Path,
        json_dir: Path | None = None,
    ) -> None:
        """Build and persist exclusive symbol ownership catalog."""
        try:
            catalog = SymbolCatalogBuilder(
                markdown_dir=markdown_dir,
                json_dir=json_dir,
                scope_resolver=self._detect_scope,
            ).build()
            processed_dir = Path(self.config.get("data.processed_dir", "./data/processed"))
            catalog.save(processed_dir / "symbol_catalog.json")
            logger.info("Built symbol ownership catalog")
        except Exception as exc:
            logger.warning("Failed to build symbol ownership catalog: %s", exc)

    def ingest_directory(
        self,
        markdown_dir: Path,
        json_dir: Path | None = None,
        batch_size: int = 1000,
    ) -> int:
        """Batch ingest all markdown files in a directory with batched embedding."""
        md_files = sorted(markdown_dir.rglob("*.md"))
        logger.info("Found %d markdown files in %s", len(md_files), markdown_dir)

        self._ensure_sparse_vocab(markdown_dir)

        total_chunks = 0
        batch_chunks: list[Chunk] = []

        for md_path in tqdm(md_files, desc="Ingesting"):
            json_path = None
            if json_dir:
                rel = md_path.relative_to(markdown_dir)
                json_path = json_dir / rel.with_suffix(".json")

            platform = self._detect_platform(md_path)
            doc_type = self._detect_doc_type(md_path)

            try:
                chunks = self._chunk_document(md_path, json_path, platform, doc_type)
            except Exception as exc:
                logger.error("Failed to chunk %s: %s", md_path, exc)
                continue

            batch_chunks.extend(chunks)

            if len(batch_chunks) >= batch_size:
                try:
                    self._embed_and_upsert(batch_chunks)
                    total_chunks += len(batch_chunks)
                except Exception as exc:
                    logger.error("Failed to embed batch containing %s: %s", md_path, exc)
                batch_chunks = []

        # Flush remaining chunks
        if batch_chunks:
            try:
                self._embed_and_upsert(batch_chunks)
                total_chunks += len(batch_chunks)
            except Exception as exc:
                logger.error("Failed to embed final batch: %s", exc)
            batch_chunks = []

        logger.info("Ingested %d chunks total.", total_chunks)

        self._build_document_graph(markdown_dir, json_dir)
        self._build_symbol_catalog(markdown_dir, json_dir)

        return total_chunks

    @staticmethod
    def _detect_platform(path: Path) -> str:
        name = path.name.lower()
        path_str = str(path).lower()
        if "igxl" in path_str:
            return "J750"
        if "j750" in name or "ultraflex" in name:
            return "J750"
        if "smt8" in path_str or "smt7" in path_str:
            return "V93000"
        if "v93000" in path_str or "smartest" in name:
            return "V93000"
        if "tdc" in name:
            # TDC is a document family under the V93000/SmarTest ecosystem,
            # not an independent tester platform.
            return "V93000"
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

    @staticmethod
    def _detect_ecosystem(source_md: str, doc_title: str, json_meta: dict[str, Any]) -> str:
        """Infer ecosystem from source path, filename, toc_path, title, or JSON metadata."""
        name = source_md.lower()
        if source_md.startswith("igxl/"):
            return "igxl"
        if source_md.startswith("v93000/"):
            return "v93000"
        if "smartest64_7" in name or "smartest64_8" in name or "smt7/" in name or "smt8/" in name:
            return "v93000"
        if source_md.startswith("tdc/"):
            return "v93000"

        # Search toc_path and title for ecosystem indicators
        haystacks = [doc_title, json_meta.get("title", "")]
        haystacks.extend(json_meta.get("toc_path", []))
        for text in haystacks:
            text_lower = text.lower()
            if "ig-xl" in text_lower or "igxl" in text_lower:
                return "igxl"
            if "smartest" in text_lower or "v93000" in text_lower:
                return "v93000"

        # Fallback to explicit JSON metadata
        eco = json_meta.get("ecosystem", "")
        if eco:
            return eco
        if IngestionPipeline._is_root_smt7_document(name):
            return "v93000"
        return ""

    @staticmethod
    def _detect_software_version(source_md: str, doc_title: str, json_meta: dict[str, Any]) -> str:
        """Infer software version from source path, filename, toc_path, title, or JSON metadata."""
        name = source_md.lower()
        if (
            source_md.startswith("v93000/smt7/")
            or source_md.startswith("smt7/")
            or "smartest64_7" in name
        ):
            return "smt7"
        if (
            source_md.startswith("v93000/smt8/")
            or source_md.startswith("smt8/")
            or "smartest64_8" in name
        ):
            return "smt8"

        # Search toc_path and title for version indicators
        haystacks = [doc_title, json_meta.get("title", "")]
        haystacks.extend(json_meta.get("toc_path", []))
        for text in haystacks:
            text_lower = text.lower()
            # Only match version numbers in V93000/SmarTest context
            if "smartest" in text_lower or "smt" in text_lower or "v93000" in text_lower:
                if any(
                    v in text_lower
                    for v in [" 7.", "7.4", "7.x", "7.0", "7.1", "7.2", "7.3", "7.5"]
                ):
                    return "smt7"
                if any(v in text_lower for v in [" 8.", "8.x", "8.0", "8.1"]):
                    return "smt8"

        sv = json_meta.get("software_version", "")
        if sv:
            return sv
        if IngestionPipeline._is_root_smt7_document(name):
            return "smt7"
        return ""

    def _detect_scope(
        self,
        source_md: str,
        doc_title: str,
        metadata: dict[str, Any],
    ) -> RetrievalScope | None:
        """Infer canonical retrieval scope while retaining metadata-aware detection."""
        ecosystem = self._detect_ecosystem(source_md, doc_title, metadata)
        software = self._detect_software_version(source_md, doc_title, metadata)
        if ecosystem == "igxl":
            return TERADYNE_J750_IGXL
        if ecosystem == "v93000":
            return RetrievalScope("advantest", "v93000", software)
        return None

    @staticmethod
    def _detect_doc_family(source_md: str, doc_title: str, json_meta: dict[str, Any]) -> str:
        """Infer document family from source path, toc_path, title, or JSON metadata."""
        if source_md.startswith("igxl/"):
            return "igxl_help"
        if source_md.startswith("tdc/"):
            return "tdc"

        # Search toc_path and title for family indicators
        haystacks = [doc_title, json_meta.get("title", "")]
        haystacks.extend(json_meta.get("toc_path", []))
        for text in haystacks:
            text_lower = text.lower()
            if "ig-xl" in text_lower or "igxl" in text_lower:
                return "igxl_help"
            if "tdc" in text_lower:
                return "tdc"

        df = json_meta.get("doc_family", "")
        if df:
            return df
        return ""

    @staticmethod
    def _is_root_smt7_document(source_md_lower: str) -> bool:
        """Return True for legacy root-level SmarTest 7 markdown files."""
        if "/" in source_md_lower:
            return False
        if re.fullmatch(r"\d+(?:_\d+)?\.md", source_md_lower):
            return True
        return bool(
            re.fullmatch(r"header_feature_rel7\.[^.]+(?:\.[^.]+)*\.md", source_md_lower)
            or re.fullmatch(r"releasenote_.*rel7\.[^.]+(?:\.[^.]+)*\.md", source_md_lower)
            or re.fullmatch(r"luna_7\.[^.]+(?:\.[^.]+)*\.readme\.md", source_md_lower)
        )

    def _should_ingest(self, path: Path, ecosystem: str, software_version: str) -> bool:
        """Return False if document is outside enabled ecosystems or software versions."""
        return DocumentScope(self.config).shouldIngest(path, ecosystem, software_version)
