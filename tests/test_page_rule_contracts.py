import json

import pytest
from page_rule_helpers import context, page_input, response
from pydantic import ValidationError

from submission.evidence_artifacts import make_synthetic_artifact
from submission.evidence_contracts import ArtifactPage
from submission.models import FrozenModel
from submission.page_rule_contracts import (
    PageRuleError,
    PageRuleInput,
    SubmissionCheckContext,
    SubmissionCheckLimits,
)
from submission.page_rule_evaluation import evaluate_page_rule
from submission.submission_check import build_submission_check


@pytest.mark.parametrize("extra", ["maximum_pages", "rule", "assessment", "status"])
def test_page_input_when_caller_proposes_rule_or_outcome_rejects(extra):
    # Given
    raw = {"requirement_id": "R5", "target": None, "selection": None, extra: 999}
    # When
    with pytest.raises(ValidationError):
        PageRuleInput.model_validate_json(json.dumps(raw))


@pytest.mark.parametrize(
    "change",
    [
        "extra",
        "selection_extra",
        "target_extra",
        "target_shape",
        "bool_scope",
        "bool_revision",
        "criteria_extra",
        "nested_sub_extra",
    ],
)
def test_page_input_when_model_copy_bypasses_shape_returns_safe_error(change, recwarn):
    # Given
    ctx = context()
    value = page_input(ctx)
    extra = {"private_extra": "private-sentinel"}
    if change == "extra":
        value = value.model_copy(update=extra)
    elif change == "selection_extra":
        value = value.model_copy(update={"selection": value.selection.model_copy(update=extra)})
    elif change == "target_extra":
        value = value.model_copy(update={"target": value.target.model_copy(update=extra)})
    elif change == "target_shape":
        value = value.model_copy(
            update={"target": value.target.model_copy(update={"binding": None})}
        )
    elif change == "bool_scope":
        value = value.model_copy(
            update={"selection": value.selection.model_copy(update={"scope_confirmed": "false"})}
        )
    elif change == "bool_revision":
        ctx = ctx.model_copy(
            update={"criteria": ctx.criteria.model_copy(update={"revision": True})}
        )
    elif change == "criteria_extra":
        ctx = ctx.model_copy(update={"criteria": ctx.criteria.model_copy(update=extra)})
    else:
        original = ctx.original_draft.requirements[4]
        original = original.model_copy(
            update={"subconditions": (original.subconditions[0].model_copy(update=extra),)}
        )
        ctx = ctx.model_copy(
            update={
                "original_draft": ctx.original_draft.model_copy(
                    update={"requirements": (*ctx.original_draft.requirements[:4], original)}
                )
            }
        )
    # When
    with pytest.raises(PageRuleError) as error:
        evaluate_page_rule(ctx, value)
    # Then
    assert "private" not in str(error.value)
    assert not recwarn.list


@pytest.mark.parametrize("case", ["unknown", "duplicate", "count", "bytes", "shape", "outer_extra"])
def test_submission_when_identity_or_budget_invalid_rejects(case):
    # Given
    ctx = context()
    value = page_input(ctx)
    limits = SubmissionCheckLimits()
    checks = (value,)
    if case == "unknown":
        checks = (value.model_copy(update={"requirement_id": "absent"}),)
    elif case == "duplicate":
        checks = (value, value)
    elif case == "count":
        checks = (value, value.model_copy(update={"requirement_id": "R1"}))
        limits = SubmissionCheckLimits(max_page_checks=1)
    elif case == "bytes":
        limits = SubmissionCheckLimits(max_total_target_bytes=1)
    combined = SubmissionCheckContext(report_check=ctx, page_checks=checks)
    if case == "shape":
        combined = combined.model_copy(update={"page_checks": None})
    elif case == "outer_extra":
        combined = combined.model_copy(update={"private_extra": "private-sentinel"})
    # When
    with pytest.raises(PageRuleError):
        build_submission_check(combined, response(), limits=limits)


@pytest.mark.parametrize(
    "target",
    ["context_none", "context_model", "limits_none", "limits_model", "report_model", "page_model"],
)
def test_submission_when_public_argument_has_wrong_model_returns_typed_error(target):
    # Given
    ctx = context()
    combined = SubmissionCheckContext(report_check=ctx, page_checks=())
    limits = SubmissionCheckLimits()
    if target == "context_none":
        combined = None
    elif target == "context_model":
        combined = FrozenModel()
    elif target == "limits_none":
        limits = None
    elif target == "limits_model":
        limits = FrozenModel()
    elif target == "report_model":
        combined = combined.model_copy(update={"report_check": FrozenModel()})
    else:
        combined = combined.model_copy(update={"page_checks": (FrozenModel(),)})
    # When / Then
    with pytest.raises(PageRuleError):
        build_submission_check(combined, response(), limits=limits)


@pytest.mark.parametrize("synthetic", [False, True])
def test_submission_when_repeated_targets_exceed_shared_budget_rejects(synthetic):
    # Given
    ctx = context()
    value = page_input(ctx)
    limits = SubmissionCheckLimits(max_total_target_bytes=len(value.target.pdf.content))
    if synthetic:
        target = make_synthetic_artifact(value.target.binding, (ArtifactPage(number=1, text="ab"),))
        value = value.model_copy(update={"target": target, "selection": None})
        limits = SubmissionCheckLimits(max_total_target_characters=2)
    values = (value, value.model_copy(update={"requirement_id": "R1"}))
    # When
    with pytest.raises(PageRuleError) as error:
        build_submission_check(
            SubmissionCheckContext(report_check=ctx, page_checks=values), response(), limits=limits
        )
    # Then
    assert error.value.code == "input_limit"


def test_evaluation_when_page_input_is_other_model_returns_typed_error():
    # Given
    ctx = context()
    # When / Then
    with pytest.raises(PageRuleError) as error:
        evaluate_page_rule(ctx, FrozenModel())
    assert error.value.code == "invalid_input"


@pytest.mark.parametrize("field", ["report_limits", "evidence_limits"])
def test_submission_when_nested_limits_are_other_model_returns_typed_error(field):
    # Given
    ctx = context()
    limits = SubmissionCheckLimits().model_copy(update={field: FrozenModel()})
    combined = SubmissionCheckContext(report_check=ctx, page_checks=(page_input(ctx),))
    # When / Then
    with pytest.raises(PageRuleError) as error:
        build_submission_check(combined, response(), limits=limits)
    assert error.value.code == "invalid_input"


def test_submission_when_target_binding_is_other_model_returns_typed_error(recwarn):
    ctx = context()
    value = page_input(ctx)
    target = value.target.model_copy(update={"binding": FrozenModel()})
    value = value.model_copy(update={"target": target})
    combined = SubmissionCheckContext(report_check=ctx, page_checks=(value,))
    with pytest.raises(PageRuleError) as error:
        build_submission_check(combined, response())
    assert error.value.code == "invalid_input"
    assert not recwarn.list
