#!/usr/bin/env python3
"""Package embedding and reranker model caches for offline distribution.

Stages model files from a Hugging Face cache directory into a clean archive
with symlink resolution, validation, and a manifest.

Usage:
    uv run python scripts/package_models.py \\
        --cache-dir ./embeddings/cache \\
        --output dist \\
        --name ate-kb-model-cache \\
        --format zip
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import shutil
import sys
import zipfile
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Minimum size (bytes) for weight files to be considered valid
_MIN_WEIGHT_FILE_SIZE = 10 * 1024 * 1024  # 10 MiB

# Weight file extensions that must pass size checks
_WEIGHT_EXTENSIONS = (".safetensors", ".bin")

# Patterns to exclude from the archive
_EXCLUDE_PATTERNS = (
    ".locks",
    ".no_exist",
    "refs",
    ".DS_Store",
    "CACHEDIR.TAG",
    "__pycache__",
    ".pyc",
)

# Known non-weight file patterns that are small but valid
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


def _should_exclude(path: Path) -> bool:
    """Return True if path matches an exclusion pattern."""
    parts = path.parts
    for part in parts:
        if any(part == pattern for pattern in _EXCLUDE_PATTERNS):
            return True
    return any(path.name == pattern for pattern in _EXCLUDE_PATTERNS)


def _is_weight_file(path: Path) -> bool:
    """Return True if the file looks like a model weight file."""
    return path.name.endswith(_WEIGHT_EXTENSIONS)


def _is_known_small_file(path: Path) -> bool:
    """Return True if the file is a known non-weight config/metadata file."""
    return path.name in _KNOWN_SMALL_FILES


def _sha256_file(path: Path) -> str:
    """Compute SHA-256 hex digest of a file."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(65536)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def stage_models(
    cache_dir: Path,
    staging_dir: Path,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Stage model files from cache into a clean staging directory.

    Returns (manifest_entries, errors).
    """
    manifest_entries: list[dict[str, Any]] = []
    errors: list[str] = []

    if not cache_dir.exists():
        errors.append(f"Cache directory does not exist: {cache_dir}")
        return manifest_entries, errors

    # Find model directories (models--*)
    model_dirs = sorted(
        d for d in cache_dir.iterdir()
        if d.is_dir() and d.name.startswith("models--")
    )

    if not model_dirs:
        errors.append(f"No model directories found in {cache_dir}")
        return manifest_entries, errors

    for model_dir in model_dirs:
        model_name = model_dir.name.replace("models--", "").replace("--", "/")
        logger.info("Staging model: %s", model_name)

        snapshots_dir = model_dir / "snapshots"
        if not snapshots_dir.exists():
            errors.append(f"No snapshots directory for {model_name} at {snapshots_dir}")
            continue

        for snapshot in sorted(snapshots_dir.iterdir()):
            if not snapshot.is_dir():
                continue
            if not (snapshot / "config.json").exists():
                errors.append(
                    f"Skipping snapshot without config.json: {snapshot}"
                )
                continue

            # Check for unresolved symlinks
            for root, _dirs, files in os.walk(snapshot):
                for fname in files:
                    fpath = Path(root) / fname
                    if fpath.is_symlink() and not fpath.exists():
                        errors.append(
                            f"Unresolved symlink: {fpath} -> {os.readlink(fpath)}"
                        )

            # Stage files
            dest_snapshot = staging_dir / "embeddings" / "cache" / model_dir.name / "snapshots" / snapshot.name
            for root, _dirs, files in os.walk(snapshot):
                rel_root = Path(root).relative_to(snapshot)
                for fname in files:
                    src = Path(root) / fname
                    rel_path = rel_root / fname

                    if _should_exclude(rel_path):
                        continue

                    dst = dest_snapshot / rel_path
                    dst.parent.mkdir(parents=True, exist_ok=True)

                    if src.is_symlink():
                        # Resolve symlink to real file
                        real_target = src.resolve()
                        if not real_target.exists():
                            errors.append(
                                f"Broken symlink: {src} -> {real_target}"
                            )
                            continue
                        shutil.copy2(real_target, dst)
                    else:
                        shutil.copy2(src, dst)

                    # Validate weight files
                    if _is_weight_file(rel_path) and not _is_known_small_file(rel_path):
                        file_size = dst.stat().st_size
                        if file_size < _MIN_WEIGHT_FILE_SIZE:
                            errors.append(
                                f"Suspiciously small weight file: {rel_path} "
                                f"({file_size} bytes, min {_MIN_WEIGHT_FILE_SIZE})"
                            )

            # Build manifest entries for this snapshot
            cache_root = staging_dir / "embeddings" / "cache"
            for root, _dirs, files in os.walk(dest_snapshot):
                for fname in files:
                    fpath = Path(root) / fname
                    # Paths relative to cache root so verify_manifest can
                    # resolve them as cache_dir / entry["path"].
                    rel = fpath.relative_to(cache_root)
                    file_size = fpath.stat().st_size
                    entry: dict[str, Any] = {
                        "model": model_name,
                        "snapshot": snapshot.name,
                        "path": str(rel),
                        "size": file_size,
                    }
                    if _is_weight_file(fpath) and file_size >= _MIN_WEIGHT_FILE_SIZE:
                        entry["sha256"] = _sha256_file(fpath)
                    manifest_entries.append(entry)

    return manifest_entries, errors


def create_manifest(
    manifest_entries: list[dict[str, Any]],
    staging_dir: Path,
) -> Path:
    """Write the manifest file into the staging directory."""
    models: dict[str, Any] = {}
    for entry in manifest_entries:
        model_name = entry["model"]
        if model_name not in models:
            models[model_name] = {
                "name": model_name,
                "snapshots": {},
            }
        snap = entry["snapshot"]
        if snap not in models[model_name]["snapshots"]:
            models[model_name]["snapshots"][snap] = []
        models[model_name]["snapshots"][snap].append({
            "path": entry["path"],
            "size": entry["size"],
            **({"sha256": entry["sha256"]} if "sha256" in entry else {}),
        })

    manifest = {
        "version": 1,
        "models": models,
    }
    manifest_path = staging_dir / "embeddings" / "cache" / "ate_kb_model_manifest.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2))
    logger.info("Manifest written: %s (%d entries)", manifest_path, len(manifest_entries))
    return manifest_path


def create_archive(
    staging_dir: Path,
    output_dir: Path,
    name: str,
    fmt: str = "zip",
) -> Path:
    """Create the distribution archive from the staging directory."""
    output_dir.mkdir(parents=True, exist_ok=True)
    ext = ".zip" if fmt == "zip" else ".tar.gz"
    archive_path = output_dir / f"{name}{ext}"

    if fmt == "zip":
        with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for root, _dirs, files in os.walk(staging_dir):
                for fname in files:
                    fpath = Path(root) / fname
                    arcname = str(fpath.relative_to(staging_dir))
                    zf.write(fpath, arcname)
    else:
        import tarfile
        with tarfile.open(archive_path, "w:gz") as tf:
            for root, _dirs, files in os.walk(staging_dir):
                for fname in files:
                    fpath = Path(root) / fname
                    arcname = str(fpath.relative_to(staging_dir))
                    tf.add(fpath, arcname)

    logger.info("Archive created: %s (%d bytes)", archive_path, archive_path.stat().st_size)
    return archive_path


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    parser = argparse.ArgumentParser(description="Package model caches for offline distribution")
    parser.add_argument(
        "--cache-dir", default="./embeddings/cache",
        help="Hugging Face cache directory (default: ./embeddings/cache)",
    )
    parser.add_argument("--output", default="dist", help="Output directory (default: dist)")
    parser.add_argument("--name", default="ate-kb-model-cache", help="Archive name (without extension)")
    parser.add_argument(
        "--format", choices=["zip", "tar.gz"], default="zip", help="Archive format"
    )
    parser.add_argument(
        "--keep-staging", action="store_true",
        help="Keep the staging directory after archiving",
    )
    args = parser.parse_args()

    cache_dir = Path(args.cache_dir)
    output_dir = Path(args.output)
    staging_dir = output_dir / ".staging"

    # Clean previous staging
    if staging_dir.exists():
        shutil.rmtree(staging_dir)

    try:
        manifest_entries, errors = stage_models(cache_dir, staging_dir)

        if errors:
            print("Packaging errors detected:", file=sys.stderr)
            for err in errors:
                print(f"  - {err}", file=sys.stderr)
            sys.exit(1)

        create_manifest(manifest_entries, staging_dir)
        archive_path = create_archive(staging_dir, output_dir, args.name, args.format)
        print(f"Archive: {archive_path}")
    finally:
        if not args.keep_staging and staging_dir.exists():
            shutil.rmtree(staging_dir)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
