from hashlib import sha256
from io import BytesIO
from pathlib import Path
from typing import Final, assert_never

from pypdf import PdfReader
from pypdf.errors import PyPdfError

from submission.document_contracts import CommonDocument, ContractError
from submission.docx_contract_validation import (
    validate_docx_document,
    validate_reference,
    validate_spans,
)
from submission.hwpx_contract_validation import (
    expected_identity,
    validate_fragment_sequence,
    validate_hwpx_document,
)
from submission.library_contracts import LibraryCode, LibraryError
from submission.models import DocumentRole
from submission.pair_contracts import PairRuntime, PreparedRole

MAX_BLOCKS: Final = 10_000
MAX_PAGES: Final = 50


def check(*conditions: bool) -> None:
    if not all(conditions):
        raise LibraryError(LibraryCode.CORRUPT)


def structure(document: CommonDocument) -> None:
    blocks = {block.block_id: block for block in document.blocks}
    check(len(blocks) == len(document.blocks) <= MAX_BLOCKS)
    for order, block in enumerate(document.blocks):
        check(block.reading_order == order)
        check(block.source_locator.source_sha256 == document.source.content_sha256)
        parent = blocks.get(block.parent_block_id) if block.parent_block_id else None
        check(
            block.parent_block_id is None or (parent is not None and parent.reading_order < order)
        )
    match document.source.detected_format:
        case "docx":
            _ = validate_docx_document(document)
        case "hwpx":
            _ = validate_hwpx_document(document)
        case "hwp":
            check(document.coverage.scope == "hwp5_structure")
            validate_fragment_sequence(document.blocks)
            for block in document.blocks:
                validate_spans(block, document.source)
                check(block.block_id == expected_identity(block, document.source))
                check(block.raw_coordinate_basis == "hwp_paragraph_unicode")
                check(block.raw_char_range.end - block.raw_char_range.start == len(block.raw_text))
                check(block.raw_text == block.normalized_text)
            for reference in document.references:
                validate_reference(reference, document.source, blocks)
        case "pdf":
            check(document.coverage.scope == "pypdf_text_layer")
        case _:
            assert_never(document.source.detected_format)
    for mapping in document.mappings:
        check(mapping.source_block_id in blocks)
        check(any(item.artifact_id == mapping.target_artifact_id for item in document.artifacts))
        check(mapping.source_char_range.end <= len(blocks[mapping.source_block_id].raw_text))
    for item in (*document.warnings, *document.typed_errors):
        check(
            item.source_locator is None
            or item.source_locator.source_sha256 == document.source.content_sha256
        )


def validate_role(role: PreparedRole, expected: DocumentRole) -> None:
    try:
        check(role.view.role == expected and len(role.original) <= 10 * 1024 * 1024)
        document = role.view.document
        if document is None:
            check(role.pdf is None and role.view.artifact_kind is None)
            check(role.view.preview_page_count is None)
            return
        check(document.source.role == expected)
        check(document.source.byte_size == len(role.original))
        check(document.source.content_sha256 == sha256(role.original).hexdigest())
        check(document.extraction_status == role.view.extraction_status)
        check(document.rendering_status == role.view.rendering_status)
        structure(document)
        if role.pdf is None:
            check(not document.artifacts and role.view.preview_page_count is None)
            return
        check(len(role.pdf) <= 10 * 1024 * 1024)
        check(len(document.artifacts) == 1)
        artifact = document.artifacts[0]
        check(artifact.parent_source_id == document.source.source_id)
        check(artifact.artifact_sha256 == sha256(role.pdf).hexdigest())
        check(artifact.kind == role.view.artifact_kind)
        check(artifact.storage_location is None)
        reader = PdfReader(BytesIO(role.pdf), strict=True)
        check(not reader.is_encrypted)
        check(1 <= len(reader.pages) <= MAX_PAGES)
        check(len(reader.pages) == role.view.preview_page_count)
        if document.source.detected_format == "pdf":
            check(role.pdf == role.original and artifact.kind == "original_pdf")
            check(document.page_count.artifact_page_count == len(reader.pages))
            check(document.page_count.artifact_sha256 == artifact.artifact_sha256)
            for block in document.blocks:
                page = block.source_locator.original_page_number
                check(page is not None and 1 <= page <= len(reader.pages))
    except (ContractError, PyPdfError, ValueError, TypeError):
        raise LibraryError(LibraryCode.CORRUPT) from None


def binary_identity(path: Path) -> str:
    try:
        with path.open("rb") as stream:
            content = stream.read(32 * 1024 * 1024 + 1)
        if len(content) > 32 * 1024 * 1024:
            return "identity-unavailable"
        return sha256(content).hexdigest()
    except OSError:
        return "identity-unavailable"


def environment(runtime: PairRuntime) -> tuple[str, ...]:
    labels = (
        "document-library-v1",
        "docx-runtime:configured" if runtime.docx is not None else "docx-runtime:unavailable",
        "hancom-runtime:configured" if runtime.hancom is not None else "hancom-runtime:unavailable",
        "hwp-reader:configured" if runtime.hwp is not None else "hwp-reader:unavailable",
        "pdf-renderer:configured" if runtime.pdftoppm is not None else "pdf-renderer:unavailable",
    )
    if runtime.docx is not None:
        labels = (*labels, f"docx-soffice:{binary_identity(runtime.docx.soffice)}")
    if runtime.pdftoppm is not None:
        labels = (*labels, f"pdf-renderer:{binary_identity(runtime.pdftoppm)}")
    if runtime.hwp is not None:
        provision = runtime.hwp.provision
        labels = (
            *labels,
            f"hwplib:{provision.library_version}:{provision.jar.sha256}",
            f"hwp-worker:{provision.worker.sha256}",
            *(f"hwp-java-{index}:{item.sha256}" for index, item in enumerate(provision.java_files)),
        )
    if runtime.hancom is not None:
        profile = runtime.hancom.provision
        labels = (
            *labels,
            f"hancom-soffice:{profile.soffice.sha256}",
            f"hancom-extension:{profile.extension_version}:{profile.extension_sha256}",
            f"hancom-profile:{profile.template_sha256}",
            *(
                f"hancom-java-{index}:{item.sha256}"
                for index, item in enumerate(profile.java_files)
            ),
        )
    return labels
