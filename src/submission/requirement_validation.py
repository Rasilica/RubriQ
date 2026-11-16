from typing import Literal, assert_never

from submission.document_contracts import CommonDocument, DocumentBlock, ProcessingStatus
from submission.models import DocumentRole
from submission.requirement_contracts import (
    CitationInput,
    CitedText,
    RequirementError,
    RequirementErrorCode,
    RequirementInput,
    RequirementItem,
    RequirementLimits,
    RequirementResponse,
    Subcondition,
    VerifiedCitation,
)


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
        len(document.blocks) > limits.max_blocks
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


def validate_response_identity(document: CommonDocument, response: RequirementResponse) -> None:
    if (
        response.source_id != document.source.source_id
        or response.document_version_id != document.source.document_version_id
        or response.source_sha256 != document.source.content_sha256
    ):
        raise RequirementError(RequirementErrorCode.SOURCE_MISMATCH)


def validate_items(response: RequirementResponse, limits: RequirementLimits) -> None:
    identifiers = tuple(item.requirement_id for item in response.requirements) + tuple(
        sub.subcondition_id for item in response.requirements for sub in item.subconditions
    )
    if len(set(identifiers)) != len(identifiers):
        raise RequirementError(RequirementErrorCode.DUPLICATE_ID)
    if len(response.requirements) > limits.max_requirements or any(
        len(item.subconditions) > limits.max_subconditions for item in response.requirements
    ):
        raise RequirementError(RequirementErrorCode.RESPONSE_LIMIT)
    for item in response.requirements:
        validate_cited_text(CitedText(description=item.title, citations=item.citations), limits)
        for sub in item.subconditions:
            validate_cited_text(sub, limits)
        if item.condition is not None:
            validate_cited_text(item.condition, limits)


def validate_cited_text(value: CitedText[CitationInput], limits: RequirementLimits) -> None:
    if (
        len(value.description) > limits.max_text_characters
        or len(value.citations) > limits.max_citations
        or any(len(cite.quote) > limits.max_quote_characters for cite in value.citations)
    ):
        raise RequirementError(RequirementErrorCode.RESPONSE_LIMIT)


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
    )


def resolve_item(item: RequirementInput, blocks: tuple[DocumentBlock, ...]) -> RequirementItem:
    condition = None
    if item.condition is not None:
        condition = CitedText[VerifiedCitation](
            description=item.condition.description,
            citations=tuple(verify_citation(cite, blocks) for cite in item.condition.citations),
        )
    return RequirementItem(
        requirement_id=item.requirement_id,
        title=item.title,
        classification=item.classification,
        condition=condition,
        citations=tuple(verify_citation(cite, blocks) for cite in item.citations),
        subconditions=tuple(
            Subcondition[VerifiedCitation](
                subcondition_id=sub.subcondition_id,
                description=sub.description,
                citations=tuple(verify_citation(cite, blocks) for cite in sub.citations),
            )
            for sub in item.subconditions
        ),
    )
