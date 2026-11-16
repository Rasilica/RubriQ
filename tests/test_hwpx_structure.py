from typing import Final

import pytest

from submission.document_contracts import DocumentSource, SourceId
from submission.format_containers import parse_xml
from submission.hwpx_structure import read_section
from submission.hwpx_structure_types import PARA_NS, SECTION_NS
from submission.input_contracts import InputLimits

SOURCE: Final = DocumentSource(
    source_id=SourceId("hwpx-test"),
    role="report",
    filename="test.hwpx",
    content_sha256="a" * 64,
    byte_size=1,
    declared_extension="hwpx",
    detected_format="hwpx",
    document_version_id="v1",
)


def section(xml: str, *, start: int = 0):
    root = parse_xml(
        f'<hs:sec xmlns:hs="{SECTION_NS}" xmlns:hp="{PARA_NS}">{xml}</hs:sec>'.encode(),
        InputLimits(),
    )
    return read_section(root, "Contents/section0.xml", SOURCE, start_order=start)


def cell(text: str):
    return (
        f"<hp:tbl><hp:tr><hp:tc><hp:subList><hp:p><hp:run>{text}</hp:run>"
        "</hp:p></hp:subList></hp:tc></hp:tr></hp:tbl>"
    )


def test_fragments_follow_nested_tables_with_projection_local_spans():
    # Given: a table interrupts two distinct paragraphs at their XML positions.
    xml = (
        "<hp:p><hp:run><hp:t>before</hp:t>"
        + cell("<hp:t>outer</hp:t>" + cell("<hp:t>inner</hp:t>") + "<hp:t>end</hp:t>")
        + "<hp:t>after</hp:t></hp:run></hp:p>"
    )
    # When
    result = section(xml, start=9)
    # Then
    assert [b.raw_text for b in result.blocks] == [
        "before",
        "",
        "outer",
        "",
        "inner",
        "end",
        "after",
    ]
    assert [b.reading_order for b in result.blocks] == list(range(9, 16))
    before, outer, middle, inner, _, end, after = result.blocks
    assert [
        (b.raw_char_range.start, b.raw_char_range.end) for b in (before, middle, end, after)
    ] == [(0, 6), (0, 5), (5, 8), (6, 11)]
    assert after.source_locator == before.source_locator
    assert after.source_fragment_index == 2
    assert before.source_fragment_index == 1
    assert str(after.block_id) == f"{SOURCE.source_id}:{before.source_locator.path}:fragment:2"
    assert after.source_spans[0].block_char_range.start == 0
    assert after.normalization_map[0].raw_range.start == 0
    assert after.normalization_map[0].raw_range.end == 5
    assert inner.parent_block_id == outer.block_id
    assert end.parent_block_id == outer.block_id
    assert outer.source_fragment_index is None
    assert outer.normalization_map == outer.source_spans == ()
    assert outer.raw_char_range.start == outer.raw_char_range.end == 0
    assert result.warnings == ()


def test_mixed_text_preserves_unicode_controls_and_child_tails():
    # Given
    xml = (
        "<hp:p><hp:run><hp:t> 한😀 <hp:tab/>끝<hp:lineBreak/><hp:nbSpace/>"
        "<hp:fwSpace/>尾</hp:t></hp:run></hp:p><hp:p/>"
    )
    # When
    result = section(xml)
    # Then
    first, empty = result.blocks
    assert first.raw_text == " 한😀 \t끝\n\u00a0\u3000尾"
    assert first.raw_coordinate_basis == "hwpx_paragraph_unicode"
    assert first.normalized_text == first.raw_text
    assert first.normalization_version == "identity-v1"
    assert [s.source_coordinate_basis for s in first.source_spans] == [
        "source_node_unicode",
        "synthetic_control_unicode",
        "source_node_tail_unicode",
        "synthetic_control_unicode",
        "synthetic_control_unicode",
        "synthetic_control_unicode",
        "source_node_tail_unicode",
    ]
    assert [s.source_char_range.end for s in first.source_spans] == [4, 1, 1, 1, 1, 1, 1]
    assert first.source_spans[2].source_locator.path.endswith("/hp:t[1]/hp:tab[1]")
    assert empty.raw_text == ""
    assert empty.source_spans == ()
    assert empty.source_fragment_index == 1
    assert all(b.source_locator.original_page_number is None for b in result.blocks)
    assert result.warnings == ()


@pytest.mark.parametrize(
    ("tag", "kind"), [("footNote", "footnote"), ("header", "header"), ("footer", "footer")]
)
@pytest.mark.parametrize("prefix", ["", "한😀"])
def test_story_reference_owns_fragment_and_actual_inline_target(tag, kind, prefix):
    # Given
    xml = (
        f"<hp:p><hp:run><hp:t>{prefix}</hp:t><hp:ctrl><hp:{tag}><hp:subList>"
        "<hp:p><hp:run><hp:t>story</hp:t></hp:run></hp:p></hp:subList>"
        f"</hp:{tag}></hp:ctrl><hp:t>after</hp:t></hp:run></hp:p>"
    )
    # When
    result = section(xml)
    # Then
    owner, container, story, after = result.blocks
    (reference,) = result.references
    assert [b.raw_text for b in result.blocks] == [prefix, "", "story", "after"]
    assert container.kind == kind
    assert container.parent_block_id is None
    assert story.parent_block_id == container.block_id
    assert reference.source_block_id == owner.block_id
    assert reference.source_char_offset == len(prefix)
    assert reference.source_locator == reference.target_locator == container.source_locator
    assert reference.source_locator.path.endswith(f"/hp:ctrl[1]/hp:{tag}[1]")
    assert reference.status == "resolved"
    assert after.raw_char_range.start == len(prefix)
    assert result.warnings == ()


@pytest.mark.parametrize(
    "payload", ["", "<hp:subList/><hp:subList/>", "<hp:subList/><hp:unknown/>", "RAW<hp:subList/>"]
)
def test_invalid_story_payload_produces_unresolved_reference(payload):
    # Given
    xml = (
        f"<hp:p><hp:run><hp:ctrl><hp:footNote>{payload}</hp:footNote></hp:ctrl>"
        "<hp:t>safe</hp:t></hp:run></hp:p>"
    )
    # When
    result = section(xml)
    # Then
    assert [b.raw_text for b in result.blocks] == ["", "safe"]
    (reference,) = result.references
    assert reference.status == "unresolved"
    assert reference.target_locator is None
    assert reference.source_char_offset == 0
    assert any(w.code == "invalid_structure" for w in result.warnings)


@pytest.mark.parametrize("payload", ["", "<hp:subList/><hp:subList/>"])
def test_cells_require_exactly_one_sublist(payload):
    # Given
    xml = f"<hp:p><hp:run><hp:tbl><hp:tr><hp:tc>{payload}</hp:tc></hp:tr></hp:tbl></hp:run></hp:p>"
    # When
    result = section(xml)
    # Then
    assert all(b.raw_text == "" for b in result.blocks)
    assert any(w.code == "invalid_structure" for w in result.warnings)


@pytest.mark.parametrize(
    "tag",
    ["hyphen", "hypen", "fieldBegin", "endNote", "shape", "equation", "insertBegin", "future"],
)
def test_unsupported_subtrees_preserve_surrounding_mixed_tail(tag):
    # Given
    xml = (
        f"<hp:p><hp:run><hp:t>safe<hp:{tag}><hp:t>hidden</hp:t></hp:{tag}>tail"
        "</hp:t></hp:run></hp:p>"
    )
    # When
    result = section(xml)
    # Then
    assert result.blocks[0].raw_text == "safetail"
    (warning,) = result.warnings
    assert warning.code == "unsupported_element"
    assert warning.source_locator.path.endswith(f"/hp:{tag}[1]")


def test_unknown_namespace_formatting_and_ctrl_content_warn_without_leaking():
    # Given
    xml = (
        "<hp:p><hp:linesegarray><hp:lineseg/><hp:t>hidden</hp:t></hp:linesegarray>"
        "<hp:run><hp:secPr/><hp:ctrl><hp:endNote/></hp:ctrl>"
        '<x:t xmlns:x="urn:alien">hidden</x:t><hp:t>safe</hp:t></hp:run></hp:p>'
    )
    # When
    result = section(xml)
    # Then
    assert result.blocks[0].raw_text == "safe"
    assert len(result.warnings) == 4
    assert all(w.code == "unsupported_element" for w in result.warnings)
    assert "{urn:alien}t[1]" in result.warnings[-1].source_locator.path


def test_unexpected_xml_text_and_tails_are_diagnosed():
    # Given
    xml = "ROOT<hp:p>PARA<hp:run>RUN<hp:t>safe</hp:t>TAIL</hp:run></hp:p>END"
    # When
    result = section(xml)
    # Then
    assert result.blocks[0].raw_text == "safe"
    assert len(result.warnings) == 5
    assert all(w.code == "invalid_structure" for w in result.warnings)


def test_aliases_empty_section_and_sibling_indices_are_canonical():
    # Given
    root = parse_xml(
        (
            f'<s:sec xmlns:s="{SECTION_NS}" xmlns:a="{PARA_NS}"><a:p/><a:p>'
            "<a:run><a:t>x</a:t><a:t>y</a:t></a:run></a:p></s:sec>"
        ).encode(),
        InputLimits(),
    )
    # When
    result = read_section(root, "Contents/section0.xml", SOURCE)
    # Then
    assert result.blocks[1].source_locator.path.endswith("/hs:sec[1]/hp:p[2]")
    assert result.blocks[1].source_spans[1].source_locator.path.endswith("/hp:t[2]")
    assert section("").blocks == ()
