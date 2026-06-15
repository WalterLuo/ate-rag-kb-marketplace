"""Retrieval planner for ATE KB query analysis and enhancement.

Analyzes user queries to detect ecosystem, doc family, expands Chinese terms
via glossary, extracts title-match terms, and infers Qdrant filters.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any

from ate_rag_kb.domain.scopes import RetrievalScope
from ate_rag_kb.retrieval.glossary import GlossaryEntry, expand_query, match_glossary
from ate_rag_kb.utils.config import Config
from ate_rag_kb.utils.scope import DocumentScope

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Ecosystem / doc-family detection vocabularies
# ---------------------------------------------------------------------------

_IGXL_ECOSYSTEM_TERMS: tuple[str, ...] = (
    "ig-xl",
    "igxl",
    "j750",
    "ultraflex",
    "mto800",
    "dsio200",
    "apmu",
    "ip750",
    "test analysis tool",
    "secs/gem",
    "available j750 features",
    "simulatedconfig_j750",
    "hsd800",
    "j750ex",
    "test program protection",
    "visual basic for test",
    "driverapi",
    "pattern tool",
    "mto",
    "vectors worksheet",
    "datatool",
    "bitmap tool",
    "redundancy analysis",
    "raplus",
    "production bit map",
    "tpprotection",
    "tppusing",
    "flow table",
    "pin map",
    "test instances",
    "vbt",
)

_V93000_ECOSYSTEM_TERMS: tuple[str, ...] = (
    "v93000",
    "smartest",
    "smt7",
    "smt8",
    "tdc",
    "test development center",
    "device preparation",
    "test program creation",
    "flow creator",
    "module",
    "test suite",
    "pin electronics",
    "channel card",
    "ps1600",
    "cmu",
    "dps",
    "dvi",
    "pvi",
    "uvi",
    "vector memory",
    "flextest",
)

_IGXL_DOC_FAMILY_TERMS: tuple[str, ...] = (
    "datatool",
    "pattern tool",
    "bitmap tool",
    "test analysis tool",
    "vbt",
    "visual basic for test",
    "driverapi",
    "mto800",
    "flow table",
    "pin map",
    "test instances",
    "secs/gem",
    "mto",
    "vectors worksheet",
)

_TDC_DOC_FAMILY_TERMS: tuple[str, ...] = (
    "tdc",
    "test development center",
)

# Weak TDC terms: may boost relevance but must NOT trigger exclusive TDC filtering.
_TDC_BOOST_TERMS: tuple[str, ...] = (
    "device preparation",
    "test program creation",
    "flow creator",
    "module",
    "test suite",
)

_SMT7_DOC_FAMILY_TERMS: tuple[str, ...] = (
    "smt7",
    "smartest 7",
    "online help",
    "operator mode",
    "engineering mode",
)

_V93000_MANUAL_TERMS: tuple[str, ...] = (
    "v93000 manual",
    "hardware manual",
    "reference manual",
    "user guide",
    "getting started",
)

# Terms that strongly indicate a NON-IG-XL query
_NON_IGXL_TERMS: tuple[str, ...] = ("v93000", "smartest", "smt7", "smt8")


@dataclass
class RetrievalPlan:
    """The output of query planning: a structured retrieval strategy."""

    original_query: str
    enhanced_query: str  # Original + glossary expansions
    inferred_filters: dict[str, Any] | None
    ecosystem: str | None  # "igxl" | "v93000"
    doc_family: str | None  # "tdc" | "smt7_help" | "igxl_help" | "v93000_manual"
    title_match_terms: list[str]  # Proper nouns for title boosting
    is_igxl_query: bool
    is_v93000_smt7_query: bool
    is_broad_concept: bool = False
    is_ambiguous: bool = False
    clarification_prompt: str | None = None
    is_blocked: bool = False
    block_reason: str | None = None


class RetrievalPlanner:
    """Analyzes ATE queries and produces structured retrieval plans."""

    def __init__(self, config: Config | None = None) -> None:
        self.config = config or Config({})
        self.scope = DocumentScope(self.config)
        self._title_boost_factor = self.config.get("retrieval.planner.title_boost_factor", 0.15)
        self._glossary_enabled = self.config.get("retrieval.planner.glossary_enabled", True)
        self._auto_filter_enabled = self.config.get("retrieval.planner.auto_filter_enabled", True)

    def plan(self, query: str, scope: RetrievalScope | None = None) -> RetrievalPlan:
        """Analyze *query* and return a ``RetrievalPlan``."""
        ecosystem = self._ecosystem_from_scope(scope) or self._detect_ecosystem(query)
        doc_family = self._detect_doc_family(query, ecosystem)
        if scope is not None and scope.software == "igxl" and doc_family is None:
            doc_family = "igxl_help"

        if self._glossary_enabled:
            matched_glossary = self._compatible_glossary_entries(
                match_glossary(query),
                ecosystem,
                scope,
            )
            enhanced_query = expand_query(query, matched_glossary)
        else:
            matched_glossary = []
            enhanced_query = query

        # Backfill ecosystem / doc_family from glossary when the query is
        # ambiguous (no explicit platform mentioned by the user).
        if matched_glossary:
            glossary_ecosystem = None
            glossary_doc_family = None
            for entry in matched_glossary:
                if entry.ecosystem:
                    glossary_ecosystem = entry.ecosystem
                if entry.doc_family:
                    glossary_doc_family = entry.doc_family

            # Only backfill if the user did not explicitly specify an
            # ecosystem, or if the glossary value is compatible.
            if ecosystem is None and glossary_ecosystem is not None:
                ecosystem = glossary_ecosystem
            if (
                doc_family is None
                and glossary_doc_family is not None
                and (
                    ecosystem is None
                    or glossary_ecosystem is None
                    or ecosystem == glossary_ecosystem
                )
            ):
                doc_family = glossary_doc_family

        title_match_terms = self._extract_title_match_terms(query, matched_glossary)

        if self._auto_filter_enabled:
            inferred_filters = self._infer_filters(ecosystem, doc_family, query)
        else:
            inferred_filters = None

        # Block detection: IG-XL queries when IG-XL is disabled
        is_blocked = False
        block_reason = None
        if ecosystem == "igxl" and not self.scope.isIgxlEnabled():
            is_blocked = True
            block_reason = "IG-XL documentation is not enabled in the current configuration."

        # Ambiguity detection: smt7 vs smt8 when both enabled and query is vague
        is_ambiguous = False
        clarification_prompt = None
        enabled_versions = self.scope.enabledSoftwareVersions("v93000")
        if (
            scope is None
            and ecosystem == "v93000"
            and len(enabled_versions) > 1
            and self.scope.shouldAskWhenMultiple()
        ):
            normalized = query.lower()
            has_version_specific = any(
                term in normalized
                for term in ("smt7", "smartest 7", "7.x", "smt8", "smartest 8", "8.x")
            )
            has_vague_version = any(term in normalized for term in ("smartest", "smt", "version"))
            if has_vague_version and not has_version_specific:
                is_ambiguous = True
                clarification_prompt = (
                    "Your query mentions SmarTest but does not specify the software version. "
                    "Please clarify whether you are asking about SMT7 or SMT8."
                )

        is_broad_concept = self._detect_broad_concept(query)

        return RetrievalPlan(
            original_query=query,
            enhanced_query=enhanced_query,
            inferred_filters=inferred_filters,
            ecosystem=ecosystem,
            doc_family=doc_family,
            title_match_terms=title_match_terms,
            is_igxl_query=ecosystem == "igxl",
            is_v93000_smt7_query=ecosystem == "v93000",
            is_broad_concept=is_broad_concept,
            is_ambiguous=is_ambiguous,
            clarification_prompt=clarification_prompt,
            is_blocked=is_blocked,
            block_reason=block_reason,
        )

    @staticmethod
    def _ecosystem_from_scope(scope: RetrievalScope | None) -> str | None:
        if scope is None:
            return None
        if scope.software == "igxl":
            return "igxl"
        if scope.platform == "v93000":
            return "v93000"
        return None

    @staticmethod
    def _compatible_glossary_entries(
        entries: list[GlossaryEntry],
        explicit_ecosystem: str | None,
        scope: RetrievalScope | None = None,
    ) -> list[GlossaryEntry]:
        """Drop glossary expansions that conflict with an explicit ecosystem.

        Generic entries without an ecosystem are allowed everywhere. Entries
        tied to IG-XL or V93000 only apply when the query did not already name
        the other ecosystem.
        """
        compatible: list[GlossaryEntry] = []
        for entry in entries:
            if scope is not None and entry.software and entry.software != scope.software:
                continue
            if (
                scope is None
                and entry.software
                and explicit_ecosystem is not None
                and RetrievalPlanner._ecosystem_from_software(entry.software) != explicit_ecosystem
            ):
                continue
            if explicit_ecosystem is not None and entry.ecosystem not in (None, explicit_ecosystem):
                continue
            compatible.append(entry)
        return compatible

    @staticmethod
    def _ecosystem_from_software(software: str) -> str | None:
        if software == "igxl":
            return "igxl"
        if software in {"smt7", "smt8"}:
            return "v93000"
        return None

    # -----------------------------------------------------------------------
    # Ecosystem detection
    # -----------------------------------------------------------------------

    @staticmethod
    def _detect_ecosystem(query: str) -> str | None:
        """Detect tester ecosystem from query text.

        Returns ``"igxl"``, ``"v93000"``, or ``None``.
        """
        normalized = query.lower()

        # If non-IGXL terms appear, prefer v93000 ecosystem
        has_non_igxl = any(term in normalized for term in _NON_IGXL_TERMS)
        if has_non_igxl:
            return "v93000"

        has_igxl = any(term in normalized for term in _IGXL_ECOSYSTEM_TERMS)
        if has_igxl:
            return "igxl"

        has_v93000 = any(term in normalized for term in _V93000_ECOSYSTEM_TERMS)
        if has_v93000:
            return "v93000"

        return None

    # -----------------------------------------------------------------------
    # Doc family detection
    # -----------------------------------------------------------------------

    @staticmethod
    def _detect_doc_family(query: str, ecosystem: str | None) -> str | None:
        """Detect document family within an ecosystem."""
        normalized = query.lower()

        # TDC is detected first because it is a sub-family under v93000
        if any(term in normalized for term in _TDC_DOC_FAMILY_TERMS):
            return "tdc"

        if ecosystem == "igxl":
            if any(term in normalized for term in _IGXL_DOC_FAMILY_TERMS):
                return "igxl_help"
            return "igxl_help"  # Default for IG-XL ecosystem

        if ecosystem == "v93000":
            if any(term in normalized for term in _SMT7_DOC_FAMILY_TERMS):
                return "smt7_help"
            if any(term in normalized for term in _V93000_MANUAL_TERMS):
                return "v93000_manual"
            return None

        return None

    # -----------------------------------------------------------------------
    # Broad concept detection
    # -----------------------------------------------------------------------

    _BROAD_CONCEPT_TERMS: tuple[str, ...] = (
        "what is",
        "how does",
        "overview",
        "introduction",
        "都有什么",
        "是什么",
        "有什么用",
        "作用",
        "用途",
        "做什么",
        "介绍一下",
        "概述",
        "explain",
        "describe",
    )

    @staticmethod
    def _detect_broad_concept(query: str) -> bool:
        """Return True when the query asks for a broad conceptual answer."""
        normalized = query.lower()
        # Long queries (>>30 chars) with broad terms are likely broad concept
        has_broad_term = any(term in normalized for term in RetrievalPlanner._BROAD_CONCEPT_TERMS)
        is_long = len(query) > 30
        return has_broad_term or is_long

    # -----------------------------------------------------------------------
    # Title match term extraction
    # -----------------------------------------------------------------------

    @staticmethod
    def _extract_title_match_terms(query: str, matched_glossary: list[GlossaryEntry]) -> list[str]:
        """Extract proper nouns (sheet names, commands, APIs) for title matching.

        Returns a list of lower-cased terms that should be searched in
        doc_title, section_title, subsection_title, and toc_path.
        """
        terms: list[str] = []

        # Add expansions from matched glossary entries
        for entry in matched_glossary:
            terms.extend(entry.expansions)
            terms.extend(entry.en_terms)

        # Extract capitalized phrases (e.g., "Job List Sheet", "MTO Resource Map")
        # Match sequences of capitalized words
        capitalized_phrases = re.findall(r"[A-Z][a-zA-Z0-9_]*(?:\s+[A-Z][a-zA-Z0-9_]*)+", query)
        terms.extend(capitalized_phrases)

        # Extract quoted phrases
        quoted = re.findall(r'"([^"]+)"', query)
        terms.extend(quoted)

        # Deduplicate and lower-case
        seen: set[str] = set()
        result: list[str] = []
        for term in terms:
            lowered = term.lower()
            if lowered not in seen and len(lowered) > 1:
                seen.add(lowered)
                result.append(lowered)
        return result

    # -----------------------------------------------------------------------
    # Filter inference
    # -----------------------------------------------------------------------

    def _infer_filters(
        self,
        ecosystem: str | None,
        doc_family: str | None,
        query: str,
    ) -> dict[str, Any] | None:
        """Build Qdrant filters from detected ecosystem / doc_family."""
        normalized = query.lower()

        if ecosystem == "igxl":
            # IG-XL queries do NOT set a platform filter;
            # contamination is handled post-search by ecosystem filter.
            return None

        if ecosystem == "v93000":
            # TDC is a doc_family under the v93000 ecosystem.
            if doc_family == "tdc":
                return {"ecosystem": "v93000", "doc_family": "tdc"}

            # Software version specific queries include general docs (empty software_version)
            if "smt7" in normalized or "smartest 7" in normalized or "7.x" in normalized:
                return {"ecosystem": "v93000", "software_version": ["smt7", ""]}
            if "smt8" in normalized or "smartest 8" in normalized or "8.x" in normalized:
                return {"ecosystem": "v93000", "software_version": ["smt8", ""]}

            # General v93000 query
            if "v93000" in normalized:
                return {"ecosystem": "v93000"}

            # If we know it's v93000 ecosystem but no specific version,
            # allow all v93000 docs
            return {"ecosystem": "v93000"}

        return None
