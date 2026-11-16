from io import BytesIO
from zipfile import ZipFile

from defusedxml import ElementTree
from hwpx_reader_helpers import FIXTURE, PARA_NS, make_hwpx, source

from submission.document_contracts import ProcessingStatus
from submission.hwpx_reader import read_hwpx
from submission.hwpx_validation import HEAD_NS, SECTION_NS

CASES = FIXTURE.parent / "cases/hwpx-structure.xml"
NAMESPACES = {"hp": PARA_NS, "hs": SECTION_NS, "hh": HEAD_NS}


def test_structural_case_preserves_dfs_order_and_fragment_projection_ranges() -> None:
    xml = CASES.read_text()
    content = make_hwpx("", (("Contents/section1.xml", xml),))
    document = read_hwpx(source(content))
    assert document.extraction_status is ProcessingStatus.COMPLETE
    assert [block.raw_text for block in document.blocks if block.raw_text] == [
        " 앞😀 \t뒤\n끝",
        "바깥 셀 앞",
        "중첩 셀",
        "바깥 셀 뒤",
        "표 뒤",
        "각주 문장",
        "각주 뒤",
        "머리말 문장",
        "꼬리말 문장",
        "마지막 본문",
        "파일명은 section0이지만 두 번째 읽기 구역.",
    ]
    body = tuple(
        block
        for block in document.blocks
        if block.source_locator.path == "Contents/section1.xml::/hs:sec[1]/hp:p[1]"
    )
    assert "".join(block.raw_text for block in body) == " 앞😀 \t뒤\n끝표 뒤각주 뒤마지막 본문"
    assert [block.source_fragment_index for block in body] == list(range(1, len(body) + 1))
    cursor = 0
    for block in body:
        assert block.raw_char_range.start == cursor
        assert block.raw_char_range.end == cursor + len(block.raw_text)
        cursor = block.raw_char_range.end
    assert len({block.block_id for block in document.blocks}) == len(document.blocks)
    assert [block.reading_order for block in document.blocks] == list(range(len(document.blocks)))
    assert {reference.kind for reference in document.references} == {"footnote", "header", "footer"}
    by_id = {block.block_id: block for block in document.blocks}
    for reference in document.references:
        assert reference.status == "resolved"
        assert reference.source_block_id in by_id
        owner = by_id[reference.source_block_id]
        assert reference.source_char_offset == len(owner.raw_text)
        assert any(
            block.kind == reference.kind and block.source_locator == reference.target_locator
            for block in document.blocks
        )
    inner = next(block for block in document.blocks if block.raw_text == "중첩 셀")
    cell = by_id[inner.parent_block_id]
    assert cell.kind == "table_cell"
    assert by_id[cell.parent_block_id].kind == "table_cell"


def test_all_spans_match_actual_xml_text_tail_or_explicit_control_projection() -> None:
    content = make_hwpx("", (("Contents/section1.xml", CASES.read_text()),))
    document = read_hwpx(source(content))
    controls = {"tab": "\t", "lineBreak": "\n", "nbSpace": "\u00a0", "fwSpace": "\u3000"}
    observed = set()
    with ZipFile(BytesIO(content)) as archive:
        for block in document.blocks:
            for span in block.source_spans:
                member, path = span.source_locator.path.split("::", 1)
                root = ElementTree.fromstring(archive.read(member))
                relative = path.split("/", 2)[2]
                nodes = root.findall("./" + relative, NAMESPACES)
                assert len(nodes) == 1
                match span.source_coordinate_basis:
                    case "source_node_unicode":
                        raw = nodes[0].text or ""
                    case "source_node_tail_unicode":
                        raw = nodes[0].tail or ""
                    case "synthetic_control_unicode":
                        raw = controls[nodes[0].tag.removeprefix(f"{{{PARA_NS}}}")]
                    case _:
                        raise AssertionError(span.source_coordinate_basis)
                piece = raw[span.source_char_range.start : span.source_char_range.end]
                assert (
                    piece == block.raw_text[span.block_char_range.start : span.block_char_range.end]
                )
                observed.add(span.source_coordinate_basis)
    assert observed == {
        "source_node_unicode",
        "source_node_tail_unicode",
        "synthetic_control_unicode",
    }
