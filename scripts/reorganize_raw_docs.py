#!/usr/bin/env python3
"""Reorganize data/raw: move root-level SMT7 docs into v93000/smt7/ subdirectories.

Supports --dry-run to preview changes without executing.
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import shutil
import sys
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = PROJECT_ROOT / "data" / "raw"

MARKDOWN_SRC = RAW_DIR / "markdown"
JSON_SRC = RAW_DIR / "json"
ASSETS_SRC = RAW_DIR / "assets"

MARKDOWN_DST = MARKDOWN_SRC / "v93000" / "smt7"
JSON_DST = JSON_SRC / "v93000" / "smt7"
ASSETS_DST = ASSETS_SRC / "v93000" / "smt7"

# Regex for markdown image syntax: ![alt](path)
_MARKDOWN_IMAGE_RE = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")

# Extensions considered images
_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".svg", ".bmp", ".webp"}


def _is_bare_image_link(link: str) -> bool:
    """Return True if link is a bare filename (no path, no protocol) that looks like an image."""
    link = link.strip()
    if not link:
        return False
    if link.startswith(("http://", "https://", "ftp://", "file://")):
        return False
    if "/" in link or "\\" in link:
        return False
    ext = Path(link).suffix.lower()
    return ext in _IMAGE_EXTENSIONS


def _rewrite_markdown_images(md_text: str) -> str:
    """Rewrite bare image links in markdown to point to new assets location."""
    def repl(match: re.Match[str]) -> str:
        alt = match.group(1)
        link = match.group(2)
        if _is_bare_image_link(link):
            new_link = f"../../../assets/v93000/smt7/{link}"
            return f"![{alt}]({new_link})"
        return match.group(0)
    return _MARKDOWN_IMAGE_RE.sub(repl, md_text)


def _rewrite_json_content_images(content: str) -> str:
    """Rewrite bare image links inside JSON content field."""
    return _rewrite_markdown_images(content)


def _should_move(path: Path) -> bool:
    """Return True for root-level files that should move to v93000/smt7/."""
    if path.is_dir():
        return False
    return not path.name.startswith(".")


def _collect_root_files(src_dir: Path) -> list[Path]:
    """Collect files directly under src_dir (not in subdirectories)."""
    return [f for f in src_dir.iterdir() if f.is_file() and _should_move(f)]


def _rewrite_markdown_file(src: Path, dst: Path, dry_run: bool) -> None:
    text = src.read_text(encoding="utf-8")
    new_text = _rewrite_markdown_images(text)
    if dry_run:
        action = "Would rewrite" if new_text != text else "Would copy"
        logger.info("[dry-run] %s %s -> %s", action, src.relative_to(PROJECT_ROOT), dst.relative_to(PROJECT_ROOT))
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(new_text, encoding="utf-8")
    if new_text == text:
        logger.info("Copied (no image changes) %s", dst.relative_to(PROJECT_ROOT))
    else:
        logger.info("Rewrote images %s", dst.relative_to(PROJECT_ROOT))
    src.unlink()


def _rewrite_json_file(src: Path, dst: Path, dry_run: bool) -> None:
    data = json.loads(src.read_text(encoding="utf-8"))

    old_md_path = data.get("markdown_path", "")
    if old_md_path.startswith("markdown/") and not old_md_path.startswith("markdown/v93000/"):
        data["markdown_path"] = old_md_path.replace("markdown/", "markdown/v93000/smt7/", 1)

    old_images = data.get("images", [])
    new_images: list[str] = []
    for img in old_images:
        if "/" not in img:
            new_images.append(f"assets/v93000/smt7/{img}")
        else:
            new_images.append(img)
    data["images"] = new_images

    old_content = data.get("content", "")
    if old_content:
        data["content"] = _rewrite_json_content_images(old_content)

    if dry_run:
        changed = (
            old_md_path != data.get("markdown_path", "")
            or old_images != data.get("images", [])
            or old_content != data.get("content", "")
        )
        action = "Would rewrite" if changed else "Would copy"
        logger.info("[dry-run] %s %s -> %s", action, src.relative_to(PROJECT_ROOT), dst.relative_to(PROJECT_ROOT))
        return

    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("Rewrote JSON %s", dst.relative_to(PROJECT_ROOT))
    src.unlink()


def run(dry_run: bool) -> dict[str, int]:
    stats = {"markdown": 0, "json": 0, "assets": 0}

    md_files = _collect_root_files(MARKDOWN_SRC)
    for src in md_files:
        if src.suffix.lower() != ".md":
            continue
        dst = MARKDOWN_DST / src.name
        _rewrite_markdown_file(src, dst, dry_run)
        stats["markdown"] += 1

    json_files = _collect_root_files(JSON_SRC)
    for src in json_files:
        if src.suffix.lower() != ".json":
            continue
        dst = JSON_DST / src.name
        _rewrite_json_file(src, dst, dry_run)
        stats["json"] += 1

    asset_files = _collect_root_files(ASSETS_SRC)
    for src in asset_files:
        dst = ASSETS_DST / src.name
        if dry_run:
            logger.info("[dry-run] Would move %s -> %s", src.relative_to(PROJECT_ROOT), dst.relative_to(PROJECT_ROOT))
        else:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(dst))
            logger.info("Moved asset %s", dst.relative_to(PROJECT_ROOT))
        stats["assets"] += 1

    return stats


def main() -> int:
    parser = argparse.ArgumentParser(description="Reorganize data/raw SMT7 docs into v93000/smt7/")
    parser.add_argument("--dry-run", action="store_true", help="Preview changes without executing")
    args = parser.parse_args()

    if args.dry_run:
        logger.info("=== DRY RUN: no files will be modified ===")

    stats = run(args.dry_run)

    logger.info("Done. Files processed: markdown=%d, json=%d, assets=%d", stats["markdown"], stats["json"], stats["assets"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
