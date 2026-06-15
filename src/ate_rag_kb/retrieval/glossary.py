"""Domain glossary for ATE KB query expansion.

Maps Chinese terms to English ATE terminology to improve retrieval
when users ask questions in Chinese against English documentation.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class GlossaryEntry:
    """A single glossary mapping between Chinese and English ATE terms."""

    cn_terms: tuple[str, ...]  # Chinese trigger terms
    en_terms: tuple[str, ...]  # English equivalents
    expansions: tuple[str, ...]  # Terms to inject into the query
    doc_family: str | None = None  # Optional doc family hint
    ecosystem: str | None = None  # Optional ecosystem hint
    software: str | None = None  # Optional canonical software hint


ATE_GLOSSARY: tuple[GlossaryEntry, ...] = (
    GlossaryEntry(
        cn_terms=("作业列表", "工作列表", "job list"),
        en_terms=("Job List Sheet", "Job List"),
        expansions=("Job List Sheet", "DataTool Job List"),
        doc_family="igxl_help",
        ecosystem="igxl",
    ),
    GlossaryEntry(
        cn_terms=("多 site 串行处理", "多site串行处理", "串行 site"),
        en_terms=("serial site loop",),
        expansions=("SelectFirst", "SelectNext", "LoopStatus", "loopDone", "FastSiteLoop"),
        doc_family="igxl_help",
        ecosystem="igxl",
        software="igxl",
    ),
    GlossaryEntry(
        cn_terms=("数组",),
        en_terms=("ARRAY", "array"),
        expansions=("ARRAY", "ARRAY_x", "ARRAY_d", "array data type"),
    ),
    GlossaryEntry(
        cn_terms=("规格", "规范"),
        en_terms=("spec", "specification"),
        expansions=("spec", "specification", "AC Specs", "DC Specs"),
    ),
    GlossaryEntry(
        cn_terms=("电平", "电压", "level"),
        en_terms=("levels", "pin levels"),
        expansions=("Pin Levels", "levels", "voltage levels"),
    ),
    GlossaryEntry(
        cn_terms=("时序", "定时"),
        en_terms=("timing",),
        expansions=("timing", "timing set", "drive edge"),
    ),
    GlossaryEntry(
        cn_terms=("测试流", "test flow", "测试流程"),
        en_terms=("testflow", "flow table"),
        expansions=("Flow Table", "testflow", "test flow"),
    ),
    GlossaryEntry(
        cn_terms=("引脚", "pin"),
        en_terms=("pins", "pin map"),
        expansions=("Pin Map", "pins", "pin configuration"),
    ),
    GlossaryEntry(
        cn_terms=("资源映射", "资源表"),
        en_terms=("resource map", "MTO Resource Map"),
        expansions=("MTO Resource Map", "resource map"),
        doc_family="igxl_help",
        ecosystem="igxl",
    ),
    GlossaryEntry(
        cn_terms=("假脱机", "离线", "脱机", "控制状态"),
        en_terms=("spooling", "off-line", "controlstate"),
        expansions=("spooling", "CONTROLSTATE", "off-line", "SECS/GEM"),
        doc_family="igxl_help",
        ecosystem="igxl",
    ),
    GlossaryEntry(
        cn_terms=("功能分类", "可用功能"),
        en_terms=("Available Features", "feature classification"),
        expansions=("Available J750 Features", "feature classification"),
        doc_family="igxl_help",
        ecosystem="igxl",
    ),
    GlossaryEntry(
        cn_terms=("tdc", "test development center"),
        en_terms=("TDC", "Test Development Center"),
        expansions=("TDC", "Test Development Center", "device preparation"),
        doc_family="tdc",
        ecosystem="v93000",
    ),
)


def match_glossary(query: str) -> list[GlossaryEntry]:
    """Return all glossary entries whose cn_terms or en_terms match the query.

    Matching is case-insensitive substring search.
    """
    normalized = query.lower()
    matched: list[GlossaryEntry] = []
    for entry in ATE_GLOSSARY:
        if any(term.lower() in normalized for term in entry.cn_terms) or any(term.lower() in normalized for term in entry.en_terms):
            matched.append(entry)
    return matched


def expand_query(query: str, matched: list[GlossaryEntry] | None = None) -> str:
    """Return an enhanced query string with glossary expansions appended.

    If *matched* is not provided, it is computed from the query automatically.
    """
    if matched is None:
        matched = match_glossary(query)
    if not matched:
        return query
    expansions: list[str] = []
    for entry in matched:
        expansions.extend(entry.expansions)
    unique = list(dict.fromkeys(expansions))
    return f"{query} {' '.join(unique)}"
