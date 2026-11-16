from io import BytesIO

import pytest
from pypdf import PageObject, PdfWriter
from pypdf.errors import PdfReadError

from submission.extraction import extract_pdf
from submission.models import DocumentRole, PdfInput, PdfLimits, UploadError


def test_extract_preserves_page_and_paragraph_locations(text_pdf: bytes) -> None:
    # Given
    source = PdfInput(filename="report.pdf", content=text_pdf, role=DocumentRole.REPORT)
    # When
    result = extract_pdf(source)
    # Then
    assert [page.number for page in result.pages] == [1, 2]
    assert "Purpose:" in result.pages[0].text
    assert "Output:" in result.pages[1].text
    assert result.pages[1].paragraphs[0].id == "p2-b1"
    assert result.complete is True


def test_blank_page_is_preserved_and_marks_incomplete(blank_pdf: bytes) -> None:
    # Given
    source = PdfInput(filename="blank.pdf", content=blank_pdf, role=DocumentRole.GUIDE)
    # When
    result = extract_pdf(source)
    # Then
    assert len(result.pages) == 1
    assert result.pages[0].error == "text_unavailable"
    assert result.complete is False


@pytest.mark.parametrize("content", [b"", b"not a PDF", b"%PDF-1.7\nbroken"])
def test_invalid_input_fails_with_structured_error(content: bytes) -> None:
    # Given
    source = PdfInput(filename="broken.pdf", content=content, role=DocumentRole.REPORT)
    # When / Then
    with pytest.raises(UploadError) as error:
        extract_pdf(source)
    assert error.value.code in {"empty_file", "invalid_pdf"}


def test_encrypted_pdf_is_rejected(text_pdf: bytes) -> None:
    # Given
    writer = PdfWriter(clone_from=BytesIO(text_pdf))
    writer.encrypt("secret")
    buffer = BytesIO()
    writer.write(buffer)
    source = PdfInput(filename="locked.pdf", content=buffer.getvalue(), role=DocumentRole.REPORT)
    # When / Then
    with pytest.raises(UploadError, match="encrypted_pdf"):
        extract_pdf(source)


def test_page_limit_is_enforced(text_pdf: bytes) -> None:
    # Given
    source = PdfInput(filename="report.pdf", content=text_pdf, role=DocumentRole.REPORT)
    # When / Then
    with pytest.raises(UploadError, match="too_many_pages"):
        extract_pdf(source, PdfLimits(max_pages=1))


def test_size_limit_is_enforced(text_pdf: bytes) -> None:
    # Given
    source = PdfInput(filename="report.pdf", content=text_pdf, role=DocumentRole.REPORT)
    # When / Then
    with pytest.raises(UploadError, match="file_too_large"):
        extract_pdf(source, PdfLimits(max_bytes=10))


def test_partial_document_keeps_unreadable_page(text_pdf: bytes) -> None:
    # Given
    writer = PdfWriter(clone_from=BytesIO(text_pdf))
    writer.add_blank_page(width=595, height=842)
    buffer = BytesIO()
    writer.write(buffer)
    source = PdfInput(filename="mixed.pdf", content=buffer.getvalue(), role=DocumentRole.REPORT)
    # When
    result = extract_pdf(source)
    # Then
    assert result.complete is False
    assert result.readable_pages == (1, 2)
    assert result.pages[2].error == "text_unavailable"


def test_page_extraction_failure_keeps_page_position(
    text_pdf: bytes, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Given
    def fail_extract(_page: PageObject) -> str:
        message = "parser details"
        raise PdfReadError(message)

    monkeypatch.setattr(PageObject, "extract_text", fail_extract)
    source = PdfInput(filename="report.pdf", content=text_pdf, role=DocumentRole.REPORT)
    # When
    result = extract_pdf(source)
    # Then
    assert [page.number for page in result.pages] == [1, 2]
    assert all(page.error == "extraction_error" for page in result.pages)
    assert "parser details" not in result.model_dump_json()


def test_document_id_changes_with_content_and_role(text_pdf: bytes, blank_pdf: bytes) -> None:
    # Given
    inputs = [
        PdfInput(filename="one.pdf", content=text_pdf, role=DocumentRole.REPORT),
        PdfInput(filename="two.pdf", content=text_pdf, role=DocumentRole.GUIDE),
        PdfInput(filename="one.pdf", content=blank_pdf, role=DocumentRole.REPORT),
    ]
    # When
    ids = [extract_pdf(source).id for source in inputs]
    # Then
    assert len(set(ids)) == 3


def test_zero_page_pdf_is_rejected() -> None:
    # Given
    buffer = BytesIO()
    PdfWriter().write(buffer)
    source = PdfInput(filename="empty.pdf", content=buffer.getvalue(), role=DocumentRole.REPORT)
    # When / Then
    with pytest.raises(UploadError, match="empty_document"):
        extract_pdf(source)
