import pytest
from page_rule_helpers import context, page_input

from submission.models import DocumentRole, PdfInput
from submission.page_rule_contracts import PageRuleError
from submission.page_rule_evaluation import evaluate_page_rule


def test_page_rule_when_original_max_and_complete_actual_pdf_verifies():
    # Given
    ctx = context()
    value = page_input(ctx)
    # When
    result = evaluate_page_rule(ctx, value)
    # Then
    assert result.status == "compliant"
    assert result.rule.maximum_pages == 2
    assert result.assessment.assessment.count == 2
    assert result.scope_subconditions[0].status == "verified"


def test_page_rule_when_caller_excludes_page_cannot_bypass_all_pages():
    # Given
    ctx = context()
    value = page_input(ctx)
    value = value.model_copy(
        update={
            "selection": value.selection.model_copy(
                update={"included_pages": (1,), "excluded_pages": (2,)}
            )
        }
    )
    # When
    result = evaluate_page_rule(ctx, value)
    # Then
    assert result.status == "deferred"


@pytest.mark.parametrize("change", ["excluded", "condition_false"])
def test_page_rule_when_criterion_not_applicable_preserves_null(change):
    # Given
    ctx = context()
    criterion = ctx.criteria.items[4]
    updates = (
        {"included": False, "exclusion_reason": "별도 확인"}
        if change == "excluded"
        else {
            "classification": "conditional",
            "condition_description": "적용 조건",
            "application_status": "does_not_apply",
            "application_reason": "적용 안함",
        }
    )
    criterion = criterion.model_copy(update=updates)
    ctx = ctx.model_copy(
        update={
            "criteria": ctx.criteria.model_copy(
                update={"items": (*ctx.criteria.items[:4], criterion)}
            )
        }
    )
    # When
    result = evaluate_page_rule(ctx, page_input(ctx))
    # Then
    assert result.status == "not_applicable"
    assert result.assessment is None
    assert result.scope_subconditions[0].effective_judgment is None


@pytest.mark.parametrize("change", ["source", "bytes", "selection"])
def test_page_rule_when_artifact_binding_is_stale_rejects(change):
    # Given
    ctx = context()
    value = page_input(ctx)
    if change == "source":
        target = value.target.model_copy(
            update={
                "binding": value.target.binding.model_copy(
                    update={
                        "source": value.target.binding.source.model_copy(
                            update={"document_version_id": "stale"}
                        )
                    }
                )
            }
        )
        value = value.model_copy(update={"target": target})
    elif change == "bytes":
        target = value.target.model_copy(
            update={"pdf": PdfInput("private.pdf", b"private-malformed", DocumentRole.REPORT)}
        )
        value = value.model_copy(update={"target": target})
    else:
        value = value.model_copy(
            update={"selection": value.selection.model_copy(update={"binding_sha256": "0" * 64})}
        )
    # When
    with pytest.raises(PageRuleError) as error:
        evaluate_page_rule(ctx, value)
    # Then
    assert "private" not in str(error.value)
