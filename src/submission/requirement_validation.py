from typing import Literal, assert_never

from submission import semantic_diagnostics as diagnostics
from submission.document_contracts import CommonDocument, DocumentBlock, ProcessingStatus
from submission.models import DocumentRole
from submission.requirement_contracts import (
    CitationInput,
    CitedText,
    RequestBlock,
    RequirementError,
    RequirementErrorCode,
    RequirementInput,
    RequirementItem,
    RequirementLimits,
    RequirementResponse,
    Subcondition,
    VerifiedCitation,
)


def response_failure(
    code: RequirementErrorCode,
    branch: diagnostics.ContractBranch,
    count: int | None = None,
    limit: int | None = None,
) -> RequirementError:
    """Record the fixed branch (and integer count/limit only) for a model-response violation."""
    diagnostics.contract_failure(code, branch, count=count, limit=limit)
    return RequirementError(code)


SENT_KINDS = {"figure": "figure", "ocr_line": "ocr"}  # payload kind per marked block kind


def is_sent(block: DocumentBlock) -> bool:
    """Blank blocks are skipped; a figure marker is sent even though it has no text."""
    return bool(block.raw_text.strip()) or block.kind == "figure"


def request_blocks(document: CommonDocument) -> tuple[RequestBlock, ...]:
    return tuple(
        RequestBlock(
            block_id=block.block_id,
            raw_text=block.raw_text,
            kind=SENT_KINDS.get(block.kind),
        )
        for block in document.blocks
        if is_sent(block)
    )


def sent_block_count(document: CommonDocument) -> int:
    """Blocks the adapters actually send to the AI, figure markers included."""
    return sum(1 for block in document.blocks if is_sent(block))


def admit_guide(
    document: CommonDocument, limits: RequirementLimits
) -> Literal["complete", "partial"]:
    match document.source.role:
        case DocumentRole.GUIDE:
            pass
        case DocumentRole.REPORT:
            raise RequirementError(RequirementErrorCode.INVALID_GUIDE)
        case _:
            assert_never(document.source.role)
    match document.extraction_status:
        case ProcessingStatus.COMPLETE:
            status = "complete"
        case ProcessingStatus.PARTIAL:
            status = "partial"
        case ProcessingStatus.FAILED | ProcessingStatus.UNSUPPORTED | ProcessingStatus.NOT_STARTED:
            raise RequirementError(RequirementErrorCode.INVALID_GUIDE)
        case _:
            assert_never(document.extraction_status)
    if not any(block.raw_text.strip() for block in document.blocks):
        raise RequirementError(RequirementErrorCode.INVALID_GUIDE)
    if (
        sent_block_count(document) > limits.max_blocks
        or sum(len(block.raw_text) for block in document.blocks) > limits.max_input_characters
    ):
        raise RequirementError(RequirementErrorCode.INPUT_LIMIT)
    identifiers = tuple(block.block_id for block in document.blocks)
    if len(set(identifiers)) != len(identifiers):
        raise RequirementError(RequirementErrorCode.DUPLICATE_ID)
    if any(
        block.source_locator.source_sha256 != document.source.content_sha256
        for block in document.blocks
    ):
        raise RequirementError(RequirementErrorCode.SOURCE_MISMATCH)
    return status


def validate_items(response: RequirementResponse, limits: RequirementLimits) -> None:
    identifiers = tuple(item.requirement_id for item in response.requirements) + tuple(
        sub.subcondition_id for item in response.requirements for sub in item.subconditions
    )
    if len(set(identifiers)) != len(identifiers):
        raise response_failure(RequirementErrorCode.DUPLICATE_ID, "requirement_id_duplicate")
    if len(response.requirements) > limits.max_requirements:
        raise response_failure(
            RequirementErrorCode.RESPONSE_LIMIT,
            "requirement_count",
            len(response.requirements),
            limits.max_requirements,
        )
    most_subconditions = max((len(item.subconditions) for item in response.requirements), default=0)
    if most_subconditions > limits.max_subconditions:
        raise response_failure(
            RequirementErrorCode.RESPONSE_LIMIT,
            "subcondition_count",
            most_subconditions,
            limits.max_subconditions,
        )
    for item in response.requirements:
        validate_cited_text(CitedText(description=item.title, citations=item.citations), limits)
        for sub in item.subconditions:
            validate_cited_text(sub, limits)
        if item.condition is not None:
            validate_cited_text(item.condition, limits)


def validate_cited_text(value: CitedText[CitationInput], limits: RequirementLimits) -> None:
    longest_quote = max((len(cite.quote) for cite in value.citations), default=0)
    checks: tuple[tuple[diagnostics.ContractBranch, int, int], ...] = (
        ("requirement_text_length", len(value.description), limits.max_text_characters),
        ("requirement_citation_count", len(value.citations), limits.max_citations),
        ("requirement_quote_length", longest_quote, limits.max_quote_characters),
    )
    for branch, count, limit in checks:
        if count > limit:
            raise response_failure(RequirementErrorCode.RESPONSE_LIMIT, branch, count, limit)


def verify_citation(citation: CitationInput, blocks: tuple[DocumentBlock, ...]) -> VerifiedCitation:
    block = next((block for block in blocks if block.block_id == citation.block_id), None)
    if block is None:
        raise RequirementError(RequirementErrorCode.INVALID_CITATION)
    start, end = citation.char_range.start, citation.char_range.end
    if not 0 <= start < end <= len(block.raw_text) or block.raw_text[start:end] != citation.quote:
        raise RequirementError(RequirementErrorCode.INVALID_CITATION)
    return VerifiedCitation(
        block_id=block.block_id,
        char_range=citation.char_range,
        quote=citation.quote,
        source_locator=block.source_locator,
        from_ocr=block.kind == "ocr_line",
    )


def verify_response_citation(
    citation: CitationInput, blocks: tuple[DocumentBlock, ...]
) -> VerifiedCitation:
    try:
        return verify_citation(citation, blocks)
    except RequirementError:
        raise response_failure(
            RequirementErrorCode.INVALID_CITATION, citation_failure_branch(citation, blocks)
        ) from None


def citation_failure_branch(
    citation: CitationInput, blocks: tuple[DocumentBlock, ...]
) -> diagnostics.ContractBranch:
    block = next((block for block in blocks if block.block_id == citation.block_id), None)
    if block is None:
        return "citation_block_missing"
    start, end = citation.char_range.start, citation.char_range.end
    return (
        "citation_range_invalid"
        if not 0 <= start < end <= len(block.raw_text)
        else "citation_quote_mismatch"
    )


def resolve_item(item: RequirementInput, blocks: tuple[DocumentBlock, ...]) -> RequirementItem:
    condition = None
    if item.condition is not None:
        condition = CitedText[VerifiedCitation](
            description=item.condition.description,
            citations=tuple(
                verify_response_citation(cite, blocks) for cite in item.condition.citations
            ),
        )
    return RequirementItem(
        requirement_id=item.requirement_id,
        title=item.title,
        classification=item.classification,
        condition=condition,
        citations=tuple(verify_response_citation(cite, blocks) for cite in item.citations),
        subconditions=tuple(
            Subcondition[VerifiedCitation](
                subcondition_id=sub.subcondition_id,
                description=sub.description,
                citations=tuple(verify_response_citation(cite, blocks) for cite in sub.citations),
            )
            for sub in item.subconditions
        ),
    )
