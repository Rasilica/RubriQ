import logging
from contextlib import closing
from io import StringIO

import pytest
from pypdf import PageObject

from submission.extraction import extract_pdf
from submission.models import DocumentRole, PdfInput


def test_parser_warning_preserves_text_but_prevents_completion(
    text_pdf: bytes, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Given
    original = PageObject.extract_text

    def warning_extract(page: PageObject) -> str:
        logging.getLogger("pypdf._cmap").warning("private-document-sentinel")
        return original(page)

    monkeypatch.setattr(PageObject, "extract_text", warning_extract)
    source = PdfInput("report.pdf", text_pdf, DocumentRole.REPORT)
    # When
    with StringIO() as output, closing(logging.StreamHandler(output)) as handler:
        root_logger = logging.getLogger()
        root_logger.addHandler(handler)
        try:
            result = extract_pdf(source)
        finally:
            root_logger.removeHandler(handler)
        captured = output.getvalue()
    # Then
    assert "Purpose:" in result.pages[0].text
    assert result.parser_warning is True
    assert result.complete is False
    assert "private-document-sentinel" not in captured


def test_warning_does_not_contaminate_subsequent_document(
    text_pdf: bytes, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Given
    source = PdfInput("report.pdf", text_pdf, DocumentRole.REPORT)
    original = PageObject.extract_text

    def warning_extract(page: PageObject) -> str:
        logging.getLogger("pypdf._cmap").warning("private-document-sentinel")
        return original(page)

    with monkeypatch.context() as context:
        context.setattr(PageObject, "extract_text", warning_extract)
        extract_pdf(source)
    # When
    result = extract_pdf(source)
    # Then
    assert result.parser_warning is False
    assert result.complete is True
