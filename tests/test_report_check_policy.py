import json

import pytest
from report_check_helpers import context, evidence, payload

from submission.document_contracts import DocumentDiagnostic, ProcessingStatus
from submission.report_check_adapter import build_report_check


@pytest.mark.parametrize("role", ["heading", "toc", "unknown"])
def test_positive_when_only_noncontent_evidence_is_deferred(role):
    # Given
    ctx = context()
    raw = payload(ctx)
    raw["items"][2].update(proposed_judgment="evidence_found", evidence=[evidence(ctx, role)])
    # When
    result = build_report_check(ctx, json.dumps(raw))
    # Then
    assert result.items[2].judgment == "deferred"
    assert "content_evidence_required" in result.items[2].reason_codes


def test_parent_when_sibling_missing_remains_partial():
    # Given
    ctx = context()
    raw = payload(ctx)
    row = raw["items"][0]
    row["proposed_judgment"] = "evidence_found"
    row["subconditions"][0].update(proposed_judgment="evidence_found", evidence=[evidence(ctx)])
    # When
    result = build_report_check(ctx, json.dumps(raw))
    # Then
    assert result.items[0].judgment == "partially_satisfied"
    assert result.items[0].subconditions[1].judgment == "evidence_missing"


def test_explicit_violation_when_caller_claims_rule_is_deferred():
    # Given
    ctx = context()
    raw = payload(ctx)
    raw["items"][2].update(proposed_judgment="explicit_noncompliance", evidence=[evidence(ctx)])
    # When
    result = build_report_check(ctx, json.dumps(raw))
    # Then
    assert result.items[2].judgment == "deferred"
    assert result.items[2].proposed_judgment == "explicit_noncompliance"
    assert result.items[2].reason_codes == ("rule_verification_required",)


def test_missing_when_partial_review_scope_is_deferred():
    # Given
    ctx = context()
    raw = payload(ctx)
    raw["reviewed_block_ids"] = []
    # When
    result = build_report_check(ctx, json.dumps(raw))
    # Then
    assert result.items[2].judgment == "deferred"
    assert "incomplete_review_scope" in result.items[2].reason_codes


@pytest.mark.parametrize("judgment", ["deferred", "explicit_noncompliance"])
def test_parent_when_all_children_found_but_parent_unresolved_keeps_deferral(judgment):
    # Given
    ctx = context()
    raw = payload(ctx)
    raw["items"][0]["proposed_judgment"] = judgment
    for sub in raw["items"][0]["subconditions"]:
        sub.update(proposed_judgment="evidence_found", evidence=[evidence(ctx)])
    # When
    result = build_report_check(ctx, json.dumps(raw))
    # Then
    assert result.items[0].judgment == "deferred"
    assert all(sub.judgment == "evidence_found" for sub in result.items[0].subconditions)


def test_partial_when_no_subconditions_cannot_claim_satisfaction():
    # Given
    ctx = context()
    raw = payload(ctx)
    raw["items"][2].update(proposed_judgment="partially_satisfied", evidence=[evidence(ctx)])
    # When
    result = build_report_check(ctx, json.dumps(raw))
    # Then
    assert result.items[2].judgment == "deferred"
    assert result.items[2].reason_codes == ("partial_requires_subconditions",)


def test_missing_when_partial_extraction_preserves_actual_diagnostics():
    # Given
    ctx = context()
    diagnostic = DocumentDiagnostic(code="text_unavailable", page_number=2)
    report = ctx.report.model_copy(
        update={
            "extraction_status": ProcessingStatus.PARTIAL,
            "warnings": (diagnostic,),
            "typed_errors": (diagnostic,),
        }
    )
    ctx = ctx.model_copy(update={"report": report})
    # When
    result = build_report_check(ctx, json.dumps(payload(ctx)))
    # Then
    assert result.items[0].judgment == "deferred"
    assert result.items[0].subconditions[0].reason_codes == ("partial_extraction",)
    assert result.report_warnings == (diagnostic,)
    assert result.report_typed_errors == (diagnostic,)


def test_exclusion_when_condition_unresolved_is_authoritative_null():
    # Given
    ctx = context()
    items = ctx.criteria.items
    conditional = items[3].model_copy(
        update={
            "included": False,
            "exclusion_reason": "후속 확인",
            "application_status": "undetermined",
            "application_reason": None,
        }
    )
    ctx = ctx.model_copy(
        update={
            "criteria": ctx.criteria.model_copy(
                update={"items": (*items[:3], conditional, *items[4:])}
            )
        }
    )
    # When
    result = build_report_check(ctx, json.dumps(payload(ctx)))
    # Then
    assert result.items[3].judgment is None
    assert result.items[3].reason_codes == ("excluded",)
    assert result.items[3].needs_attention is False
