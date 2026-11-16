from tools.run_submission_check_demo import DemoCase, run_demo


def test_real_page_limits_change_only_the_mechanical_finding() -> None:
    # Given
    expected = {
        DemoCase.NORMAL: ("compliant", 2),
        DemoCase.MISSING: ("compliant", 2),
        DemoCase.PARAPHRASED: ("compliant", 2),
        DemoCase.OVER_LIMIT: ("noncompliant", 3),
    }
    # When
    results = {item.case_name: item.check for item in run_demo()}
    # Then
    for name, (status, count) in expected.items():
        check = results[name]
        item = check.items[4]
        assert item.page_rule is not None
        assert item.page_rule.status == status
        assert item.page_rule.assessment is not None
        assert item.page_rule.assessment.assessment.count == count
        assert item.page_rule.rule is not None
        assert item.page_rule.rule.maximum_pages == 2
        assert item.page_rule.scope_subconditions[0].status == "verified"
        assert item.evaluation_basis == "page_rule"
        assert item.semantic.judgment == "deferred"
        assert item.semantic.subconditions[0].judgment == "deferred"
        assert check.semantic.items[4] == item.semantic
        assert check.ai_called is check.stored is check.guarantees_all_page_rules is False
    assert results[DemoCase.NORMAL].items[4].effective_judgment == "evidence_found"
    assert results[DemoCase.OVER_LIMIT].items[4].effective_judgment == "explicit_noncompliance"
    assert results[DemoCase.OVER_LIMIT].items[4].needs_attention
    assert results[DemoCase.MISSING].items[1].effective_judgment == "partially_satisfied"
    assert results[DemoCase.NORMAL].items[2].needs_attention is False
    assert results[DemoCase.NORMAL].items[3].effective_judgment is None


def test_uncertain_scope_edited_criterion_and_synthetic_pages_remain_deferred() -> None:
    # Given
    cases = (
        DemoCase.UNCONFIRMED_SCOPE,
        DemoCase.PARTIAL_SCOPE,
        DemoCase.EDITED_CRITERION,
        DemoCase.MISSING_ARTIFACT,
        DemoCase.SYNTHETIC,
    )
    # When
    results = {item.case_name: item.check for item in run_demo()}
    # Then
    for name in cases:
        item = results[name].items[4]
        assert item.page_rule is not None
        assert item.page_rule.status == "deferred"
        assert item.effective_judgment == "deferred"
        assert item.page_rule.scope_subconditions[0].status == "deferred"
    partial = results[DemoCase.PARTIAL_SCOPE].items[4].page_rule
    assert partial is not None
    assert partial.assessment is not None
    assert partial.assessment.assessment.count == 1
    assert partial.status == "deferred"
