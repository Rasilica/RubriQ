import json
import logging

import pytest
from fastapi.responses import JSONResponse
from report_check_helpers import context, evidence

from submission import report_check_validation
from submission import semantic_diagnostics as diagnostics
from submission.report_check_contracts import ReportEvidence
from submission.requirement_contracts import RequirementError, RequirementErrorCode
from submission.semantic_routes import invoke


@pytest.mark.parametrize(
    ("change", "branch"),
    [
        ({"block_id": "private-missing-block"}, "citation_block_missing"),
        ({"char_range": {"start": 0, "end": 987654}}, "citation_range_invalid"),
        ({"char_range": {"start": 987653, "end": 987654}}, "citation_range_invalid"),
        ({"quote": "private-mismatched-quote"}, "citation_quote_mismatch"),
    ],
)
def test_citation_failure_branch_is_private_and_preserves_public_contract(change, branch, caplog):
    ctx = context()
    raw = evidence(ctx)
    proposed = ReportEvidence.model_validate(raw | {"citation": raw["citation"] | change})
    with caplog.at_level(logging.WARNING):
        response = invoke(lambda: report_check_validation.verify_evidence(proposed, ctx))
    assert isinstance(response, JSONResponse)
    assert response.status_code == 422
    body = json.loads(response.body)
    assert body["error"]["code"] == "ai_invalid_citation"
    diagnostic = body["error"]["diagnostic"]
    assert set(diagnostic) == {"id", "stage", "reason"}
    assert diagnostic["reason"] == "citation_invalid"
    assert diagnostic["stage"] == "report_validation"
    assert f'"branch":"{branch}"' in caplog.text
    assert '"issues":[]' in caplog.text
    for private in (
        raw["citation"]["block_id"],
        raw["citation"]["quote"],
        "private-missing-block",
        "private-mismatched-quote",
        "987653",
        "987654",
    ):
        assert private not in caplog.text
        assert private not in response.body.decode()
    assert diagnostics.TRACE.get() is None


def test_unclassified_authoritative_rejection_is_never_accepted(monkeypatch, caplog):
    ctx = context()
    proposed = ReportEvidence.model_validate(evidence(ctx))

    def reject(*_args):
        raise RequirementError(RequirementErrorCode.INVALID_CITATION)

    monkeypatch.setattr(report_check_validation, "verify_citation", reject)
    with caplog.at_level(logging.WARNING):
        response = invoke(lambda: report_check_validation.verify_evidence(proposed, ctx))
    assert isinstance(response, JSONResponse)
    assert response.status_code == 422
    assert '"branch":"citation_quote"' in caplog.text


def test_success_keeps_exact_citation_and_has_no_failure_diagnostic(caplog):
    ctx = context()
    proposed = ReportEvidence.model_validate(evidence(ctx))
    with diagnostics.scope():
        verified = report_check_validation.verify_evidence(proposed, ctx)
        assert diagnostics.TRACE.get() is None
    assert verified.citation.block_id == proposed.citation.block_id
    assert verified.citation.char_range == proposed.citation.char_range
    assert verified.citation.quote == proposed.citation.quote
    assert not caplog.records
