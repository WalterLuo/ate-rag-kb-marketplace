#!/usr/bin/env python3
"""Verify model cache integrity for offline use.

Checks:
- Required model snapshots exist
- No unresolved symlinks
- Weight files meet minimum size thresholds
- Optional manifest SHA-256 hashes match

Usage:
    uv run python scripts/verify_models.py
    uv run python scripts/verify_models.py --skip-load
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

_MIN_WEIGHT_FILE_SIZE = 10 * 1024 * 1024  # 10 MiB

_REQUIRED_MODELS = [
    "BAAI/bge-m3",
    "BAAI/bge-reranker-v2-m3",
]

_WEIGHT_EXTENSIONS = (".safetensors", ".bin")

_KNOWN_SMALL_FILES = (
    "config.json",
    "tokenizer.json",
    "tokenizer_config.json",
    "special_tokens_map.json",
    "vocab.txt",
    "sentence_bert_config.json",
    "modules.json",
    "tokenizer.model",
    "generation_config.json",
    "model.safetensors.index.json",
    "pytorch_model.bin.index.json",
    "preprocessor_config.json",
    "special_tokens_map.json",
    "tokenizer_class.json",
    "added_tokens.json",
)


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(65536)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def verify_structure(cache_dir: Path) -> list[str]:
    """Verify cache directory structure without loading ML libraries."""
    errors: list[str] = []

    if not cache_dir.exists():
        errors.append(f"Cache directory does not exist: {cache_dir}")
        return errors

    for model_name in _REQUIRED_MODELS:
        safe_name = model_name.replace("/", "--")
        model_dir = cache_dir / f"models--{safe_name}"

        if not model_dir.exists():
            errors.append(f"Missing model directory: {model_name} ({model_dir})")
            continue

        snapshots_dir = model_dir / "snapshots"
        if not snapshots_dir.exists():
            errors.append(f"Missing snapshots directory for {model_name}")
            continue

        valid_snapshots = [
            s for s in snapshots_dir.iterdir()
            if s.is_dir() and (s / "config.json").exists()
        ]
        if not valid_snapshots:
            errors.append(f"No valid snapshot with config.json for {model_name}")
            continue

        for snapshot in valid_snapshots:
            for root, _dirs, files in _walk_snapshot(snapshot):
                for fname in files:
                    fpath = root / fname
                    rel = fpath.relative_to(snapshot)

                    # Check for unresolved symlinks
                    if fpath.is_symlink() and not fpath.exists():
                        errors.append(
                            f"Unresolved symlink in {model_name}: {rel} "
                            f"-> {fpath.resolve()}"
                        )
                        continue

                    # Check weight file sizes
                    if (
                        fname.endswith(_WEIGHT_EXTENSIONS)
                        and fname not in _KNOWN_SMALL_FILES
                        and fpath.exists()
                    ):
                        file_size = fpath.stat().st_size
                        if file_size < _MIN_WEIGHT_FILE_SIZE:
                            errors.append(
                                f"Suspiciously small weight file in {model_name}: "
                                f"{rel} ({file_size} bytes, min {_MIN_WEIGHT_FILE_SIZE})"
                            )

    return errors


def verify_manifest(cache_dir: Path) -> list[str]:
    """Verify the optional manifest file if present."""
    errors: list[str] = []
    manifest_path = cache_dir / "ate_kb_model_manifest.json"

    if not manifest_path.exists():
        logger.info("No manifest file found at %s — skipping manifest verification", manifest_path)
        return errors

    try:
        manifest = json.loads(manifest_path.read_text())
    except json.JSONDecodeError as exc:
        errors.append(f"Invalid manifest JSON: {exc}")
        return errors

    models = manifest.get("models", {})
    for _model_name, model_data in models.items():
        for _snapshot_hash, files in model_data.get("snapshots", {}).items():
            for file_entry in files:
                file_path = cache_dir / file_entry["path"]
                if not file_path.exists():
                    errors.append(
                        f"Manifest references missing file: {file_entry['path']}"
                    )
                    continue

                expected_size = file_entry.get("size")
                if expected_size is not None:
                    actual_size = file_path.stat().st_size
                    if actual_size != expected_size:
                        errors.append(
                            f"Size mismatch for {file_entry['path']}: "
                            f"expected {expected_size}, got {actual_size}"
                        )

                expected_hash = file_entry.get("sha256")
                if expected_hash is not None:
                    actual_hash = _sha256_file(file_path)
                    if actual_hash != expected_hash:
                        errors.append(
                            f"SHA-256 mismatch for {file_entry['path']}: "
                            f"expected {expected_hash}, got {actual_hash}"
                        )

    return errors


def verify_loadable(cache_dir: Path) -> list[str]:
    """Verify models can actually be loaded (requires ML libraries)."""
    errors: list[str] = []
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError:
        errors.append("sentence-transformers not installed; cannot verify model loading")
        return errors

    for model_name in _REQUIRED_MODELS:
        safe_name = model_name.replace("/", "--")
        model_dir = cache_dir / f"models--{safe_name}"
        snapshots_dir = model_dir / "snapshots"

        if not snapshots_dir.exists():
            continue

        for snapshot in sorted(snapshots_dir.iterdir()):
            if snapshot.is_dir() and (snapshot / "config.json").exists():
                try:
                    SentenceTransformer(
                        str(snapshot),
                        cache_folder=str(cache_dir),
                        local_files_only=True,
                    )
                    logger.info("Verified loadable: %s (%s)", model_name, snapshot.name)
                except Exception as exc:
                    errors.append(f"Failed to load {model_name} from {snapshot}: {exc}")
                break

    return errors


def _walk_snapshot(snapshot_dir: Path):
    """Walk a snapshot directory yielding (root, dirs, files)."""
    import os
    for root, dirs, files in os.walk(snapshot_dir):
        yield Path(root), dirs, files


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    parser = argparse.ArgumentParser(description="Verify model cache integrity")
    parser.add_argument(
        "--cache-dir", default="./embeddings/cache",
        help="Model cache directory (default: ./embeddings/cache)",
    )
    parser.add_argument(
        "--skip-load", action="store_true",
        help="Skip loading models (structure-only check)",
    )
    args = parser.parse_args()

    cache_dir = Path(args.cache_dir)
    all_errors: list[str] = []

    print(f"Verifying model cache at: {cache_dir}")
    print()

    print("Checking structure...")
    structure_errors = verify_structure(cache_dir)
    all_errors.extend(structure_errors)
    _print_results("Structure", structure_errors)

    print("Checking manifest...")
    manifest_errors = verify_manifest(cache_dir)
    all_errors.extend(manifest_errors)
    _print_results("Manifest", manifest_errors)

    if not args.skip_load:
        print("Checking model loading...")
        load_errors = verify_loadable(cache_dir)
        all_errors.extend(load_errors)
        _print_results("Load", load_errors)
    else:
        print("Skipping model loading (--skip-load)")

    print()
    if all_errors:
        print(f"FAILED: {len(all_errors)} error(s) found", file=sys.stderr)
        sys.exit(1)
    else:
        print("PASSED: All checks passed")


def _print_results(check_name: str, errors: list[str]) -> None:
    if errors:
        print(f"  {check_name}: {len(errors)} error(s)")
        for err in errors:
            print(f"    - {err}")
    else:
        print(f"  {check_name}: OK")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
