import json
from unittest.mock import patch

import pytest
from billing_json_helpers import responses_body
from pydantic import SecretStr
from test_billing_client import billing_connection

from submission.cloud_client import INFERENCE
from submission.semantic_client import complete
from submission.semantic_contracts import AIRequest
from submission.semantic_routes import invoke


def semantic_call():
    request = AIRequest(provider="billingai", model="gpt-6-luna", consent=True)
    return complete(request, "Private instructions", '{"blocks": []}', SecretStr("test-key"))


def test_semantic_billing_requests_stateless_json_object_once():
    connection = billing_connection(responses_body())
    with patch("submission.cloud_client.HTTPSConnection", return_value=connection) as transport:
        result = semantic_call()
    assert result.suggestion == '{"ok": true}'
    assert result.usage.input_tokens == 12
    assert result.usage.output_tokens == 34
    assert transport.call_args.args == ("billing-ai.doubleze.ro",)
    assert transport.call_args.kwargs["timeout"] == 180
    assert transport.call_args.kwargs["context"].check_hostname
    connection.request.assert_called_once()
    request = connection.request.call_args
    assert request.args == ("POST", "/api/v1/responses")
    assert request.kwargs["headers"]["Authorization"] == "Bearer test-key"
    body = json.loads(request.kwargs["body"])
    assert set(body) == {"model", "input", "instructions", "stream", "max_output_tokens", "text"}
    assert body["model"] == "gpt-6-luna"
    assert body["input"] == '{"blocks": []}'
    assert isinstance(body["instructions"], str)
    assert body["instructions"].strip()
    assert body["stream"] is False
    assert body["max_output_tokens"] == 8192
    assert body["text"] == {"format": {"type": "json_object"}}
    assert b"test-key" not in request.kwargs["body"]
    assert not INFERENCE.locked()


@pytest.mark.parametrize(
    "text",
    ["[]", "null", '"plain"', "```json\n{}\n```", "Here: {}", "{} trailing", '{"cut":', "{bad}"],
)
def test_non_object_or_malformed_json_never_repaired_or_retried(text, caplog):
    connection = billing_connection(responses_body(text))
    with patch("submission.cloud_client.HTTPSConnection", return_value=connection):
        response = invoke(semantic_call)
    assert response.status_code == 502
    assert json.loads(response.body)["error"]["diagnostic"]["reason"] == "malformed_json"
    assert "Private instructions" not in caplog.text + response.body.decode()
    assert "test-key" not in caplog.text + response.body.decode()
    connection.request.assert_called_once()
    assert not INFERENCE.locked()


@pytest.mark.parametrize(
    ("body", "reason"),
    [
        (
            responses_body(status="incomplete", incomplete_details={"reason": "content_filter"}),
            "response_refused",
        ),
        (
            responses_body(status="incomplete", incomplete_details={"reason": "private-unknown"}),
            "provider_envelope_invalid",
        ),
        (
            responses_body(status="failed", error={"message": "private-provider-error"}),
            "provider_envelope_invalid",
        ),
        (responses_body(None), "empty_output"),
        (responses_body(""), "empty_output"),
        (responses_body(output=[]), "empty_output"),
        (responses_body(output=[{"type": "reasoning"}]), "empty_output"),
        (responses_body(output=None), "provider_envelope_invalid"),
        (responses_body(usage={"input_tokens": True}), "provider_envelope_invalid"),
        (responses_body(usage={"output_tokens": -1}), "provider_envelope_invalid"),
        (responses_body(usage=None), "provider_envelope_invalid"),
        (responses_body(error={"message": "private-provider-error"}), "provider_envelope_invalid"),
    ],
)
def test_responses_incomplete_empty_or_invalid_are_sanitized(body, reason, caplog):
    connection = billing_connection(body)
    with patch("submission.cloud_client.HTTPSConnection", return_value=connection):
        response = invoke(semantic_call)
    assert response.status_code == 502
    assert json.loads(response.body)["error"]["diagnostic"]["reason"] == reason
    assert "private-" not in caplog.text + response.body.decode()
    assert "upstream_status=200" in caplog.text
    connection.request.assert_called_once()
    assert not INFERENCE.locked()


@pytest.mark.parametrize("raw", [b"private-invalid-envelope", b"null", b"[]"])
def test_invalid_outer_json_is_not_reported_as_generated_json(raw):
    connection = billing_connection({})
    connection.getresponse.return_value.read.return_value = raw
    with patch("submission.cloud_client.HTTPSConnection", return_value=connection):
        response = invoke(semantic_call)
    assert response.status_code == 502
    assert json.loads(response.body)["error"]["diagnostic"]["reason"] == "provider_envelope_invalid"
    assert not INFERENCE.locked()


def test_responses_multiple_text_parts_form_one_complete_object():
    body = responses_body()
    message = body["output"][1]
    message["content"] = [
        {"type": "output_text", "text": '{"ok":'},
        {"type": "output_text", "text": "true}"},
    ]
    connection = billing_connection(body)
    with patch("submission.cloud_client.HTTPSConnection", return_value=connection):
        result = semantic_call()
    assert result.suggestion == '{"ok": true}'
