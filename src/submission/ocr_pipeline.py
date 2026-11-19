"""Add machine-recognised text for pages without extractable text (optional local OCR)."""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from time import monotonic
from typing import Final

from submission.document_contracts import (
    BlockId,
    CharacterRange,
    CommonDocument,
    DocumentBlock,
    DocumentDiagnostic,
    EvidenceMapping,
    ExtractionCoverage,
    NormalizationSpan,
    OcrBlockInfo,
    ProcessingStatus,
    SourceLocator,
)
from submission.ocr_contracts import OcrError, OcrErrorCode
from submission.ocr_rows import OcrLine, OcrObservation, reconstruct_lines
from submission.ocr_runner import run_ocr
from submission.pair_assets import render_pdf_page
from submission.pair_contracts import PairRuntime

LOGGER = logging.getLogger(__name__)

MAX_OCR_PAGES: Final = 20
OCR_RENDER_EDGE: Final = 2400
WARNING_USED: Final = "ocr_text_used"
WARNING_PAGE_LIMIT: Final = "ocr_page_limit"
WARNING_TIMEOUT: Final = "ocr_timeout"
WARNING_FAILED: Final = "ocr_failed"

type PageReader = Callable[[bytes, int, float], tuple[OcrLine, ...]]


@dataclass(frozen=True, slots=True)
class OcrOutcome:
    document: CommonDocument
    warnings: tuple[str, ...] = ()


def recognize_page(
    pdf: bytes,
    page: int,
    runtime: PairRuntime,
    deadline: float,
) -> tuple[OcrLine, ...]:
    if runtime.ocr is None:
        raise OcrError(OcrErrorCode.UNAVAILABLE)
    png = render_pdf_page(pdf, page, runtime.pdftoppm, max_edge=OCR_RENDER_EDGE, wait=True)
    result = run_ocr(png, runtime.ocr, deadline=deadline)
    return reconstruct_lines(
        [OcrObservation(o.text, o.confidence, o.box) for o in result.observations]
    )


def pages_to_read(document: CommonDocument, page_count: int | None) -> tuple[int, ...]:
    """Pages without extractable text: unreadable PDF pages, or every page of an image-only file."""
    if isinstance(document.coverage, ExtractionCoverage):
        return document.coverage.unreadable_pages
    if any(block.raw_text.strip() for block in document.blocks):
        return ()
    return tuple(range(1, (page_count or 0) + 1))


def build_blocks(
    document: CommonDocument, page: int, lines: tuple[OcrLine, ...]
) -> tuple[DocumentBlock, ...]:
    sha = document.source.content_sha256
    blocks = []
    for number, line in enumerate(lines, start=1):
        span = CharacterRange(start=0, end=len(line.text))
        blocks.append(
            DocumentBlock(
                block_id=BlockId(f"p{page}-ocr{number}"),
                kind="ocr_line",
                raw_text=line.text,
                normalized_text=line.text,
                normalization_version="identity-v1",
                normalization_map=(NormalizationSpan(raw_range=span, normalized_range=span),),
                source_locator=SourceLocator(
                    source_sha256=sha, path=f"page[{page}]/ocr[{number}]", original_page_number=page
                ),
                raw_char_range=span,
                raw_coordinate_basis="ocr_unicode",
                reading_order=0,
                ocr=OcrBlockInfo(confidence=line.confidence, box=line.box, page_number=page),
            )
        )
    return tuple(blocks)


def merge_blocks(
    existing: tuple[DocumentBlock, ...], added: dict[int, tuple[DocumentBlock, ...]]
) -> tuple[DocumentBlock, ...]:
    """Place OCR pages in page order; blocks without a page (non-PDF) keep OCR text after them."""
    merged: list[DocumentBlock] = []
    pending = sorted(added)
    for block in existing:
        page = block.source_locator.original_page_number or 0
        while pending and page and pending[0] < page:
            merged.extend(added[pending.pop(0)])
        merged.append(block)
    for page in pending:
        merged.extend(added[page])
    return tuple(
        block.model_copy(update={"reading_order": order}) for order, block in enumerate(merged)
    )


def ocr_mappings(
    document: CommonDocument, blocks: tuple[DocumentBlock, ...]
) -> tuple[EvidenceMapping, ...]:
    if not document.artifacts:
        return ()
    artifact = document.artifacts[0]
    is_original = artifact.kind == "original_pdf"
    return tuple(
        EvidenceMapping(
            source_block_id=block.block_id,
            source_char_range=CharacterRange(start=0, end=len(block.raw_text)),
            target_artifact_id=artifact.artifact_id,
            target_page_numbers=(block.source_locator.original_page_number or 1,),
            target_text_ranges=(),
            original_page_numbers=(block.source_locator.original_page_number or 1,)
            if is_original
            else None,
            mapping_status="ocr_page",
            verification_method="ocr_page_only",
        )
        for block in blocks
    )


def with_ocr(document: CommonDocument, found: dict[int, tuple[OcrLine, ...]]) -> CommonDocument:
    added = {page: build_blocks(document, page, lines) for page, lines in found.items()}
    new_blocks = tuple(block for blocks in added.values() for block in blocks)
    return document.model_copy(
        update={
            "blocks": merge_blocks(document.blocks, added),
            "mappings": (*document.mappings, *ocr_mappings(document, new_blocks)),
            "warnings": (
                *document.warnings,
                *(DocumentDiagnostic(code=WARNING_USED, page_number=page) for page in added),
            ),
            "extraction_status": ProcessingStatus.PARTIAL,
        }
    )


def apply_ocr(  # noqa: PLR0913
    document: CommonDocument,
    pdf: bytes,
    page_count: int | None,
    runtime: PairRuntime,
    deadline: float,
    *,
    read_page: PageReader | None = None,
) -> OcrOutcome:
    """Recognise text on image-only pages; any failure keeps the document as read."""
    pages = pages_to_read(document, page_count) if runtime.ocr is not None else ()
    if not pages:
        return OcrOutcome(document)
    read = read_page or (lambda data, page, limit: recognize_page(data, page, runtime, limit))
    warnings = (WARNING_PAGE_LIMIT,) if len(pages) > MAX_OCR_PAGES else ()
    found: dict[int, tuple[OcrLine, ...]] = {}
    for page in pages[:MAX_OCR_PAGES]:
        if monotonic() >= deadline:
            warnings += (WARNING_TIMEOUT,)
            break
        try:
            lines = read(pdf, page, deadline)
        except OcrError as error:
            warnings += (str(error),)
            break
        except Exception:  # OCR is optional and must not fail document reading.
            LOGGER.warning("OCR failed on page %d", page, exc_info=True)
            warnings += (WARNING_FAILED,)
            break
        if lines:
            found[page] = lines
    if not found:
        return OcrOutcome(document, warnings)
    return OcrOutcome(with_ocr(document, found), (*warnings, WARNING_USED))
