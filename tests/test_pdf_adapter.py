from hashlib import sha256
from typing import Literal, assert_never

import pytest

from submission.document_contracts import ContractError, ContractErrorCode, ProcessingStatus
from submission.extraction import extract_pdf
from submission.models import DocumentRole, ExtractedDocument, ExtractedPage, Paragraph, PdfInput
from submission.pdf_adapter import adapt_pdf

type ProvenanceChange = Literal["bytes", "role", "id", "page_number", "block_text"]


def test_adapter_preserves_hash_role_and_original_artifact(text_pdf: bytes) -> None:
    # Given
    source = PdfInput("folder/report.PDF", text_pdf, DocumentRole.REPORT)
    extracted = extract_pdf(source)
    original = extracted.model_dump_json()
    # When
    document = adapt_pdf(source, extracted)
    # Then
    assert document.source.source_id == extracted.id
    assert document.source.filename == "report.PDF"
    assert document.source.content_sha256 == sha256(text_pdf).hexdigest()
    assert document.source.byte_size == len(text_pdf)
    assert document.source.role is DocumentRole.REPORT
    assert document.source.declared_extension == ".pdf"
    assert document.source.detected_format == "pdf"
    assert document.artifacts[0].artifact_sha256 == document.source.content_sha256
    assert document.artifacts[0].parent_source_id == extracted.id
    assert document.artifacts[0].conversion_chain == ()
    assert document.artifacts[0].storage_location is None
    assert document.artifacts[0].renderer is None
    assert document.artifacts[0].created_at is None
    assert extracted.model_dump_json() == original


def test_adapter_maps_blocks_with_unicode_ranges_and_identity_normalization(
    text_pdf: bytes,
) -> None:
    # Given
    source = PdfInput("report.pdf", text_pdf, DocumentRole.REPORT)
    page_text = "  한글 😀 근거\n\n반복 문장\n\n\n\n반복 문장  "
    page = ExtractedPage(
        number=1,
        text=page_text,
        paragraphs=(
            Paragraph(id="p1-b1", text="한글 😀 근거"),
            Paragraph(id="p1-b2", text="반복 문장"),
            Paragraph(id="p1-b4", text="반복 문장"),
        ),
    )
    extracted = extract_pdf(source).model_copy(update={"pages": (page,)})
    # When
    document = adapt_pdf(source, extracted)
    # Then
    assert [block.block_id for block in document.blocks] == ["p1-b1", "p1-b2", "p1-b4"]
    assert [block.reading_order for block in document.blocks] == [0, 1, 2]
    assert document.blocks[0].raw_char_range.start == 2
    assert document.blocks[2].raw_char_range.start > document.blocks[1].raw_char_range.end
    for block, anchor in zip(document.blocks, document.mappings, strict=True):
        assert page_text[block.raw_char_range.start : block.raw_char_range.end] == block.raw_text
        assert block.normalized_text == block.raw_text
        assert block.normalization_version == "identity-v1"
        assert block.normalization_map[0].raw_range.end == len(block.raw_text)
        assert anchor.source_block_id == block.block_id
        assert anchor.original_page_numbers == (1,)
        assert anchor.target_page_numbers == (1,)
        assert anchor.mapping_status == "identity"
        assert anchor.target_text_ranges[0].char_range == block.raw_char_range


def test_adapter_preserves_unreadable_pages_without_inventing_anchors(blank_pdf: bytes) -> None:
    # Given
    source = PdfInput("blank.pdf", blank_pdf, DocumentRole.GUIDE)
    # When
    document = adapt_pdf(source, extract_pdf(source))
    # Then
    assert document.extraction_status is ProcessingStatus.FAILED
    assert document.coverage.total_pages == 1
    assert document.coverage.processed_pages == ()
    assert document.coverage.unreadable_pages == (1,)
    assert document.typed_errors[0].code == "text_unavailable"
    assert document.blocks == ()
    assert document.mappings == ()
    assert document.content_review_available is False
    assert document.display_artifact_available is True


def test_adapter_preserves_partial_page_errors(text_pdf: bytes) -> None:
    # Given
    source = PdfInput("report.pdf", text_pdf, DocumentRole.REPORT)
    extracted = extract_pdf(source)
    pages = (
        extracted.pages[0],
        ExtractedPage(
            number=2,
            text="",
            paragraphs=(),
            error="extraction_error",
        ),
    )
    extracted = extracted.model_copy(update={"pages": pages})
    # When
    document = adapt_pdf(source, extracted)
    # Then
    assert document.extraction_status is ProcessingStatus.PARTIAL
    assert document.coverage.processed_pages == (1,)
    assert document.coverage.unreadable_pages == (2,)
    assert document.typed_errors[0].page_number == 2
    assert all(anchor.target_page_numbers == (1,) for anchor in document.mappings)


def test_adapter_preserves_warning_and_defers_policy_page_count(text_pdf: bytes) -> None:
    # Given
    source = PdfInput("report.pdf", text_pdf, DocumentRole.REPORT)
    extracted = extract_pdf(source).model_copy(update={"parser_warning": True})
    # When
    document = adapt_pdf(source, extracted)
    # Then
    assert document.extraction_status is ProcessingStatus.PARTIAL
    assert document.warnings[0].code == "parser_warning"
    assert document.warnings[0].page_number is None
    assert document.page_count.artifact_page_count == 2
    assert document.page_count.basis == "original_pdf"
    assert document.page_count.status == "deferred"
    assert document.page_count.count is None
    assert document.page_count.included_pages is None
    assert document.page_count_verification_available is False
    assert document.rendering_status is ProcessingStatus.NOT_STARTED
    assert document.ai_called is False
    assert document.stored is False


def test_successful_extraction_does_not_confirm_policy_count(text_pdf: bytes) -> None:
    # Given
    source = PdfInput("report.pdf", text_pdf, DocumentRole.REPORT)
    # When
    document = adapt_pdf(source, extract_pdf(source))
    # Then
    assert document.extraction_status is ProcessingStatus.COMPLETE
    assert document.content_review_available is True
    assert document.page_count.count is None
    assert document.page_count.status == "deferred"


@pytest.mark.parametrize("change", ["bytes", "role", "id", "page_number", "block_text"])
def test_adapter_rejects_inconsistent_provenance(
    change: ProvenanceChange,
    text_pdf: bytes,
    blank_pdf: bytes,
) -> None:
    # Given
    source = PdfInput("report.pdf", text_pdf, DocumentRole.REPORT)
    extracted = extract_pdf(source)
    match change:
        case "bytes":
            source = PdfInput("report.pdf", blank_pdf, DocumentRole.REPORT)
        case "role":
            source = PdfInput("report.pdf", text_pdf, DocumentRole.GUIDE)
        case "id":
            extracted = extracted.model_copy(update={"id": "unrelated"})
        case "page_number":
            page = extracted.pages[0].model_copy(update={"number": 3})
            extracted = extracted.model_copy(update={"pages": (page, *extracted.pages[1:])})
        case "block_text":
            page = extracted.pages[0].model_copy(
                update={
                    "paragraphs": (Paragraph(id="p1-b1", text="invented"),),
                }
            )
            extracted = extracted.model_copy(update={"pages": (page, *extracted.pages[1:])})
        case unreachable:
            assert_never(unreachable)
    # When / Then
    with pytest.raises(ContractError):
        adapt_pdf(source, extracted)


def test_adapter_is_deterministic_for_same_source(text_pdf: bytes) -> None:
    # Given
    source = PdfInput("report.pdf", text_pdf, DocumentRole.REPORT)
    extracted: ExtractedDocument = extract_pdf(source)
    # When
    first = adapt_pdf(source, extracted)
    second = adapt_pdf(source, extracted)
    # Then
    assert first.model_dump_json() == second.model_dump_json()


@pytest.mark.parametrize(
    "paragraphs",
    [
        (Paragraph(id="p1-b1", text=""),),
        (Paragraph(id="p1-b1", text="Repeat"), Paragraph(id="p1-b1", text="Repeat")),
    ],
    ids=["empty-block", "duplicate-block-id"],
)
def test_adapter_rejects_ambiguous_block_identity(
    paragraphs: tuple[Paragraph, ...],
    text_pdf: bytes,
) -> None:
    # Given
    source = PdfInput("report.pdf", text_pdf, DocumentRole.REPORT)
    page = ExtractedPage(number=1, text="Repeat\n\nRepeat", paragraphs=paragraphs)
    extracted = extract_pdf(source).model_copy(update={"pages": (page,)})
    # When
    with pytest.raises(ContractError) as caught:
        adapt_pdf(source, extracted)
    # Then
    assert caught.value.code is ContractErrorCode.INVALID_BLOCK_IDENTITY
