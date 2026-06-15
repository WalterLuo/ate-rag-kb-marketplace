#!/usr/bin/env python3
"""Convert extracted IG-XL help documents into project-ingestible Markdown."""

from __future__ import annotations

import argparse
import json
import posixpath
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup, NavigableString, Tag, UnicodeDammit

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = Path("/Users/walter_luo/Project/ig-xl-help-docs")
DEFAULT_MARKDOWN_DIR = PROJECT_ROOT / "data" / "raw" / "markdown" / "igxl"
DEFAULT_JSON_DIR = PROJECT_ROOT / "data" / "raw" / "json" / "igxl"
DEFAULT_ASSETS_DIR = PROJECT_ROOT / "data" / "raw" / "assets" / "igxl"

NAV_IMAGE_ALTS = {
    "",
    "next",
    "previous",
    "print",
    "collapse",
    "expanded",
}
CONTENT_IMAGE_NAMES = {
    "caution",
    "danger",
    "note",
    "noticenew",
    "notice",
    "warning",
}


@dataclass
class ConvertedDocument:
    markdown_path: Path
    json_path: Path
    title: str
    source: str
    kind: str


@dataclass
class ExtractedChm:
    chm_path: Path
    stem: str
    extract_dir: Path
    toc: dict[str, list[str]]
    html_files: list[Path]


def read_text_lossy(path: Path) -> str:
    data = path.read_bytes()
    decoded = UnicodeDammit(data, is_html=False).unicode_markup
    if decoded is not None:
        return decoded
    return data.decode("utf-8", errors="replace")


def read_html_lossy(path: Path) -> str:
    data = path.read_bytes()
    decoded = UnicodeDammit(data, is_html=True).unicode_markup
    if decoded is not None:
        return decoded
    return data.decode("utf-8", errors="replace")


def normalize_space(text: str) -> str:
    text = text.replace("\xa0", " ").replace("\u200b", "")
    text = text.replace("\u2011", "-").replace("\u2013", "-").replace("\u2014", "-")
    return re.sub(r"[ \t\r\f\v]+", " ", text).strip()


def normalize_inline_text(text: str) -> str:
    text = text.replace("\xa0", " ").replace("\u200b", "")
    text = text.replace("\u2011", "-").replace("\u2013", "-").replace("\u2014", "-")
    return re.sub(r"[ \t\r\f\v]+", " ", text)


def polish_markdown_text(text: str) -> str:
    nested_link = r"\[(?:[^\[\]]|\[[^\[\]]*\])*\]\([^)]+\)"
    text = re.sub(rf"(?<=[A-Za-z0-9,.;:])(?={nested_link})", " ", text)
    text = re.sub(r"(!\[[^\]]*\]\([^)]+\))(?=[A-Za-z0-9])", r"\1 ", text)
    text = re.sub(rf"({nested_link})(?=[A-Za-z0-9])", r"\1 ", text)
    text = re.sub(r"\b(Note|Caution|Warning|Danger):(?=\S)", r"\1: ", text)
    text = re.sub(r"\b([A-Za-z][A-Za-z0-9]*_\w+)or([A-Za-z][A-Za-z0-9]*_\w+)\b", r"\1 or \2", text)
    for pattern, replacement in {
        r"\bthe(?=Startmenu\b)": "the ",
        r"\bunder(?=Open\b)": "under ",
        r"\bto(?=analyze\b)": "to ",
        r"\band(?=difficult\b)": "and ",
    }.items():
        text = re.sub(pattern, replacement, text)
    return normalize_space(text)


def safe_stem(path: Path) -> str:
    raw = "_".join(path.with_suffix("").parts).lower()
    raw = re.sub(r"[^a-z0-9]+", "_", raw)
    return re.sub(r"_+", "_", raw).strip("_") or "document"


def title_from_path(path: Path) -> str:
    return normalize_space(path.stem.replace("_", " ").replace("-", " ")).title()


def inline_markdown(node: Tag | NavigableString) -> str:
    if isinstance(node, NavigableString):
        return normalize_inline_text(str(node))
    if not isinstance(node, Tag):
        return ""

    name = node.name.lower()
    if name in {"script", "style"}:
        return ""
    if name == "br":
        return "\n"
    if name == "a":
        text = normalize_space(" ".join(inline_markdown(c) for c in node.children)) or normalize_space(
            node.get_text(" ", strip=True)
        )
        href = normalize_space(node.get("href", ""))
        return f"[{text}]({href})" if text and href else text
    if name == "img":
        alt = normalize_space(node.get("alt", ""))
        src = normalize_space(node.get("src", ""))
        if alt.lower() in NAV_IMAGE_ALTS:
            return ""
        return f"![{alt}]({src})" if src else alt
    if name in {"code", "tt"}:
        text = normalize_space(node.get_text(" ", strip=True))
        return f"`{text}`" if text else ""

    return normalize_space("".join(inline_markdown(c) for c in node.children))


def table_to_markdown(table: Tag) -> str:
    rows: list[list[str]] = []
    for tr in table.find_all("tr", recursive=True):
        cells = [normalize_space(cell.get_text(" ", strip=True)) for cell in tr.find_all(["th", "td"])]
        cells = [c for c in cells if c]
        if cells:
            rows.append(cells)
    if not rows:
        return ""

    if len(rows) == 1:
        return " ".join(rows[0])

    width = max(len(r) for r in rows)
    rows = [r + [""] * (width - len(r)) for r in rows]
    header = rows[0]
    sep = ["---"] * width
    body = rows[1:]
    lines = [
        "| " + " | ".join(header) + " |",
        "| " + " | ".join(sep) + " |",
    ]
    lines.extend("| " + " | ".join(row) + " |" for row in body)
    return "\n".join(lines)


def class_names(tag: Tag) -> set[str]:
    values = tag.get("class", [])
    if isinstance(values, str):
        values = values.split()
    return {str(v) for v in values}


def block_markdown(tag: Tag, level: int = 1) -> list[str]:
    if not isinstance(tag, Tag):
        return []
    name = tag.name.lower()
    classes = class_names(tag)

    if name in {"script", "style", "head", "meta", "link"}:
        return []
    if name == "table" and ("navi" in classes or "hidden" in classes):
        return []
    if "WebWorks_Breadcrumbs" in classes:
        return []

    if name in {"h1", "h2", "h3", "h4", "h5", "h6"}:
        heading_level = int(name[1])
        text = normalize_space(inline_markdown(tag))
        return [f"{'#' * heading_level} {text}"] if text else []

    if name in {"ul", "ol"}:
        lines: list[str] = []
        for idx, li in enumerate(tag.find_all("li", recursive=False), start=1):
            text = polish_markdown_text(inline_markdown(li))
            if text:
                prefix = f"{idx}." if name == "ol" else "-"
                lines.append(f"{prefix} {text}")
            for child in li.find_all(["ul", "ol"], recursive=False):
                lines.extend(block_markdown(child, level + 1))
        return lines

    if name == "li":
        text = polish_markdown_text(inline_markdown(tag))
        return [f"- {text}"] if text else []

    if name == "table":
        return [table_to_markdown(tag)]

    if name in {"pre"}:
        text = tag.get_text("\n", strip=False).strip()
        return [f"```text\n{text}\n```"] if text else []

    if name in {"p", "blockquote"}:
        if name == "blockquote":
            lines: list[str] = []
            for child in tag.children:
                if isinstance(child, Tag):
                    lines.extend(block_markdown(child, level))
            return lines
        text = polish_markdown_text(inline_markdown(tag))
        return [text] if text else []

    if name == "div":
        text = polish_markdown_text(inline_markdown(tag))
        if "Chapter" in classes or "Heading1" in classes:
            return [f"# {text}"] if text else []
        if "Heading2" in classes:
            return [f"## {text}"] if text else []
        if "Heading3" in classes:
            return [f"### {text}"] if text else []
        if any(c.startswith("Bullet") for c in classes):
            text = text.lstrip("•").strip()
            return [f"- {polish_markdown_text(text)}"] if text else []
        if any(c.startswith("Number") for c in classes):
            text = re.sub(r"^\d+[\.)]\s*", "", text)
            return [f"1. {polish_markdown_text(text)}"] if text else []
        if any(c in classes for c in {"Body", "BodyRelative", "CellBody", "Note", "Caution"}):
            return [polish_markdown_text(text)] if text else []
        child_blocks: list[str] = []
        direct_tags = [c for c in tag.children if isinstance(c, Tag)]
        if direct_tags:
            for child in direct_tags:
                child_blocks.extend(block_markdown(child, level))
            if child_blocks:
                return child_blocks
        return [polish_markdown_text(text)] if text else []

    lines: list[str] = []
    for child in tag.children:
        if isinstance(child, Tag):
            lines.extend(block_markdown(child, level))
    if lines:
        return lines
    text = polish_markdown_text(inline_markdown(tag))
    return [text] if text else []


def html_to_markdown(html: str, title: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    for table in soup.find_all("table", class_="navi"):
        table.decompose()
    for breadcrumb in soup.find_all(class_="WebWorks_Breadcrumbs"):
        breadcrumb.decompose()
    for anchor in soup.find_all("a"):
        if not anchor.get_text(strip=True) and anchor.get("name"):
            anchor.decompose()

    body = soup.find("blockquote") or soup.body or soup
    blocks: list[str] = []
    for child in body.children:
        if isinstance(child, Tag):
            blocks.extend(block_markdown(child))

    cleaned: list[str] = []
    seen_blank = False
    for block in blocks:
        block = block.strip()
        if not block:
            if not seen_blank:
                cleaned.append("")
            seen_blank = True
            continue
        cleaned.append(block)
        seen_blank = False

    title = normalize_space(title) or "IG-XL Help Topic"
    if not cleaned or not cleaned[0].startswith("# "):
        cleaned.insert(0, f"# {title}")
    return "\n\n".join(cleaned).strip() + "\n"


def normalize_help_href(href: str) -> tuple[str | None, str, str]:
    href = normalize_space(href).replace("\\", "/")
    anchor = ""
    if "#" in href:
        href, anchor = href.split("#", 1)
        anchor = f"#{anchor}" if anchor else ""
    if "?" in href:
        href, _query = href.split("?", 1)
    href = href.strip()

    ms_its = re.match(r"(?i)^ms-its:([^:]+\.chm)::/?(.+)$", href)
    if ms_its:
        return ms_its.group(1).lower(), ms_its.group(2).lstrip("/"), anchor

    ms_store = re.match(r"(?i)^mk:@MSITStore:([^:]+\.chm)::/?(.+)$", href)
    if ms_store:
        return ms_store.group(1).lower(), ms_store.group(2).lstrip("/"), anchor

    return None, href.lstrip("/"), anchor


def resolve_target_markdown(
    href: str,
    *,
    current_chm: str,
    current_rel_md: Path,
    link_map: dict[tuple[str, str], Path],
) -> Path | None:
    if not href or href.startswith(("http://", "https://", "mailto:", "data:", "#")):
        return None

    target_chm, target_path, _anchor = normalize_help_href(href)
    if not target_path.lower().endswith((".htm", ".html")):
        return None

    chm_key = (target_chm or current_chm).lower()
    target_norm = posixpath.normpath(target_path)
    if target_chm is None:
        rel_parts = current_rel_md.parts[1:] if len(current_rel_md.parts) > 1 else current_rel_md.parts
        current_html_dir = Path(*rel_parts).with_suffix(".html").parent.as_posix()
        target_norm = posixpath.normpath(posixpath.join(current_html_dir, target_path))

    return link_map.get((chm_key, target_norm))


def rewrite_markdown_links(
    markdown: str,
    *,
    current_chm: str,
    current_rel_md: Path,
    link_map: dict[tuple[str, str], Path],
) -> str:
    link_pattern = re.compile(r"\[((?:[^\[\]]|\[[^\[\]]*\])*)\]\(([^)]+)\)")

    def replace(match: re.Match[str]) -> str:
        label = match.group(1)
        href = match.group(2)
        target_rel = resolve_target_markdown(
            href,
            current_chm=current_chm,
            current_rel_md=current_rel_md,
            link_map=link_map,
        )
        if target_rel is None:
            return match.group(0)
        _target_chm, _target_path, anchor = normalize_help_href(href)
        rel_href = posixpath.relpath(target_rel.as_posix(), start=current_rel_md.parent.as_posix())
        return f"[{label}]({rel_href}{anchor})"

    return link_pattern.sub(replace, markdown).strip() + "\n"


def parse_hhc_toc(hhc_text: str, root_title: str) -> dict[str, list[str]]:
    soup = BeautifulSoup(hhc_text, "html.parser")
    toc: dict[str, list[str]] = {}

    def object_info(obj: Tag) -> tuple[str, str] | None:
        params: dict[str, str] = {}
        for param in obj.find_all("param", recursive=False):
            name = param.get("name")
            value = param.get("value")
            if name and value:
                params[name.lower()] = value
        title = normalize_space(params.get("name", ""))
        local = normalize_space(params.get("local", ""))
        if title and local:
            return title, local
        return None

    def walk_ul(ul: Tag, parents: list[str]) -> None:
        for li in ul.find_all("li", recursive=False):
            obj = li.find("object", recursive=False)
            current = parents
            if obj:
                info = object_info(obj)
                if info:
                    title, local = info
                    current = [*parents, title]
                    toc[local] = current
            for child_ul in li.find_all("ul", recursive=False):
                walk_ul(child_ul, current)

    for ul in soup.find_all("ul", recursive=False):
        walk_ul(ul, ["IG-XL Help", root_title])
    if not toc:
        first_ul = soup.find("ul")
        if first_ul:
            walk_ul(first_ul, ["IG-XL Help", root_title])
    return toc


def ensure_dirs(markdown_dir: Path, json_dir: Path, assets_dir: Path) -> None:
    markdown_dir.mkdir(parents=True, exist_ok=True)
    json_dir.mkdir(parents=True, exist_ok=True)
    assets_dir.mkdir(parents=True, exist_ok=True)


def metadata_for(
    *,
    title: str,
    source: str,
    markdown_rel: Path,
    toc_path: list[str],
    kind: str,
    images: list[str] | None = None,
    warnings: list[str] | None = None,
) -> dict[str, Any]:
    tags = ["ig-xl", "teradyne", "j750", kind]
    return {
        "title": title,
        "source_html": source if kind == "chm" else "",
        "source_original": source,
        "toc_path": toc_path,
        "markdown_path": str(Path("markdown") / markdown_rel),
        "images": images or [],
        "platform": "J750",
        "doc_family": "IG-XL",
        "doc_type": "reference",
        "tags": tags,
        "conversion": {
            "kind": kind,
            "converter": "scripts/convert_igxl_help.py",
            "warnings": warnings or [],
        },
    }


def write_document(
    *,
    markdown_dir: Path,
    json_dir: Path,
    rel_md: Path,
    title: str,
    source: str,
    toc_path: list[str],
    kind: str,
    markdown: str,
    images: list[str] | None = None,
    warnings: list[str] | None = None,
) -> ConvertedDocument:
    md_path = markdown_dir / rel_md
    json_path = json_dir / rel_md.with_suffix(".json")
    md_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.write_text(markdown, encoding="utf-8")
    meta = metadata_for(
        title=title,
        source=source,
        markdown_rel=Path("igxl") / rel_md,
        toc_path=toc_path,
        kind=kind,
        images=images,
        warnings=warnings,
    )
    json_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return ConvertedDocument(md_path, json_path, title, source, kind)


def copy_html_images(soup: BeautifulSoup, extract_dir: Path, asset_root: Path, doc_root: str) -> list[str]:
    images: list[str] = []
    for img in soup.find_all("img"):
        src = normalize_space(img.get("src", ""))
        if not src or src.startswith(("http://", "https://", "data:")):
            continue
        alt = normalize_space(img.get("alt", ""))
        if alt.lower() in NAV_IMAGE_ALTS and Path(src).stem.lower() not in CONTENT_IMAGE_NAMES:
            continue
        src_path = (extract_dir / src).resolve()
        try:
            src_path.relative_to(extract_dir.resolve())
        except ValueError:
            continue
        if not src_path.exists() or not src_path.is_file():
            continue
        dest = asset_root / doc_root / src
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src_path, dest)
        rel_asset = Path("assets") / "igxl" / doc_root / src
        img["src"] = str(Path("..") / ".." / ".." / rel_asset)
        images.append(str(rel_asset))
    return sorted(set(images))


def extract_chm(chm_path: Path, temp_dir: Path) -> ExtractedChm:
    stem = safe_stem(Path(chm_path.stem))
    extract_dir = temp_dir / stem
    if extract_dir.exists():
        shutil.rmtree(extract_dir)
    extract_dir.mkdir(parents=True, exist_ok=True)

    subprocess.run(["extract_chmLib", str(chm_path), str(extract_dir)], check=True, capture_output=True)
    toc_file = extract_dir / "toc.hhc"
    toc = parse_hhc_toc(read_html_lossy(toc_file), chm_path.stem) if toc_file.exists() else {}
    html_files = sorted(
        p
        for p in extract_dir.rglob("*")
        if p.is_file() and p.suffix.lower() in {".htm", ".html"} and p.name.lower() != "toc.hhc"
    )
    return ExtractedChm(chm_path=chm_path, stem=stem, extract_dir=extract_dir, toc=toc, html_files=html_files)


def build_chm_link_map(contexts: list[ExtractedChm]) -> dict[tuple[str, str], Path]:
    link_map: dict[tuple[str, str], Path] = {}
    for context in contexts:
        chm_key = context.chm_path.name.lower()
        for html_path in context.html_files:
            rel_html = html_path.relative_to(context.extract_dir).as_posix()
            rel_md = Path(context.stem) / Path(rel_html).with_suffix(".md")
            link_map[(chm_key, rel_html)] = rel_md
    return link_map


def convert_chm_context(
    context: ExtractedChm,
    chm_path: Path,
    *,
    markdown_dir: Path,
    json_dir: Path,
    assets_dir: Path,
    link_map: dict[tuple[str, str], Path],
) -> list[ConvertedDocument]:
    docs: list[ConvertedDocument] = []
    for html_path in context.html_files:
        rel_html = html_path.relative_to(context.extract_dir)
        html = read_html_lossy(html_path)
        soup = BeautifulSoup(html, "html.parser")
        title_tag = soup.find("title")
        title = normalize_space(title_tag.get_text(" ", strip=True)) if title_tag else ""
        if not title:
            title = (
                context.toc.get(str(rel_html), [])[-1]
                if str(rel_html) in context.toc
                else title_from_path(html_path)
            )
        images = copy_html_images(soup, context.extract_dir, assets_dir, context.stem)
        markdown = html_to_markdown(str(soup), title)
        rel_md = Path(context.stem) / rel_html.with_suffix(".md")
        markdown = rewrite_markdown_links(
            markdown,
            current_chm=chm_path.name,
            current_rel_md=rel_md,
            link_map=link_map,
        )
        source = f"{chm_path.name}::{rel_html.as_posix()}"
        docs.append(
            write_document(
                markdown_dir=markdown_dir,
                json_dir=json_dir,
                rel_md=rel_md,
                title=title,
                source=source,
                toc_path=context.toc.get(str(rel_html), ["IG-XL Help", chm_path.stem, title]),
                kind="chm",
                markdown=markdown,
                images=images,
            )
        )
    return docs


def text_to_markdown(path: Path, source_root: Path, kind: str) -> tuple[Path, str, str, list[str]]:
    rel = path.relative_to(source_root)
    title = title_from_path(path)
    text = read_text_lossy(path)
    warnings: list[str] = []
    if kind == "cnt":
        title, body, _topics = cnt_to_markdown(text, rel)
    elif kind == "hlp":
        title, body = hlp_manifest_markdown(rel, matching_cnt=None, topic_count=0)
        warnings.append(
            "Legacy WinHelp .hlp topic bodies were not decoded because no WinHelp decoder is available in this environment."
        )
    else:
        body = "# " + title + "\n\n"
        body += "Source text file: `" + rel.as_posix() + "`\n\n"
        body += "```text\n" + text.strip() + "\n```\n"
    return Path(kind) / safe_stem(rel), title, body, warnings


def cnt_to_markdown(text: str, rel_path: Path) -> tuple[str, str, list[dict[str, str]]]:
    title = title_from_path(rel_path)
    base = ""
    lines: list[str] = []
    topics: list[dict[str, str]] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.lower().startswith(":title"):
            _, value = line.split(" ", 1) if " " in line else (line, "")
            title = normalize_space(value).title() or title
            continue
        if line.lower().startswith(":base"):
            _, value = line.split(" ", 1) if " " in line else (line, "")
            base = normalize_space(value)
            continue
        match = re.match(r"^(\d+)\s+(.+)$", line)
        if not match:
            continue
        level = int(match.group(1))
        label_target = match.group(2)
        label, sep, target = label_target.partition("=")
        label = normalize_space(label)
        target = normalize_space(target)
        if not label:
            continue
        if level <= 1:
            lines.append(f"## {label}")
        else:
            indent = "  " * max(level - 2, 0)
            if sep and target:
                lines.append(f"{indent}- {label} (`{target}`)")
                topics.append({"title": label, "target": target})
            else:
                lines.append(f"{indent}- {label}")

    markdown = f"# {title}\n\n"
    markdown += f"Source table of contents file: `{rel_path.as_posix()}`\n\n"
    if base:
        markdown += f"Base WinHelp file: `{base}`\n\n"
    markdown += "\n".join(lines).strip() + "\n"
    return title, markdown, topics


def hlp_manifest_markdown(
    rel_path: Path,
    *,
    matching_cnt: Path | None,
    topic_count: int,
) -> tuple[str, str]:
    title = title_from_path(rel_path)
    lines = [
        f"# {title}",
        "",
        f"Source WinHelp file: `{rel_path.as_posix()}`",
        "",
        "Legacy WinHelp package.",
        "",
    ]
    if matching_cnt:
        lines.append(
            f"The topic directory for this package is available in `{matching_cnt.as_posix()}` with {topic_count} indexed topics."
        )
    else:
        lines.append(
            "No matching `.cnt` table-of-contents file was found, so topic bodies were not decoded in this environment."
        )
    lines.extend(
        [
            "",
            "Conversion note: `.hlp` topic bodies require a WinHelp decoder such as helpdeco. "
            "This manifest is kept to preserve source traceability without embedding noisy binary strings.",
            "",
        ]
    )
    return title, "\n".join(lines)


def printable_strings(path: Path, min_len: int = 4) -> str:
    data = path.read_bytes()
    chunks = re.findall(rb"[\x20-\x7E]{" + str(min_len).encode() + rb",}", data)
    lines = [c.decode("ascii", errors="ignore").strip() for c in chunks]
    lines = [line for line in lines if line and not re.fullmatch(r"[._~`!@#$%^&*()+=|\\{}\[\]:;\"'<>,?/ -]+", line)]
    return "\n".join(dict.fromkeys(lines))


def convert_textlike(
    source_root: Path,
    *,
    markdown_dir: Path,
    json_dir: Path,
) -> list[ConvertedDocument]:
    docs: list[ConvertedDocument] = []
    cnt_index: dict[str, tuple[Path, int]] = {}
    for cnt in sorted(source_root.rglob("*")):
        if cnt.is_file() and cnt.suffix.lower() == ".cnt":
            rel_cnt = cnt.relative_to(source_root)
            _title, _markdown, topics = cnt_to_markdown(read_text_lossy(cnt), rel_cnt)
            cnt_index[cnt.stem.lower()] = (rel_cnt, len(topics))

    for path in sorted(source_root.rglob("*")):
        if not path.is_file():
            continue
        ext = path.suffix.lower()
        kind = {".txt": "txt", ".cnt": "cnt", ".hlp": "hlp"}.get(ext)
        if not kind:
            continue
        rel_stem, title, markdown, warnings = text_to_markdown(path, source_root, kind)
        if kind == "hlp":
            rel = path.relative_to(source_root)
            matching_cnt, topic_count = cnt_index.get(path.stem.lower(), (None, 0))
            title, markdown = hlp_manifest_markdown(
                rel,
                matching_cnt=matching_cnt,
                topic_count=topic_count,
            )
        rel_md = rel_stem.with_suffix(".md")
        rel = path.relative_to(source_root)
        docs.append(
            write_document(
                markdown_dir=markdown_dir,
                json_dir=json_dir,
                rel_md=rel_md,
                title=title,
                source=rel.as_posix(),
                toc_path=["IG-XL Help", kind.upper(), *rel.parent.parts, title],
                kind=kind,
                markdown=markdown,
                warnings=warnings,
            )
        )
    return docs


def extract_pdf_text(path: Path) -> tuple[str, list[str]]:
    warnings: list[str] = []
    try:
        from pypdf import PdfReader  # type: ignore

        reader = PdfReader(str(path))
        pages: list[str] = []
        for idx, page in enumerate(reader.pages, start=1):
            text = page.extract_text() or ""
            pages.append(f"## Page {idx}\n\n{text.strip()}")
        return "\n\n".join(pages).strip(), warnings
    except Exception as exc:
        warnings.append(f"pypdf extraction unavailable or failed: {exc}")
    try:
        result = subprocess.run(["pdftotext", "-layout", str(path), "-"], check=True, capture_output=True)
        return result.stdout.decode("utf-8", errors="replace").strip(), warnings
    except Exception as exc:
        warnings.append(f"pdftotext extraction unavailable or failed: {exc}")
    strings = printable_strings(path, min_len=6)
    warnings.append("PDF was converted with printable-string extraction; install pypdf or poppler for better quality.")
    return strings, warnings


def convert_pdfs(
    source_root: Path,
    *,
    markdown_dir: Path,
    json_dir: Path,
) -> list[ConvertedDocument]:
    docs: list[ConvertedDocument] = []
    for path in sorted(source_root.rglob("*")):
        if not path.is_file() or path.suffix.lower() != ".pdf":
            continue
        rel = path.relative_to(source_root)
        title = title_from_path(path)
        text, warnings = extract_pdf_text(path)
        markdown = f"# {title}\n\nSource PDF file: `{rel.as_posix()}`\n\n{text.strip()}\n"
        rel_md = (Path("pdf") / safe_stem(rel)).with_suffix(".md")
        docs.append(
            write_document(
                markdown_dir=markdown_dir,
                json_dir=json_dir,
                rel_md=rel_md,
                title=title,
                source=rel.as_posix(),
                toc_path=["IG-XL Help", "PDF", *rel.parent.parts, title],
                kind="pdf",
                markdown=markdown,
                warnings=warnings,
            )
        )
    return docs


def convert_all(
    source_root: Path,
    markdown_dir: Path,
    json_dir: Path,
    assets_dir: Path,
    temp_dir: Path,
) -> list[ConvertedDocument]:
    ensure_dirs(markdown_dir, json_dir, assets_dir)
    docs: list[ConvertedDocument] = []

    chm_contexts = [extract_chm(chm, temp_dir) for chm in sorted(source_root.rglob("*.chm"))]
    link_map = build_chm_link_map(chm_contexts)
    for context in chm_contexts:
        docs.extend(
            convert_chm_context(
                context,
                context.chm_path,
                markdown_dir=markdown_dir,
                json_dir=json_dir,
                assets_dir=assets_dir,
                link_map=link_map,
            )
        )
    docs.extend(convert_textlike(source_root, markdown_dir=markdown_dir, json_dir=json_dir))
    docs.extend(convert_pdfs(source_root, markdown_dir=markdown_dir, json_dir=json_dir))
    return docs


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--markdown-dir", type=Path, default=DEFAULT_MARKDOWN_DIR)
    parser.add_argument("--json-dir", type=Path, default=DEFAULT_JSON_DIR)
    parser.add_argument("--assets-dir", type=Path, default=DEFAULT_ASSETS_DIR)
    parser.add_argument("--temp-dir", type=Path, default=Path(tempfile.gettempdir()) / "ate-rag-kb-igxl-chm")
    parser.add_argument("--clean", action="store_true", help="Remove existing IG-XL output directories first.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    if args.clean:
        for path in [args.markdown_dir, args.json_dir, args.assets_dir, args.temp_dir]:
            if path.exists():
                shutil.rmtree(path)
    args.temp_dir.mkdir(parents=True, exist_ok=True)
    docs = convert_all(args.source, args.markdown_dir, args.json_dir, args.assets_dir, args.temp_dir)
    summary: dict[str, int] = {}
    for doc in docs:
        summary[doc.kind] = summary.get(doc.kind, 0) + 1
    print(json.dumps({"documents": len(docs), "by_kind": summary}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
