from dataclasses import FrozenInstanceError

import pytest

from ate_rag_kb.domain import ADVANTEST_V93000_SMT8
from ate_rag_kb.domain.scopes import (
    ADVANTEST_V93000_SMT7,
    TERADYNE_J750_IGXL,
    RetrievalScope,
    configured_scopes,
    infer_scope_from_source,
)
from ate_rag_kb.utils.config import Config


def test_scope_filters_use_canonical_fields() -> None:
    assert TERADYNE_J750_IGXL.to_filters() == {
        "vendor": "teradyne",
        "platform": "j750",
        "software": "igxl",
    }


def test_v93000_scope_filters_include_platform_common_docs() -> None:
    assert ADVANTEST_V93000_SMT7.to_filters() == {
        "vendor": "advantest",
        "platform": "v93000",
        "software": ["smt7", ""],
    }


def test_scope_filters_include_nonempty_software_release() -> None:
    scope = RetrievalScope("advantest", "v93000", "smt7", "7.3.1")

    assert scope.to_filters()["software_release"] == "7.3.1"


def test_scope_key_uses_platform_and_software() -> None:
    assert TERADYNE_J750_IGXL.key == "j750/igxl"


def test_scope_is_frozen_and_uses_slots() -> None:
    with pytest.raises(FrozenInstanceError):
        TERADYNE_J750_IGXL.software = "other"  # type: ignore[misc]
    assert not hasattr(TERADYNE_J750_IGXL, "__dict__")


def test_enabled_scopes_are_loaded_from_config() -> None:
    config = Config(
        {
            "documents": {
                "enabled_scopes": [
                    {"vendor": "teradyne", "platform": "j750", "software": "igxl"},
                    {"vendor": "advantest", "platform": "v93000", "software": "smt7"},
                ]
            }
        }
    )

    assert configured_scopes(config) == (
        TERADYNE_J750_IGXL,
        ADVANTEST_V93000_SMT7,
    )


def test_enabled_scopes_fall_back_to_legacy_config() -> None:
    config = Config(
        {
            "documents": {
                "igxl": {"enabled": True},
                "v93000": {"enabled_software_versions": ["smt7", "smt8"]},
            }
        }
    )

    assert configured_scopes(config) == (
        TERADYNE_J750_IGXL,
        ADVANTEST_V93000_SMT7,
        ADVANTEST_V93000_SMT8,
    )


def test_source_path_infers_igxl_scope() -> None:
    assert infer_scope_from_source("igxl/vbt/execSites.39.08.md") == TERADYNE_J750_IGXL


def test_source_path_infers_smt7_scope() -> None:
    assert infer_scope_from_source("v93000/smt7/100096.md") == ADVANTEST_V93000_SMT7


def test_source_path_infers_smt8_scope() -> None:
    assert infer_scope_from_source("v93000/smt8/reference.md") == ADVANTEST_V93000_SMT8


@pytest.mark.parametrize("source_md", ["v93000/timing/levels.md", "tdc/overview.md"])
def test_source_path_infers_v93000_common_scope(source_md: str) -> None:
    assert infer_scope_from_source(source_md) == RetrievalScope("advantest", "v93000", "")


def test_unknown_source_path_has_no_scope() -> None:
    assert infer_scope_from_source("misc/overview.md") is None


def test_v93000_scope_matches_platform_common_docs() -> None:
    assert ADVANTEST_V93000_SMT7.matches_document("advantest", "v93000", "")


def test_scope_match_isolated_by_vendor() -> None:
    assert not ADVANTEST_V93000_SMT7.matches_document("teradyne", "v93000", "smt7")
