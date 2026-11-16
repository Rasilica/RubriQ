import asyncio
import json
import logging
from time import monotonic

import pytest
from pydantic import ValidationError
from report_check_helpers import context, evidence, payload

from submission import semantic_diagnostics as diagnostics
from submission.report_check_contracts import (
    ReportCheckError,
    ReportCheckErrorCode,
    ReportCheckLimits,
    ReportCheckResponse,
)
from submission.report_check_validation import parse_response, validate_response, verify_evidence


@pytest.mark.parametrize(
    ("change", "code", "branch"),
    [
        ({"report_source_id": "wrong"}, "source_mismatch", "source_binding"),
        ({"criteria_sha256": "0" * 64}, "criteria_mismatch", "criteria_binding"),
        ({"reviewed_block_ids": ["absent", "absent"]}, "invalid_scope", "scope_duplicate"),
        ({"reviewed_block_ids": ["absent"]}, "invalid_scope", "scope_unsubmitted"),
        ({"items": []}, "invalid_identity", "identity_items"),
    ],
)
def test_branch_details(change, code, branch, caplog):
    ctx = context()
    response = ReportCheckResponse.model_validate_json(json.dumps(payload(ctx) | change))
    with diagnostics.scope(), caplog.at_level(logging.WARNING):
        with pytest.raises(ReportCheckError) as caught:
            validate_response(ctx, response)
        assert caught.value.code == code
        diagnostics.mark("report_validation", "report_contract_invalid")
        public = diagnostics.failure(422, monotonic())
        assert set(public.model_dump()) == {"id", "stage", "reason"}
    assert f'"code":"{code}"' in caplog.text
    assert f'"branch":"{branch}"' in caplog.text


def test_schema_detail_does_not_log_values(caplog):
    raw = payload(context())
    raw["items"][0]["secret-key-123"] = "secret-value-456"
    raw["items"][0]["reason"] = 42
    with diagnostics.scope(), caplog.at_level(logging.WARNING):
        with pytest.raises(ReportCheckError):
            parse_response(json.dumps(raw), ReportCheckLimits())
        diagnostics.failure(422, monotonic())
    assert '"branch":"schema_invalid"' in caplog.text
    assert '"path":["items",0,"extra"]' in caplog.text
    assert "secret-key-123" not in caplog.text
    assert "secret-value-456" not in caplog.text
    assert '"type":"string_type"' in caplog.text


def test_citation_detail(caplog):
    ctx = context()
    raw = payload(ctx)
    cite = evidence(ctx)
    cite["citation"]["quote"] = "wrong"
    raw["items"][0]["evidence"] = [cite]
    response = ReportCheckResponse.model_validate_json(json.dumps(raw))
    with diagnostics.scope(), caplog.at_level(logging.WARNING):
        with pytest.raises(ReportCheckError):
            verify_evidence(response.items[0].evidence[0], ctx)
        diagnostics.failure(422, monotonic())
    assert '"branch":"citation_quote_mismatch"' in caplog.text


@pytest.mark.parametrize("branch", ["identity_subconditions", "scope_cite_unreviewed"])
def test_nested_branches(branch, caplog):
    ctx = context()
    raw = payload(ctx)
    if branch == "identity_subconditions":
        item = next(item for item in raw["items"] if item["subconditions"])
        item["subconditions"] = []
        code = "invalid_identity"
    else:
        raw["reviewed_block_ids"] = []
        raw["items"][0]["evidence"] = [evidence(ctx)]
        code = "invalid_scope"
    response = ReportCheckResponse.model_validate_json(json.dumps(raw))
    with diagnostics.scope(), caplog.at_level(logging.WARNING):
        with pytest.raises(ReportCheckError) as caught:
            validate_response(ctx, response)
        assert caught.value.code == code
        diagnostics.failure(422, monotonic())
    assert f'"branch":"{branch}"' in caplog.text


def test_scope_preserves_detail_without_leaking():

    diagnostics.contract_failure(ReportCheckErrorCode.INVALID_RESPONSE)
    assert diagnostics.TRACE.get() is None
    with diagnostics.scope():
        diagnostics.contract_failure(ReportCheckErrorCode.INVALID_SCOPE, "scope_duplicate")
        original = diagnostics.TRACE.get()
        diagnostics.contract_failure(ReportCheckErrorCode.INVALID_SCOPE)
        assert diagnostics.TRACE.get() is original
        with diagnostics.scope():
            assert diagnostics.TRACE.get() is None
            diagnostics.contract_failure(ReportCheckErrorCode.INVALID_RESPONSE)
            assert diagnostics.TRACE.get().detail.branch == "unknown"
        assert diagnostics.TRACE.get() is original
    assert diagnostics.TRACE.get() is None


def test_schema_detail_boundaries():

    error = ValidationError.from_exception_data(
        "secret-title",
        [
            {"type": "extra_forbidden", "loc": ("items", 50000, "secret-field"), "input": "secret"}
            for _ in range(8)
        ],
    )
    with diagnostics.scope():
        diagnostics.contract_failure(ReportCheckErrorCode.INVALID_RESPONSE, "schema_invalid", error)
        detail = diagnostics.TRACE.get().detail
        assert len(detail.issues) == 5
        assert detail.issues[0].path == ("items", 2000, "extra")
        assert "secret" not in diagnostics.detail_json(detail)


def test_concurrent_contexts_are_isolated():

    async def inspect(branch):
        with diagnostics.scope():
            diagnostics.contract_failure(ReportCheckErrorCode.INVALID_SCOPE, branch)
            await asyncio.sleep(0)
            return diagnostics.TRACE.get().detail.branch

    async def run():
        return await asyncio.gather(inspect("scope_duplicate"), inspect("scope_unsubmitted"))

    assert asyncio.run(run()) == ["scope_duplicate", "scope_unsubmitted"]
    assert diagnostics.TRACE.get() is None


def test_unknown_schema_error_kind_is_redacted():
    error = ValidationError.from_exception_data(
        "private-title", [{"type": "bool_type", "loc": ("secret-field",), "input": "private"}]
    )
    with diagnostics.scope():
        diagnostics.contract_failure(ReportCheckErrorCode.INVALID_RESPONSE, "schema_invalid", error)
        detail = diagnostics.TRACE.get().detail
        assert detail.issues[0].type == "unknown"
        assert detail.issues[0].path == ("extra",)
        assert "private" not in diagnostics.detail_json(detail)
