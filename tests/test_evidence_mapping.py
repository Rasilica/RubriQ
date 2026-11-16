from evidence_helpers import document, synthetic_context

from submission.document_contracts import ArtifactTextRange, CharacterRange
from submission.evidence_artifacts import inspect_artifact
from submission.evidence_contracts import (
    ArtifactBinding,
    EvidenceMapContext,
    EvidenceMapRequest,
    PdfArtifactInput,
)
from submission.evidence_mapping import map_evidence
from submission.models import DocumentRole, PdfInput
from submission.requirement_contracts import CitationInput


def test_mapping_when_original_pdf_rechecks_actual_identity(text_pdf):
    # Given
    source = document(text_pdf)
    target = PdfArtifactInput(
        binding=ArtifactBinding(source=source.source, artifact=source.artifacts[0]),
        pdf=PdfInput("source.pdf", text_pdf, DocumentRole.REPORT),
    )
    block = source.blocks[0]
    request = EvidenceMapRequest(
        citation=CitationInput(
            block_id=block.block_id,
            quote=block.raw_text,
            char_range=CharacterRange(start=0, end=len(block.raw_text)),
        )
    )
    # When
    result = map_evidence(EvidenceMapContext(document=source, target=target), request)
    # Then
    assert result.mapping.mapping_status == "identity"
    assert result.mapping.original_page_numbers == (1,)
    assert result.snapshot_origin == "real_pdf"


def test_mapping_when_quote_spans_contiguous_pages_preserves_ranges(text_pdf):
    # Given
    source = document(text_pdf)
    block = source.blocks[0]
    middle = len(block.raw_text) // 2
    ctx = synthetic_context(text_pdf, (block.raw_text[:middle], block.raw_text[middle:]))
    request = EvidenceMapRequest(
        citation=CitationInput(
            block_id=block.block_id,
            quote=block.raw_text,
            char_range=CharacterRange(start=0, end=len(block.raw_text)),
        )
    )
    # When
    result = map_evidence(ctx, request)
    # Then
    assert result.mapping.mapping_status == "verified_anchor"
    assert result.mapping.target_page_numbers == (1, 2)
    assert result.mapping.original_page_numbers is None
    assert inspect_artifact(ctx.target).physical_verified is False


def test_mapping_when_expected_ranges_split_same_page_still_matches(text_pdf):
    # Given
    source = document(text_pdf)
    block = source.blocks[0]
    ctx = synthetic_context(text_pdf, (block.raw_text,))
    request = EvidenceMapRequest(
        citation=CitationInput(
            block_id=block.block_id,
            quote=block.raw_text,
            char_range=CharacterRange(start=0, end=len(block.raw_text)),
        ),
        expected_target_ranges=(
            ArtifactTextRange(page_number=1, char_range=CharacterRange(start=0, end=1)),
            ArtifactTextRange(
                page_number=1, char_range=CharacterRange(start=1, end=len(block.raw_text))
            ),
        ),
    )
    # When
    result = map_evidence(ctx, request)
    # Then
    assert result.mapping.mapping_status == "verified_anchor"
