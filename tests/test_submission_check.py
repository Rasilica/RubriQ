import json

import pytest
from page_rule_helpers import changed_rule, context, page_input, response
from report_check_helpers import evidence, payload

from submission.page_rule_contracts import PageRuleError, SubmissionCheckContext
from submission.submission_check import build_submission_check


def test_submission_when_rule_verified_keeps_semantic_result_separate():
    # Given
    ctx = context()
    combined = SubmissionCheckContext(report_check=ctx, page_checks=(page_input(ctx),))
    # When
    result = build_submission_check(combined, response())
    # Then
    assert result.semantic.items[4].judgment == "deferred"
    assert result.items[4].effective_judgment == "evidence_found"
    assert result.items[4].evaluation_basis == "page_rule"
    assert result.items[2].needs_attention is False
    assert result.items[3].effective_judgment is None


def test_submission_when_response_invalid_returns_safe_page_rule_error():
    # Given
    ctx = SubmissionCheckContext(report_check=context(), page_checks=())
    # When
    with pytest.raises(PageRuleError) as error:
        build_submission_check(ctx, "private-invalid-response")
    # Then
    assert "private" not in str(error.value)


@pytest.mark.parametrize("raw", [None, b"{}"])
def test_submission_when_response_has_wrong_python_type_rejects_safely(raw):
    # Given
    ctx = SubmissionCheckContext(report_check=context(), page_checks=())
    # When
    with pytest.raises(PageRuleError):
        build_submission_check(ctx, raw)


@pytest.mark.parametrize("optional", [True, False])
def test_submission_when_verified_limit_exceeded_preserves_scope_and_attention(optional):
    # Given
    ctx = changed_rule(context(), "보고서는 PDF 파일 전체가 1페이지 이하여야 합니다.")
    criterion = ctx.criteria.items[4]
    if optional:
        criterion = criterion.model_copy(update={"classification": "optional"})
    ctx = ctx.model_copy(
        update={
            "criteria": ctx.criteria.model_copy(
                update={"items": (*ctx.criteria.items[:4], criterion)}
            )
        }
    )
    combined = SubmissionCheckContext(report_check=ctx, page_checks=(page_input(ctx),))
    # When
    result = build_submission_check(combined, json.dumps(payload(ctx)))
    # Then
    rule = result.items[4]
    assert rule.effective_judgment == "explicit_noncompliance"
    assert rule.needs_attention is not optional
    assert rule.page_rule.scope_subconditions[0].status == "verified"
    assert rule.semantic.judgment == "evidence_missing"


def test_submission_when_page_criterion_excluded_is_not_applicable():
    # Given
    ctx = context()
    criterion = ctx.criteria.items[4].model_copy(
        update={"included": False, "exclusion_reason": "제외"}
    )
    ctx = ctx.model_copy(
        update={
            "criteria": ctx.criteria.model_copy(
                update={"items": (*ctx.criteria.items[:4], criterion)}
            )
        }
    )
    combined = SubmissionCheckContext(report_check=ctx, page_checks=(page_input(ctx),))
    # When
    result = build_submission_check(combined, json.dumps(payload(ctx)))
    # Then
    assert result.items[4].evaluation_basis == "not_applicable"
    assert result.items[4].effective_judgment is None
    assert result.items[4].needs_attention is False


def test_submission_when_page_rule_deferred_keeps_semantic_positive_separate():
    # Given
    ctx = context()
    value = page_input(ctx).model_copy(update={"target": None, "selection": None})
    raw = payload(ctx)
    raw["items"][-1]["proposed_judgment"] = "evidence_found"
    raw["items"][-1]["subconditions"][0].update(
        proposed_judgment="evidence_found", evidence=[evidence(ctx)]
    )
    # When
    result = build_submission_check(
        SubmissionCheckContext(report_check=ctx, page_checks=(value,)), json.dumps(raw)
    )
    # Then
    assert result.items[4].semantic.judgment == "evidence_found"
    assert result.items[4].effective_judgment == "deferred"
