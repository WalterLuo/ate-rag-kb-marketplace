"""Deterministic query-to-scope routing for retrieval coordination."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from ate_rag_kb.domain.scopes import (
    ADVANTEST_V93000_SMT7,
    ADVANTEST_V93000_SMT8,
    TERADYNE_J750_IGXL,
    RetrievalScope,
)
from ate_rag_kb.ingestion.symbol_catalog import SymbolCatalog

AnswerMode = Literal["direct", "platform_comparison", "clarification"]


@dataclass(frozen=True, slots=True)
class QueryRoute:
    answer_mode: AnswerMode
    scopes: tuple[RetrievalScope, ...] = ()
    correction_notice: str = ""
    clarification_prompt: str = ""


class ScopeRouter:
    """Resolve a user query to one or more isolated retrieval scopes."""

    def __init__(
        self,
        enabled_scopes: tuple[RetrievalScope, ...],
        symbol_catalog: SymbolCatalog,
    ) -> None:
        self.enabled_scopes = enabled_scopes
        self.symbol_catalog = symbol_catalog

    def route(self, query: str) -> QueryRoute:
        symbol_owner = self.symbol_catalog.find_owner_in_query(query)
        explicit = self._explicit_scopes(query)
        requested_platforms = self._explicit_platforms(query)

        if symbol_owner is not None and symbol_owner.scope in self.enabled_scopes:
            correction = ""
            conflicts_with_scope = bool(explicit) and symbol_owner.scope not in explicit
            conflicts_with_platform = (
                bool(requested_platforms)
                and symbol_owner.scope.platform not in requested_platforms
            )
            if conflicts_with_scope or conflicts_with_platform:
                correction = (
                    f"{symbol_owner.symbol} belongs to "
                    f"{self._scope_label(symbol_owner.scope)}, "
                    "so the answer is routed to its owning software."
                )
            return QueryRoute("direct", (symbol_owner.scope,), correction_notice=correction)

        if "j750" in requested_platforms:
            explicit = (*explicit, *self._enabled_matches(TERADYNE_J750_IGXL))

        if "v93000" in requested_platforms and not any(
            scope.platform == "v93000" for scope in explicit
        ):
            versions = self._v93000_scopes()
            if len(versions) != 1:
                return QueryRoute(
                    "clarification",
                    clarification_prompt=(
                        "V93000 currently has multiple software versions. "
                        "Do you need SMT7 or SMT8?"
                    ),
                )
            explicit = (*explicit, *versions)

        explicit = tuple(dict.fromkeys(explicit))
        if explicit:
            return QueryRoute(
                "platform_comparison" if len(explicit) > 1 else "direct",
                explicit,
            )

        v93000_scopes = self._v93000_scopes()
        if len(v93000_scopes) > 1:
            if any(scope.platform == "j750" for scope in self.enabled_scopes):
                return QueryRoute(
                    "clarification",
                    clarification_prompt="Which tester platform do you need: J750 or V93000?",
                )
            return QueryRoute(
                "clarification",
                clarification_prompt=(
                    "V93000 currently has multiple software versions. "
                    "Do you need SMT7 or SMT8?"
                ),
            )

        return QueryRoute(
            "platform_comparison" if len(self.enabled_scopes) > 1 else "direct",
            self.enabled_scopes,
        )

    def _explicit_scopes(self, query: str) -> tuple[RetrievalScope, ...]:
        normalized = self._normalize(query)
        scopes: list[RetrievalScope] = []
        if "igxl" in normalized:
            scopes.extend(self._enabled_matches(TERADYNE_J750_IGXL))
        if "smt7" in normalized or "smartest 7" in normalized or "smartest7" in normalized:
            scopes.extend(self._enabled_matches(ADVANTEST_V93000_SMT7))
        if "smt8" in normalized or "smartest 8" in normalized or "smartest8" in normalized:
            scopes.extend(self._enabled_matches(ADVANTEST_V93000_SMT8))
        return tuple(dict.fromkeys(scopes))

    def _explicit_platforms(self, query: str) -> set[str]:
        normalized = self._normalize(query)
        platforms: set[str] = set()
        if "j750" in normalized:
            platforms.add("j750")
        if "v93000" in normalized:
            platforms.add("v93000")
        return platforms

    def _v93000_scopes(self) -> tuple[RetrievalScope, ...]:
        return tuple(scope for scope in self.enabled_scopes if scope.platform == "v93000")

    def _enabled_matches(self, target: RetrievalScope) -> tuple[RetrievalScope, ...]:
        return tuple(scope for scope in self.enabled_scopes if scope == target)

    @staticmethod
    def _normalize(query: str) -> str:
        return query.casefold().replace("ig-xl", "igxl").replace("ig xl", "igxl")

    @staticmethod
    def _scope_label(scope: RetrievalScope) -> str:
        if scope == TERADYNE_J750_IGXL:
            return "J750 / IG-XL"
        if scope == ADVANTEST_V93000_SMT7:
            return "V93000 / SMT7"
        if scope == ADVANTEST_V93000_SMT8:
            return "V93000 / SMT8"
        software = scope.software.upper() if scope.software else "general"
        return f"{scope.platform.upper()} / {software}"
