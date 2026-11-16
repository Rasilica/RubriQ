from hashlib import sha256
from pathlib import PurePosixPath

from submission.document_contracts import (
    ArtifactId,
    ArtifactTextRange,
    BlockId,
    CharacterRange,
    CommonDocument,
    ContractError,
    ContractErrorCode,
    DocumentArtifact,
    DocumentBlock,
    DocumentDiagnostic,
    DocumentSource,
    EvidenceMapping,
    ExtractionCoverage,
    NormalizationSpan,
    PageCountAssessment,
    ProcessingStatus,
    SourceId,
    SourceLocator,
)
from submission.models import ExtractedDocument, PdfInput


def adapt_pdf(source: PdfInput, extracted: ExtractedDocument) -> CommonDocument:
    """Map existing extraction without parsing, storing, rendering, or changing its response."""
    content_hash = sha256(source.content).hexdigest()
    if extracted.id != f"{source.role.value}-{content_hash}" or extracted.role != source.role:
        raise ContractError(ContractErrorCode.SOURCE_IDENTITY_MISMATCH)
    if not extracted.pages:
        raise ContractError(ContractErrorCode.MISSING_PAGES)
    source_id = SourceId(extracted.id)
    artifact_id = ArtifactId(f"{extracted.id}:original_pdf")
    blocks, errors = collect_blocks(extracted, content_hash)
    mappings = tuple(identity_mapping(block, artifact_id) for block in blocks)
    if extracted.complete:
        extraction_status = ProcessingStatus.COMPLETE
    elif extracted.readable_pages:
        extraction_status = ProcessingStatus.PARTIAL
    else:
        extraction_status = ProcessingStatus.FAILED
    return CommonDocument(
        source=DocumentSource(
            source_id=source_id,
            role=extracted.role,
            filename=extracted.filename,
            content_sha256=content_hash,
            byte_size=len(source.content),
            declared_extension=PurePosixPath(source.filename.replace("\\", "/")).suffix.lower(),
            detected_format="pdf",
            document_version_id=extracted.id,
        ),
        blocks=blocks,
        artifacts=(
            DocumentArtifact(
                artifact_id=artifact_id,
                artifact_sha256=content_hash,
                kind="original_pdf",
                parent_source_id=source_id,
            ),
        ),
        coverage=ExtractionCoverage(
            scope="pypdf_text_layer",
            total_pages=len(extracted.pages),
            processed_pages=extracted.readable_pages,
            unreadable_pages=tuple(
                page.number for page in extracted.pages if page.error is not None
            ),
        ),
        extraction_status=extraction_status,
        rendering_status=ProcessingStatus.NOT_STARTED,
        warnings=(DocumentDiagnostic(code="parser_warning", page_number=None),)
        if extracted.parser_warning
        else (),
        typed_errors=errors,
        mappings=mappings,
        page_count=PageCountAssessment(
            basis="original_pdf",
            artifact_sha256=content_hash,
            artifact_page_count=len(extracted.pages),
            status="deferred",
            reason_code="inclusion_scope_unconfirmed",
        ),
    )


def collect_blocks(
    extracted: ExtractedDocument,
    content_hash: str,
) -> tuple[tuple[DocumentBlock, ...], tuple[DocumentDiagnostic, ...]]:
    blocks: list[DocumentBlock] = []
    seen: set[str] = set()
    errors: tuple[DocumentDiagnostic, ...] = ()
    for expected_number, page in enumerate(extracted.pages, start=1):
        if page.number != expected_number:
            raise ContractError(ContractErrorCode.PAGE_SEQUENCE_MISMATCH)
        match page.error:
            case None:
                cursor = 0
            case code:
                errors += (DocumentDiagnostic(code=code, page_number=page.number),)
                continue
        for paragraph in page.paragraphs:
            if not paragraph.text or paragraph.id in seen:
                raise ContractError(ContractErrorCode.INVALID_BLOCK_IDENTITY)
            start = page.text.find(paragraph.text, cursor)
            if start < 0:
                raise ContractError(ContractErrorCode.BLOCK_TEXT_MISMATCH)
            end = start + len(paragraph.text)
            local_range = CharacterRange(start=0, end=len(paragraph.text))
            seen.add(paragraph.id)
            blocks.append(
                DocumentBlock(
                    block_id=BlockId(paragraph.id),
                    kind="extraction_block",
                    raw_text=paragraph.text,
                    normalized_text=paragraph.text,
                    normalization_version="identity-v1",
                    normalization_map=(
                        NormalizationSpan(raw_range=local_range, normalized_range=local_range),
                    ),
                    source_locator=SourceLocator(
                        source_sha256=content_hash,
                        path=f"pages/{page.number}/blocks/{paragraph.id}",
                        original_page_number=page.number,
                    ),
                    raw_char_range=CharacterRange(start=start, end=end),
                    raw_coordinate_basis="extracted_page_unicode",
                    reading_order=len(blocks),
                )
            )
            cursor = end
    return tuple(blocks), errors


def identity_mapping(block: DocumentBlock, artifact_id: ArtifactId) -> EvidenceMapping:
    page_number = block.source_locator.original_page_number
    if page_number is None:
        raise ContractError(ContractErrorCode.MISSING_PDF_PAGE)
    return EvidenceMapping(
        source_block_id=block.block_id,
        source_char_range=CharacterRange(start=0, end=len(block.raw_text)),
        target_artifact_id=artifact_id,
        target_page_numbers=(page_number,),
        target_text_ranges=(
            ArtifactTextRange(page_number=page_number, char_range=block.raw_char_range),
        ),
        original_page_numbers=(page_number,),
        mapping_status="identity",
        verification_method="same_source_artifact",
    )
