import pytest
from page_rule_helpers import changed_rule, context

from submission.page_rule_parser import derive_page_rule


def test_local_rule_fingerprint_when_original_quote_changes_binds_both_texts():
    # Given
    ctx = context()
    first = derive_page_rule(ctx, "R5")
    changed = changed_rule(ctx, "보고서는 PDF 파일 전체가 3페이지 이하여야 합니다.")
    # When
    second = derive_page_rule(changed, "R5")
    # Then
    assert first.rule.criterion_sha256 != second.rule.criterion_sha256


@pytest.mark.parametrize(
    "text",
    [
        "보고서는 PDF 파일 전체가 2페이지 이상이어야 합니다.",
        "보고서는 PDF 파일 전체가 1~2페이지여야 합니다.",
        "보고서는 PDF 파일 전체가 2쪽 이하여야 합니다.",
        "보고서는 PDF 파일 전체가 두페이지 이하여야 합니다.",
        "보고서는 PDF 파일 전체가 0페이지 이하여야 합니다.",
        "보고서는 PDF 파일 전체가 10000페이지 이하여야 합니다.",
    ],
)
def test_rule_when_outside_narrow_grammar_defers(text):
    # Given
    ctx = changed_rule(context(), text)
    # When
    result = derive_page_rule(ctx, "R5")
    # Then
    assert result.rule is None
    assert result.reason_code == "unsupported_rule_grammar"


def test_rule_when_citation_omits_line_prefix_does_not_verify():
    # Given
    ctx = changed_rule(context(), "보고서는 PDF 파일 전체가 2페이지 이하여야 합니다.", "예시: ")
    # When
    result = derive_page_rule(ctx, "R5")
    # Then
    assert result.rule is None
    assert result.reason_code == "unsupported_rule_grammar"


@pytest.mark.parametrize("maximum", [1, 2, 9999])
def test_rule_when_bounded_ascii_integer_is_supported(maximum):
    # Given
    ctx = changed_rule(context(), f"보고서는 PDF 파일 전체가 {maximum}페이지 이하여야 합니다.")
    # When
    result = derive_page_rule(ctx, "R5")
    # Then
    assert result.rule.maximum_pages == maximum


@pytest.mark.parametrize(
    "change", ["title", "subcondition", "metadata_only", "scope_count", "root_count", "scope_quote"]
)
def test_rule_when_actual_criterion_or_scope_changes_is_conservative(change):
    # Given
    ctx = context()
    criterion = ctx.criteria.items[4]
    original = ctx.original_draft.requirements[4]
    if change == "title":
        criterion = criterion.model_copy(update={"title": "수정된 제목", "edited_fields": ()})
    elif change == "subcondition":
        criterion = criterion.model_copy(
            update={
                "subconditions": (
                    criterion.subconditions[0].model_copy(update={"description": "별도 집계"}),
                ),
                "edited_fields": (),
            }
        )
    elif change == "metadata_only":
        criterion = criterion.model_copy(update={"edited_fields": ("title",)})
    elif change == "scope_count":
        original = original.model_copy(
            update={
                "subconditions": (
                    original.subconditions[0].model_copy(
                        update={"citations": original.subconditions[0].citations * 2}
                    ),
                )
            }
        )
    elif change == "root_count":
        original = original.model_copy(update={"citations": original.citations * 2})
    else:
        original = original.model_copy(
            update={
                "subconditions": (
                    original.subconditions[0].model_copy(update={"citations": original.citations}),
                )
            }
        )
    ctx = ctx.model_copy(
        update={
            "criteria": ctx.criteria.model_copy(
                update={"items": (*ctx.criteria.items[:4], criterion)}
            ),
            "original_draft": ctx.original_draft.model_copy(
                update={"requirements": (*ctx.original_draft.requirements[:4], original)}
            ),
        }
    )
    # When
    result = derive_page_rule(ctx, "R5")
    # Then
    assert (result.rule is not None) is (change == "metadata_only")
