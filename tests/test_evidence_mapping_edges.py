import pytest
from evidence_helpers import document, original_target, request_for, synthetic_context

from submission.document_contracts import ArtifactTextRange, CharacterRange
from submission.evidence_contracts import (
    ArtifactPage,
    EvidenceError,
    EvidenceLimits,
    EvidenceMapContext,
)
from submission.evidence_mapping import map_evidence


def mapping_case(text_pdf, case):
    # Given
    quote = document(text_pdf).blocks[0].raw_text
    ctx = synthetic_context(text_pdf, (quote,))
    request = request_for(ctx)
    limits = EvidenceLimits()
    expected = None
    if case == "repeated":
        ctx = synthetic_context(text_pdf, (quote, quote))
        expected = "ambiguous"
    elif case == "absent":
        ctx = synthetic_context(text_pdf, ("different",))
        expected = "unmapped"
    elif case == "mismatch":
        request = request.model_copy(
            update={
                "expected_target_ranges": (
                    ArtifactTextRange(page_number=1, char_range=CharacterRange(start=0, end=1)),
                )
            }
        )
        expected = "mismatch"
    elif case == "incomplete":
        ctx = ctx.model_copy(
            update={
                "target": ctx.target.model_copy(
                    update={
                        "pages": (
                            ArtifactPage(number=1, text=quote),
                            ArtifactPage(number=2, text="", status="extraction_error"),
                        )
                    }
                )
            }
        )
        expected = "unmapped"
    elif case == "candidate_limit":
        ctx = synthetic_context(text_pdf, (quote, quote))
        limits = EvidenceLimits(max_candidates=1)
    elif case == "range":
        request = request.model_copy(
            update={
                "expected_target_ranges": (
                    ArtifactTextRange(page_number=2, char_range=CharacterRange(start=0, end=1)),
                )
            }
        )
    elif case == "claim_limit":
        request = request.model_copy(update={"expected_target_ranges": ()})
    elif case == "citation":
        request = request.model_copy(
            update={"citation": request.citation.model_copy(update={"quote": "wrong"})}
        )
    elif case == "source":
        ctx = ctx.model_copy(
            update={
                "document": ctx.document.model_copy(
                    update={
                        "source": ctx.document.source.model_copy(
                            update={"document_version_id": "stale"}
                        )
                    }
                )
            }
        )
    else:
        limits = EvidenceLimits(max_blocks=1)
    return ctx, request, limits, expected


@pytest.mark.parametrize(
    "case",
    [
        "repeated",
        "absent",
        "mismatch",
        "incomplete",
        "candidate_limit",
        "range",
        "claim_limit",
        "citation",
        "source",
        "blocks",
    ],
)
def test_mapping_when_edge_has_conservative_result_or_safe_error(text_pdf, case):
    # Given
    ctx, request, limits, expected = mapping_case(text_pdf, case)
    # When / Then
    if expected is None:
        with pytest.raises(EvidenceError):
            map_evidence(ctx, request, limits=limits)
    else:
        result = map_evidence(ctx, request, limits=limits)
        assert result.mapping.mapping_status == expected
        assert result.mapping.original_page_numbers is None
        if case == "incomplete":
            assert len(result.candidates) == 1
            assert result.reason_code == "incomplete_target_coverage"


@pytest.mark.parametrize("change", ["text", "page", "range"])
def test_identity_when_source_block_forged_cannot_verify(text_pdf, change):
    # Given
    target = original_target(text_pdf)
    source = document(text_pdf)
    block = source.blocks[0]
    if change == "text":
        block = block.model_copy(update={"raw_text": "fabricated"})
    elif change == "page":
        block = block.model_copy(
            update={
                "source_locator": block.source_locator.model_copy(
                    update={"original_page_number": 99}
                )
            }
        )
    else:
        block = block.model_copy(
            update={"raw_char_range": CharacterRange(start=1, end=len(block.raw_text) + 1)}
        )
    source = source.model_copy(update={"blocks": (block, *source.blocks[1:])})
    ctx = EvidenceMapContext(document=source, target=target)
    # When
    result = map_evidence(ctx, request_for(ctx))
    # Then
    assert result.mapping.mapping_status == "mismatch"
    assert result.mapping.original_page_numbers is None


def test_mapping_when_blank_page_interrupts_quote_does_not_join(text_pdf):
    # Given
    quote = document(text_pdf).blocks[0].raw_text
    ctx = synthetic_context(text_pdf, (quote[:2], quote[2:]))
    ctx = ctx.model_copy(
        update={
            "target": ctx.target.model_copy(
                update={
                    "pages": (
                        ArtifactPage(number=1, text=quote[:2]),
                        ArtifactPage(number=2, text="", status="text_unavailable"),
                        ArtifactPage(number=3, text=quote[2:]),
                    )
                }
            )
        }
    )
    # When
    result = map_evidence(ctx, request_for(ctx))
    # Then
    assert result.mapping.mapping_status == "unmapped"
    assert result.candidates == ()


def test_mapping_when_repeated_hint_matches_retains_ambiguity(text_pdf):
    # Given
    quote = document(text_pdf).blocks[0].raw_text
    ctx = synthetic_context(text_pdf, (quote, quote))
    request = request_for(ctx).model_copy(
        update={
            "expected_target_ranges": (
                ArtifactTextRange(
                    page_number=1, char_range=CharacterRange(start=0, end=len(quote))
                ),
            )
        }
    )
    # When
    result = map_evidence(ctx, request)
    # Then
    assert result.mapping.mapping_status == "ambiguous"
    assert len(result.candidates) == 2
