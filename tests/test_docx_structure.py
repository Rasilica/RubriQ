from typing import Literal

import pytest

from submission.document_contracts import DocumentSource, SourceId
from submission.docx_structure import read_region
from submission.docx_structure_types import RegionPosition
from submission.docx_validation import WORD_NS
from submission.format_containers import parse_xml
from submission.input_contracts import InputLimits

REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
SOURCE = DocumentSource(
    source_id=SourceId("docx-test"),
    role="report",
    filename="test.docx",
    content_sha256="a" * 64,
    byte_size=1,
    declared_extension="docx",
    detected_format="docx",
    document_version_id="v1",
)


def region(xml: str, kind: Literal["body", "header", "footer", "footnote"] = "body"):
    root = parse_xml(xml.encode(), InputLimits())
    return read_region(root, "word/document.xml", SOURCE, kind)


def body(xml: str):
    return region(f'<w:body xmlns:w="{WORD_NS}" xmlns:r="{REL}">{xml}</w:body>')


def test_unicode_leaf_coordinates_and_whitespace():
    result = body(
        '<w:p><w:r><w:t xml:space="preserve"> 한😀 </w:t><w:tab/>'
        '<w:t>글</w:t><w:br w:type="page"/><w:cr/><w:noBreakHyphen/>'
        "<w:softHyphen/><w:lastRenderedPageBreak/></w:r>"
        "<w:hyperlink><w:r><w:t>끝</w:t></w:r></w:hyperlink></w:p><w:p/>"
    )
    first, empty = result.blocks
    assert first.raw_text == " 한😀 \t글\n\n\u2011\u00ad끝"
    assert first.normalized_text == first.raw_text
    assert first.normalization_version == "identity-v1"
    assert first.raw_coordinate_basis == "docx_paragraph_unicode"
    assert first.raw_char_range.start == 0
    assert first.raw_char_range.end == len(first.raw_text)
    assert first.normalization_map[0].raw_range == first.raw_char_range
    assert first.normalization_map[0].normalized_range == first.raw_char_range
    assert [span.source_char_range.end for span in first.source_spans] == [4, 1, 1, 1, 1, 1, 1, 1]
    assert [
        (span.block_char_range.start, span.block_char_range.end) for span in first.source_spans
    ] == [(0, 4), (4, 5), (5, 6), (6, 7), (7, 8), (8, 9), (9, 10), (10, 11)]
    assert first.source_spans[2].source_locator.path.endswith("/w:r[1]/w:t[2]")
    assert [span.source_coordinate_basis for span in first.source_spans] == [
        "source_node_unicode",
        "synthetic_control_unicode",
        "source_node_unicode",
        "synthetic_control_unicode",
        "synthetic_control_unicode",
        "synthetic_control_unicode",
        "synthetic_control_unicode",
        "source_node_unicode",
    ]
    assert first.source_locator.path == "word/document.xml::/w:body[1]/w:p[1]"
    assert str(first.block_id) == f"{SOURCE.source_id}:{first.source_locator.path}"
    assert all(block.source_locator.original_page_number is None for block in result.blocks)
    assert empty.raw_text == ""
    assert result.warnings == ()


def test_nested_tables_preserve_parents_without_duplicate_text():
    result = body(
        "<w:p><w:r><w:t>before</w:t></w:r></w:p><w:tbl><w:tblPr/>"
        "<w:tblGrid><w:gridCol/></w:tblGrid><w:tr><w:trPr/><w:tc><w:tcPr/>"
        "<w:p><w:r><w:t>outer</w:t></w:r></w:p><w:tbl><w:tr><w:tc>"
        "<w:p><w:r><w:t>inner</w:t></w:r></w:p></w:tc></w:tr></w:tbl>"
        "<w:p><w:r><w:t>after</w:t></w:r></w:p></w:tc><w:tc><w:p/>"
        "</w:tc></w:tr></w:tbl>"
    )
    assert [block.kind for block in result.blocks] == [
        "paragraph",
        "table_cell",
        "paragraph",
        "table_cell",
        "paragraph",
        "paragraph",
        "table_cell",
        "paragraph",
    ]
    assert [block.raw_text for block in result.blocks] == [
        "before",
        "",
        "outer",
        "",
        "inner",
        "after",
        "",
        "",
    ]
    assert result.blocks[3].parent_block_id == result.blocks[1].block_id
    assert result.blocks[4].parent_block_id == result.blocks[3].block_id
    assert result.blocks[5].parent_block_id == result.blocks[1].block_id
    assert result.blocks[6].parent_block_id is None
    assert all(
        block.normalization_map == () for block in result.blocks if block.kind == "table_cell"
    )
    assert [block.reading_order for block in result.blocks] == list(range(8))
    assert result.warnings == ()


@pytest.mark.parametrize(
    ("kind", "tag"), [("header", "hdr"), ("footer", "ftr"), ("footnote", "footnote")]
)
def test_region_container_and_custom_absolute_path(kind, tag):
    root = parse_xml(
        f'<w:{tag} xmlns:w="{WORD_NS}"><w:p><w:r><w:footnoteRef/>'
        f"<w:t>x</w:t></w:r></w:p></w:{tag}>".encode(),
        InputLimits(),
    )
    result = read_region(
        root,
        "word/extra.xml",
        SOURCE,
        kind,
        position=RegionPosition("/w:footnotes[1]/w:footnote[3]", 7),
    )
    container, paragraph = result.blocks
    assert container.kind == kind
    assert container.raw_text == ""
    assert container.normalization_map == ()
    assert container.reading_order == 7
    assert paragraph.reading_order == 8
    assert paragraph.parent_block_id == container.block_id
    assert paragraph.source_locator.path == ("word/extra.xml::/w:footnotes[1]/w:footnote[3]/w:p[1]")
    assert result.warnings == ()


def test_references_in_paragraph_and_section_properties():
    result = body(
        '<w:p><w:pPr><w:sectPr><w:headerReference r:id="h1"/>'
        '</w:sectPr></w:pPr><w:r><w:t>한😀</w:t><w:footnoteReference w:id="7"/>'
        '<w:t>끝</w:t></w:r></w:p><w:sectPr><w:footerReference r:id="f1"/>'
        "</w:sectPr>"
    )
    assert [ref.kind for ref in result.references] == ["header", "footnote", "footer"]
    assert [ref.key for ref in result.references] == ["h1", "7", "f1"]
    assert result.references[1].source_char_offset == 2
    assert result.references[1].source_block_id == result.blocks[0].block_id
    assert result.references[2].source_block_id is None
    assert result.references[2].source_char_offset is None
    assert result.blocks[0].raw_text == "한😀끝"
    assert result.warnings == ()


@pytest.mark.parametrize(
    "tag",
    [
        "ins",
        "del",
        "moveFrom",
        "moveTo",
        "drawing",
        "pict",
        "object",
        "txbxContent",
        "fldSimple",
        "instrText",
        "fldChar",
        "commentReference",
        "unexpected",
        "rPrChange",
    ],
)
def test_unsupported_inline_subtrees_warn_and_skip(tag):
    result = body(
        f"<w:p><w:r><w:t>safe</w:t><w:{tag}><w:t>hidden</w:t></w:{tag}><w:t>tail</w:t></w:r></w:p>"
    )
    assert result.blocks[0].raw_text == "safetail"
    assert len(result.warnings) == 1
    assert result.warnings[0].code == "unsupported_element"
    assert result.warnings[0].source_locator.path.endswith(f"/w:{tag}[1]")


def test_property_revision_reference_and_unknown_namespace_are_visible():
    result = body(
        '<w:p><w:pPr><w:pStyle w:val="Normal"/><w:pPrChange>'
        "<w:pPr/></w:pPrChange></w:pPr><w:r><w:rPr><w:b/>"
        '<w:footnoteReference w:id="9"/></w:rPr><x:t xmlns:x="urn:alien">bad</x:t>'
        "<w:t>ok</w:t></w:r></w:p><w:mystery><w:p/></w:mystery>"
    )
    assert result.blocks[0].raw_text == "ok"
    assert [warning.code for warning in result.warnings] == ["unsupported_element"] * 3
    assert "{urn:alien}t[1]" in result.warnings[1].source_locator.path
    assert result.references[0].key == "9"


def test_xml_text_tails_and_nonempty_markers_warn():
    result = body(
        "BAD<w:p>RAW<w:r><w:t>ok</w:t>TAIL<w:bookmarkStart/>"
        "<w:bookmarkEnd>BAD</w:bookmarkEnd><w:proofErr/><w:commentRangeStart/>"
        "<w:commentRangeEnd/></w:r></w:p>"
    )
    assert result.blocks[0].raw_text == "ok"
    assert [warning.code for warning in result.warnings] == [
        "invalid_structure",
        "invalid_structure",
        "invalid_structure",
        "unsupported_element",
    ]
    assert all(warning.source_locator is not None for warning in result.warnings)


def test_empty_root_and_repeatability():
    assert body("").blocks == ()
    first = body("<w:p><w:r><w:t>a</w:t></w:r></w:p>")
    assert first == body("<w:p><w:r><w:t>a</w:t></w:r></w:p>")


def test_unknown_properties_and_unqualified_elements_are_omissions():
    result = body(
        "<w:p><w:pPr><w:future/><w:rPr><w:ins/></w:rPr></w:pPr>"
        "<w:r><t>hidden</t><w:t>ok</w:t></w:r></w:p>"
    )
    assert result.blocks[0].raw_text == "ok"
    assert len(result.warnings) == 3


def test_namespace_prefix_alias_and_illegal_structure():
    result = region(
        f'<a:body xmlns:a="{WORD_NS}"><a:p><a:r><a:t>x</a:t></a:r></a:p>'
        "<a:tc><a:p><a:r><a:t>wrong</a:t></a:r></a:p></a:tc></a:body>"
    )
    assert len(result.blocks) == 1
    assert result.blocks[0].source_locator.path.endswith("/w:body[1]/w:p[1]")
    assert len(result.warnings) == 1


def test_invalid_text_leaf_and_property_text_never_leak():
    result = body(
        "<w:p><w:pPr><w:t>hidden</w:t></w:pPr><w:r><w:t><w:t>nested</w:t>"
        "</w:t><w:tab>RAW</w:tab><w:t>ok</w:t></w:r></w:p>TAIL"
    )
    assert result.blocks[0].raw_text == "\tok"
    assert [warning.code for warning in result.warnings] == [
        "unsupported_element",
        "unsupported_element",
        "invalid_structure",
        "invalid_structure",
    ]


def test_formatting_tab_stop_is_ignored_and_reference_payload_warns():
    result = body(
        '<w:p><w:pPr><w:tabs><w:tab w:pos="720"/></w:tabs></w:pPr>'
        '<w:r><w:footnoteReference w:id="1">unexpected</w:footnoteReference>'
        "<w:t>x</w:t></w:r></w:p>"
    )
    assert result.blocks[0].raw_text == "x"
    assert len(result.references) == 1
    assert [warning.code for warning in result.warnings] == ["invalid_structure"]
