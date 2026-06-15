"""Tests for the IG-XL help conversion helpers."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def load_converter():
    script = Path(__file__).resolve().parents[1] / "scripts" / "convert_igxl_help.py"
    spec = importlib.util.spec_from_file_location("convert_igxl_help", script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_html_to_markdown_removes_navigation_and_preserves_links() -> None:
    converter = load_converter()
    html = """
    <html><head><title>IG-XL Licensing</title><script>skip()</script></head>
    <body>
      <table class="navi"><tr><td>Previous</td></tr></table>
      <div class="WebWorks_Breadcrumbs">IG-XL Licensing</div>
      <blockquote>
        <div class="Chapter">IG-XL Licensing</div>
        <div class="Body">Use the <a href="portal.html">licensing portal</a>.</div>
        <div class="Bullet1_outer"><table><tr><td>•</td><td>J750 feature license</td></tr></table></div>
      </blockquote>
    </body></html>
    """

    result = converter.html_to_markdown(html, title="IG-XL Licensing")

    assert result.startswith("# IG-XL Licensing")
    assert "Previous" not in result
    assert "[licensing portal](portal.html)" in result
    assert "- J750 feature license" in result


def test_rewrite_markdown_links_retargets_same_chm_html_links() -> None:
    converter = load_converter()
    mapping = {
        ("igxladmin.chm", "adLicensing.2.2.html"): Path("igxladmin/adLicensing.2.2.md"),
    }
    markdown = "See [Enabling Licensed Features](adLicensing.2.2.html)."

    result = converter.rewrite_markdown_links(
        markdown,
        current_chm="IGXLAdmin.chm",
        current_rel_md=Path("igxladmin/adLicensing.2.1.md"),
        link_map=mapping,
    )

    assert result == "See [Enabling Licensed Features](adLicensing.2.2.md).\n"


def test_rewrite_markdown_links_retargets_cross_chm_ms_its_links() -> None:
    converter = load_converter()
    mapping = {
        ("hardwarespecs.chm", "APMUSpecs.03.01.html"): Path("hardwarespecs/APMUSpecs.03.01.md"),
    }
    markdown = (
        "For more information, see "
        "[APMU Specifications](ms-its:HardwareSpecs.chm::/APMUSpecs.03.01.html)."
    )

    result = converter.rewrite_markdown_links(
        markdown,
        current_chm="APMU.chm",
        current_rel_md=Path("apmu/apmu_about.1.2.md"),
        link_map=mapping,
    )

    assert result == (
        "For more information, see "
        "[APMU Specifications](../hardwarespecs/APMUSpecs.03.01.md).\n"
    )


def test_rewrite_markdown_links_handles_brackets_in_link_text() -> None:
    converter = load_converter()
    mapping = {
        ("testtemplates.chm", "ttCtoAdc.05.20.html"): Path("testtemplates/ttCtoAdc.05.20.md"),
    }
    markdown = "See [Diff-Err, Absolute, GainErr [%]](ttCtoAdc.05.20.html)."

    result = converter.rewrite_markdown_links(
        markdown,
        current_chm="TestTemplates.chm",
        current_rel_md=Path("testtemplates/ttCtoAdc.05.22.md"),
        link_map=mapping,
    )

    assert result == "See [Diff-Err, Absolute, GainErr [%]](ttCtoAdc.05.20.md).\n"


def test_rewrite_markdown_links_preserves_unresolved_anchors() -> None:
    converter = load_converter()
    markdown = "See [external](https://example.com) and [local](missing.html#anchor)."

    result = converter.rewrite_markdown_links(
        markdown,
        current_chm="APMU.chm",
        current_rel_md=Path("apmu/topic.md"),
        link_map={},
    )

    assert "[external](https://example.com)" in result
    assert "[local](missing.html#anchor)" in result


def test_html_to_markdown_keeps_inline_span_text_in_body_blocks() -> None:
    converter = load_converter()
    html = """
    <html><head><title>Spooling</title></head><body><blockquote>
      <div class="Heading1">Spooling</div>
      <div class="Body">Tester sends S<span class="Emphasis">n</span>F0 messages.</div>
    </blockquote></body></html>
    """

    result = converter.html_to_markdown(html, title="Spooling")

    assert "Tester sends SnF0 messages." in result
    assert result.strip() != "# Spooling\n\nn"


def test_html_to_markdown_separates_adjacent_links_and_note_labels() -> None:
    converter = load_converter()
    html = """
    <html><head><title>Links</title></head><body><blockquote>
      <div class="Body">For more information, see<a href="spec.html">APMU Specifications</a>.</div>
      <div class="Body"><img src="note.gif" alt="*" />Note:Use the template.</div>
    </blockquote></body></html>
    """

    result = converter.html_to_markdown(html, title="Links")

    assert "see [APMU Specifications](spec.html)." in result
    assert "Note: Use the template." in result


def test_polish_markdown_text_separates_nested_bracket_links_and_common_joined_words() -> None:
    converter = load_converter()

    result = converter.polish_markdown_text(
        "see[Diff-Err, GainErr [%]](topic.md) from theStartmenu underOpen STDF File toanalyze data"
    )

    assert result == (
        "see [Diff-Err, GainErr [%]](topic.md) from the Startmenu "
        "under Open STDF File to analyze data"
    )


def test_html_to_markdown_preserves_spaces_around_inline_spans_and_or_terms() -> None:
    converter = load_converter()
    html = """
    <html><head><title>Inline Terms</title></head><body><blockquote>
      <div class="Body">If <span class="Code">virtual_serial_sites</span> is enabled.</div>
      <div class="Body">Use dgen_2bitordgen_16bit for the data generator.</div>
    </blockquote></body></html>
    """

    result = converter.html_to_markdown(html, title="Inline Terms")

    assert "If virtual_serial_sites is enabled." in result
    assert "dgen_2bit or dgen_16bit" in result


def test_parse_hhc_toc_returns_nested_paths() -> None:
    converter = load_converter()
    hhc = """
    <ul>
      <li><object type="text/sitemap">
        <param name="Name" value="IG-XL Licensing">
        <param name="Local" value="adLicensing.2.1.html">
      </object>
      <ul>
        <li><object type="text/sitemap">
          <param name="Name" value="Available J750 Features">
          <param name="Local" value="adLicensing.2.6.html">
        </object>
      </ul>
    </ul>
    """

    toc = converter.parse_hhc_toc(hhc, root_title="IGXLAdmin")

    assert toc["adLicensing.2.1.html"] == ["IG-XL Help", "IGXLAdmin", "IG-XL Licensing"]
    assert toc["adLicensing.2.6.html"] == [
        "IG-XL Help",
        "IGXLAdmin",
        "IG-XL Licensing",
        "Available J750 Features",
    ]


def test_relative_output_stem_is_stable_and_safe() -> None:
    converter = load_converter()

    assert converter.safe_stem(Path("MaintenanceBin/BatchMode_Help.cnt")) == (
        "maintenancebin_batchmode_help"
    )
    assert converter.safe_stem(Path("HPT User Manual.pdf")) == "hpt_user_manual"


def test_cnt_to_markdown_builds_headings_and_links() -> None:
    converter = load_converter()
    text = """:Base DriverAPI.HLP>DrWindow
:Title J750 Visual Basic for Test
1 Overview
2 Visual Basic for Test Overview=Visual_Basic_for_Test@driverapi.hlp>DrWindow
2 Error Handling=Error_Handling_for_VBT@driverapi.hlp>DrWindow
1 Hardware Instruments
2 Hardware (TheHdw)=Hdw_object@driverapi.hlp>DrWindow
"""

    title, markdown, topics = converter.cnt_to_markdown(text, Path("DriverAPI.CNT"))

    assert title == "J750 Visual Basic For Test"
    assert "## Overview" in markdown
    assert "- Visual Basic for Test Overview (`Visual_Basic_for_Test@driverapi.hlp>DrWindow`)" in markdown
    assert "## Hardware Instruments" in markdown
    assert len(topics) == 3


def test_hlp_manifest_uses_matching_cnt_without_binary_strings() -> None:
    converter = load_converter()
    title, markdown = converter.hlp_manifest_markdown(
        Path("DRIVERAPI.HLP"),
        matching_cnt=Path("DriverAPI.CNT"),
        topic_count=42,
    )

    assert title == "Driverapi"
    assert "Legacy WinHelp package" in markdown
    assert "DriverAPI.CNT" in markdown
    assert "42 indexed topics" in markdown
    assert "```text" not in markdown
