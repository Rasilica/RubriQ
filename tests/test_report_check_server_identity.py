import json
from unittest.mock import patch

import pytest
from report_check_helpers import context, payload
from test_semantic_chunk_routes import (
    check,
    confirmed_draft,
    environment,
    provider_response,
)
from test_semantic_chunks import CHECK_LIMITS, chunk_fixture

from submission.report_check_adapter import (
    INSTRUCTIONS,
    build_report_check,
    prepare_report_check_request,
)
from submission.report_check_contracts import (
    ReportCheckError,
    ReportCheckErrorCode,
    ReportCheckModelResponse,
)
from submission.report_check_validation import criteria_fingerprint
from submission.semantic_chunks import merge_check_completions

IDENTITY_KEYS = (
    "criteria_sha256",
    "report_source_id",
    "report_document_version_id",
    "report_source_sha256",
)


def model_reply(ctx):
    return {k: v for k, v in payload(ctx).items() if k not in IDENTITY_KEYS}


def assert_server_identity(result, ctx):
    source = ctx.report.source
    assert result.criteria_sha256 == criteria_fingerprint(ctx)
    assert result.report_source_id == source.source_id
    assert result.report_document_version_id == source.document_version_id
    assert result.report_source_sha256 == source.content_sha256


def test_reply_without_identity_fields_gets_server_identity():
    ctx = context()
    assert_server_identity(build_report_check(ctx, json.dumps(model_reply(ctx))), ctx)


def test_reply_with_miscopied_identity_is_overwritten_by_server_values():
    ctx = context()
    raw = model_reply(ctx) | {
        "criteria_sha256": "0" * 64,
        "report_source_id": "other",
        "report_document_version_id": "other",
        "report_source_sha256": "f" * 64,
    }
    assert_server_identity(build_report_check(ctx, json.dumps(raw)), ctx)


def test_unknown_extra_field_is_still_rejected():
    ctx = context()
    with pytest.raises(ReportCheckError, match=ReportCheckErrorCode.INVALID_RESPONSE.value):
        build_report_check(ctx, json.dumps(model_reply(ctx) | {"extra": 1}))


def test_request_and_instructions_no_longer_ask_for_identity_echo():
    request = prepare_report_check_request(context())
    dumped = request.model_dump(mode="json")
    assert not set(IDENTITY_KEYS) & set(dumped)
    assert "복사하세요" not in INSTRUCTIONS
    schema = json.loads(request.response_schema_json)
    assert schema == ReportCheckModelResponse.model_json_schema()
    assert not set(IDENTITY_KEYS) & set(schema["properties"])


def test_chunked_check_without_identity_merges_with_full_identity():
    ctx, chunks = chunk_fixture()
    raws = [json.dumps(model_reply(chunk)) for chunk in chunks]
    merged = json.loads(merge_check_completions(ctx, chunks, raws, CHECK_LIMITS))
    assert merged["criteria_sha256"] == criteria_fingerprint(ctx)
    assert merged["report_source_id"] == ctx.report.source.source_id
    assert_server_identity(build_report_check(ctx, json.dumps(merged)), ctx)


def test_route_payload_sent_to_provider_has_no_identity_fields():
    with environment() as env:
        draft = confirmed_draft(env)
        with patch("submission.semantic_service.complete", side_effect=provider_response) as call:
            assert check(env, draft).status_code == 200
        instructions, payload_json = call.call_args.args[1:3]
        sent = json.loads(payload_json)
        assert not set(IDENTITY_KEYS) & set(sent)
        assert "복사하세요" not in instructions
