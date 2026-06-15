"""Canonical retrieval scope identities."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath

from ate_rag_kb.utils.config import Config


@dataclass(frozen=True, slots=True)
class RetrievalScope:
    vendor: str
    platform: str
    software: str
    software_release: str = ""

    @property
    def key(self) -> str:
        return f"{self.platform}/{self.software}"

    def to_filters(self) -> dict[str, str | list[str]]:
        software_filter: str | list[str] = self.software
        if self.platform == "v93000" and self.software:
            software_filter = [self.software, ""]
        filters: dict[str, str | list[str]] = {
            "vendor": self.vendor,
            "platform": self.platform,
            "software": software_filter,
        }
        if self.software_release:
            filters["software_release"] = self.software_release
        return filters

    def matches_document(self, vendor: str, platform: str, software: str) -> bool:
        if vendor != self.vendor or platform != self.platform:
            return False
        return software == self.software or (
            self.platform == "v93000" and software == ""
        )


TERADYNE_J750_IGXL = RetrievalScope("teradyne", "j750", "igxl")
ADVANTEST_V93000_SMT7 = RetrievalScope("advantest", "v93000", "smt7")
ADVANTEST_V93000_SMT8 = RetrievalScope("advantest", "v93000", "smt8")


def configured_scopes(config: Config) -> tuple[RetrievalScope, ...]:
    raw_scopes = config.get("documents.enabled_scopes", ())
    if raw_scopes:
        return tuple(RetrievalScope(**raw_scope) for raw_scope in raw_scopes)

    scopes: list[RetrievalScope] = []
    if config.get("documents.igxl.enabled", False):
        scopes.append(TERADYNE_J750_IGXL)
    enabled_versions = config.get("documents.v93000.enabled_software_versions", ())
    if "smt7" in enabled_versions:
        scopes.append(ADVANTEST_V93000_SMT7)
    if "smt8" in enabled_versions:
        scopes.append(ADVANTEST_V93000_SMT8)
    return tuple(scopes)


def infer_scope_from_source(source_md: str) -> RetrievalScope | None:
    parts = {part.lower() for part in PurePosixPath(source_md).parts}
    if "igxl" in parts:
        return TERADYNE_J750_IGXL
    if "smt7" in parts:
        return ADVANTEST_V93000_SMT7
    if "smt8" in parts:
        return ADVANTEST_V93000_SMT8
    if "v93000" in parts or "tdc" in parts:
        return RetrievalScope("advantest", "v93000", "")
    return None
