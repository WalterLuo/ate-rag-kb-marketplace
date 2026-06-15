#!/usr/bin/env python3
"""Validate data/raw reorganization after migration."""

from __future__ import annotations

import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = PROJECT_ROOT / "data" / "raw"

_MARKDOWN_IMAGE_RE = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")


def _count_files(directory: Path, pattern: str) -> int:
    return sum(1 for f in directory.rglob(pattern) if f.is_file())


def validate() -> dict[str, bool]:
    results: dict[str, bool] = {}

    # 1. Root markdown should have no .md files
    root_md = list((RAW_DIR / "markdown").glob("*.md"))
    results["markdown_root_empty"] = len(root_md) == 0
    print(f"markdown root .md files: {len(root_md)} (expect 0)")

    # 2. Root json should have no .json files
    root_json = list((RAW_DIR / "json").glob("*.json"))
    results["json_root_empty"] = len(root_json) == 0
    print(f"json root .json files: {len(root_json)} (expect 0)")

    # 3. Root assets should have no files
    root_assets = [f for f in (RAW_DIR / "assets").iterdir() if f.is_file()]
    results["assets_root_empty"] = len(root_assets) == 0
    print(f"assets root files: {len(root_assets)} (expect 0)")

    # 4. v93000/smt7 markdown count
    smt7_md_count = _count_files(RAW_DIR / "markdown" / "v93000" / "smt7", "*.md")
    results["smt7_md_count"] = smt7_md_count == 13194
    print(f"markdown/v93000/smt7 .md files: {smt7_md_count} (expect 13194)")

    # 5. v93000/smt7 json count
    smt7_json_count = _count_files(RAW_DIR / "json" / "v93000" / "smt7", "*.json")
    results["smt7_json_count"] = smt7_json_count == 13194
    print(f"json/v93000/smt7 .json files: {smt7_json_count} (expect 13194)")

    # 6. igxl markdown count
    igxl_md_count = _count_files(RAW_DIR / "markdown" / "igxl", "*.md")
    results["igxl_md_count"] = igxl_md_count == 7713
    print(f"markdown/igxl .md files: {igxl_md_count} (expect 7713)")

    # 7. igxl json count
    igxl_json_count = _count_files(RAW_DIR / "json" / "igxl", "*.json")
    results["igxl_json_count"] = igxl_json_count == 7713
    print(f"json/igxl .json files: {igxl_json_count} (expect 7713)")

    # 8. Every markdown has matching JSON
    smt7_md_dir = RAW_DIR / "markdown" / "v93000" / "smt7"
    smt7_json_dir = RAW_DIR / "json" / "v93000" / "smt7"
    missing_json: list[str] = []
    for md_path in sorted(smt7_md_dir.glob("*.md")):
        json_path = smt7_json_dir / (md_path.stem + ".json")
        if not json_path.exists():
            missing_json.append(md_path.name)
    results["all_md_have_json"] = len(missing_json) == 0
    print(f"markdowns without matching JSON: {len(missing_json)} (expect 0)")
    if missing_json:
        print(f"  examples: {missing_json[:5]}")

    # 9. Image links in markdown resolve to real files
    assets_dir = RAW_DIR / "assets" / "v93000" / "smt7"
    broken_images: list[tuple[str, str]] = []
    for md_path in sorted(smt7_md_dir.glob("*.md")):
        text = md_path.read_text(encoding="utf-8")
        for match in _MARKDOWN_IMAGE_RE.finditer(text):
            link = match.group(2)
            # Only check links that point to our new assets location
            if "assets/v93000/smt7/" in link:
                filename = link.split("/")[-1]
                asset_path = assets_dir / filename
                if not asset_path.exists():
                    broken_images.append((md_path.name, link))
    results["image_links_valid"] = len(broken_images) == 0
    print(f"broken image links: {len(broken_images)} (expect 0)")
    if broken_images:
        print(f"  examples: {broken_images[:5]}")

    all_pass = all(results.values())
    print(f"\nOverall: {'PASS' if all_pass else 'FAIL'}")
    return results


def main() -> int:
    results = validate()
    return 0 if all(results.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
