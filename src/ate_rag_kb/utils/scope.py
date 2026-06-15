"""Unified document scope helper for ecosystem / software-version gating."""

from __future__ import annotations

import logging
from pathlib import Path

from ate_rag_kb.domain.scopes import RetrievalScope, configured_scopes
from ate_rag_kb.utils.config import Config

logger = logging.getLogger(__name__)


class DocumentScope:
    """Encapsulates config-driven document ingestion and retrieval scope."""

    def __init__(self, config: Config | None = None) -> None:
        self.config = config or Config({})

    def enabledEcosystems(self) -> list[str]:
        """Return list of enabled ecosystem names."""
        return self.config.get("documents.enabled_ecosystems", []) or []

    def isEcosystemEnabled(self, ecosystem: str) -> bool:
        """Return True if *ecosystem* is enabled (or no filtering is configured)."""
        if ecosystem == "igxl":
            igxl_enabled = self.config.get("documents.igxl.enabled", None)
            if igxl_enabled is not None:
                return bool(igxl_enabled)

        enabled = self.enabledEcosystems()
        if not enabled:
            return True
        return ecosystem in enabled

    def isIgxlEnabled(self) -> bool:
        """Return True when IG-XL docs are enabled."""
        return self.config.get("documents.igxl.enabled", False)

    def enabledSoftwareVersions(self, ecosystem: str) -> list[str]:
        """Return enabled software versions for *ecosystem*."""
        if ecosystem == "v93000":
            return self.config.get("documents.v93000.enabled_software_versions", []) or []
        return []

    def isSoftwareVersionEnabled(self, ecosystem: str, softwareVersion: str) -> bool:
        """Return True if *softwareVersion* is enabled for *ecosystem*."""
        enabled = self.enabledSoftwareVersions(ecosystem)
        if not enabled:
            return True
        return softwareVersion in enabled

    def includeGeneralDocs(self, ecosystem: str) -> bool:
        """Return True if general docs (no specific version) are included."""
        if ecosystem == "v93000":
            return self.config.get("documents.v93000.include_general_docs", True)
        return True

    def ambiguityPolicy(self) -> str:
        """Return the ambiguity policy string."""
        return self.config.get("documents.v93000.ambiguity_policy", "")

    def shouldAskWhenMultiple(self) -> bool:
        """Return True when ambiguity policy is 'ask_when_multiple'."""
        return self.ambiguityPolicy() == "ask_when_multiple"

    def should_ingest_scope(self, path: Path, scope: RetrievalScope | None) -> bool:
        """Return False if a canonical document scope is unavailable or disabled."""
        if scope is None:
            logger.debug("Skipping %s: no canonical document scope", path)
            return False
        if self.config.get("documents.enabled_scopes", None) is not None:
            enabled = configured_scopes(self.config)
            return any(
                candidate.matches_document(scope.vendor, scope.platform, scope.software)
                for candidate in enabled
            )
        ecosystem = (
            "igxl" if scope.software == "igxl" else "v93000" if scope.platform == "v93000" else ""
        )
        software_version = scope.software if ecosystem == "v93000" else ""
        return self.shouldIngest(path, ecosystem, software_version)

    def shouldIngest(self, path: Path, ecosystem: str, softwareVersion: str) -> bool:
        """Return False if document is outside enabled scope."""
        if not self.isEcosystemEnabled(ecosystem):
            logger.debug(
                "Skipping %s: ecosystem '%s' not in %s",
                path,
                ecosystem,
                self.enabledEcosystems(),
            )
            return False

        if ecosystem == "v93000":
            if softwareVersion:
                if not self.isSoftwareVersionEnabled(ecosystem, softwareVersion):
                    logger.debug(
                        "Skipping %s: software_version '%s' not in %s",
                        path,
                        softwareVersion,
                        self.enabledSoftwareVersions(ecosystem),
                    )
                    return False
            else:
                if not self.includeGeneralDocs(ecosystem):
                    logger.debug("Skipping %s: general docs disabled", path)
                    return False

        return True
