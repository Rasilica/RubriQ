import json

import pytest
from report_check_helpers import context, evidence, payload

from submission.report_check_adapter import build_report_check
from submission.report_check_contracts import ReportCheckError, ReportCheckLimits
from submission.report_check_validation import criteria_fingerprint


@pytest.mark.parametrize("change", ["title", "exclusion", "revision", "reason"])
def test_fingerprint_when_confirmed_criteria_changes_is_bound(change):
    # Given
    ctx = context()
    original = criteria_fingerprint(ctx)
    items = ctx.criteria.items
    updates = {
        "title": {"title": "새 기준"},
        "exclusion": {"included": False, "exclusion_reason": "제외"},
        "reason": {"application_reason": "다른 이유"},
    }
    altered = (
        ctx.criteria.model_copy(update={"revision": 2})
        if change == "revision"
        else ctx.criteria.model_copy(
            update={"items": (items[0].model_copy(update=updates[change]), *items[1:])}
        )
    )
    # When
    fingerprint = criteria_fingerprint(ctx.model_copy(update={"criteria": altered}))
    # Then
    assert fingerprint != original
    assert criteria_fingerprint(ctx) == original


@pytest.mark.parametrize("raw", ["{}", "[]", "NaN", "null", "{", "\ud800"])
def test_schema_when_malformed_json_returns_safe_error(raw):
    # Given
    ctx = context()
    # When
    with pytest.raises(ReportCheckError) as error:
        build_report_check(ctx, raw)
    # Then
    assert str(error.value) == "invalid_response"


@pytest.mark.parametrize(
    "change", ["extra", "null", "boolean_offset", "blank_relation", "role", "forged_locator"]
)
def test_schema_when_untrusted_field_is_invalid_rejects(change):
    # Given
    ctx = context()
    raw = payload(ctx)
    cite = evidence(ctx)
    raw["items"][2]["evidence"] = [cite]
    if change == "extra":
        raw["ai_called"] = True
    elif change == "null":
        raw["items"][2]["proposed_judgment"] = None
    elif change == "boolean_offset":
        cite["citation"]["char_range"]["start"] = False
    elif change == "blank_relation":
        cite["relation"] = "  "
    elif change == "role":
        cite["evidence_role"] = "trusted"
    else:
        cite["citation"]["source_locator"] = {"path": "forged"}
    # When
    with pytest.raises(ReportCheckError) as error:
        build_report_check(ctx, json.dumps(raw))
    # Then
    assert error.value.code == "invalid_response"


@pytest.mark.parametrize("raw", ["x" * 11, "한" * 5])
def test_response_when_exceeding_byte_limit_is_rejected(raw):
    # Given
    ctx = context()
    # When
    with pytest.raises(ReportCheckError) as error:
        build_report_check(ctx, raw, limits=ReportCheckLimits(max_response_bytes=10))
    # Then
    assert error.value.code == "response_limit"


@pytest.mark.parametrize(
    "update",
    [
        {"included": False},
        {"condition_description": "잘못된 조건"},
        {"application_status": "does_not_apply"},
        {"application_reason": "필수 항목의 잘못된 이유"},
    ],
)
def test_context_when_unconditional_criterion_breaks_confirmation_contract(update):
    # Given
    ctx = context()
    first = ctx.criteria.items[0].model_copy(update=update)
    ctx = ctx.model_copy(
        update={
            "criteria": ctx.criteria.model_copy(update={"items": (first, *ctx.criteria.items[1:])})
        }
    )
    # When
    with pytest.raises(ReportCheckError) as error:
        build_report_check(ctx, json.dumps(payload(ctx)))
    # Then
    assert error.value.code == "invalid_context"


@pytest.mark.parametrize(
    "update",
    [
        {"condition_description": None},
        {"application_reason": None},
        {"application_status": "undetermined", "application_reason": None},
    ],
)
def test_context_when_conditional_criterion_is_unresolved_or_reason_missing(update):
    # Given
    ctx = context()
    items = ctx.criteria.items
    conditional = items[3].model_copy(update=update)
    ctx = ctx.model_copy(
        update={
            "criteria": ctx.criteria.model_copy(
                update={"items": (*items[:3], conditional, *items[4:])}
            )
        }
    )
    # When
    with pytest.raises(ReportCheckError) as error:
        build_report_check(ctx, json.dumps(payload(ctx)))
    # Then
    assert error.value.code == "invalid_context"


def test_context_when_boolean_snapshot_revision_is_rejected():
    # Given
    ctx = context()
    ctx = ctx.model_copy(update={"criteria": ctx.criteria.model_copy(update={"revision": True})})
    # When
    with pytest.raises(ReportCheckError) as error:
        build_report_check(ctx, json.dumps(payload(ctx)))
    # Then
    assert error.value.code == "invalid_context"


def test_context_when_too_many_criteria_rejects_before_identity():
    # Given
    ctx = context()
    ctx = ctx.model_copy(
        update={"criteria": ctx.criteria.model_copy(update={"items": ctx.criteria.items * 21})}
    )
    # When
    with pytest.raises(ReportCheckError) as error:
        build_report_check(ctx, json.dumps(payload(ctx)))
    # Then
    assert error.value.code == "input_limit"
