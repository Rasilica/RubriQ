from hashlib import sha256
from io import BytesIO

import pytest
from evidence_helpers import document, request_for
from reportlab.pdfgen.canvas import Canvas

from submission.document_contracts import (
    ArtifactId,
    ArtifactTextRange,
    CharacterRange,
    DocumentArtifact,
)
from submission.evidence_anchors import find_candidates
from submission.evidence_artifacts import inspect_artifact
from submission.evidence_contracts import (
    ArtifactBinding,
    ArtifactPage,
    EvidenceError,
    EvidenceLimits,
    EvidenceMapContext,
    PdfArtifactInput,
)
from submission.evidence_mapping import map_evidence
from submission.models import DocumentRole, PdfInput


def real_context(text_pdf, lines):
    source = document(text_pdf)
    buffer = BytesIO()
    canvas = Canvas(buffer)
    for index, line in enumerate(lines):
        canvas.drawString(72, 720 - index * 20, line)
    canvas.save()
    content = buffer.getvalue()
    artifact = DocumentArtifact(
        artifact_id=ArtifactId("preview"),
        artifact_sha256=sha256(content).hexdigest(),
        kind="preview_pdf",
        parent_source_id=source.source.source_id,
    )
    return EvidenceMapContext(
        document=source,
        target=PdfArtifactInput(
            binding=ArtifactBinding(source=source.source, artifact=artifact),
            pdf=PdfInput("preview.pdf", content, DocumentRole.REPORT),
        ),
    )


def test_real_pdf_layout_anchor_preserves_raw_ranges(text_pdf):
    # Given
    ctx = real_context(text_pdf, ["Purpose: help stu", "dents check requirements."])
    # When
    result = map_evidence(ctx, request_for(ctx))
    # Then
    assert result.reason_code == "layout_whitespace_anchor"
    assert result.mapping.verification_method == "ascii_layout_whitespace_anchor"
    assert result.mapping.original_page_numbers is None
    assert result.original_layout_verified is False
    assert result.mapping.target_text_ranges == (
        ArtifactTextRange(page_number=1, char_range=CharacterRange(start=0, end=43)),
    )


@pytest.mark.parametrize("claim_index", [None, 0, 1])
def test_real_pdf_counts_exact_and_layout_alternative(
    text_pdf: bytes, claim_index: int | None
) -> None:
    # Given
    ctx = real_context(
        text_pdf,
        [
            "Purpose: help students check requirements.",
            "Purpose: help stu",
            "dents check requirements.",
        ],
    )
    request = request_for(ctx)
    if claim_index is not None:
        text = inspect_artifact(ctx.target).pages[0].text
        start = 0 if claim_index == 0 else text.index("Purpose:", 1)
        end = text.index(".", start) + 1
        request = request.model_copy(
            update={
                "expected_target_ranges": (
                    ArtifactTextRange(
                        page_number=1,
                        char_range=CharacterRange(start=start, end=end),
                    ),
                )
            }
        )
    # When
    result = map_evidence(ctx, request)
    # Then
    assert result.mapping.mapping_status == "ambiguous"
    assert result.reason_code == "repeated_anchor"
    assert result.mapping.target_text_ranges == ()
    assert len(result.candidates) == 2


@pytest.mark.parametrize("forged", [False, True])
def test_real_pdf_layout_claim_revalidated(text_pdf, forged):
    # Given
    ctx = real_context(text_pdf, ["Purpose: help stu", "dents check requirements."])
    request = request_for(ctx).model_copy(
        update={
            "expected_target_ranges": (
                ArtifactTextRange(
                    page_number=1, char_range=CharacterRange(start=int(forged), end=43)
                ),
            )
        }
    )
    # When
    result = map_evidence(ctx, request)
    # Then
    assert result.mapping.mapping_status == ("mismatch" if forged else "verified_anchor")


@pytest.mark.parametrize(
    ("quote", "text"),
    [
        ("abcdefgh", "abcd\nefgh"),
        ("abcdefgh", "a b\tc\rd\ne\ffgh"),
        ("abcdefgh", "abcd\u00a0efgh"),
        ("abcdefgh", "Abcdefgh"),
        ("abcdefgh", "abcd-efgh"),
        ("abcdefg", "abc\ndefg"),
    ],
)
def test_layout_candidates_only_ascii_whitespace_with_minimum(quote, text):
    # Given
    pages = (ArtifactPage(number=1, text=text),)
    # When
    candidates = find_candidates(pages, quote, EvidenceLimits(), whitespace_layout=True)
    # Then
    assert bool(candidates) == (text in ("abcd\nefgh", "a b\tc\rd\ne\ffgh"))


def test_layout_candidates_count_overlaps_with_original_ranges() -> None:
    # Given
    pages = (ArtifactPage(number=1, text="aaaa aaaaa"),)
    # When
    candidates = find_candidates(
        pages, "aaaaaaaa", EvidenceLimits(max_candidates=2), whitespace_layout=True
    )
    # Then
    assert len(candidates) == 2
    assert candidates == (
        (ArtifactTextRange(page_number=1, char_range=CharacterRange(start=0, end=9)),),
        (ArtifactTextRange(page_number=1, char_range=CharacterRange(start=1, end=10)),),
    )
    assert tuple(
        pages[0].text[candidate[0].char_range.start : candidate[0].char_range.end]
        for candidate in candidates
    ) == ("aaaa aaaa", "aaa aaaaa")


def test_layout_candidates_enforce_limit_for_overlaps() -> None:
    # Given
    pages = (ArtifactPage(number=1, text="aaaa aaaaa"),)
    # When / Then
    with pytest.raises(EvidenceError, match="candidate_limit"):
        find_candidates(pages, "aaaaaaaa", EvidenceLimits(max_candidates=1), whitespace_layout=True)


def test_layout_candidates_do_not_bridge_unreadable_page():
    # Given
    pages = (
        ArtifactPage(number=1, text="abcd"),
        ArtifactPage(number=2, text="", status="text_unavailable"),
        ArtifactPage(number=3, text="efgh"),
    )
    # When
    candidates = find_candidates(pages, "abcdefgh", EvidenceLimits(), whitespace_layout=True)
    # Then
    assert candidates == ()


@pytest.mark.parametrize("layout", [False, True])
def test_layout_claim_cannot_skip_nonwhitespace_content(text_pdf: bytes, *, layout: bool) -> None:
    # Given
    ctx = real_context(
        text_pdf,
        [
            "Purpose: help stu dents check requirements."
            if layout
            else "Purpose: help students check requirements.",
            "Purpose: help stuXXXdents check requirements.",
        ],
    )
    text = inspect_artifact(ctx.target).pages[0].text
    start = text.index("Purpose:", 1)
    gap = text.index("XXX")
    request = request_for(ctx).model_copy(
        update={
            "expected_target_ranges": (
                ArtifactTextRange(page_number=1, char_range=CharacterRange(start=start, end=gap)),
                ArtifactTextRange(
                    page_number=1, char_range=CharacterRange(start=gap + 3, end=len(text.rstrip()))
                ),
            )
        }
    )
    # When
    result = map_evidence(ctx, request)
    # Then
    assert result.mapping.mapping_status == "mismatch"


@pytest.mark.parametrize("expanded", [False, True])
def test_layout_claim_requires_candidate_coordinates_with_equivalent_splits(
    text_pdf: bytes, *, expanded: bool
) -> None:
    # Given
    ctx = real_context(text_pdf, ["prefix Purpose: help stu", "dents check requirements. suffix"])
    text = inspect_artifact(ctx.target).pages[0].text
    start = text.index("Purpose:")
    end = text.index(".") + 1
    request = request_for(ctx).model_copy(
        update={
            "expected_target_ranges": (
                ArtifactTextRange(
                    page_number=1,
                    char_range=CharacterRange(start=start - int(expanded), end=start + 10),
                ),
                ArtifactTextRange(
                    page_number=1,
                    char_range=CharacterRange(start=start + 10, end=end + int(expanded)),
                ),
            )
        }
    )
    # When
    result = map_evidence(ctx, request)
    # Then
    assert result.mapping.mapping_status == ("mismatch" if expanded else "verified_anchor")


def test_layout_candidate_crosses_readable_pages_with_original_coordinates():
    # Given
    pages = (
        ArtifactPage(number=1, text="prefix abcd\n"),
        ArtifactPage(number=2, text="\tefgh suffix"),
    )
    # When
    candidates = find_candidates(pages, "abcdefgh", EvidenceLimits(), whitespace_layout=True)
    # Then
    assert candidates == (
        (
            ArtifactTextRange(page_number=1, char_range=CharacterRange(start=7, end=12)),
            ArtifactTextRange(page_number=2, char_range=CharacterRange(start=0, end=5)),
        ),
    )


def test_layout_anchor_does_not_relax_source_citation(text_pdf):
    # Given
    ctx = real_context(text_pdf, ["Purpose: help stu", "dents check requirements."])
    request = request_for(ctx)
    request = request.model_copy(
        update={
            "citation": request.citation.model_copy(
                update={"quote": request.citation.quote.replace("students", "stu dents")}
            )
        }
    )
    # When / Then
    with pytest.raises(EvidenceError, match="invalid_citation"):
        map_evidence(ctx, request)
