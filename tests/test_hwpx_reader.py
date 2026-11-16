from hashlib import sha256

import pytest
from hwpx_reader_helpers import FIXTURE, make_hwpx, section, source

from submission.document_contracts import CommonDocument, ProcessingStatus, StructuralCoverage
from submission.hwpx_reader import read_hwpx
from submission.input_contracts import InputErrorCode, InputLimits, InputValidationError
from submission.models import DocumentRole


def test_spine_sequence_preserves_source_and_does_not_infer_pages() -> None:
    content = FIXTURE.read_bytes()
    document = read_hwpx(source(content))
    assert document.source.content_sha256 == sha256(content).hexdigest()
    assert document.source.filename == "report.hwpx"
    assert [block.raw_text for block in document.blocks] == [
        "파일명은 section1이지만 첫 번째 읽기 구역.",
        "파일명은 section0이지만 두 번째 읽기 구역.",
    ]
    assert isinstance(document.coverage, StructuralCoverage)
    assert document.coverage.scope == "hwpx_xml_structure"
    assert document.coverage.processed_parts == ("Contents/section1.xml", "Contents/section0.xml")
    assert not document.coverage.guarantees_all_content
    assert document.coverage.omitted_locators == ()
    assert document.extraction_status is ProcessingStatus.COMPLETE
    assert document.warnings == document.typed_errors == ()
    assert [block.reading_order for block in document.blocks] == [0, 1]
    assert all(block.source_locator.original_page_number is None for block in document.blocks)
    assert all(block.raw_coordinate_basis == "hwpx_paragraph_unicode" for block in document.blocks)
    assert all(block.source_fragment_index == 1 for block in document.blocks)
    assert document.page_count.status == "deferred"
    assert document.page_count.basis == "unknown"
    assert document.page_count.count is document.page_count.artifact_page_count is None
    assert document.artifacts == document.mappings == document.references == ()
    assert document.rendering_status is ProcessingStatus.NOT_STARTED
    assert document.content_review_available
    assert not any(
        (
            document.display_artifact_available,
            document.page_count_verification_available,
            document.stored,
            document.ai_called,
        )
    )
    assert CommonDocument.model_validate_json(document.model_dump_json(round_trip=True)) == document


def test_unlisted_section_and_unknown_binary_member_are_explicit_omissions() -> None:
    document = read_hwpx(
        source(
            make_hwpx(
                "<hp:p><hp:run><hp:t>본문</hp:t></hp:run></hp:p>",
                (
                    (
                        "Contents/orphan.xml",
                        section("<hp:p><hp:run><hp:t>미연결</hp:t></hp:run></hp:p>"),
                    ),
                    ("BinData/unknown.dat", "small benign bytes"),
                ),
            )
        )
    )
    assert document.extraction_status is ProcessingStatus.PARTIAL
    assert all(block.raw_text != "미연결" for block in document.blocks)
    assert {item.path.split("::", 1)[0] for item in document.coverage.omitted_locators} == {
        "Contents/orphan.xml",
        "BinData/unknown.dat",
    }
    assert {item.code for item in document.warnings} == {"unsupported_part"}


def test_unsupported_only_content_remains_partial_and_not_reviewable() -> None:
    document = read_hwpx(
        source(
            make_hwpx(
                "<hp:p><hp:run><hp:pic><hp:t>도형 속 글자</hp:t></hp:pic></hp:run></hp:p>",
                (("Contents/section0.xml", section("")),),
            )
        )
    )
    assert document.extraction_status is ProcessingStatus.PARTIAL
    assert not document.content_review_available
    assert document.typed_errors[0].code == "empty_content"
    assert document.warnings[0].source_locator is not None


def test_empty_sections_are_failed_even_when_empty_paragraph_blocks_exist() -> None:
    document = read_hwpx(source(make_hwpx("<hp:p/>", (("Contents/section0.xml", section("")),))))
    assert document.extraction_status is ProcessingStatus.FAILED
    assert not document.content_review_available
    assert document.typed_errors[0].code == "empty_content"


def test_input_boundaries_are_revalidated_and_limits_are_obeyed() -> None:
    with pytest.raises(InputValidationError) as caught:
        read_hwpx(source(FIXTURE.read_bytes()), InputLimits(max_xml_bytes=4))
    assert caught.value.code is InputErrorCode.XML_LIMIT
    assert caught.value.role is DocumentRole.REPORT
    with pytest.raises(InputValidationError):
        read_hwpx(source(b"not a package"))


def test_role_ids_are_distinct_but_original_hash_is_shared() -> None:
    content = FIXTURE.read_bytes()
    report = read_hwpx(source(content))
    guide = read_hwpx(source(content, DocumentRole.GUIDE))
    assert report == read_hwpx(source(content))
    assert guide.source.content_sha256 == report.source.content_sha256
    assert guide.source.role is DocumentRole.GUIDE
    assert guide.source.source_id != report.source.source_id
    assert {item.block_id for item in guide.blocks}.isdisjoint(
        item.block_id for item in report.blocks
    )
