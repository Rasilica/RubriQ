import os
import time
from pathlib import Path
from typing import Final

import pytest

from submission.conversion_contracts import ConversionError, ConversionErrorCode
from submission.conversion_process import run_process
from submission.hwp_reader import read_hwp
from submission.hwp_reading import provision_hwp_reader
from submission.hwp_reading_contracts import HwpReadConfig
from submission.input_contracts import DocumentInput
from submission.models import DocumentRole

JAVA: Final = Path(
    os.environ.get(
        "JAVA_HOME",
        "vendor/java/microsoft17.0.20.1/jdk-17.0.20.1+1/Contents/Home",
    )
).resolve()
pytestmark = pytest.mark.skipif(
    not (JAVA / "bin/java").is_file(),
    reason="Native HWP tests require a JDK17 JAVA_HOME",
)
JAR: Final = Path("vendor/hwplib/1.1.11/hwplib-1.1.11.jar").resolve()
ROOT: Final = "BodyText/Section0/paragraph[0]"


def fixture_input(tmp_path: Path, mode: str = "") -> DocumentInput:
    destination = tmp_path / "synthetic.hwp"
    _ = run_process(
        (
            str(JAVA / "bin/java"),
            "--class-path",
            str(JAR),
            str(Path("tools/MakeHwpNestedFixture.java").resolve()),
            str(destination),
            mode,
        ),
        tmp_path,
        time.monotonic() + 60,
        2,
    )
    return DocumentInput("synthetic.hwp", destination.read_bytes(), DocumentRole.REPORT)


def native_config(tmp_path: Path) -> HwpReadConfig:
    return HwpReadConfig(
        provision=provision_hwp_reader(JAVA, JAR, Path("tools/HwpNestedReader.java")),
        work_root=tmp_path / "jobs",
    )


def test_native_korean_nested_paths_references_and_unicode(tmp_path: Path) -> None:
    source = fixture_input(tmp_path)
    document = read_hwp(source, native_config(tmp_path))
    assert [block.raw_text for block in document.blocks if block.raw_text] == [
        "본문 앞😀",
        "바깥 셀 앞",
        "중첩 셀 내용",
        "바깥 셀 뒤",
        "본문 뒤",
        "머리말 기준",
        "꼬리말 기준",
        "각주 근거",
    ]
    nested = document.blocks[6]
    assert nested.source_locator.path == (
        ROOT + "/control[2]/row[0]/cell[0]/paragraph[0]/control[0]/row[0]/cell[0]/paragraph[0]"
    )
    assert nested.parent_block_id == document.blocks[5].block_id
    assert [reference.kind for reference in document.references] == ["header", "footer", "footnote"]
    assert all(reference.status == "resolved" for reference in document.references)
    assert document.blocks[8].raw_char_range.start == 5
    assert document.coverage.scope == "hwp5_structure"
    assert [position.path for position in document.coverage.omitted_locators] == [
        ROOT + "/control[6]",
    ]
    assert tuple((tmp_path / "jobs").iterdir()) == ()


def test_native_inert_controls_are_silent_but_equation_is_reported(tmp_path: Path) -> None:
    document = read_hwp(fixture_input(tmp_path, "inert"), native_config(tmp_path))
    assert "".join(block.raw_text for block in document.blocks) == "링크 앞링크 글자링크 뒤"
    omitted = [position.path for position in document.coverage.omitted_locators]
    assert omitted == [ROOT + "/control[5]"]


def test_native_result_can_exceed_stdout_limit(tmp_path: Path) -> None:
    source = fixture_input(tmp_path, "large")
    document = read_hwp(source, native_config(tmp_path))
    assert sum(len(block.raw_text) for block in document.blocks) > 200000
    assert document.blocks[-1].raw_text == "한글" * 1000


def test_native_depth_limit_preserves_visited_and_omission(tmp_path: Path) -> None:
    source = fixture_input(tmp_path, "deep")
    document = read_hwp(source, native_config(tmp_path))
    assert document.coverage.scope == "hwp5_structure"
    assert document.extraction_status == "partial"
    assert any(block.raw_text == "중첩 셀 내용" for block in document.blocks)
    assert not any(block.raw_text == "깊이39" for block in document.blocks)
    assert any(
        position.path.count("/control[") >= 32 for position in document.coverage.omitted_locators
    )


def test_native_block_limit_preserves_ten_thousand_blocks(tmp_path: Path) -> None:
    source = fixture_input(tmp_path, "blocks")
    document = read_hwp(source, native_config(tmp_path))
    assert len(document.blocks) == 10000
    assert document.extraction_status == "partial"
    assert document.coverage.scope == "hwp5_structure"
    assert any(
        position.path == "BodyText/Section0" for position in document.coverage.omitted_locators
    )


def test_native_result_limit_is_typed_and_cleans_job(tmp_path: Path) -> None:
    source = fixture_input(tmp_path, "overflow")
    config = native_config(tmp_path)
    with pytest.raises(ConversionError) as failure:
        _ = read_hwp(source, config)
    assert failure.value.code == ConversionErrorCode.OUTPUT_LIMIT
    assert tuple(config.work_root.iterdir()) == ()


def test_native_pictures_become_figure_blocks_with_caption_children(tmp_path: Path) -> None:
    source = fixture_input(tmp_path, "figures")
    document = read_hwp(source, native_config(tmp_path))
    figures = [block for block in document.blocks if block.kind == "figure"]
    assert len(figures) == 2
    assert all(figure.raw_text == "" for figure in figures)
    children = [
        [b.raw_text for b in document.blocks if b.parent_block_id == figure.block_id]
        for figure in figures
    ]
    assert children == [["그림 프론트엔드 대시보드"], []]
    texts = [block.raw_text for block in document.blocks if block.raw_text]
    assert sorted(texts) == sorted(
        ["그림 앞", "그림 프론트엔드 대시보드", "그림 뒤", "표 문단", "표 성능 지표", "표 셀 내용"]
    )
    assert [w.code for w in document.warnings].count("figure_content_unread") == 2
    assert document.extraction_status == "partial"
    assert not any(
        position.path.endswith("control[2]") or position.path.endswith("control[3]")
        for position in document.coverage.omitted_locators
    )


def test_native_text_box_shape_is_figure_with_paragraph_children(tmp_path: Path) -> None:
    document = read_hwp(fixture_input(tmp_path, "textboxes"), native_config(tmp_path))
    figures = [block for block in document.blocks if block.kind == "figure"]
    assert len(figures) == 2
    box, picture = figures
    children = [b for b in document.blocks if b.parent_block_id == box.block_id]
    assert [b.raw_text for b in children] == ["상자 안 첫 줄", "둘째 줄"]
    assert all("/control[2]/textbox/paragraph[" in b.source_locator.path for b in children)
    assert [b.raw_text for b in document.blocks if b.parent_block_id == picture.block_id] == []
    # Only the picture keeps the unread warning; the fully read text box does not.
    unread = [w for w in document.warnings if w.code == "figure_content_unread"]
    assert [w.source_locator for w in unread] == [picture.source_locator]
    assert not any(
        position.path.endswith(("control[2]", "textbox"))
        for position in document.coverage.omitted_locators
    )
