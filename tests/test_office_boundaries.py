from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

import pytest
from pydantic import ValidationError

from submission.docx_validation import DOCX_CONTENT, STRICT_WORD_NS, WORD_NS
from submission.formats import inspect_document
from submission.input_contracts import (
    DocumentInput,
    InputErrorCode,
    InputLimits,
    InputValidationError,
)
from submission.models import DocumentRole

FIXTURES = Path(__file__).parents[1] / "samples/formats"


def replace_member(content: bytes, path: str, data: bytes | None) -> bytes:
    with ZipFile(BytesIO(content)) as archive:
        members = tuple((name, archive.read(name)) for name in archive.namelist() if name != path)
    if data is not None:
        members += ((path, data),)
    result = BytesIO()
    with ZipFile(result, "w") as archive:
        for name, payload in members:
            archive.writestr(name, payload)
    return result.getvalue()


def test_docx_main_part_is_discovered_through_relationships() -> None:
    original = (FIXTURES / "boundary.docx").read_bytes()
    result = BytesIO()
    with ZipFile(BytesIO(original)) as archive, ZipFile(result, "w") as renamed:
        for name in archive.namelist():
            renamed.writestr(
                name.replace("word/", "custom/"), archive.read(name).replace(b"word/", b"custom/")
            )
    inspection = inspect_document(
        DocumentInput("report.docx", result.getvalue(), DocumentRole.REPORT)
    )
    assert inspection.content_members == ("custom/document.xml",)


@pytest.mark.parametrize(
    ("filename", "path", "old", "new", "expected"),
    [
        (
            "boundary.docx",
            "word/document.xml",
            WORD_NS.encode(),
            STRICT_WORD_NS.encode(),
            InputErrorCode.UNSUPPORTED_VERSION,
        ),
        (
            "boundary.docx",
            "[Content_Types].xml",
            DOCX_CONTENT.encode(),
            b"application/vnd.ms-word.document.macroEnabled.main+xml",
            InputErrorCode.UNSUPPORTED_FEATURE,
        ),
        (
            "boundary.docx",
            "_rels/.rels",
            b"word/document.xml",
            b"word/missing.xml",
            InputErrorCode.CORRUPT_DOCUMENT,
        ),
        (
            "boundary.docx",
            "word/document.xml",
            b"</w:document>",
            b"",
            InputErrorCode.CORRUPT_DOCUMENT,
        ),
        (
            "spine-order.hwpx",
            "version.xml",
            b'xmlVersion="1.5"',
            b'xmlVersion="9.0"',
            InputErrorCode.UNSUPPORTED_VERSION,
        ),
        (
            "spine-order.hwpx",
            "Contents/content.hpf",
            b'idref="section1"',
            b'idref="missing"',
            InputErrorCode.CORRUPT_DOCUMENT,
        ),
    ],
)
def test_office_structure_and_profile_failures_are_distinct(
    filename: str,
    path: str,
    old: bytes,
    new: bytes,
    expected: InputErrorCode,
) -> None:
    source = (FIXTURES / filename).read_bytes()
    with ZipFile(BytesIO(source)) as archive:
        original = archive.read(path)
    assert old in original
    changed = replace_member(source, path, original.replace(old, new))
    with pytest.raises(InputValidationError) as caught:
        inspect_document(DocumentInput(filename, changed, DocumentRole.GUIDE))
    assert caught.value.code is expected
    assert caught.value.role is DocumentRole.GUIDE


def test_docx_edit_protection_is_not_encryption() -> None:
    content = (FIXTURES / "boundary.docx").read_bytes()
    settings = (
        f'<w:settings xmlns:w="{WORD_NS}"><w:documentProtection w:enforcement="1"/></w:settings>'
    )
    changed = replace_member(content, "word/settings.xml", settings.encode())
    with pytest.raises(InputValidationError) as caught:
        inspect_document(DocumentInput("report.docx", changed, DocumentRole.REPORT))
    assert caught.value.code is InputErrorCode.PROTECTED_DOCUMENT


def test_hwpx_encryption_metadata_precedes_unreadable_section_xml() -> None:
    content = (FIXTURES / "spine-order.hwpx").read_bytes()
    manifest = (
        b'<manifest xmlns="urn:oasis:names:tc:opendocument:xmlns:manifest:1.0">'
        b"<file-entry><encryption-data/></file-entry></manifest>"
    )
    changed = replace_member(content, "META-INF/manifest.xml", manifest)
    changed = replace_member(changed, "Contents/section1.xml", b"not XML")
    with pytest.raises(InputValidationError) as caught:
        inspect_document(DocumentInput("report.hwpx", changed, DocumentRole.REPORT))
    assert caught.value.code is InputErrorCode.ENCRYPTED_DOCUMENT
    assert caught.value.detected_format == "hwpx"


def test_xml_in_a_relationship_part_is_also_bounded() -> None:
    content = (FIXTURES / "boundary.docx").read_bytes()
    with pytest.raises(InputValidationError) as caught:
        inspect_document(
            DocumentInput("report.docx", content, DocumentRole.REPORT), InputLimits(max_xml_bytes=4)
        )
    assert caught.value.code is InputErrorCode.XML_LIMIT


@pytest.mark.parametrize(
    "mime", [None, "application/octet-stream", "APPLICATION/PDF; charset=binary"]
)
def test_missing_generic_or_matching_mime_is_neutral(mime: str | None, text_pdf: bytes) -> None:
    source = DocumentInput("report.pdf", text_pdf, DocumentRole.REPORT, mime)
    assert inspect_document(source).declared_mime == mime


def test_contradictory_mime_is_rejected(text_pdf: bytes) -> None:
    with pytest.raises(InputValidationError) as caught:
        inspect_document(
            DocumentInput("report.pdf", text_pdf, DocumentRole.REPORT, "application/hwp+zip")
        )
    assert caught.value.code is InputErrorCode.MIME_MISMATCH
    assert caught.value.detected_format == "pdf"


def test_roles_share_bytes_hash_but_not_source_identity(text_pdf: bytes) -> None:
    guide = inspect_document(DocumentInput("same.pdf", text_pdf, DocumentRole.GUIDE))
    report = inspect_document(DocumentInput("same.pdf", text_pdf, DocumentRole.REPORT))
    assert guide.source.content_sha256 == report.source.content_sha256
    assert guide.source.source_id != report.source.source_id
    with pytest.raises(ValidationError):
        guide.stored = True


def test_limits_must_be_positive() -> None:
    with pytest.raises(ValidationError):
        InputLimits(max_members=0)
