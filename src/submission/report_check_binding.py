from typing import assert_never

from submission.document_contracts import CommonDocument, ProcessingStatus
from submission.models import DocumentRole
from submission.report_check_contracts import (
    CriteriaContext,
    ReportCheckContext,
    ReportCheckError,
    ReportCheckErrorCode,
    ReportCheckLimits,
)
from submission.requirement_contracts import (
    DEFAULT_REQUIREMENT_LIMITS,
    CitationInput,
    RequirementLimits,
)
from submission.requirement_validation import admit_guide, sent_block_count, verify_citation
from submission.review_contracts import ReviewedItem


def validate_document(document: CommonDocument, limits: ReportCheckLimits) -> None:
    if (
        sent_block_count(document) > limits.max_blocks
        or sum(len(block.raw_text) for block in document.blocks) > limits.max_input_characters
    ):
        raise ReportCheckError(ReportCheckErrorCode.INPUT_LIMIT)
    ids = tuple(block.block_id for block in document.blocks)
    if len(set(ids)) != len(ids):
        raise ReportCheckError(ReportCheckErrorCode.INVALID_IDENTITY)
    if any(
        block.source_locator.source_sha256 != document.source.content_sha256
        for block in document.blocks
    ):
        raise ReportCheckError(ReportCheckErrorCode.SOURCE_MISMATCH)
    match document.extraction_status:
        case ProcessingStatus.COMPLETE | ProcessingStatus.PARTIAL:
            if not any(block.raw_text.strip() for block in document.blocks):
                raise ReportCheckError(ReportCheckErrorCode.INVALID_REPORT)
        case ProcessingStatus.FAILED | ProcessingStatus.UNSUPPORTED | ProcessingStatus.NOT_STARTED:
            raise ReportCheckError(ReportCheckErrorCode.INVALID_REPORT)
        case _:
            assert_never(document.extraction_status)


def validate_criterion(item: ReviewedItem) -> None:
    if not item.included and item.exclusion_reason is None:
        raise ReportCheckError(ReportCheckErrorCode.INVALID_CONTEXT)
    match item.classification:
        case "required" | "optional":
            if (
                item.condition_description is not None
                or item.application_status != "applies"
                or item.application_reason is not None
            ):
                raise ReportCheckError(ReportCheckErrorCode.INVALID_CONTEXT)
        case "conditional":
            if item.condition_description is None:
                raise ReportCheckError(ReportCheckErrorCode.INVALID_CONTEXT)
            match item.application_status:
                case "applies" | "does_not_apply":
                    if item.application_reason is None:
                        raise ReportCheckError(ReportCheckErrorCode.INVALID_CONTEXT)
                case "undetermined":
                    if item.included:
                        raise ReportCheckError(ReportCheckErrorCode.INVALID_CONTEXT)
                case _:
                    assert_never(item.application_status)
        case _:
            assert_never(item.classification)


def validate_binding(context: ReportCheckContext, limits: ReportCheckLimits) -> None:
    validate_context_budget(context, limits)
    validate_criteria_binding(context, limits)
    validate_document(context.report, limits)
    match context.report.source.role:
        case DocumentRole.REPORT:
            pass
        case DocumentRole.GUIDE:
            raise ReportCheckError(ReportCheckErrorCode.INVALID_REPORT)
        case _:
            assert_never(context.report.source.role)


def validate_criteria_binding(context: CriteriaContext, limits: ReportCheckLimits) -> None:
    if (
        len(context.criteria.items) > DEFAULT_REQUIREMENT_LIMITS.max_requirements
        or len(context.original_draft.requirements) > DEFAULT_REQUIREMENT_LIMITS.max_requirements
    ):
        raise ReportCheckError(ReportCheckErrorCode.INPUT_LIMIT)
    guide, draft, criteria = context.guide, context.original_draft, context.criteria
    _ = admit_guide(
        guide,
        RequirementLimits(
            max_blocks=limits.max_blocks, max_input_characters=limits.max_input_characters
        ),
    )
    validate_document(guide, limits)
    if (
        draft.source_id != guide.source.source_id
        or draft.document_version_id != guide.source.document_version_id
        or draft.source_sha256 != guide.source.content_sha256
        or criteria.document_version_id != draft.document_version_id
        or criteria.source_sha256 != draft.source_sha256
    ):
        raise ReportCheckError(ReportCheckErrorCode.SOURCE_MISMATCH)
    if (
        criteria.version < 1
        or criteria.revision < 0
        or not any(item.included for item in criteria.items)
    ):
        raise ReportCheckError(ReportCheckErrorCode.INVALID_CONTEXT)
    ids = tuple(item.requirement_id for item in draft.requirements) + tuple(
        sub.subcondition_id for item in draft.requirements for sub in item.subconditions
    )
    if len(ids) != len(set(ids)) or tuple(item.requirement_id for item in criteria.items) != tuple(
        item.requirement_id for item in draft.requirements
    ):
        raise ReportCheckError(ReportCheckErrorCode.INVALID_IDENTITY)
    validate_originals(context)


def validate_originals(context: CriteriaContext) -> None:
    guide, draft, criteria = context.guide, context.original_draft, context.criteria
    for original, criterion in zip(draft.requirements, criteria.items, strict=True):
        validate_criterion(criterion)
        if tuple(sub.subcondition_id for sub in original.subconditions) != tuple(
            sub.subcondition_id for sub in criterion.subconditions
        ):
            raise ReportCheckError(ReportCheckErrorCode.INVALID_IDENTITY)
        citations = original.citations + tuple(
            cite for sub in original.subconditions for cite in sub.citations
        )
        if original.condition is not None:
            citations += original.condition.citations
        for citation in citations:
            verified = verify_citation(
                CitationInput(
                    block_id=citation.block_id, char_range=citation.char_range, quote=citation.quote
                ),
                guide.blocks,
            )
            if verified != citation:
                raise ReportCheckError(ReportCheckErrorCode.INVALID_CITATION)


def criteria_budget_size(context: CriteriaContext) -> int:
    """Characters of guide text, criteria and original requirements counted by the budget."""
    source_size = sum(len(block.raw_text) for block in context.guide.blocks)
    criteria_size = sum(
        len(item.title)
        + len(item.condition_description or "")
        + len(item.exclusion_reason or "")
        + len(item.application_reason or "")
        + sum(len(sub.description) for sub in item.subconditions)
        for item in context.criteria.items
    )
    original_size = sum(
        len(item.title)
        + sum(len(sub.description) for sub in item.subconditions)
        + (len(item.condition.description) if item.condition else 0)
        for item in context.original_draft.requirements
    )
    return source_size + criteria_size + original_size


def validate_context_budget(context: ReportCheckContext, limits: ReportCheckLimits) -> None:
    report_size = sum(len(block.raw_text) for block in context.report.blocks)
    if criteria_budget_size(context) + report_size > limits.max_input_characters:
        raise ReportCheckError(ReportCheckErrorCode.INPUT_LIMIT)
