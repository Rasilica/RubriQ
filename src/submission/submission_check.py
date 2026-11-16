from typing import assert_never

from pydantic import TypeAdapter, ValidationError

from submission.evidence_boundary import reject_extra_fields
from submission.evidence_contracts import EvidenceError
from submission.page_rule_contracts import (
    DEFAULT_SUBMISSION_CHECK_LIMITS,
    CombinedItemResult,
    PageRuleError,
    PageRuleErrorCode,
    PageRuleInput,
    PageRuleResult,
    SubmissionCheckContext,
    SubmissionCheckLimits,
    SubmissionCheckResult,
)
from submission.page_rule_evaluation import evaluate_page_rule
from submission.page_rule_validation import (
    admit_limits,
    admit_page_input,
    admit_rule_context,
    validate_page_checks,
)
from submission.report_check_adapter import build_report_check
from submission.report_check_contracts import ReportCheckError
from submission.report_check_results import ItemResult


def combine_item(semantic: ItemResult, page_rule: PageRuleResult | None) -> CombinedItemResult:
    if page_rule is None:
        return CombinedItemResult(
            semantic=semantic,
            page_rule=None,
            effective_judgment=semantic.judgment,
            evaluation_basis="semantic",
            needs_attention=semantic.needs_attention,
        )
    match page_rule.status:
        case "compliant":
            judgment, basis, attention = "evidence_found", "page_rule", False
        case "noncompliant":
            judgment, basis, attention = (
                "explicit_noncompliance",
                "page_rule",
                semantic.criterion.classification != "optional",
            )
        case "deferred":
            judgment, basis, attention = (
                "deferred",
                "page_rule",
                semantic.criterion.classification != "optional",
            )
        case "not_applicable":
            judgment, basis, attention = None, "not_applicable", False
        case _:
            assert_never(page_rule.status)
    return CombinedItemResult(
        semantic=semantic,
        page_rule=page_rule,
        effective_judgment=judgment,
        evaluation_basis=basis,
        needs_attention=attention,
    )


def build_submission_check(
    context: SubmissionCheckContext,
    response_json: str,
    *,
    limits: SubmissionCheckLimits = DEFAULT_SUBMISSION_CHECK_LIMITS,
) -> SubmissionCheckResult:
    try:
        context = TypeAdapter(SubmissionCheckContext).validate_python(context, strict=True)
        reject_extra_fields(context)
        response_json = TypeAdapter(str).validate_python(response_json, strict=True)
        page_inputs = TypeAdapter[tuple[PageRuleInput, ...]](
            tuple[PageRuleInput, ...]
        ).validate_python(context.page_checks, strict=True)
    except (EvidenceError, ValidationError):
        raise PageRuleError(PageRuleErrorCode.INVALID_INPUT) from None
    limits = admit_limits(limits)
    report_context = admit_rule_context(context.report_check, limits)
    if len(page_inputs) > limits.max_page_checks:
        raise PageRuleError(PageRuleErrorCode.INPUT_LIMIT)
    page_inputs = tuple(admit_page_input(value) for value in page_inputs)
    validate_page_checks(page_inputs, limits)
    try:
        semantic = build_report_check(report_context, response_json, limits=limits.report_limits)
    except ReportCheckError:
        raise PageRuleError(PageRuleErrorCode.INVALID_INPUT) from None
    page_rules = {
        value.requirement_id: evaluate_page_rule(report_context, value, limits=limits)
        for value in page_inputs
    }
    return SubmissionCheckResult(
        semantic=semantic,
        items=tuple(
            combine_item(item, page_rules.get(item.requirement_id)) for item in semantic.items
        ),
    )
