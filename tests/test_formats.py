from io import BytesIO
from pathlib import Path
from zipfile import ZIP_STORED, ZipFile

import pytest
from pypdf import PdfWriter

from submission.formats import inspect_document
from submission.input_contracts import (
    DocumentInput,
    InputErrorCode,
    InputLimits,
    InputValidationError,
)
from submission.models import DocumentRole


def package_bytes(members: tuple[tuple[str, bytes], ...]) -> bytes:
    buffer = BytesIO()
    with ZipFile(buffer, "w", compression=ZIP_STORED) as archive:
        for name, content in members:
            archive.writestr(name, content)
    return buffer.getvalue()


def input_file(filename: str, content: bytes) -> DocumentInput:
    return DocumentInput(filename, content, DocumentRole.REPORT)


def test_pdf_boundary_preserves_identity_without_extracting(text_pdf: bytes) -> None:
    # Given
    source = input_file("folder/report.PDF", text_pdf)
    # When
    result = inspect_document(source)
    # Then
    assert result.source.detected_format == "pdf"
    assert result.source.filename == "report.PDF"
    assert result.source.format_version == "1.3"
    assert result.source.source_id == result.source.document_version_id
    assert result.extraction_performed is False
    assert result.rendering_performed is False
    assert result.stored is False


@pytest.mark.parametrize(
    ("filename", "content", "expected"),
    [
        ("empty.pdf", b"", InputErrorCode.EMPTY_FILE),
        ("unknown.hwp", b"plain text", InputErrorCode.UNSUPPORTED_FORMAT),
        ("broken.pdf", b"%PDF-1.7\n", InputErrorCode.CORRUPT_DOCUMENT),
        ("broken.docx", b"PK\x03\x04", InputErrorCode.CORRUPT_DOCUMENT),
        ("old.hwp", b"HWP Document File V3.00", InputErrorCode.UNSUPPORTED_VERSION),
    ],
)
def test_invalid_inputs_have_typed_errors(
    filename: str,
    content: bytes,
    expected: InputErrorCode,
) -> None:
    # Given / When
    with pytest.raises(InputValidationError) as caught:
        inspect_document(input_file(filename, content))
    # Then
    assert caught.value.code is expected
    assert caught.value.role is DocumentRole.REPORT


@pytest.mark.parametrize("filename", ["report.docx", "report", "report.pdf.exe"])
def test_extension_cannot_override_pdf_content(filename: str, text_pdf: bytes) -> None:
    with pytest.raises(InputValidationError) as caught:
        inspect_document(input_file(filename, text_pdf))
    assert caught.value.code is InputErrorCode.EXTENSION_MISMATCH
    assert caught.value.detected_format == "pdf"


def test_upload_size_limit_precedes_container_parsing(text_pdf: bytes) -> None:
    with pytest.raises(InputValidationError) as caught:
        inspect_document(input_file("report.pdf", text_pdf), InputLimits(max_bytes=10))
    assert caught.value.code is InputErrorCode.FILE_TOO_LARGE


def test_pdf_encryption_is_distinct_from_corruption() -> None:
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    writer.encrypt("local-fixture")
    buffer = BytesIO()
    writer.write(buffer)
    with pytest.raises(InputValidationError) as caught:
        inspect_document(input_file("protected.pdf", buffer.getvalue()))
    assert caught.value.code is InputErrorCode.ENCRYPTED_DOCUMENT


def test_pdf_page_limit_is_enforced(text_pdf: bytes) -> None:
    with pytest.raises(InputValidationError) as caught:
        inspect_document(input_file("report.pdf", text_pdf), InputLimits(max_pdf_pages=1))
    assert caught.value.code is InputErrorCode.TOO_MANY_PAGES


@pytest.mark.parametrize("name", ["../node.xml", "/node.xml", "a\\node.xml"])
def test_package_paths_are_checked_without_extraction(name: str) -> None:
    payload = package_bytes(((name, b"<node/>"),))
    with pytest.raises(InputValidationError) as caught:
        inspect_document(input_file("report.docx", payload))
    assert caught.value.code is InputErrorCode.UNSAFE_PACKAGE_PATH


def test_zip_limits_use_small_configurable_boundaries() -> None:
    payload = package_bytes((("a.xml", b"<a/>"), ("b.xml", b"<b/>")))
    with pytest.raises(InputValidationError) as caught:
        inspect_document(input_file("report.hwpx", payload), InputLimits(max_members=1))
    assert caught.value.code is InputErrorCode.PACKAGE_LIMIT


@pytest.mark.parametrize(
    ("filename", "relative", "expected_format"),
    [
        ("report.docx", "boundary.docx", "docx"),
        ("report.hwpx", "spine-order.hwpx", "hwpx"),
        ("report.hwp", "minimal-5.1.1.0.hwp", "hwp"),
    ],
)
def test_synthetic_containers_are_identified(
    filename: str,
    relative: str,
    expected_format: str,
) -> None:
    content = (Path(__file__).parents[1] / "samples/formats" / relative).read_bytes()
    result = inspect_document(input_file(filename, content))
    assert result.source.detected_format == expected_format
    assert result.source.format_version
    assert result.content_members
    assert result.extraction_performed is False


def test_hwpx_content_order_comes_from_spine() -> None:
    content = (Path(__file__).parents[1] / "samples/formats/spine-order.hwpx").read_bytes()
    result = inspect_document(input_file("report.hwpx", content))
    assert result.content_members == ("Contents/section1.xml", "Contents/section0.xml")
