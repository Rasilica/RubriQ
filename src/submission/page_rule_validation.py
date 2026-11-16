from typing import assert_never

from pydantic import TypeAdapter, ValidationError

from submission.evidence_artifacts import strict_model
from submission.evidence_boundary import (
    reject_extra_fields,
    validate_document_models,
    validate_target_models,
)
from submission.evidence_contracts import (
    ArtifactBinding,
    ArtifactInput,
    EvidenceError,
    EvidenceLimits,
    PdfArtifactInput,
    SyntheticArtifactInput,
)
from submission.models import DocumentRole
from submission.page_rule_contracts import (
    PageRuleError,
    PageRuleErrorCode,
    PageRuleInput,
    SubmissionCheckLimits,
)
from submission.report_check_contracts import (
    ReportCheckContext,
    ReportCheckError,
    ReportCheckLimits,
)
from submission.report_check_validation import criteria_fingerprint, validate_context
from submission.requirement_contracts import RequirementItem


def validate_original_item(item: RequirementItem) -> None:
    reject_extra_fields(item)
    cited = (*item.subconditions, *((item.condition,) if item.condition else ()))
    for child in cited:
        reject_extra_fields(child)
    citations = item.citations + tuple(cite for child in cited for cite in child.citations)
    for citation in citations:
        reject_extra_fields(citation)
        reject_extra_fields(citation.char_range)
        reject_extra_fields(citation.source_locator)


def admit_rule_context(
    context: ReportCheckContext, limits: SubmissionCheckLimits
) -> ReportCheckContext:
    try:
        context = TypeAdapter(ReportCheckContext).validate_python(context, strict=True)
        limits = admit_limits(limits)
        parsed = strict_model(context)
        validate_document_models(context.guide)
        validate_document_models(context.report)
        reject_extra_fields(context.original_draft)
        reject_extra_fields(context.criteria)
        for item in context.original_draft.requirements:
            validate_original_item(item)
        for item in context.criteria.items:
            reject_extra_fields(item)
            for sub in item.subconditions:
                reject_extra_fields(sub)
        validate_context(parsed, limits.report_limits)
        _ = criteria_fingerprint(parsed)
    except (EvidenceError, ReportCheckError, ValidationError):
        raise PageRuleError(PageRuleErrorCode.INVALID_INPUT) from None
    return parsed


def admit_limits(value: SubmissionCheckLimits) -> SubmissionCheckLimits:
    try:
        value = TypeAdapter(SubmissionCheckLimits).validate_python(value, strict=True)
        _ = TypeAdapter(ReportCheckLimits).validate_python(value.report_limits, strict=True)
        _ = TypeAdapter(EvidenceLimits).validate_python(value.evidence_limits, strict=True)
        parsed = strict_model(value)
        reject_extra_fields(value.report_limits)
        reject_extra_fields(value.evidence_limits)
    except (EvidenceError, ValidationError):
        raise PageRuleError(PageRuleErrorCode.INVALID_INPUT) from None
    return parsed


def admit_target(target: ArtifactInput) -> ArtifactInput:
    _ = TypeAdapter[ArtifactInput](ArtifactInput).validate_python(target, strict=True)
    match target:
        case PdfArtifactInput():
            _ = TypeAdapter(ArtifactBinding).validate_python(target.binding, strict=True)
            binding = strict_model(target.binding)
            validate_target_models(target)
            parsed = PdfArtifactInput.model_validate(
                {"binding": binding, "pdf": target.pdf, "origin": target.origin}, strict=True
            )
            _ = TypeAdapter(bytes).validate_python(parsed.pdf.content, strict=True)
            _ = TypeAdapter(str).validate_python(parsed.pdf.filename, strict=True)
            _ = TypeAdapter(DocumentRole).validate_python(parsed.pdf.role, strict=True)
            return parsed
        case SyntheticArtifactInput():
            parsed_synthetic = strict_model(target)
            validate_target_models(target)
            return parsed_synthetic
        case _:
            assert_never(target)


def admit_page_input(value: PageRuleInput) -> PageRuleInput:
    try:
        value = TypeAdapter(PageRuleInput).validate_python(value, strict=True)
        reject_extra_fields(value)
        parsed = PageRuleInput.model_validate(
            {**value.model_dump(exclude={"target"}, warnings=False), "target": value.target},
            strict=True,
        )
        if value.selection is not None:
            _ = strict_model(value.selection)
        target = admit_target(parsed.target) if parsed.target is not None else None
        return PageRuleInput(
            requirement_id=parsed.requirement_id, selection=parsed.selection, target=target
        )
    except (EvidenceError, ValidationError):
        raise PageRuleError(PageRuleErrorCode.INVALID_INPUT) from None


def validate_page_checks(values: tuple[PageRuleInput, ...], limits: SubmissionCheckLimits) -> None:
    if len(values) > limits.max_page_checks:
        raise PageRuleError(PageRuleErrorCode.INPUT_LIMIT)
    ids = tuple(item.requirement_id for item in values)
    if len(ids) != len(set(ids)):
        raise PageRuleError(PageRuleErrorCode.DUPLICATE_REQUIREMENT)
    byte_count, character_count = 0, 0
    for value in values:
        match value.target:
            case PdfArtifactInput():
                byte_count += len(value.target.pdf.content)
            case SyntheticArtifactInput():
                character_count += sum(len(page.text) for page in value.target.pages)
            case None:
                pass
            case _:
                assert_never(value.target)
    if (
        byte_count > limits.max_total_target_bytes
        or character_count > limits.max_total_target_characters
    ):
        raise PageRuleError(PageRuleErrorCode.INPUT_LIMIT)
