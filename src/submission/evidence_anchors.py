from typing import Final, assert_never

from submission.document_contracts import ArtifactTextRange, CharacterRange
from submission.evidence_contracts import (
    ArtifactPage,
    EvidenceError,
    EvidenceErrorCode,
    EvidenceLimits,
)

ASCII_LAYOUT_WHITESPACE: Final = " \t\r\n\f"
MIN_LAYOUT_ANCHOR_CHARACTERS: Final = 8


def layout_text(text: str) -> str:
    return text.translate(str.maketrans("", "", ASCII_LAYOUT_WHITESPACE))


def validate_claims(
    claims: tuple[ArtifactTextRange, ...] | None,
    pages: tuple[ArtifactPage, ...],
    limits: EvidenceLimits,
) -> None:
    if claims is None:
        return
    if not claims or len(claims) > limits.max_claims:
        raise EvidenceError(EvidenceErrorCode.INPUT_LIMIT)
    previous = (0, 0)
    for claim in claims:
        if not 1 <= claim.page_number <= len(pages):
            raise EvidenceError(EvidenceErrorCode.INVALID_RANGE)
        start, end = claim.char_range.start, claim.char_range.end
        if (
            not 0 <= start < end <= len(pages[claim.page_number - 1].text)
            or (claim.page_number, start) < previous
        ):
            raise EvidenceError(EvidenceErrorCode.INVALID_RANGE)
        previous = (claim.page_number, end)


def page_segments(pages: tuple[ArtifactPage, ...]) -> tuple[tuple[ArtifactPage, ...], ...]:
    segments: list[tuple[ArtifactPage, ...]] = []
    current: tuple[ArtifactPage, ...] = ()
    for page in pages:
        match page.status:
            case "readable":
                current += (page,)
            case "text_unavailable" | "extraction_error":
                if current:
                    segments.append(current)
                    current = ()
            case _:
                assert_never(page.status)
    if current:
        segments.append(current)
    return tuple(segments)


def fragment_ranges(
    pages: tuple[ArtifactPage, ...], start: int, end: int
) -> tuple[ArtifactTextRange, ...]:
    ranges: list[ArtifactTextRange] = []
    offset = 0
    for page in pages:
        local_start, local_end = max(0, start - offset), min(len(page.text), end - offset)
        if local_start < local_end:
            ranges.append(
                ArtifactTextRange(
                    page_number=page.number,
                    char_range=CharacterRange(start=local_start, end=local_end),
                )
            )
        offset += len(page.text)
    return tuple(ranges)


def find_candidates(
    pages: tuple[ArtifactPage, ...],
    quote: str,
    limits: EvidenceLimits,
    *,
    whitespace_layout: bool = False,
) -> tuple[tuple[ArtifactTextRange, ...], ...]:
    normalized_quote = layout_text(quote)
    normalize = whitespace_layout and len(normalized_quote) >= MIN_LAYOUT_ANCHOR_CHARACTERS
    needle = normalized_quote if normalize else quote
    found: list[tuple[ArtifactTextRange, ...]] = []
    for segment in page_segments(pages):
        text = "".join(page.text for page in segment)
        offsets = (
            tuple(i for i, char in enumerate(text) if char not in ASCII_LAYOUT_WHITESPACE)
            if normalize
            else ()
        )
        searchable = layout_text(text) if normalize else text
        position = searchable.find(needle)
        while position >= 0:
            if len(found) >= limits.max_candidates:
                raise EvidenceError(EvidenceErrorCode.CANDIDATE_LIMIT)
            start = offsets[position] if normalize else position
            end = offsets[position + len(needle) - 1] + 1 if normalize else position + len(quote)
            if normalize:
                exact_start = start - (len(quote) - len(quote.lstrip(ASCII_LAYOUT_WHITESPACE)))
                if exact_start >= 0 and text[exact_start : exact_start + len(quote)] == quote:
                    start, end = exact_start, exact_start + len(quote)
            found.append(fragment_ranges(segment, start, end))
            position = searchable.find(needle, position + 1)
    return tuple(found)
