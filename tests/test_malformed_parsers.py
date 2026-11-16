from pathlib import Path
from time import monotonic

import pytest

from submission import compound_documents, extraction, formats
from submission.extraction import read_pdf
from submission.formats import inspect_document
from submission.input_contracts import DocumentInput, InputErrorCode, InputValidationError
from submission.models import DocumentRole, PdfInput, PdfLimits, UploadError
from submission.pair_contracts import PairErrorCode, PairRuntime
from submission.pair_prepare import prepare_role

CFB_HEADER = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 504
PARSER_CRASHES = [RecursionError, TypeError, AttributeError, ZeroDivisionError]


def raise_error(error: type[Exception]):
    def crash(*_args: object, **_kwargs: object) -> None:
        raise error

    return crash


@pytest.mark.parametrize("error", PARSER_CRASHES)
def test_pdf_parser_crash_is_corrupt_document(
    monkeypatch: pytest.MonkeyPatch, text_pdf: bytes, error: type[Exception]
) -> None:
    monkeypatch.setattr(formats, "PdfReader", raise_error(error))

    with pytest.raises(InputValidationError) as caught:
        _ = inspect_document(DocumentInput("a.pdf", text_pdf, DocumentRole.REPORT))

    assert caught.value.code == InputErrorCode.CORRUPT_DOCUMENT


@pytest.mark.parametrize("error", PARSER_CRASHES)
def test_extraction_reader_crash_is_invalid_pdf(
    monkeypatch: pytest.MonkeyPatch, text_pdf: bytes, error: type[Exception]
) -> None:
    monkeypatch.setattr(extraction, "PdfReader", raise_error(error))

    with pytest.raises(UploadError) as caught:
        _ = read_pdf(PdfInput("a.pdf", text_pdf, DocumentRole.REPORT), PdfLimits())

    assert caught.value.code == "invalid_pdf"


def test_page_text_crash_is_page_extraction_error() -> None:
    class Page:
        def extract_text(self) -> str:
            raise RecursionError

    class Reader:
        pages = (Page(),)

    page = extraction.extract_page(Reader(), 0)  # pyright: ignore[reportArgumentType]

    assert page.error == "extraction_error"


@pytest.mark.parametrize("error", [RecursionError, TypeError])
def test_compound_parser_crash_is_corrupt_document(
    monkeypatch: pytest.MonkeyPatch, error: type[Exception]
) -> None:
    monkeypatch.setattr(compound_documents, "OleFileIO", raise_error(error))

    with pytest.raises(InputValidationError) as caught:
        _ = inspect_document(DocumentInput("a.hwp", CFB_HEADER, DocumentRole.REPORT))

    assert caught.value.code == InputErrorCode.CORRUPT_DOCUMENT


def test_unexpected_read_failure_fails_only_that_role(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("submission.pair_prepare.read_source", raise_error(RuntimeError))
    source = DocumentInput("a.pdf", b"%PDF-1.7", DocumentRole.REPORT)

    result = prepare_role(source, PairRuntime(), monotonic() + 10)

    assert result.view.extraction_status == "failed"
    assert result.view.error_code == PairErrorCode.FAILED


def test_unexpected_conversion_failure_keeps_read_structure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("submission.pair_prepare.convert_source", raise_error(RuntimeError))
    source = DocumentInput(
        "a.docx", Path("samples/formats/boundary.docx").read_bytes(), DocumentRole.REPORT
    )

    result = prepare_role(source, PairRuntime(), monotonic() + 10)

    assert result.view.rendering_status == "failed"
    assert result.view.error_code == PairErrorCode.FAILED
    assert result.view.document is not None
