import json
import re
from hashlib import sha256
from typing import Final

from submission.page_rule_contracts import (
    DEFAULT_SUBMISSION_CHECK_LIMITS,
    DerivedPageRule,
    PageRuleError,
    PageRuleErrorCode,
    RuleDerivation,
    SubmissionCheckLimits,
)
from submission.page_rule_validation import admit_rule_context
from submission.report_check_contracts import ReportCheckContext
from submission.report_check_validation import criteria_fingerprint
from submission.requirement_contracts import VerifiedCitation

MAXIMUM_PATTERN: Final = re.compile(
    r"보고서는 PDF 파일 전체가 ([1-9][0-9]{0,3})페이지 이하여야 합니다\."
)
SCOPE_QUOTE: Final = "표지, 본문, 참고문헌, 부록, 구현 화면을 포함한 모든 페이지를 셉니다."


def whole_line(context: ReportCheckContext, citation: VerifiedCitation) -> bool:
    block = next(block for block in context.guide.blocks if block.block_id == citation.block_id)
    start, end = citation.char_range.start, citation.char_range.end
    return (start == 0 or block.raw_text[start - 1] == "\n") and (
        end == len(block.raw_text) or block.raw_text[end] == "\n"
    )


def derive_page_rule(
    context: ReportCheckContext,
    requirement_id: str,
    *,
    limits: SubmissionCheckLimits = DEFAULT_SUBMISSION_CHECK_LIMITS,
) -> RuleDerivation:
    context = admit_rule_context(context, limits)
    original = next(
        (
            item
            for item in context.original_draft.requirements
            if item.requirement_id == requirement_id
        ),
        None,
    )
    if original is None:
        raise PageRuleError(PageRuleErrorCode.UNKNOWN_REQUIREMENT)
    criterion = next(
        item for item in context.criteria.items if item.requirement_id == requirement_id
    )
    if (
        criterion.title != original.title
        or criterion.condition_description
        != (original.condition.description if original.condition else None)
        or tuple(sub.description for sub in criterion.subconditions)
        != tuple(sub.description for sub in original.subconditions)
    ):
        return RuleDerivation(rule=None, reason_code="criterion_text_changed")
    if len(original.citations) != 1:
        return RuleDerivation(rule=None, reason_code="unsupported_rule_grammar")
    citation = original.citations[0]
    maximum = MAXIMUM_PATTERN.fullmatch(citation.quote)
    if maximum is None or not whole_line(context, citation):
        return RuleDerivation(rule=None, reason_code="unsupported_rule_grammar")
    if len(original.subconditions) != 1 or len(original.subconditions[0].citations) != 1:
        return RuleDerivation(rule=None, reason_code="unsupported_scope_grammar")
    scope = original.subconditions[0]
    scope_citation = scope.citations[0]
    if scope_citation.quote != SCOPE_QUOTE or not whole_line(context, scope_citation):
        return RuleDerivation(rule=None, reason_code="unsupported_scope_grammar")
    fingerprint = sha256(
        json.dumps(
            {
                "original": original.model_dump(mode="json"),
                "criterion": criterion.model_dump(mode="json"),
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    return RuleDerivation(
        rule=DerivedPageRule(
            criteria_sha256=criteria_fingerprint(context),
            requirement_id=requirement_id,
            criterion_sha256=fingerprint,
            guide_source_sha256=context.guide.source.content_sha256,
            guide_document_version_id=context.guide.source.document_version_id,
            maximum_pages=int(maximum.group(1)),
            rule_citation=citation,
            scope_citation=scope_citation,
            scope_subcondition_id=scope.subcondition_id,
        ),
        reason_code="supported",
    )
