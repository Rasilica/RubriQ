from dataclasses import dataclass
from typing import Literal, assert_never

from submission.document_contracts import ArtifactTextRange, CharacterRange, EvidenceMapping
from submission.evidence_anchors import find_candidates, validate_claims
from submission.evidence_artifacts import inspect_artifact, strict_model
from submission.evidence_boundary import (
    reject_extra_fields,
    validate_document_models,
    validate_request_models,
)
from submission.evidence_contracts import (
    DEFAULT_EVIDENCE_LIMITS,
    ArtifactSnapshot,
    BoundEvidenceMapping,
    EvidenceError,
    EvidenceErrorCode,
    EvidenceLimits,
    EvidenceMapContext,
    EvidenceMapRequest,
)
from submission.requirement_contracts import RequirementError
from submission.requirement_validation import verify_citation


@dataclass(frozen=True, slots=True)
class MappingDecision:
    status: Literal["identity", "verified_anchor", "ambiguous", "unmapped", "mismatch"]
    reason: Literal[
        "exact_identity",
        "exact_anchor",
        "layout_whitespace_anchor",
        "repeated_anchor",
        "anchor_absent",
        "range_mismatch",
        "incomplete_target_coverage",
    ]
    ranges: tuple[ArtifactTextRange, ...] = ()


def identity_ranges(
    context: EvidenceMapContext, request: EvidenceMapRequest, snapshot: ArtifactSnapshot
) -> tuple[ArtifactTextRange, ...] | None:
    match snapshot.origin:
        case "synthetic":
            return None
        case "real_pdf":
            pass
        case _:
            assert_never(snapshot.origin)
    match context.target.binding.artifact.kind:
        case "preview_pdf":
            return None
        case "original_pdf":
            pass
        case _:
            assert_never(context.target.binding.artifact.kind)
    block = next(
        block for block in context.document.blocks if block.block_id == request.citation.block_id
    )
    page_number = block.source_locator.original_page_number
    if page_number is None or not 1 <= page_number <= len(snapshot.pages):
        return ()
    start = block.raw_char_range.start + request.citation.char_range.start
    end = block.raw_char_range.start + request.citation.char_range.end
    page = snapshot.pages[page_number - 1]
    if (
        block.raw_coordinate_basis != "extracted_page_unicode"
        or block.raw_char_range.end > len(page.text)
        or page.text[block.raw_char_range.start : block.raw_char_range.end] != block.raw_text
        or page.text[start:end] != request.citation.quote
    ):
        return ()
    return (
        ArtifactTextRange(page_number=page_number, char_range=CharacterRange(start=start, end=end)),
    )


def choose_mapping(
    candidates: tuple[tuple[ArtifactTextRange, ...], ...],
    request: EvidenceMapRequest,
    snapshot: ArtifactSnapshot,
) -> MappingDecision:
    ranges = candidates[0] if len(candidates) == 1 else ()
    whitespace_layout = bool(ranges) and range_text(ranges, snapshot) != request.citation.quote
    if not claims_match(request, candidates):
        return MappingDecision("mismatch", "range_mismatch")
    if snapshot.diagnostics:
        return MappingDecision("unmapped", "incomplete_target_coverage")
    if not candidates:
        return MappingDecision("unmapped", "anchor_absent")
    if len(candidates) > 1:
        return MappingDecision("ambiguous", "repeated_anchor")
    return MappingDecision(
        "verified_anchor",
        "layout_whitespace_anchor" if whitespace_layout else "exact_anchor",
        ranges,
    )


def range_text(ranges: tuple[ArtifactTextRange, ...], snapshot: ArtifactSnapshot) -> str:
    return "".join(
        snapshot.pages[item.page_number - 1].text[item.char_range.start : item.char_range.end]
        for item in ranges
    )


def coalesced_ranges(ranges: tuple[ArtifactTextRange, ...]) -> tuple[ArtifactTextRange, ...]:
    merged: tuple[ArtifactTextRange, ...] = ()
    for current in ranges:
        if (
            merged
            and merged[-1].page_number == current.page_number
            and merged[-1].char_range.end == current.char_range.start
        ):
            combined = ArtifactTextRange(
                page_number=current.page_number,
                char_range=CharacterRange(
                    start=merged[-1].char_range.start, end=current.char_range.end
                ),
            )
            merged = merged[:-1]
            merged += (combined,)
        else:
            merged += (current,)
    return merged


def claims_match(
    request: EvidenceMapRequest, candidates: tuple[tuple[ArtifactTextRange, ...], ...]
) -> bool:
    if request.expected_target_ranges is None:
        return True
    claims = coalesced_ranges(request.expected_target_ranges)
    return any(claims == coalesced_ranges(candidate) for candidate in candidates)


def map_evidence(
    context: EvidenceMapContext,
    request: EvidenceMapRequest,
    *,
    limits: EvidenceLimits = DEFAULT_EVIDENCE_LIMITS,
) -> BoundEvidenceMapping:
    reject_extra_fields(context)
    document = strict_model(context.document)
    checked_request = strict_model(request)
    limits = strict_model(limits)
    validate_document_models(context.document)
    validate_request_models(request)
    request = checked_request
    snapshot = inspect_artifact(context.target, limits=limits)
    if context.target.binding.source != document.source:
        raise EvidenceError(EvidenceErrorCode.SOURCE_MISMATCH)
    ids = tuple(block.block_id for block in document.blocks)
    if len(ids) != len(set(ids)) or any(
        block.source_locator.source_sha256 != document.source.content_sha256
        for block in document.blocks
    ):
        raise EvidenceError(EvidenceErrorCode.SOURCE_MISMATCH)
    if (
        len(document.blocks) > limits.max_blocks
        or sum(len(block.raw_text) for block in document.blocks) > limits.max_characters
    ):
        raise EvidenceError(EvidenceErrorCode.INPUT_LIMIT)
    try:
        citation = verify_citation(request.citation, document.blocks)
    except RequirementError:
        raise EvidenceError(EvidenceErrorCode.INVALID_CITATION) from None
    validate_claims(request.expected_target_ranges, snapshot.pages, limits)
    identity = identity_ranges(context, request, snapshot)
    candidates = (
        find_candidates(
            snapshot.pages, citation.quote, limits, whitespace_layout=snapshot.origin == "real_pdf"
        )
        if identity is None
        else ((identity,) if identity else ())
    )
    if identity is not None:
        agrees = claims_match(request, candidates)
        decision = (
            MappingDecision("identity", "exact_identity", identity)
            if identity and agrees
            else MappingDecision("mismatch", "range_mismatch")
        )
    else:
        decision = choose_mapping(candidates, request, snapshot)
    target_pages = tuple(dict.fromkeys(item.page_number for item in decision.ranges))
    match decision.status:
        case "identity":
            original_pages, method = target_pages, "same_source_artifact"
        case "verified_anchor":
            original_pages, method = (
                None,
                (
                    "ascii_layout_whitespace_anchor"
                    if decision.reason == "layout_whitespace_anchor"
                    else "exact_block_unicode_anchor"
                ),
            )
        case "ambiguous" | "unmapped" | "mismatch":
            original_pages, method = None, None
        case _:
            assert_never(decision.status)
    return BoundEvidenceMapping(
        binding_sha256=snapshot.binding_sha256,
        source_id=document.source.source_id,
        source_sha256=document.source.content_sha256,
        document_version_id=document.source.document_version_id,
        target_artifact_sha256=snapshot.target_sha256,
        snapshot_origin=snapshot.origin,
        source_locator=citation.source_locator,
        candidates=candidates,
        reason_code=decision.reason,
        mapping=EvidenceMapping(
            source_block_id=citation.block_id,
            source_char_range=citation.char_range,
            target_artifact_id=context.target.binding.artifact.artifact_id,
            target_page_numbers=target_pages,
            target_text_ranges=decision.ranges,
            original_page_numbers=original_pages,
            mapping_status=decision.status,
            verification_method=method,
        ),
    )
