from hwpx_reader_helpers import make_hwpx
from hwpx_reader_helpers import source as hwpx_source

from submission.document_contracts import DocumentSource, ProcessingStatus, SourceId
from submission.format_containers import parse_xml
from submission.hwpx_reader import read_hwpx
from submission.hwpx_structure import read_section
from submission.hwpx_structure_types import PARA_NS, SECTION_NS
from submission.input_contracts import InputLimits


def _source(ext: str) -> DocumentSource:
    return DocumentSource(
        source_id=SourceId("t"),
        role="report",
        filename=f"t.{ext}",
        content_sha256="a" * 64,
        byte_size=1,
        declared_extension=ext,
        detected_format=ext,
        document_version_id="v1",
    )


def hwpx(xml: str):
    root = parse_xml(
        f'<hs:sec xmlns:hs="{SECTION_NS}" xmlns:hp="{PARA_NS}">{xml}</hs:sec>'.encode(),
        InputLimits(),
    )
    return read_section(root, "Contents/section0.xml", _source("hwpx"))


def caption(text: str) -> str:
    return (
        "<hp:caption><hp:subList><hp:p><hp:run>"
        f"<hp:t>{text}</hp:t></hp:run></hp:p></hp:subList></hp:caption>"
    )


def kinds(result):
    return [(b.kind, b.raw_text) for b in result.blocks]


def test_hwpx_picture_with_caption_is_figure_with_caption_child():
    result = hwpx(f"<hp:p><hp:run><hp:pic>{caption('그림 1')}</hp:pic></hp:run></hp:p>")
    assert kinds(result) == [("figure", ""), ("paragraph", "그림 1")]
    assert result.blocks[1].parent_block_id == result.blocks[0].block_id
    assert result.blocks[0].parent_block_id is None
    assert [w.code for w in result.warnings] == ["figure_content_unread"]


def test_hwpx_picture_without_caption_is_empty_figure():
    result = hwpx("<hp:p><hp:run><hp:t>앞</hp:t><hp:pic/><hp:t>뒤</hp:t></hp:run></hp:p>")
    assert kinds(result) == [("paragraph", "앞"), ("figure", ""), ("paragraph", "뒤")]
    assert [w.code for w in result.warnings] == ["figure_content_unread"]


def test_hwpx_container_is_one_figure():
    result = hwpx("<hp:p><hp:run><hp:container><hp:pic/><hp:pic/></hp:container></hp:run></hp:p>")
    assert [b.kind for b in result.blocks] == ["figure"]


def test_hwpx_table_caption_is_read_before_cells_under_table_parent():
    result = hwpx(
        f"<hp:p><hp:run><hp:tbl>{caption('표 1')}<hp:tr><hp:tc><hp:subList><hp:p><hp:run>"
        "<hp:t>셀</hp:t></hp:run></hp:p></hp:subList></hp:tc></hp:tr></hp:tbl></hp:run></hp:p>"
    )
    assert kinds(result) == [("paragraph", "표 1"), ("table_cell", ""), ("paragraph", "셀")]
    assert result.warnings == ()


def test_hwpx_document_with_figure_is_partial_and_valid():
    doc = read_hwpx(
        hwpx_source(
            make_hwpx(
                f"<hp:p><hp:run><hp:t>본문</hp:t><hp:pic>{caption('그림')}</hp:pic></hp:run></hp:p>"
            )
        )
    )
    assert doc.extraction_status is ProcessingStatus.PARTIAL
    assert [b.kind for b in doc.blocks if b.kind == "figure"] == ["figure"]
    assert "figure_content_unread" in {w.code for w in doc.warnings}


def test_hwpx_bare_shape_without_text_box_stays_unsupported():
    result = hwpx("<hp:p><hp:run><hp:rect/></hp:run></hp:p>")
    assert [w.code for w in result.warnings] == ["unsupported_element"]
    assert all(b.kind != "figure" for b in result.blocks)


def draw_text(*texts: str) -> str:
    paragraphs = "".join(f"<hp:p><hp:run><hp:t>{t}</hp:t></hp:run></hp:p>" for t in texts)
    return f"<hp:drawText><hp:subList>{paragraphs}</hp:subList></hp:drawText>"


def test_hwpx_caption_nested_deeper_under_picture_is_read():
    result = hwpx(
        f"<hp:p><hp:run><hp:pic><hp:shapeComment/><hp:wrap>{caption('깊은 캡션')}</hp:wrap>"
        "</hp:pic></hp:run></hp:p>"
    )
    assert kinds(result) == [("figure", ""), ("paragraph", "깊은 캡션")]
    assert result.blocks[1].parent_block_id == result.blocks[0].block_id


def test_hwpx_caption_inside_nested_picture_is_not_taken_by_outer():
    result = hwpx(
        f"<hp:p><hp:run><hp:container>{caption('바깥')}<hp:pic>{caption('안쪽')}</hp:pic>"
        "</hp:container></hp:run></hp:p>"
    )
    assert kinds(result) == [("figure", ""), ("paragraph", "바깥")]


def test_hwpx_rect_text_box_is_figure_with_paragraphs_and_no_unread_warning():
    result = hwpx(
        "<hp:p><hp:run><hp:t>앞</hp:t>"
        f"<hp:rect>{draw_text('상자 1', '상자 2')}</hp:rect></hp:run></hp:p>"
    )
    assert kinds(result) == [
        ("paragraph", "앞"),
        ("figure", ""),
        ("paragraph", "상자 1"),
        ("paragraph", "상자 2"),
    ]
    assert result.blocks[2].parent_block_id == result.blocks[1].block_id
    assert [b.reading_order for b in result.blocks] == [0, 1, 2, 3]
    assert result.warnings == ()


def test_hwpx_container_with_picture_and_text_box_keeps_warning():
    result = hwpx(
        f"<hp:p><hp:run><hp:container><hp:rect>{draw_text('글')}</hp:rect><hp:pic/>"
        "</hp:container></hp:run></hp:p>"
    )
    assert kinds(result) == [("figure", ""), ("paragraph", "글")]
    assert [w.code for w in result.warnings] == ["figure_content_unread"]
