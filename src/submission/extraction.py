from hashlib import sha256
from io import BytesIO
from pathlib import PurePosixPath
from typing import Final

from pypdf import PdfReader

from submission.models import (
    ExtractedDocument,
    ExtractedPage,
    Paragraph,
    PdfInput,
    PdfLimits,
    UploadError,
)
from submission.pdf_diagnostics import PARSER_WARNING

DEFAULT_LIMITS: Final = PdfLimits()


def extract_pdf(source: PdfInput, limits: PdfLimits = DEFAULT_LIMITS) -> ExtractedDocument:
    """Preserve file page positions, including pages whose text cannot be read."""
    token = PARSER_WARNING.set(False)
    try:
        result = read_pdf(source, limits)
        return result.model_copy(update={"parser_warning": PARSER_WARNING.get()})
    finally:
        PARSER_WARNING.reset(token)


def read_pdf(source: PdfInput, limits: PdfLimits) -> ExtractedDocument:
    if not source.content:
        raise UploadError("empty_file", "빈 파일입니다.", source.role)
    if len(source.content) > limits.max_bytes:
        raise UploadError("file_too_large", "파일 크기 한도를 초과했습니다.", source.role)
    if not source.content.startswith(b"%PDF-"):
        raise UploadError("invalid_pdf", "PDF 파일만 지원합니다.", source.role)
    try:
        reader = PdfReader(BytesIO(source.content), strict=True)
        encrypted = reader.is_encrypted
        count = 0 if encrypted else len(reader.pages)
    except Exception as error:  # pypdf raises arbitrary errors on hostile input.
        raise UploadError("invalid_pdf", "PDF 구조를 읽을 수 없습니다.", source.role) from error
    if encrypted:
        raise UploadError("encrypted_pdf", "암호화된 PDF는 지원하지 않습니다.", source.role)
    if count == 0:
        raise UploadError("empty_document", "페이지가 없는 PDF입니다.", source.role)
    if count > limits.max_pages:
        raise UploadError("too_many_pages", "PDF 페이지 수 한도를 초과했습니다.", source.role)
    pages = tuple(extract_page(reader, index) for index in range(count))
    return ExtractedDocument(
        id=f"{source.role.value}-{sha256(source.content).hexdigest()}",
        role=source.role,
        filename=PurePosixPath(source.filename.replace("\\", "/")).name,
        pages=pages,
    )


def extract_page(reader: PdfReader, index: int) -> ExtractedPage:
    """Paragraph IDs identify extraction blocks, not inferred semantic paragraphs."""
    number = index + 1
    try:
        text = reader.pages[index].extract_text().strip()
    except Exception:  # noqa: BLE001 -- pypdf raises arbitrary errors on hostile input.
        return ExtractedPage(number=number, text="", paragraphs=(), error="extraction_error")
    paragraphs = tuple(
        Paragraph(id=f"p{number}-b{block}", text=part.strip())
        for block, part in enumerate(text.split("\n\n"), start=1)
        if part.strip()
    )
    return ExtractedPage(
        number=number,
        text=text,
        paragraphs=paragraphs,
        error=None if text else "text_unavailable",
    )
