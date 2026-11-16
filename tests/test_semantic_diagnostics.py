import json
import re
import ssl
from unittest.mock import MagicMock, patch

import pytest
from billing_json_helpers import responses_body
from pydantic import SecretStr

from submission import semantic_diagnostics as diagnostics
from submission.cloud_client import INFERENCE
from submission.cloud_contracts import TextCompletion
from submission.report_check_contracts import ReportCheckError, ReportCheckErrorCode
from submission.semantic_client import complete
from submission.semantic_contracts import AIRequest, SemanticCode, SemanticError
from submission.semantic_routes import invoke


@pytest.mark.parametrize(
    ("body", "reason"),
    [
        (
            responses_body(
                "partial-private",
                status="incomplete",
                incomplete_details={"reason": "max_output_tokens"},
            ),
            "output_truncated",
        ),
        (responses_body("{broken-private"), "malformed_json"),
        (responses_body(" "), "empty_output"),
        (responses_body("synthetic-key"), "unsafe_output"),
        (responses_body("가" * 90000), "response_too_large"),
        (
            responses_body(
                output=[{"type": "message", "content": [{"type": "refusal", "refusal": "private"}]}]
            ),
            "response_refused",
        ),
        (responses_body(output=[{"type": "function_call", "name": "private"}]), "tool_call"),
        (responses_body(status=None), "provider_envelope_invalid"),
    ],
    ids=["length", "json", "blank", "secret", "size", "refusal", "tool", "envelope"],
)
def test_semantic_safe_diagnostic(body, reason, caplog):
    connection = MagicMock()
    connection.getresponse.return_value.status = 200
    connection.getresponse.return_value.read.return_value = json.dumps(body).encode()
    request = AIRequest(provider="billingai", model="gpt-6-luna", consent=True)
    with patch("submission.cloud_client.HTTPSConnection", return_value=connection):
        response = invoke(
            lambda: complete(request, "private-instructions", "{}", SecretStr("synthetic-key"))
        )
    assert response.status_code == 502
    body = json.loads(response.body)
    assert body["error"]["code"] == "cloud_invalid_response"
    diagnostic = body["error"]["diagnostic"]
    assert diagnostic["reason"] == reason
    assert re.fullmatch("[a-f0-9]{32}", diagnostic["id"])
    assert "private" not in response.body.decode() + caplog.text
    assert "synthetic-key" not in response.body.decode() + caplog.text
    assert diagnostic["id"] in caplog.text
    assert not INFERENCE.locked()
    connection.request.assert_called_once()


@pytest.mark.parametrize(("status", "expected"), [(502, 503), (401, 401), (429, 429)])
def test_upstream_http_preserves_status(status, expected):
    connection = MagicMock()
    connection.getresponse.return_value.status = status
    request = AIRequest(provider="billingai", model="gpt-6-luna", consent=True)
    with patch("submission.cloud_client.HTTPSConnection", return_value=connection):
        response = invoke(lambda: complete(request, "private", "{}", SecretStr("synthetic-key")))
    assert response.status_code == expected
    assert json.loads(response.body)["error"]["diagnostic"]["reason"] == "upstream_http"
    connection.getresponse.return_value.read.assert_not_called()


def test_success_does_not_leak_request_diagnostic_to_next_call():
    request = AIRequest(provider="billingai", model="gpt-6-luna", consent=True)
    with patch("submission.semantic_client.generate_json") as generate:
        generate.return_value = TextCompletion(suggestion="{}")
        response = invoke(lambda: complete(request, "private", "{}", SecretStr("synthetic-key")))
    assert response.success

    def rejected():
        raise SemanticError(SemanticCode.FORBIDDEN, 403)

    failure = invoke(rejected)
    assert "diagnostic" not in json.loads(failure.body)["error"]


@pytest.mark.parametrize(
    ("error", "status", "reason"),
    [
        (TimeoutError("private"), 504, "timeout"),
        (ssl.SSLCertVerificationError("private"), 503, "tls_failed"),
        (OSError("private"), 503, "transport_failed"),
    ],
)
def test_transport_safe_diagnostic(error, status, reason, caplog):
    request = AIRequest(provider="billingai", model="model", consent=True)
    with patch("submission.cloud_client.HTTPSConnection", side_effect=error):
        response = invoke(lambda: complete(request, "private", "{}", SecretStr("synthetic-key")))
    assert response.status_code == status
    assert json.loads(response.body)["error"]["diagnostic"]["reason"] == reason
    assert "private" not in caplog.text


@pytest.mark.parametrize(
    "usage",
    [
        {"input_tokens": 3, "output_tokens": 8},
        {"input_tokens": True},
        {"output_tokens": -1},
        {"input_tokens": "private"},
        None,
    ],
)
def test_truncated_usage_validated_independently(usage, caplog):
    connection = MagicMock()
    connection.getresponse.return_value.status = 200
    connection.getresponse.return_value.read.return_value = json.dumps(
        responses_body(
            "private",
            status="incomplete",
            incomplete_details={"reason": "max_output_tokens"},
            usage=usage,
        )
    ).encode()
    request = AIRequest(provider="billingai", model="model", consent=True)
    with patch("submission.cloud_client.HTTPSConnection", return_value=connection):
        response = invoke(lambda: complete(request, "private", "{}", SecretStr("synthetic-key")))
    assert json.loads(response.body)["error"]["diagnostic"]["reason"] == "output_truncated"
    expected = (
        "input_tokens=3 output_tokens=8"
        if usage == {"input_tokens": 3, "output_tokens": 8}
        else "input_tokens=None output_tokens=None"
    )
    assert expected in caplog.text
    assert "private" not in caplog.text


@pytest.mark.parametrize(
    "code", [ReportCheckErrorCode.INVALID_CITATION, ReportCheckErrorCode.INVALID_RESPONSE]
)
def test_domain_diagnostic_keeps_422(code):
    def action():
        diagnostics.mark("report_validation", "report_contract_invalid")
        raise ReportCheckError(code)

    response = invoke(action)
    assert response.status_code == 422
    expected = (
        "citation_invalid"
        if code == ReportCheckErrorCode.INVALID_CITATION
        else "report_contract_invalid"
    )
    assert json.loads(response.body)["error"]["diagnostic"]["reason"] == expected


def test_final_result_validation_is_sanitized(caplog):
    def action():
        diagnostics.mark("result_build", "result_invalid")
        return TextCompletion.model_validate({"suggestion": {"private": "secret"}})

    response = invoke(action)
    assert response.status_code == 502
    assert json.loads(response.body)["error"]["diagnostic"]["reason"] == "result_invalid"
    assert "private" not in caplog.text + response.body.decode()


def test_diagnostic_helpers_outside_scope_do_not_retain_state():
    diagnostics.mark("transport", "timeout")
    diagnostics.billing_response(b"private")
    diagnostics.transport_status(200)
    diagnostics.usage(1, 2)
    assert diagnostics.failure(502, 0) is None
    assert diagnostics.TRACE.get() is None


@pytest.mark.parametrize(
    ("body", "reason", "finish"),
    [
        (
            {"choices": [{"finish_reason": "stop", "message": {"content": "text"}}]},
            "provider_envelope_invalid",
            "stop",
        ),
        ({"choices": [{"finish_reason": "length"}]}, "output_truncated", "length"),
        ({"choices": [{"finish_reason": "content_filter"}]}, "response_refused", "content_filter"),
        ({"choices": [{"message": {"refusal": "private"}}]}, "response_refused", None),
        ({"choices": [{"finish_reason": "tool_calls"}]}, "tool_call", "tool_calls"),
        ({"choices": [{"finish_reason": "function_call"}]}, "tool_call", "function_call"),
        ({"choices": [{"message": {"tool_calls": [{"id": "private"}]}}]}, "tool_call", None),
        ({"choices": [{"message": {"function_call": {"name": "private"}}}]}, "tool_call", None),
        ({"choices": [{"message": {"content": " "}}]}, "empty_output", None),
        ({"choices": [{"message": {"content": "가" * 90000}}]}, "response_too_large", None),
        (
            {"choices": [{"finish_reason": "private", "message": {"content": None}}]},
            "provider_envelope_invalid",
            None,
        ),
        ({"choices": []}, "provider_envelope_invalid", None),
        ({"choices": [{}, {}]}, "provider_envelope_invalid", None),
        ({"choices": "private"}, "provider_envelope_invalid", None),
    ],
)
def test_legacy_chat_probe_remains_safe(body, reason, finish, caplog):
    with diagnostics.scope():
        diagnostics.mark("transport", "upstream_http")
        diagnostics.billing_response(json.dumps(body).encode())
        result = diagnostics.failure(502, 0)
    assert result.reason == reason
    assert f"finish={finish}" in caplog.text
    assert "private" not in caplog.text


@pytest.mark.parametrize(
    ("counts", "expected"),
    [
        ({"prompt_tokens": 3, "completion_tokens": 8}, "input_tokens=3 output_tokens=8"),
        ({"prompt_tokens": True}, "input_tokens=None output_tokens=None"),
        (None, "input_tokens=None output_tokens=None"),
    ],
)
def test_legacy_chat_usage_is_independently_validated(counts, expected, caplog):
    with diagnostics.scope():
        diagnostics.mark("transport", "upstream_http")
        diagnostics.billing_response(json.dumps({"usage": counts}).encode())
        diagnostics.failure(502, 0)
    assert expected in caplog.text
