"""Incremental ingestion with change detection and profile-isolated state."""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from typing import Any

from ate_rag_kb.chunking.models import Chunk
from ate_rag_kb.ingestion.pipeline import IngestionPipeline
from ate_rag_kb.utils.config import Config

logger = logging.getLogger(__name__)

LEGACY_STATE_FILE = Path("./data/processed/ingestion_state.json")
STATE_DIR = Path("./data/processed")
DEFAULT_SCHEMA_VERSION = 6


def _compute_profile_key(config: Config) -> str:
    """Compute a short deterministic hash that identifies this ingestion profile.

    The profile covers vector-store backend, collection, embedding model,
    chunking strategy, and document scope so that switching any of them
    produces a separate state file and triggers a full rebuild.
    """
    mode = config.get("vector_store.mode")
    url = config.get("vector_store.url", "")
    host = config.get("vector_store.host", "localhost")
    port = config.get("vector_store.port", 6333)
    local_path = config.get("vector_store.local_path", "")
    use_local = config.get("vector_store.use_local", False)

    # Normalize legacy mode
    if mode is None:
        mode = "local" if use_local else "server"

    collection = config.get("vector_store.collection_name", "ate_kb")
    endpoint = (
        url if mode == "server" and url else (f"{host}:{port}" if mode == "server" else local_path)
    )
    embedding_model = config.get("embedding.model_name", "")
    chunking_strategies = config.get("chunking.strategies", {})
    chunking_hash = hashlib.sha256(
        json.dumps(chunking_strategies, sort_keys=True).encode()
    ).hexdigest()[:16]
    documents = config.get("documents", {})
    documents_hash = hashlib.sha256(json.dumps(documents, sort_keys=True).encode()).hexdigest()[:16]
    schema_version = config.get("ingestion.schema_version", DEFAULT_SCHEMA_VERSION)

    raw = f"{mode}:{collection}:{endpoint}:{embedding_model}:{chunking_hash}:{documents_hash}:{schema_version}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def _get_state_file(config: Config) -> Path:
    """Return the profile-specific state file path."""
    profile_key = _compute_profile_key(config)
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    return STATE_DIR / f"state_{profile_key}.json"


def _build_profile(config: Config) -> dict[str, Any]:
    """Build the profile metadata dict stored inside the state file."""
    mode = config.get("vector_store.mode")
    url = config.get("vector_store.url", "")
    host = config.get("vector_store.host", "localhost")
    port = config.get("vector_store.port", 6333)
    local_path = config.get("vector_store.local_path", "")
    use_local = config.get("vector_store.use_local", False)

    # Normalize legacy mode
    if mode is None:
        mode = "local" if use_local else "server"

    endpoint = (
        url if mode == "server" and url else (f"{host}:{port}" if mode == "server" else local_path)
    )
    documents = config.get("documents", {})
    return {
        "mode": mode,
        "collection_name": config.get("vector_store.collection_name", "ate_kb"),
        "endpoint": endpoint,
        "embedding_model": config.get("embedding.model_name", ""),
        "schema_version": config.get("ingestion.schema_version", DEFAULT_SCHEMA_VERSION),
        "documents_hash": hashlib.sha256(
            json.dumps(documents, sort_keys=True).encode()
        ).hexdigest()[:16],
    }


class IncrementalIngestion:
    """Track file changes and only ingest new/modified documents.

    State is isolated per ingestion profile (backend + collection + model +
    chunking + document scope).  Switching profiles never reuses old state,
    and the first run with a new profile always performs a full rebuild.
    """

    def __init__(
        self,
        pipeline: IngestionPipeline,
        state_file: Path | None = None,
    ) -> None:
        self.pipeline = pipeline
        self.config = pipeline.config
        self.state_file = state_file or _get_state_file(self.config)
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        self._maybe_rename_legacy_state()

    def _maybe_rename_legacy_state(self) -> None:
        """Rename the old monolithic state file to .legacy once."""
        if LEGACY_STATE_FILE.exists():
            legacy = LEGACY_STATE_FILE.with_suffix(".json.legacy")
            LEGACY_STATE_FILE.rename(legacy)
            logger.info("Renamed legacy state file to %s", legacy)

    def state_exists(self) -> bool:
        """Return True if a state file exists for the current profile."""
        return self.state_file.exists()

    def needs_full_rebuild(self) -> bool:
        """Return True when no valid state exists for the current profile.

        This happens on first run with a new profile or when the profile
        metadata stored inside the state file does not match the current
        configuration.
        """
        if not self.state_file.exists():
            return True
        state = self._load_state()
        stored_profile = state.get("_profile", {})
        current_profile = _build_profile(self.config)
        if stored_profile != current_profile:
            logger.warning(
                "Profile mismatch detected (stored %s vs current %s). Triggering full rebuild.",
                stored_profile,
                current_profile,
            )
            return True
        return False

    def _load_state(self) -> dict[str, Any]:
        if self.state_file.exists():
            return json.loads(self.state_file.read_text(encoding="utf-8"))
        return {}

    def _save_state(self, state: dict[str, Any]) -> None:
        self.state_file.write_text(json.dumps(state, indent=2), encoding="utf-8")

    def mark_all_files_current(self, markdown_dir: Path) -> None:
        """Record the current markdown tree as already ingested for this profile."""
        file_states = {
            str(md_path.relative_to(markdown_dir)): md_path.stat().st_mtime
            for md_path in sorted(markdown_dir.rglob("*.md"))
        }
        self._save_state(
            {
                "_profile": _build_profile(self.config),
                "files": file_states,
            }
        )

    def scan_for_changes(
        self,
        markdown_dir: Path,
    ) -> tuple[list[Path], list[Path], list[str]]:
        """Return (new_files, modified_files, deleted_source_mds)."""
        state = self._load_state()
        file_states = state.get("files", {})
        new_files: list[Path] = []
        modified_files: list[Path] = []
        current_files: set[str] = set()

        for md_path in sorted(markdown_dir.rglob("*.md")):
            rel = str(md_path.relative_to(markdown_dir))
            current_files.add(rel)
            mtime = md_path.stat().st_mtime
            if rel not in file_states:
                new_files.append(md_path)
            elif mtime > file_states[rel]:
                modified_files.append(md_path)

        deleted_files = sorted(set(file_states) - current_files)
        return new_files, modified_files, deleted_files

    def run_incremental(
        self,
        markdown_dir: Path,
        json_dir: Path | None = None,
        batch_size: int = 1000,
    ) -> dict[str, int]:
        """Ingest only changed documents."""
        new_files, modified_files, deleted_files = self.scan_for_changes(markdown_dir)
        logger.info(
            "Incremental scan: %d new, %d modified, %d deleted",
            len(new_files),
            len(modified_files),
            len(deleted_files),
        )

        # Ensure sparse vocab is available before upserting
        self.pipeline._ensure_sparse_vocab(markdown_dir)

        state = self._load_state()
        file_states: dict[str, float] = state.get("files", {})
        state["_profile"] = _build_profile(self.config)
        failed_count = 0

        for rel in deleted_files:
            try:
                self.pipeline.vector_store.delete_by_source(rel)
                file_states.pop(rel, None)
                logger.info("Deleted chunks for removed file: %s", rel)
            except Exception as exc:
                logger.error("Failed to delete chunks for removed file %s: %s", rel, exc)
                failed_count += 1

        if deleted_files:
            state["files"] = file_states
            self._save_state(state)

        # Delete old chunks for modified files first
        for md_path in modified_files:
            rel = str(md_path.relative_to(markdown_dir))
            try:
                self.pipeline.vector_store.delete_by_source(rel)
                logger.info("Deleted old chunks for modified file: %s", rel)
            except Exception as exc:
                logger.error("Failed to delete old chunks for %s: %s", rel, exc)

        batch_chunks: list[Chunk] = []
        batch_rels: list[str] = []
        total_chunks = 0
        successful_rels: list[str] = []

        # Helper to persist state immediately after a batch succeeds
        def _commit_batch(successful_batch_rels: list[str]) -> None:
            for r in successful_batch_rels:
                file_states[r] = (markdown_dir / r).stat().st_mtime
            state["files"] = file_states
            self._save_state(state)

        for md_path in new_files + modified_files:
            rel = str(md_path.relative_to(markdown_dir))
            json_path = None
            if json_dir:
                json_path = json_dir / md_path.relative_to(markdown_dir).with_suffix(".json")

            platform = self.pipeline._detect_platform(md_path)
            doc_type = self.pipeline._detect_doc_type(md_path)

            # Step 1: chunk document (failure isolated to current file)
            try:
                chunks = self.pipeline._chunk_document(md_path, json_path, platform, doc_type)
            except Exception as exc:
                logger.error("Failed to chunk %s: %s", rel, exc)
                failed_count += 1
                continue

            batch_chunks.extend(chunks)
            batch_rels.append(rel)

            # Step 2: embed and upsert when batch is full (failure isolated to current batch)
            if len(batch_chunks) >= batch_size:
                try:
                    self.pipeline._embed_and_upsert(batch_chunks)
                    total_chunks += len(batch_chunks)
                    successful_rels.extend(batch_rels)
                    _commit_batch(batch_rels)
                except Exception as exc:
                    logger.error("Failed to embed batch ending at %s: %s", rel, exc)
                    failed_count += len(batch_rels)
                batch_chunks = []
                batch_rels = []

        # Flush remaining chunks
        if batch_chunks:
            try:
                self.pipeline._embed_and_upsert(batch_chunks)
                total_chunks += len(batch_chunks)
                successful_rels.extend(batch_rels)
                _commit_batch(batch_rels)
            except Exception as exc:
                logger.error("Failed to embed final batch: %s", exc)
                failed_count += len(batch_rels)
            batch_chunks = []
            batch_rels = []

        if total_chunks:
            logger.info(
                "Upserted %d chunks for %d changed files",
                total_chunks,
                len(successful_rels),
            )

        # Rebuild document graph to reflect any changed links.
        if new_files or modified_files or deleted_files:
            self.pipeline._build_document_graph(markdown_dir, json_dir)
            self.pipeline._build_symbol_catalog(markdown_dir, json_dir)

        logger.info("Incremental ingestion complete.")
        return {
            "new": len(new_files),
            "modified": len(modified_files),
            "deleted": len(deleted_files),
            "chunks": total_chunks,
            "failed": failed_count,
        }
