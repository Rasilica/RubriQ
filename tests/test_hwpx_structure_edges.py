from dataclasses import FrozenInstanceError

import pytest
from test_hwpx_structure import SOURCE, cell, section

from submission.format_containers import parse_xml
from submission.hwpx_structure import read_section
from submission.hwpx_structure_types import HEAD_NS, PARA_NS, SECTION_NS
from submission.input_contracts import InputLimits


def test_nested_story_references_follow_control_order_and_nearest_parent():
    # Given: footnote inside header inside a table cell.
    inner = "<hp:ctrl><hp:footNote><hp:subList><hp:p/></hp:subList></hp:footNote></hp:ctrl>"
    header = (
        "<hp:ctrl><hp:header><hp:subList><hp:p><hp:run><hp:t>header</hp:t>"
        f"{inner}</hp:run></hp:p></hp:subList></hp:header></hp:ctrl>"
    )
    xml = f"<hp:p><hp:run>{cell(header)}</hp:run></hp:p>"
    # When
    result = section(xml)
    # Then
    assert [r.kind for r in result.references] == ["header", "footnote"]
    containers = [b for b in result.blocks if b.kind != "paragraph"]
    assert [b.kind for b in containers] == ["table_cell", "header", "footnote"]
    assert containers[1].parent_block_id == containers[0].block_id
    assert containers[2].parent_block_id == containers[1].block_id
    assert [r.source_char_offset for r in result.references] == [0, 6]
    assert result.warnings == ()


def test_consecutive_stories_receive_distinct_zero_width_fragment_owners():
    # Given
    story = "<hp:footNote><hp:subList><hp:p/></hp:subList></hp:footNote>"
    # When
    result = section(f"<hp:p><hp:run><hp:ctrl>{story}{story}</hp:ctrl></hp:run></hp:p>")
    # Then
    assert len(result.references) == 2
    owners = [
        b for b in result.blocks if b.block_id in {r.source_block_id for r in result.references}
    ]
    assert [b.source_fragment_index for b in owners] == [1, 2]
    assert all(b.raw_text == "" and b.source_spans == () for b in owners)
    assert all(r.source_char_offset == 0 for r in result.references)
    assert result.references[1].source_locator.path.endswith("/hp:footNote[2]")


@pytest.mark.parametrize("payload", ["RAW", "<hp:t>hidden</hp:t>"])
def test_malformed_synthetic_control_is_omitted_with_tail_preserved(payload):
    # Given
    xml = f"<hp:p><hp:run><hp:t>left<hp:tab>{payload}</hp:tab>right</hp:t></hp:run></hp:p>"
    # When
    result = section(xml)
    # Then
    assert result.blocks[0].raw_text == "leftright"
    assert result.blocks[0].source_spans[1].source_coordinate_basis == "source_node_tail_unicode"
    (warning,) = result.warnings
    assert warning.code == "invalid_structure"
    assert warning.source_locator.path.endswith("/hp:tab[1]")


def test_table_metadata_is_explicit_and_hidden_text_never_leaks():
    # Given
    xml = (
        "<hp:p><hp:run><hp:tbl><hp:sz/><hp:pos/><hp:outMargin/><hp:inMargin/>"
        "<hp:tr><hp:tc><hp:cellAddr/><hp:cellSpan/><hp:cellSz/><hp:cellMargin>RAW"
        "<hp:t>hidden</hp:t>TAIL</hp:cellMargin><hp:subList><hp:p/></hp:subList>"
        "</hp:tc><hp:wrong/></hp:tr></hp:tbl></hp:run></hp:p>"
    )
    # When
    result = section(xml)
    # Then
    assert all(b.raw_text == "" for b in result.blocks)
    assert [w.code for w in result.warnings] == [
        "invalid_structure",
        "unsupported_element",
        "invalid_structure",
        "unsupported_element",
    ]


def test_unsupported_root_is_located_with_canonical_header_namespace():
    # Given
    root = parse_xml(f'<h:head xmlns:h="{HEAD_NS}"/>'.encode(), InputLimits())
    # When
    result = read_section(root, "Contents/section0.xml", SOURCE)
    # Then
    assert result.blocks == ()
    (warning,) = result.warnings
    assert warning.code == "unsupported_element"
    assert warning.source_locator.path == "Contents/section0.xml::/hh:head[1]"


def test_illegal_structure_and_same_local_name_different_namespaces_are_distinct():
    # Given
    xml = (
        '<hp:p><hp:run><t>hidden</t><x:t xmlns:x="urn:foreign">hidden</x:t>'
        "<hp:t>safe</hp:t><hp:t>again</hp:t></hp:run></hp:p><hp:tc/><hp:tbl/>"
    )
    # When
    result = section(xml)
    # Then
    assert [b.raw_text for b in result.blocks] == ["safeagain"]
    assert len(result.warnings) == 4
    assert result.blocks[0].source_spans[0].source_locator.path.endswith("/hp:t[1]")
    assert result.blocks[0].source_spans[1].source_locator.path.endswith("/hp:t[2]")


def test_read_result_is_frozen_and_repeatable():
    # Given
    xml = "<hp:p><hp:run><hp:t>😀 e\u0301 </hp:t></hp:run></hp:p>"
    first = section(xml)
    # When
    second = section(xml)
    # Then
    assert first == second
    assert second.blocks[0].raw_text == "😀 e\u0301 "
    with pytest.raises(FrozenInstanceError):
        second.__setattr__("blocks", ())


def test_namespace_aliases_share_expanded_tag_sibling_counts():
    # Given
    xml = (
        f'<hs:sec xmlns:hs="{SECTION_NS}" xmlns:a="{PARA_NS}" xmlns:b="{PARA_NS}">'
        "<a:p><a:run><a:t>one</a:t><b:t>two</b:t></a:run></a:p><b:p/></hs:sec>"
    )
    root = parse_xml(xml.encode(), InputLimits())
    # When
    result = read_section(root, "Contents/section0.xml", SOURCE)
    # Then
    assert result.blocks[0].source_spans[1].source_locator.path.endswith("/hp:t[2]")
    assert result.blocks[1].source_locator.path.endswith("/hp:p[2]")


def test_table_only_paragraph_does_not_fabricate_an_empty_trailing_fragment():
    # Given: the parent paragraph contains a table, with no direct projected text.
    xml = f"<hp:p><hp:run>{cell('<hp:t>cell</hp:t>')}</hp:run></hp:p>"
    # When
    result = section(xml)
    # Then
    assert [b.kind for b in result.blocks] == ["table_cell", "paragraph"]
    assert [b.raw_text for b in result.blocks] == ["", "cell"]
