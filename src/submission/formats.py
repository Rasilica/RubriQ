from hashlib import sha256
from io import BytesIO
from pathlib import PurePosixPath
from typing import Final

from pypdf import PdfReader

from submission.compound_documents import inspect_compound
from submission.document_contracts import DocumentSource, SourceId
from submission.docx_validation import inspect_docx
from submission.format_containers import read_package, validate_package_xml
from submission.hwpx_validation import inspect_hwpx
from submission.input_contracts import (
    DocumentInput,
    FormatDetails,
    FormatInspection,
    InputErrorCode,
    InputLimits,
    InputValidationError,
)
from submission.pdf_diagnostics import PARSER_WARNING

DEFAULT_INPUT_LIMITS: Final = InputLimits()
CFB_MAGIC: Final = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
MIME_TYPES: Final = {
    "pdf": frozenset({"application/pdf"}),
    "docx": frozenset({"application/vnd.openxmlformats-officedocument.wordprocessingml.document"}),
    "hwpx": frozenset({"application/hwp+zip", "application/vnd.hancom.hwpx"}),
    "hwp": frozenset(
        {"application/x-hwp", "application/haansofthwp", "application/vnd.hancom.hwp"}
    ),
}


def inspect_pdf(content: bytes, limits: InputLimits) -> FormatDetails:
    version = content[5:8].decode("ascii", errors="replace")
    if version not in {"1.0", "1.1", "1.2", "1.3", "1.4", "1.5", "1.6", "1.7", "2.0"}:
        raise InputValidationError(InputErrorCode.UNSUPPORTED_VERSION, detected_format="pdf")
    token = PARSER_WARNING.set(False)
    try:
        try:
            reader = PdfReader(BytesIO(content), strict=True)
            encrypted = reader.is_encrypted
            count = 0 if encrypted else len(reader.pages)
        except Exception as error:  # pypdf raises arbitrary errors on hostile input.
            raise InputValidationError(
                InputErrorCode.CORRUPT_DOCUMENT, detected_format="pdf"
            ) from error
        if encrypted:
            raise InputValidationError(InputErrorCode.ENCRYPTED_DOCUMENT, detected_format="pdf")
        if count == 0:
            raise InputValidationError(InputErrorCode.EMPTY_DOCUMENT, detected_format="pdf")
        if count > limits.max_pdf_pages:
            raise InputValidationError(InputErrorCode.TOO_MANY_PAGES, detected_format="pdf")
        return FormatDetails(
            detected_format="pdf", version=version, parser_warning=PARSER_WARNING.get()
        )
    finally:
        PARSER_WARNING.reset(token)


def detect_and_validate(content: bytes, limits: InputLimits) -> FormatDetails:
    if content.startswith(b"%PDF-"):
        return inspect_pdf(content, limits)
    if content.startswith(CFB_MAGIC):
        return inspect_compound(content, limits)
    if content.startswith(b"HWP Document File V3.00"):
        raise InputValidationError(InputErrorCode.UNSUPPORTED_VERSION, detected_format="hwp")
    if not content.startswith((b"PK\x03\x04", b"PK\x05\x06")):
        raise InputValidationError(InputErrorCode.UNSUPPORTED_FORMAT)
    members = read_package(content, limits)
    names = frozenset(member.name for member in members)
    is_hwpx = "mimetype" in names or "Contents/content.hpf" in names
    is_docx = "[Content_Types].xml" in names or "_rels/.rels" in names
    if is_hwpx and is_docx:
        raise InputValidationError(InputErrorCode.CORRUPT_DOCUMENT)
    if is_hwpx:
        result = inspect_hwpx(members, limits)
    elif is_docx:
        result = inspect_docx(members, limits)
    else:
        raise InputValidationError(InputErrorCode.UNSUPPORTED_FORMAT)
    validate_package_xml(members, limits)
    return result


def inspect_document(
    source: DocumentInput, limits: InputLimits = DEFAULT_INPUT_LIMITS
) -> FormatInspection:
    if not source.content:
        raise InputValidationError(InputErrorCode.EMPTY_FILE, source.role)
    if len(source.content) > limits.max_bytes:
        raise InputValidationError(InputErrorCode.FILE_TOO_LARGE, source.role)
    try:
        details = detect_and_validate(source.content, limits)
    except InputValidationError as error:
        raise InputValidationError(error.code, source.role, error.detected_format) from None
    filename = PurePosixPath(source.filename.replace("\\", "/")).name
    extension = PurePosixPath(filename).suffix.lower()
    if extension != f".{details.detected_format}":
        raise InputValidationError(
            InputErrorCode.EXTENSION_MISMATCH, source.role, details.detected_format
        )
    mime = source.declared_mime
    if mime is not None:
        normalized_mime = mime.partition(";")[0].strip().lower()
        if normalized_mime not in {
            "",
            "application/octet-stream",
            *MIME_TYPES[details.detected_format],
        }:
            raise InputValidationError(
                InputErrorCode.MIME_MISMATCH, source.role, details.detected_format
            )
    content_hash = sha256(source.content).hexdigest()
    source_id = SourceId(f"{source.role.value}-{content_hash}")
    return FormatInspection(
        source=DocumentSource(
            source_id=source_id,
            role=source.role,
            filename=filename,
            content_sha256=content_hash,
            byte_size=len(source.content),
            declared_extension=extension,
            detected_format=details.detected_format,
            format_version=details.version,
            document_version_id=source_id,
        ),
        declared_mime=mime,
        container_members=details.members,
        content_members=details.content_members,
        parser_warning=details.parser_warning,
    )
