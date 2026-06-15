"""Unit tests for ingestion pipeline helpers."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from ate_rag_kb.domain.scopes import ADVANTEST_V93000_SMT7, TERADYNE_J750_IGXL
from ate_rag_kb.ingestion.pipeline import IngestionPipeline
from ate_rag_kb.utils.config import Config


class TestDetectPlatform:
    def test_detects_j750(self) -> None:
        assert IngestionPipeline._detect_platform(Path("j750_guide.md")) == "J750"
        assert IngestionPipeline._detect_platform(Path("ultraflex_ref.md")) == "J750"

    def test_detects_smt7(self) -> None:
        assert IngestionPipeline._detect_platform(Path("smt7_api.md")) == "V93000"

    def test_detects_smt8(self) -> None:
        assert IngestionPipeline._detect_platform(Path("smt8_flow.md")) == "V93000"

    def test_detects_v93000(self) -> None:
        assert IngestionPipeline._detect_platform(Path("v93000_setup.md")) == "V93000"
        assert IngestionPipeline._detect_platform(Path("smartest_guide.md")) == "V93000"

    def test_detects_tdc_as_v93000_ecosystem(self) -> None:
        assert IngestionPipeline._detect_platform(Path("tdc_overview.md")) == "V93000"

    def test_unknown_returns_empty(self) -> None:
        assert IngestionPipeline._detect_platform(Path("unknown.md")) == ""


class TestDetectDocType:
    def test_detects_api(self) -> None:
        assert IngestionPipeline._detect_doc_type(Path("api_reference.md")) == "api"
        assert IngestionPipeline._detect_doc_type(Path("commands.md")) == "api"

    def test_detects_flow(self) -> None:
        assert IngestionPipeline._detect_doc_type(Path("testflow_guide.md")) == "flow"

    def test_detects_hardware_config(self) -> None:
        assert IngestionPipeline._detect_doc_type(Path("timing_setup.md")) == "hardware_config"
        assert IngestionPipeline._detect_doc_type(Path("pin_config.md")) == "hardware_config"

    def test_detects_guide(self) -> None:
        assert IngestionPipeline._detect_doc_type(Path("getting started.md")) == "guide"
        assert IngestionPipeline._detect_doc_type(Path("tutorial.md")) == "guide"

    def test_default_is_reference(self) -> None:
        assert IngestionPipeline._detect_doc_type(Path("random.md")) == "reference"


class TestDetectEcosystem:
    def test_detects_igxl_from_path(self) -> None:
        assert IngestionPipeline._detect_ecosystem("igxl/overview.md", "", {}) == "igxl"

    def test_detects_v93000_from_smt7_path(self) -> None:
        assert IngestionPipeline._detect_ecosystem("smt7/api.md", "", {}) == "v93000"

    def test_detects_v93000_from_smt8_path(self) -> None:
        assert IngestionPipeline._detect_ecosystem("smt8/flow.md", "", {}) == "v93000"

    def test_detects_v93000_from_smartest64_7_filename(self) -> None:
        assert IngestionPipeline._detect_ecosystem("docs/smartest64_7_guide.md", "", {}) == "v93000"

    def test_detects_v93000_from_smartest64_8_filename(self) -> None:
        assert IngestionPipeline._detect_ecosystem("docs/smartest64_8_guide.md", "", {}) == "v93000"

    def test_detects_v93000_from_tdc_path(self) -> None:
        assert IngestionPipeline._detect_ecosystem("tdc/overview.md", "", {}) == "v93000"

    def test_detects_v93000_from_v93000_path(self) -> None:
        assert IngestionPipeline._detect_ecosystem("v93000/setup.md", "", {}) == "v93000"

    def test_detects_v93000_from_v93000_smt7_path(self) -> None:
        assert IngestionPipeline._detect_ecosystem("v93000/smt7/api.md", "", {}) == "v93000"

    def test_detects_v93000_from_v93000_smt8_path(self) -> None:
        assert IngestionPipeline._detect_ecosystem("v93000/smt8/flow.md", "", {}) == "v93000"

    def test_uses_json_meta_fallback(self) -> None:
        assert IngestionPipeline._detect_ecosystem("unknown.md", "", {"ecosystem": "igxl"}) == "igxl"

    def test_detects_v93000_from_toc_path(self) -> None:
        assert (
            IngestionPipeline._detect_ecosystem(
                "20847.md", "", {"toc_path": ["SmarTest 7.4.3 Documentation", "System Reference"]}
            )
            == "v93000"
        )

    def test_detects_v93000_from_title(self) -> None:
        assert (
            IngestionPipeline._detect_ecosystem(
                "some_doc.md", "SmarTest 7.x Guide", {}
            )
            == "v93000"
        )

    def test_detects_igxl_from_toc_path(self) -> None:
        assert (
            IngestionPipeline._detect_ecosystem(
                "unknown.md", "", {"toc_path": ["IG-XL Help", "Overview"]}
            )
            == "igxl"
        )

    def test_returns_empty_when_unknown(self) -> None:
        assert IngestionPipeline._detect_ecosystem("random.md", "", {}) == ""

    def test_detects_v93000_from_root_numeric_markdown(self) -> None:
        assert IngestionPipeline._detect_ecosystem("119718.md", "119718", {"toc_path": []}) == "v93000"

    def test_detects_v93000_from_root_rel7_release_note(self) -> None:
        assert IngestionPipeline._detect_ecosystem("HEADER_FEATURE_rel7.2.2.md", "", {}) == "v93000"
        assert IngestionPipeline._detect_ecosystem("RELEASENOTE_Platform_rel7.3.1.md", "", {}) == "v93000"
        assert IngestionPipeline._detect_ecosystem("luna_7.2.0.3.readme.md", "", {}) == "v93000"


class TestDetectSoftwareVersion:
    def test_detects_smt7_from_path(self) -> None:
        assert IngestionPipeline._detect_software_version("smt7/api.md", "", {}) == "smt7"

    def test_detects_smt7_from_filename(self) -> None:
        assert IngestionPipeline._detect_software_version("docs/smartest64_7_guide.md", "", {}) == "smt7"

    def test_detects_smt8_from_path(self) -> None:
        assert IngestionPipeline._detect_software_version("smt8/flow.md", "", {}) == "smt8"

    def test_detects_smt8_from_filename(self) -> None:
        assert IngestionPipeline._detect_software_version("docs/smartest64_8_guide.md", "", {}) == "smt8"

    def test_uses_json_meta_fallback(self) -> None:
        assert IngestionPipeline._detect_software_version("unknown.md", "", {"software_version": "smt7"}) == "smt7"

    def test_returns_empty_when_unknown(self) -> None:
        assert IngestionPipeline._detect_software_version("v93000/general.md", "", {}) == ""

    def test_detects_smt7_from_toc_path(self) -> None:
        assert (
            IngestionPipeline._detect_software_version(
                "20847.md", "", {"toc_path": ["SmarTest 7.4.3 Documentation", "System Reference"]}
            )
            == "smt7"
        )

    def test_detects_smt7_from_title(self) -> None:
        assert (
            IngestionPipeline._detect_software_version(
                "some_doc.md", "V93000 SmarTest 7.x API", {}
            )
            == "smt7"
        )

    def test_detects_smt8_from_toc_path(self) -> None:
        assert (
            IngestionPipeline._detect_software_version(
                "some_doc.md", "", {"toc_path": ["SmarTest 8.0 Documentation"]}
            )
            == "smt8"
        )

    def test_detects_smt7_from_root_numeric_markdown(self) -> None:
        assert IngestionPipeline._detect_software_version("119718.md", "119718", {"toc_path": []}) == "smt7"

    def test_detects_smt7_from_root_rel7_release_note(self) -> None:
        assert IngestionPipeline._detect_software_version("HEADER_FEATURE_rel7.2.2.md", "", {}) == "smt7"
        assert IngestionPipeline._detect_software_version("RELEASENOTE_Platform_rel7.3.1.md", "", {}) == "smt7"
        assert IngestionPipeline._detect_software_version("luna_7.2.0.3.readme.md", "", {}) == "smt7"


class TestDetectScope:
    def test_detects_igxl_scope(self) -> None:
        pipeline = IngestionPipeline(Config({}), MagicMock(), MagicMock())

        assert pipeline._detect_scope("igxl/vbt/execSites.39.08.md", "", {}) == TERADYNE_J750_IGXL

    def test_detects_root_smt7_scope_from_toc_metadata(self) -> None:
        pipeline = IngestionPipeline(Config({}), MagicMock(), MagicMock())

        assert (
            pipeline._detect_scope(
                "20847.md",
                "",
                {"toc_path": ["SmarTest 7.4.3 Documentation", "System Reference"]},
            )
            == ADVANTEST_V93000_SMT7
        )

    def test_unknown_document_has_no_scope(self) -> None:
        pipeline = IngestionPipeline(Config({}), MagicMock(), MagicMock())

        assert pipeline._detect_scope("misc/overview.md", "", {}) is None


class TestDetectDocFamily:
    def test_detects_igxl_help(self) -> None:
        assert IngestionPipeline._detect_doc_family("igxl/overview.md", "", {}) == "igxl_help"

    def test_detects_tdc(self) -> None:
        assert IngestionPipeline._detect_doc_family("tdc/timing.md", "", {}) == "tdc"

    def test_uses_json_meta_fallback(self) -> None:
        assert IngestionPipeline._detect_doc_family("unknown.md", "", {"doc_family": "api_ref"}) == "api_ref"

    def test_returns_empty_when_unknown(self) -> None:
        assert IngestionPipeline._detect_doc_family("v93000/general.md", "", {}) == ""


class TestRealFixtureDetection:
    """Tests against real JSON metadata files in data/raw/json/."""

    REAL_JSON_DIR = Path("./data/raw/json/v93000/smt7")

    def test_real_20847_detected_as_v93000_smt7(self) -> None:
        json_path = self.REAL_JSON_DIR / "20847.json"
        if not json_path.exists():
            pytest.skip("20847.json not found")
        import json

        meta = json.loads(json_path.read_text(encoding="utf-8"))
        title = meta.get("title", "")
        assert IngestionPipeline._detect_ecosystem("v93000/smt7/20847.md", title, meta) == "v93000"
        assert IngestionPipeline._detect_software_version("v93000/smt7/20847.md", title, meta) == "smt7"

    def test_real_130224_detected_as_v93000_smt7(self) -> None:
        json_path = self.REAL_JSON_DIR / "130224.json"
        if not json_path.exists():
            pytest.skip("130224.json not found")
        import json

        meta = json.loads(json_path.read_text(encoding="utf-8"))
        title = meta.get("title", "")
        assert IngestionPipeline._detect_ecosystem("v93000/smt7/130224.md", title, meta) == "v93000"
        assert IngestionPipeline._detect_software_version("v93000/smt7/130224.md", title, meta) == "smt7"

    def test_real_102025_detected_as_v93000_smt7(self) -> None:
        json_path = self.REAL_JSON_DIR / "102025.json"
        if not json_path.exists():
            pytest.skip("102025.json not found")
        import json

        meta = json.loads(json_path.read_text(encoding="utf-8"))
        title = meta.get("title", "")
        assert IngestionPipeline._detect_ecosystem("v93000/smt7/102025.md", title, meta) == "v93000"
        assert IngestionPipeline._detect_software_version("v93000/smt7/102025.md", title, meta) == "smt7"


class TestShouldIngest:
    def test_allows_when_no_enabled_ecosystems_configured(self, tmp_path: Path) -> None:
        cfg = Config({})
        pipeline = IngestionPipeline(cfg, MagicMock(), MagicMock())
        assert pipeline._should_ingest(tmp_path / "test.md", "v93000", "smt7") is True

    def test_allows_matching_ecosystem(self, tmp_path: Path) -> None:
        cfg = Config({"documents": {"enabled_ecosystems": ["v93000"]}})
        pipeline = IngestionPipeline(cfg, MagicMock(), MagicMock())
        assert pipeline._should_ingest(tmp_path / "test.md", "v93000", "") is True

    def test_skips_disabled_ecosystem(self, tmp_path: Path) -> None:
        cfg = Config({"documents": {"enabled_ecosystems": ["v93000"]}})
        pipeline = IngestionPipeline(cfg, MagicMock(), MagicMock())
        assert pipeline._should_ingest(tmp_path / "test.md", "igxl", "") is False

    def test_allows_matching_software_version(self, tmp_path: Path) -> None:
        cfg = Config({"documents": {"enabled_ecosystems": ["v93000"], "v93000": {"enabled_software_versions": ["smt7"]}}})
        pipeline = IngestionPipeline(cfg, MagicMock(), MagicMock())
        assert pipeline._should_ingest(tmp_path / "test.md", "v93000", "smt7") is True

    def test_skips_disabled_software_version(self, tmp_path: Path) -> None:
        cfg = Config({"documents": {"enabled_ecosystems": ["v93000"], "v93000": {"enabled_software_versions": ["smt7"]}}})
        pipeline = IngestionPipeline(cfg, MagicMock(), MagicMock())
        assert pipeline._should_ingest(tmp_path / "test.md", "v93000", "smt8") is False

    def test_allows_general_docs_when_versions_filtered(self, tmp_path: Path) -> None:
        cfg = Config({"documents": {"enabled_ecosystems": ["v93000"], "v93000": {"enabled_software_versions": ["smt7"]}}})
        pipeline = IngestionPipeline(cfg, MagicMock(), MagicMock())
        assert pipeline._should_ingest(tmp_path / "test.md", "v93000", "") is True

    def test_skips_general_docs_when_disabled(self, tmp_path: Path) -> None:
        cfg = Config({"documents": {"enabled_ecosystems": ["v93000"], "v93000": {"enabled_software_versions": ["smt7"], "include_general_docs": False}}})
        pipeline = IngestionPipeline(cfg, MagicMock(), MagicMock())
        assert pipeline._should_ingest(tmp_path / "test.md", "v93000", "") is False
