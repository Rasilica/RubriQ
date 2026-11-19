import json
from pathlib import Path
from typing import Literal, assert_never

import pytest
from run_report_check_demo import DemoReportName, demo_context, run_demo

from submission.report_check_adapter import OfflineReportCheckAdapter
from submission.report_check_contracts import ReportCheckError


def test_three_pdf_demo_keeps_evidence_and_uncertainty_separate():
    normal, missing, paraphrased = run_demo()
    assert (normal.report_name, missing.report_name, paraphrased.report_name) == (
        "normal",
        "missing",
        "paraphrased",
    )
    for demo in (normal, missing, paraphrased):
        assert demo.check.ai_called is False
        assert demo.check.semantic_accuracy_verified is False
        assert len(demo.check.items) == 5
        optional = demo.check.items[2]
        assert optional.judgment == "evidence_missing"
        assert optional.needs_attention is False
        conditional = demo.check.items[3]
        assert conditional.applicability == "not_applicable"
        assert conditional.judgment is None
        assert demo.check.items[4].judgment == "deferred"
    assert normal.check.items[1].judgment == "evidence_found"
    assert missing.check.items[1].judgment == "partially_satisfied"
    assert missing.check.items[1].subconditions[1].judgment == "evidence_missing"
    assert paraphrased.check.items[1].judgment == "evidence_found"
    evidence = normal.check.items[1].subconditions[1].evidence[0]
    assert (
        evidence.citation.quote
        == "API 출력은 요구사항별 판단 상태와 보고서 근거 인용 및 페이지입니다."
    )
    assert evidence.citation.source_locator.original_page_number == 2


@pytest.mark.parametrize("field", ["quote"])
def test_authored_response_cannot_move_between_versions_or_invent_a_quote(
    field: Literal["quote"],
):
    response_path = (
        Path(__file__).resolve().parents[1] / "samples/checks/normal-offline-response.json"
    )
    response = json.loads(response_path.read_text(encoding="utf-8"))
    match field:
        case "quote":
            response["items"][0]["subconditions"][0]["evidence"][0]["citation"]["quote"] += "거짓"
        case unreachable:
            assert_never(unreachable)
    with pytest.raises(ReportCheckError):
        OfflineReportCheckAdapter(json.dumps(response, ensure_ascii=False)).check(
            demo_context(DemoReportName.NORMAL)
        )
