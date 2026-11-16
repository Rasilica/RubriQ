import pytest
from evidence_helpers import document, original_target, request_for, synthetic_context

from submission.document_contracts import ArtifactTextRange, CharacterRange
from submission.evidence_contracts import EvidenceMapContext
from submission.evidence_mapping import map_evidence


@pytest.mark.parametrize("wrong_location", [False, True])
def test_identity_claim_must_reference_source_coordinates(
    text_pdf: bytes, *, wrong_location: bool
) -> None:
    # Given
    source = document(text_pdf)
    block = source.blocks[0]
    start = block.raw_text.index("e")
    claimed = block.raw_text.index("e", start + 1) if wrong_location else start
    ctx = EvidenceMapContext(document=source, target=original_target(text_pdf))
    request = request_for(ctx)
    request = request.model_copy(
        update={
            "citation": request.citation.model_copy(
                update={"quote": "e", "char_range": CharacterRange(start=start, end=start + 1)}
            ),
            "expected_target_ranges": (
                ArtifactTextRange(
                    page_number=1,
                    char_range=CharacterRange(
                        start=block.raw_char_range.start + claimed,
                        end=block.raw_char_range.start + claimed + 1,
                    ),
                ),
            ),
        }
    )
    # When
    result = map_evidence(ctx, request)
    # Then
    assert result.mapping.mapping_status == ("mismatch" if wrong_location else "identity")


@pytest.mark.parametrize("gap", ["", "XXX"])
def test_claims_across_pages_require_complete_candidate_coverage(text_pdf: bytes, gap: str) -> None:
    # Given
    quote = document(text_pdf).blocks[0].raw_text
    middle = len(quote) // 2
    ctx = synthetic_context(text_pdf, (quote[:middle] + gap, quote[middle:]))
    request = request_for(ctx).model_copy(
        update={
            "expected_target_ranges": (
                ArtifactTextRange(page_number=1, char_range=CharacterRange(start=0, end=1)),
                ArtifactTextRange(page_number=1, char_range=CharacterRange(start=1, end=middle)),
                ArtifactTextRange(
                    page_number=2, char_range=CharacterRange(start=0, end=len(quote) - middle)
                ),
            ),
        }
    )
    # When
    result = map_evidence(ctx, request)
    # Then
    assert result.mapping.mapping_status == ("mismatch" if gap else "verified_anchor")
    assert result.mapping.target_page_numbers == (() if gap else (1, 2))
