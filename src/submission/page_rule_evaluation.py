from typing import Literal, assert_never

from submission.document_contracts import PageCountAssessment
from submission.evidence_contracts import EvidenceError, PageSelection
from submission.evidence_page_count import assess_page_count
from submission.page_rule_contracts import (
    DEFAULT_SUBMISSION_CHECK_LIMITS,
    DerivedPageRule,
    PageRuleError,
    PageRuleErrorCode,
    PageRuleInput,
    PageRuleResult,
    PageScopeResult,
    SubmissionCheckLimits,
)
from submission.page_rule_parser import derive_page_rule
from submission.page_rule_validation import (
    admit_limits,
    admit_page_input,
    admit_rule_context,
    validate_page_checks,
)
from submission.report_check_contracts import ReportCheckContext
from submission.review_contracts import ReviewedItem


def scope_results(
    criterion: ReviewedItem,
    verdict: Literal["compliant", "noncompliant", "deferred", "not_applicable"],
) -> tuple[PageScopeResult, ...]:
    match verdict:
        case "compliant" | "noncompliant":
            status, judgment, code = "verified", "evidence_found", "all_pdf_pages_verified"
        case "deferred":
            status, judgment, code = "deferred", "deferred", "page_rule_scope_unverified"
        case "not_applicable":
            status, judgment, code = "not_applicable", None, "criterion_not_applicable"
        case _:
            assert_never(verdict)
    return tuple(
        PageScopeResult(
            subcondition_id=sub.subcondition_id,
            status=status,
            effective_judgment=judgment,
            reason_codes=(code,),
        )
        for sub in criterion.subconditions
    )


def evaluate_page_rule(
    context: ReportCheckContext,
    value: PageRuleInput,
    *,
    limits: SubmissionCheckLimits = DEFAULT_SUBMISSION_CHECK_LIMITS,
) -> PageRuleResult:
    limits = admit_limits(limits)
    context, value = admit_rule_context(context, limits), admit_page_input(value)
    validate_page_checks((value,), limits)
    criterion = next(
        (item for item in context.criteria.items if item.requirement_id == value.requirement_id),
        None,
    )
    if criterion is None:
        raise PageRuleError(PageRuleErrorCode.UNKNOWN_REQUIREMENT)
    if value.target is not None and value.target.binding.source != context.report.source:
        raise PageRuleError(PageRuleErrorCode.SOURCE_MISMATCH)
    if not criterion.included or criterion.application_status == "does_not_apply":
        return PageRuleResult(
            requirement_id=criterion.requirement_id,
            status="not_applicable",
            rule=None,
            assessment=None,
            scope_subconditions=scope_results(criterion, "not_applicable"),
            reason_codes=("criterion_not_applicable",),
        )
    derivation = derive_page_rule(context, value.requirement_id, limits=limits)
    assessment = None
    status: Literal["compliant", "noncompliant", "deferred"] = "deferred"
    reason = derivation.reason_code
    if derivation.rule is not None:
        if value.target is None or value.selection is None:
            reason = "artifact_or_selection_missing"
        else:
            try:
                assessment = assess_page_count(
                    value.target, value.selection, limits=limits.evidence_limits
                )
            except EvidenceError:
                raise PageRuleError(PageRuleErrorCode.INVALID_ARTIFACT) from None
            status, reason = count_outcome(assessment.assessment, derivation.rule, value.selection)
    return PageRuleResult(
        requirement_id=criterion.requirement_id,
        status=status,
        rule=derivation.rule,
        assessment=assessment,
        scope_subconditions=scope_results(criterion, status),
        reason_codes=(reason,),
    )


def count_outcome(
    count: PageCountAssessment, rule: DerivedPageRule, selection: PageSelection
) -> tuple[Literal["compliant", "noncompliant", "deferred"], str]:
    match count.status:
        case "deferred" | "not_applicable":
            return "deferred", "all_pdf_pages_unverified"
        case "verified":
            if (
                count.count is None
                or count.count != count.artifact_page_count
                or selection.excluded_pages != ()
            ):
                return "deferred", "all_pdf_pages_unverified"
            within_limit = count.count <= rule.maximum_pages
            return (
                ("compliant", "maximum_pages_satisfied")
                if within_limit
                else ("noncompliant", "maximum_pages_exceeded")
            )
        case _:
            assert_never(count.status)
