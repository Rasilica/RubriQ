import hashlib
import json
from collections.abc import Sequence
from typing import Final

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
    ReportCheckModelResponse,
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


IDENTITY_KEYS: Final = (
    "criteria_sha256",
    "report_source_id",
    "report_document_version_id",
    "report_source_sha256",
)


def _drop_identity(raw: str) -> str:
    """Old-style replies may still echo identity; the server's values replace them."""
    try:
        value = json.loads(raw)
    except ValueError:
        return raw  # the strict validator reports the malformed JSON
    if not isinstance(value, dict):
        return raw
    return json.dumps({k: v for k, v in value.items() if k not in IDENTITY_KEYS})


def parse_response(
    raw: str, limits: ReportCheckLimits, context: ReportCheckContext
) -> ReportCheckResponse:
    if len(raw) > limits.max_response_bytes:
        raise ReportCheckError(ReportCheckErrorCode.RESPONSE_LIMIT)
    try:
        size = len(raw.encode("utf-8"))
    except UnicodeEncodeError:
        raise ReportCheckError(ReportCheckErrorCode.INVALID_RESPONSE) from None
    if size > limits.max_response_bytes:
        raise ReportCheckError(ReportCheckErrorCode.RESPONSE_LIMIT)
    try:
        parsed = ReportCheckModelResponse.model_validate_json(_drop_identity(raw), strict=True)
    except ValidationError as error:
        diagnostics.contract_failure(ReportCheckErrorCode.INVALID_RESPONSE, "schema_invalid", error)
        raise ReportCheckError(ReportCheckErrorCode.INVALID_RESPONSE) from None
    source = context.report.source
    return ReportCheckResponse(
        criteria_sha256=criteria_fingerprint(context),
        report_source_id=source.source_id,
        report_document_version_id=source.document_version_id,
        report_source_sha256=source.content_sha256,
        **parsed.model_dump(),
    )


def submitted_report_block_ids(context: ReportCheckContext) -> tuple[str, ...]:
    return tuple(block.block_id for block in context.report.blocks if block.raw_text.strip())


def without_sent_figures(
    response: ReportCheckResponse, context: ReportCheckContext
) -> ReportCheckResponse:
    """Figure markers were sent but are never reviewed text; a model listing one is harmless."""
    figures = {block.block_id for block in context.report.blocks if block.kind == "figure"}
    kept = tuple(b for b in response.reviewed_block_ids if b not in figures)
    if len(kept) == len(response.reviewed_block_ids):
        return response
    return response.model_copy(update={"reviewed_block_ids": kept})


def with_cited_blocks_reviewed(
    response: ReportCheckResponse, submitted_ids: Sequence[str]
) -> ReportCheckResponse:
    """Citing a submitted block proves it was read; unsubmitted ids still fail the scope checks."""
    cited = {
        entry.citation.block_id
        for item in response.items
        for group in (item.evidence, *(sub.evidence for sub in item.subconditions))
        for entry in group
    }
    reviewed = response.reviewed_block_ids
    added = tuple(b for b in submitted_ids if b in cited and b not in reviewed)
    if not added:
        return response
    order = {block_id: index for index, block_id in enumerate(submitted_ids)}
    merged = sorted((*reviewed, *added), key=lambda b: order.get(b, len(order)))
    return response.model_copy(update={"reviewed_block_ids": tuple(merged)})


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
    submitted = set(submitted_report_block_ids(context))
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
