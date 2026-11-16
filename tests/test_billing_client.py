import json
from unittest.mock import MagicMock, patch

import pytest
from billing_json_helpers import responses_body
from pydantic import SecretStr

from submission.cloud_client import INFERENCE, MAX_RESPONSE, rewrite
from submission.cloud_contracts import CloudError, Provider
from submission.semantic_client import complete
from submission.semantic_contracts import AIRequest


def billing_body(text="Revised", **overrides):
    return {
        "choices": [{"finish_reason": "stop", "message": {"role": "assistant", "content": text}}],
        "usage": {"prompt_tokens": 12, "completion_tokens": 34},
        **overrides,
    }


def billing_connection(body):
    connection = MagicMock()
    connection.getresponse.return_value.status = 200
    connection.getresponse.return_value.read.return_value = json.dumps(body).encode()
    return connection


@pytest.mark.parametrize("model", ["gpt-5-4", "claude-sonnet-4-6", "gemini-2-5-flash"])
def test_billing_rewrite_when_text_completion_succeeds(model):
    # Given: a completed chat response with optional usage metadata.
    connection = billing_connection(billing_body())
    # When: the real client dispatches the selected passage.
    with patch("submission.cloud_client.HTTPSConnection", return_value=connection) as transport:
        result = rewrite(Provider("billingai"), model, "Selected only", SecretStr("test-key"))
    # Then: the fixed TLS endpoint receives one request and no credential in its body.
    assert transport.call_count == 1
    assert transport.call_args.args == ("billing-ai.doubleze.ro",)
    assert transport.call_args.kwargs["timeout"] == 60
    assert transport.call_args.kwargs["context"].check_hostname
    request = connection.request.call_args
    assert request.args == ("POST", "/api/v1/chat/completions")
    assert request.kwargs["headers"] == {
        "Content-Type": "application/json",
        "Authorization": "Bearer test-key",
    }
    body = json.loads(request.kwargs["body"])
    assert set(body) == {"model", "messages", "max_tokens", "stream"}
    assert body["model"] == model
    assert body["messages"][0]["role"] == "system"
    assert body["messages"][0]["content"]
    assert body["messages"][1] == {"role": "user", "content": "Selected only"}
    assert len(body["messages"]) == 2
    assert body["max_tokens"] == 1024
    assert body["stream"] is False
    assert b"test-key" not in request.kwargs["body"]
    assert result.suggestion == "Revised"
    assert result.usage.input_tokens == 12
    assert result.usage.output_tokens == 34
    connection.request.assert_called_once()
    connection.getresponse.return_value.read.assert_called_once_with(MAX_RESPONSE + 1)
    connection.close.assert_called_once()


@pytest.mark.parametrize(
    "body",
    [
        {"choices": []},
        {"choices": billing_body()["choices"] * 2},
        *[
            billing_body(
                choices=[
                    {
                        "finish_reason": reason,
                        "message": {
                            "role": "assistant",
                            "content": "Partial",
                        },
                    }
                ]
            )
            for reason in ("length", "content_filter", "tool_calls", "function_call", None)
        ],
        *[
            billing_body(choices=[{"finish_reason": "stop", "message": message}])
            for message in (
                {"role": "user", "content": "Wrong role"},
                {"role": "assistant", "content": None},
                {"role": "assistant", "content": []},
                {"role": "assistant", "content": "Text", "refusal": "Refused"},
                {"role": "assistant", "content": "Text", "tool_calls": [{"id": "tool"}]},
                {"role": "assistant", "content": "Text", "function_call": {"name": "tool"}},
            )
        ],
        *[billing_body(text) for text in ("", " ", "test-key", "x" * 8001)],
        *[
            billing_body(usage=usage)
            for usage in (
                None,
                {"prompt_tokens": -1},
                {"completion_tokens": "3"},
                {"prompt_tokens": True},
            )
        ],
    ],
)
def test_billing_rejects_invalid_envelopes_when_provider_returns_200(body):
    # Given: successful HTTP status with unsafe or invalid response contents.
    connection = billing_connection(body)
    # When: the real response parser and rewrite guard process the response.
    with (
        patch("submission.cloud_client.HTTPSConnection", return_value=connection),
        pytest.raises(CloudError, match="cloud_invalid_response") as caught,
    ):
        rewrite(Provider("billingai"), "gpt-5-4", "Selected", SecretStr("test-key"))
    # Then: the failure is sanitized and the shared lock is released.
    assert caught.value.status == 502
    assert not INFERENCE.locked()


@pytest.mark.parametrize("usage", [{}, {"prompt_tokens": None, "completion_tokens": None}])
def test_billing_usage_is_optional_when_counts_absent(usage):
    # Given: usage counts may be omitted or null.
    connection = billing_connection(billing_body(usage=usage))
    # When: the rewrite is completed.
    with patch("submission.cloud_client.HTTPSConnection", return_value=connection):
        result = rewrite(Provider("billingai"), "gpt-5-4", "Selected", SecretStr("test-key"))
    # Then: absent counts remain unknown.
    assert result.usage.input_tokens is None
    assert result.usage.output_tokens is None


def test_billing_keys_are_per_request_when_usage_omitted():
    # Given: responses omit usage and contain empty optional tool metadata.
    connection = billing_connection(
        {
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {
                        "role": "assistant",
                        "content": "Revised",
                        "refusal": None,
                        "tool_calls": [],
                    },
                }
            ]
        }
    )
    # When: separate invocations supply different ephemeral credentials.
    with patch("submission.cloud_client.HTTPSConnection", return_value=connection):
        results = [
            rewrite(Provider("billingai"), "gpt-5-4", "Selected", SecretStr(key))
            for key in ("first-test-key", "second-test-key")
        ]
    # Then: each request carries only its own key and no metadata leaks into results.
    assert [
        call.kwargs["headers"]["Authorization"] for call in connection.request.call_args_list
    ] == [
        "Bearer first-test-key",
        "Bearer second-test-key",
    ]
    for result in results:
        assert result.suggestion == "Revised"
        assert result.usage.input_tokens is None
        assert result.usage.output_tokens is None
        assert "test-key" not in result.model_dump_json()


@pytest.mark.parametrize(
    "text",
    [json.dumps({"items": "x" * 9000}), "x" * 262145, "가" * 90000, " ", "test-key"],
    ids=["large-valid", "character-limit", "byte-limit", "blank", "key-echo"],
)
def test_billing_semantic_output_when_large_or_invalid(text):
    # Given: semantic responses have a larger cap than passage rewrites.
    connection = billing_connection(responses_body(text))
    request = AIRequest(provider="billingai", model="gpt-5-4", consent=True)
    # When: the semantic client uses the same transport and provider parser.
    with patch("submission.cloud_client.HTTPSConnection", return_value=connection):
        if text.startswith("{"):
            result = complete(request, "Instructions", "{}", SecretStr("test-key"))
            assert result.suggestion == text
        else:
            with pytest.raises(CloudError, match="cloud_invalid_response"):
                complete(request, "Instructions", "{}", SecretStr("test-key"))
    # Then: semantic requests retain their output budget and the lock is released.
    body = json.loads(connection.request.call_args.kwargs["body"])
    assert body["max_output_tokens"] == 8192
    assert not INFERENCE.locked()


@pytest.mark.parametrize(
    "raw",
    [b"invalid json", b"x" * (MAX_RESPONSE + 1)],
    ids=["malformed", "wire-limit"],
)
def test_billing_rejects_bad_or_oversized_wire_response(raw):
    # Given: a malformed or oversized raw response.
    connection = billing_connection({})
    connection.getresponse.return_value.read.return_value = raw
    # When: the transport and parser consume it.
    with (
        patch("submission.cloud_client.HTTPSConnection", return_value=connection),
        pytest.raises(CloudError, match="cloud_invalid_response"),
    ):
        rewrite(Provider("billingai"), "gpt-5-4", "Selected", SecretStr("test-key"))
    # Then: the lock remains usable after failure.
    assert not INFERENCE.locked()
