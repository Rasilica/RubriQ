import json
from unittest.mock import MagicMock, patch

import pytest
from pydantic import SecretStr

from submission.cloud_client import INFERENCE, rewrite
from submission.cloud_contracts import CloudError, Provider


def response_body(provider):
    match provider:
        case Provider.GEMINI:
            return {
                "candidates": [
                    {"finishReason": "STOP", "content": {"parts": [{"text": "Revised"}]}}
                ]
            }
        case Provider.OPENAI:
            return {
                "status": "completed",
                "output": [
                    {
                        "type": "message",
                        "role": "assistant",
                        "status": "completed",
                        "content": [{"type": "output_text", "text": "Revised"}],
                    }
                ],
            }
        case Provider.ANTHROPIC:
            return {"stop_reason": "end_turn", "content": [{"type": "text", "text": "Revised"}]}
        case Provider.BILLINGAI:
            return {
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"role": "assistant", "content": "Revised"},
                    }
                ],
            }


@pytest.mark.parametrize("provider", list(Provider))
def test_fixed_https_single_request_and_text_output(provider):
    connection = MagicMock()
    connection.getresponse.return_value.status = 200
    connection.getresponse.return_value.read.return_value = json.dumps(
        response_body(provider)
    ).encode()
    with patch("submission.cloud_client.HTTPSConnection", return_value=connection) as transport:
        result = rewrite(provider, "model-1", "Selected only", SecretStr("test-key"))
    assert result.suggestion == "Revised"
    assert transport.call_args.kwargs["timeout"] == 60
    assert transport.call_args.kwargs["context"].check_hostname
    assert transport.call_args.args[0] in {
        "generativelanguage.googleapis.com",
        "api.openai.com",
        "api.anthropic.com",
        "billing-ai.doubleze.ro",
    }
    connection.request.assert_called_once()
    request = connection.request.call_args
    payload = json.loads(request.kwargs["body"])
    assert "test-key" not in request.kwargs["body"].decode()
    assert "Selected only" in request.kwargs["body"].decode()
    assert "tools" not in payload
    if provider == Provider.OPENAI:
        assert payload["store"] is False
        assert payload["max_output_tokens"] == 1024
    elif provider == Provider.GEMINI:
        assert payload["generationConfig"]["maxOutputTokens"] == 1024
    else:
        assert payload["max_tokens"] == 1024


@pytest.mark.parametrize(
    ("status", "code"),
    [
        (401, "cloud_auth_failed"),
        (403, "cloud_auth_failed"),
        (429, "cloud_rate_limited"),
        (302, "cloud_unavailable"),
        (500, "cloud_unavailable"),
    ],
)
def test_provider_errors_are_sanitized(status, code):
    connection = MagicMock()
    connection.getresponse.return_value.status = status
    with (
        patch("submission.cloud_client.HTTPSConnection", return_value=connection),
        pytest.raises(CloudError) as caught,
    ):
        rewrite(Provider.OPENAI, "model", "text", SecretStr("test-key"))
    assert caught.value.code == code
    connection.getresponse.return_value.read.assert_not_called()


@pytest.mark.parametrize(
    "body",
    [
        b"bad-json",
        b"x" * (1024 * 1024 + 1),
        b'{"status":"incomplete","output":[]}',
        b'{"status":"completed","output":[{"type":"function_call"}]}',
    ],
)
def test_invalid_response_is_rejected(body):
    connection = MagicMock()
    connection.getresponse.return_value.status = 200
    connection.getresponse.return_value.read.return_value = body
    with (
        patch("submission.cloud_client.HTTPSConnection", return_value=connection),
        pytest.raises(CloudError, match="cloud_invalid_response"),
    ):
        rewrite(Provider.OPENAI, "model", "text", SecretStr("test-key"))


def test_busy_never_connects():
    with (
        INFERENCE,
        patch("submission.cloud_client.HTTPSConnection") as connect,
        pytest.raises(CloudError, match="cloud_busy"),
    ):
        rewrite(Provider.GEMINI, "model", "text", SecretStr("test-key"))
    connect.assert_not_called()


def test_openai_reasoning_metadata_is_discarded():
    connection = MagicMock()
    body = response_body(Provider.OPENAI)
    body["output"] = [
        {
            "type": "reasoning",
            "summary": [{"text": "private reasoning"}],
            "encrypted_content": "private bytes",
        },
        *body["output"],
    ]
    body["usage"] = {"input_tokens": 12, "output_tokens": 34}
    connection.getresponse.return_value.status = 200
    connection.getresponse.return_value.read.return_value = json.dumps(body).encode()
    with patch("submission.cloud_client.HTTPSConnection", return_value=connection):
        result = rewrite(Provider.OPENAI, "model", "text", SecretStr("test-key"))
    assert result.suggestion == "Revised"
    assert result.usage.input_tokens == 12
    assert result.usage.output_tokens == 34
    assert "private" not in result.model_dump_json()


@pytest.mark.parametrize(
    ("provider", "body"),
    [
        (Provider.OPENAI, {"status": "completed", "output": [{"type": "reasoning"}]}),
        (
            Provider.OPENAI,
            {
                "status": "completed",
                "output": [
                    {
                        "type": "message",
                        "role": "assistant",
                        "status": "completed",
                        "content": [{"type": "refusal", "refusal": "No"}],
                    }
                ],
            },
        ),
        (
            Provider.GEMINI,
            {
                "candidates": [
                    {"finishReason": "MAX_TOKENS", "content": {"parts": [{"text": "cut"}]}}
                ]
            },
        ),
        (
            Provider.GEMINI,
            {
                "candidates": [
                    {
                        "finishReason": "STOP",
                        "content": {"parts": [{"text": "thought", "thought": True}]},
                    }
                ]
            },
        ),
        (
            Provider.GEMINI,
            {
                "candidates": [
                    {
                        "finishReason": "STOP",
                        "content": {"parts": [{"functionCall": {"name": "test"}}]},
                    }
                ]
            },
        ),
        (
            Provider.ANTHROPIC,
            {"stop_reason": "max_tokens", "content": [{"type": "text", "text": "cut"}]},
        ),
        (
            Provider.ANTHROPIC,
            {"stop_reason": "end_turn", "content": [{"type": "tool_use", "name": "test"}]},
        ),
        (
            Provider.ANTHROPIC,
            {"stop_reason": "end_turn", "content": [{"type": "text", "text": " "}]},
        ),
        (
            Provider.ANTHROPIC,
            {"stop_reason": "end_turn", "content": [{"type": "text", "text": "test-key"}]},
        ),
    ],
)
def test_incomplete_tool_refusal_or_secret_output_is_rejected(provider, body):
    connection = MagicMock()
    connection.getresponse.return_value.status = 200
    connection.getresponse.return_value.read.return_value = json.dumps(body).encode()
    with (
        patch("submission.cloud_client.HTTPSConnection", return_value=connection),
        pytest.raises(CloudError, match="cloud_invalid_response"),
    ):
        rewrite(provider, "model", "text", SecretStr("test-key"))


@pytest.mark.parametrize(
    ("error", "code"),
    [(TimeoutError("private-key"), "cloud_timeout"), (OSError("private-key"), "cloud_unavailable")],
)
def test_network_failures_are_sanitized(error, code):
    with (
        patch("submission.cloud_client.HTTPSConnection", side_effect=error),
        pytest.raises(CloudError) as caught,
    ):
        rewrite(Provider.OPENAI, "model", "text", SecretStr("test-key"))
    assert str(caught.value) == code
    assert not INFERENCE.locked()


@pytest.mark.parametrize("provider", list(Provider))
def test_exact_provider_auth_endpoint_and_selected_text(provider):
    connection = MagicMock()
    connection.getresponse.return_value.status = 200
    connection.getresponse.return_value.read.return_value = json.dumps(
        response_body(provider)
    ).encode()
    with patch("submission.cloud_client.HTTPSConnection", return_value=connection) as transport:
        rewrite(provider, "model-1", "ONLY SELECTION", SecretStr("test-key"))
    request = connection.request.call_args
    body = json.loads(request.kwargs["body"])
    headers = request.kwargs["headers"]
    match provider:
        case Provider.GEMINI:
            assert transport.call_args.args == ("generativelanguage.googleapis.com",)
            assert request.args == ("POST", "/v1beta/models/model-1:generateContent")
            assert headers == {"Content-Type": "application/json", "x-goog-api-key": "test-key"}
            assert body["contents"] == [{"role": "user", "parts": [{"text": "ONLY SELECTION"}]}]
        case Provider.OPENAI:
            assert transport.call_args.args == ("api.openai.com",)
            assert request.args == ("POST", "/v1/responses")
            assert headers == {
                "Content-Type": "application/json",
                "Authorization": "Bearer test-key",
            }
            assert body["input"] == "ONLY SELECTION"
        case Provider.ANTHROPIC:
            assert transport.call_args.args == ("api.anthropic.com",)
            assert request.args == ("POST", "/v1/messages")
            assert headers == {
                "Content-Type": "application/json",
                "x-api-key": "test-key",
                "anthropic-version": "2023-06-01",
            }
            assert body["messages"] == [{"role": "user", "content": "ONLY SELECTION"}]
        case Provider.BILLINGAI:
            assert transport.call_args.args == ("billing-ai.doubleze.ro",)
            assert request.args == ("POST", "/api/v1/chat/completions")
            assert headers == {
                "Content-Type": "application/json",
                "Authorization": "Bearer test-key",
            }
            assert body["messages"][1] == {"role": "user", "content": "ONLY SELECTION"}


def test_gemini_blocked_safety_rating_rejects_even_stop_candidate():
    body = response_body(Provider.GEMINI)
    body["candidates"][0]["safetyRatings"] = [
        {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "blocked": True}
    ]
    connection = MagicMock()
    connection.getresponse.return_value.status = 200
    connection.getresponse.return_value.read.return_value = json.dumps(body).encode()
    with (
        patch("submission.cloud_client.HTTPSConnection", return_value=connection),
        pytest.raises(CloudError, match="cloud_invalid_response"),
    ):
        rewrite(Provider.GEMINI, "model", "text", SecretStr("test-key"))


def test_gemini_text_thought_signature_is_accepted_but_not_returned():
    body = response_body(Provider.GEMINI)
    body["candidates"][0]["content"]["parts"][0]["thoughtSignature"] = "private-signature"
    connection = MagicMock()
    connection.getresponse.return_value.status = 200
    connection.getresponse.return_value.read.return_value = json.dumps(body).encode()
    with patch("submission.cloud_client.HTTPSConnection", return_value=connection):
        result = rewrite(Provider.GEMINI, "model", "text", SecretStr("test-key"))
    assert result.suggestion == "Revised"
    assert "private-signature" not in result.model_dump_json()
