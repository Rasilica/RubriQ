import hashlib
import json

from pydantic import ValidationError
from pydantic_core import PydanticSerializationError

from submission import semantic_diagnostics as diagnostics
from submission.document_contracts import ContractError
from submission.report_check_binding import validate_binding, validate_criteria_binding
from submission.report_check_contracts import (
    CriteriaContext,
    ReportCheckContext,
    ReportCheckError,
    ReportCheckErrorCode,
    ReportCheckLimits,
    ReportCheckResponse,
    ReportEvidence,
)
from submission.report_check_results import VerifiedReportEvidence
from submission.requirement_contracts import RequirementError
from submission.requirement_validation import verify_citation


def criteria_fingerprint(context: CriteriaContext) -> str:
    canonical = json.dumps(
        {
            "guide_source_id": context.guide.source.source_id,
            "original_draft": context.original_draft.model_dump(mode="json"),
            "criteria": context.criteria.model_dump(mode="json"),
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    try:
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    except UnicodeEncodeError:
        raise ReportCheckError(ReportCheckErrorCode.INVALID_CONTEXT) from None


def validate_context(context: ReportCheckContext, limits: ReportCheckLimits) -> None:
    try:
        _ = ReportCheckContext.model_validate(
            context.model_dump(exclude_computed_fields=True), strict=True
        )
        validate_binding(context, limits)
    except (ValidationError, PydanticSerializationError, ContractError):
        raise ReportCheckError(ReportCheckErrorCode.INVALID_CONTEXT) from None
    except RequirementError:
        raise ReportCheckError(ReportCheckErrorCode.INVALID_CONTEXT) from None


def validate_criteria_context(context: CriteriaContext, limits: ReportCheckLimits) -> None:
    try:
        _ = CriteriaContext.model_validate(
            context.model_dump(exclude_computed_fields=True), strict=True
        )
        validate_criteria_binding(context, limits)
    except (ValidationError, PydanticSerializationError, ContractError, RequirementError):
        raise ReportCheckError(ReportCheckErrorCode.INVALID_CONTEXT) from None


def parse_response(raw: str, limits: ReportCheckLimits) -> ReportCheckResponse:
    if len(raw) > limits.max_response_bytes:
        raise ReportCheckError(ReportCheckErrorCode.RESPONSE_LIMIT)
    try:
        size = len(raw.encode("utf-8"))
    except UnicodeEncodeError:
        raise ReportCheckError(ReportCheckErrorCode.INVALID_RESPONSE) from None
    if size > limits.max_response_bytes:
        raise ReportCheckError(ReportCheckErrorCode.RESPONSE_LIMIT)
    try:
        return ReportCheckResponse.model_validate_json(raw, strict=True)
    except ValidationError as error:
        diagnostics.contract_failure(ReportCheckErrorCode.INVALID_RESPONSE, "schema_invalid", error)
        raise ReportCheckError(ReportCheckErrorCode.INVALID_RESPONSE) from None


def validate_response(context: ReportCheckContext, response: ReportCheckResponse) -> None:
    source = context.report.source
    if (
        response.report_source_id != source.source_id
        or response.report_document_version_id != source.document_version_id
        or response.report_source_sha256 != source.content_sha256
    ):
        diagnostics.contract_failure(ReportCheckErrorCode.SOURCE_MISMATCH, "source_binding")
        raise ReportCheckError(ReportCheckErrorCode.SOURCE_MISMATCH)
    if response.criteria_sha256 != criteria_fingerprint(context):
        diagnostics.contract_failure(ReportCheckErrorCode.CRITERIA_MISMATCH, "criteria_binding")
        raise ReportCheckError(ReportCheckErrorCode.CRITERIA_MISMATCH)
    submitted = {block.block_id for block in context.report.blocks if block.raw_text.strip()}
    if len(set(response.reviewed_block_ids)) != len(response.reviewed_block_ids):
        diagnostics.contract_failure(ReportCheckErrorCode.INVALID_SCOPE, "scope_duplicate")
        raise ReportCheckError(ReportCheckErrorCode.INVALID_SCOPE)
    if not set(response.reviewed_block_ids) <= submitted:
        diagnostics.contract_failure(ReportCheckErrorCode.INVALID_SCOPE, "scope_unsubmitted")
        raise ReportCheckError(ReportCheckErrorCode.INVALID_SCOPE)
    applicable = tuple(
        item
        for item in context.criteria.items
        if item.included and item.application_status == "applies"
    )
    if tuple(item.requirement_id for item in response.items) != tuple(
        item.requirement_id for item in applicable
    ):
        diagnostics.contract_failure(ReportCheckErrorCode.INVALID_IDENTITY, "identity_items")
        raise ReportCheckError(ReportCheckErrorCode.INVALID_IDENTITY)
    for proposed, criterion in zip(response.items, applicable, strict=True):
        if tuple(sub.subcondition_id for sub in proposed.subconditions) != tuple(
            sub.subcondition_id for sub in criterion.subconditions
        ):
            diagnostics.contract_failure(
                ReportCheckErrorCode.INVALID_IDENTITY, "identity_subconditions"
            )
            raise ReportCheckError(ReportCheckErrorCode.INVALID_IDENTITY)
        citations = proposed.evidence + tuple(
            cite for sub in proposed.subconditions for cite in sub.evidence
        )
        if any(
            evidence.citation.block_id not in response.reviewed_block_ids for evidence in citations
        ):
            diagnostics.contract_failure(
                ReportCheckErrorCode.INVALID_SCOPE, "scope_cite_unreviewed"
            )
            raise ReportCheckError(ReportCheckErrorCode.INVALID_SCOPE)


def verify_evidence(
    evidence: ReportEvidence, context: ReportCheckContext
) -> VerifiedReportEvidence:
    try:
        citation = verify_citation(evidence.citation, context.report.blocks)
    except RequirementError:
        diagnostics.contract_failure(
            ReportCheckErrorCode.INVALID_CITATION, _citation_failure_branch(evidence, context)
        )
        raise ReportCheckError(ReportCheckErrorCode.INVALID_CITATION) from None
    return VerifiedReportEvidence(
        citation=citation, evidence_role=evidence.evidence_role, relation=evidence.relation
    )


def _citation_failure_branch(
    evidence: ReportEvidence, context: ReportCheckContext
) -> diagnostics.ContractBranch:
    citation = evidence.citation
    block = next(
        (block for block in context.report.blocks if block.block_id == citation.block_id), None
    )
    if block is None:
        return "citation_block_missing"
    start, end = citation.char_range.start, citation.char_range.end
    if not 0 <= start < end <= len(block.raw_text):
        return "citation_range_invalid"
    if block.raw_text[start:end] != citation.quote:
        return "citation_quote_mismatch"
    return "citation_quote"
