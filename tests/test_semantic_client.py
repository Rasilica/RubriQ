import json
from unittest.mock import MagicMock, patch

import pytest
from billing_json_helpers import responses_body
from pydantic import SecretStr
from test_cloud_client import response_body

from submission.cloud_client import INFERENCE
from submission.cloud_contracts import CloudError, Provider, TextCompletion
from submission.semantic_client import complete
from submission.semantic_contracts import AIRequest


@pytest.mark.parametrize("provider", [*Provider, "ollama"])
def test_semantic_large_output_when_provider_completes(provider):
    # Given: structured outputs exceed the old passage-rewrite cap.
    text = json.dumps({"items": "x" * 9000})
    connection = MagicMock()
    connection.getresponse.return_value.status = 200
    if provider == "ollama":
        connection.getresponse.return_value.read.side_effect = [
            b'{"models":[{"name":"model-1"}]}',
            b'{"capabilities":["completion"]}',
            json.dumps(
                {
                    "model": "model-1",
                    "done": True,
                    "done_reason": "stop",
                    "message": {"role": "assistant", "content": text},
                }
            ).encode(),
        ]
        target = "submission.ollama_client.HTTPConnection"
    else:
        body = json.dumps(
            responses_body(text) if provider == Provider.BILLINGAI else response_body(provider)
        )
        if provider != Provider.BILLINGAI:
            body = body.replace("Revised", text.replace('"', '\\"'))
        connection.getresponse.return_value.read.return_value = body.encode()
        target = "submission.cloud_client.HTTPSConnection"
    request = AIRequest(provider=provider, model="model-1", consent=True)
    # When: the real transport boundary receives the provider envelope.
    with patch(target, return_value=connection) as transport:
        result = complete(request, "instructions", "{}", SecretStr("test-key"))
    # Then: the complete JSON survives without truncation.
    assert result.suggestion == text
    assert connection.request.call_count == (3 if provider == "ollama" else 1)
    assert transport.call_args.kwargs["timeout"] == (300 if provider == Provider.BILLINGAI else 180)


@pytest.mark.parametrize(
    "text", [" ", "test-key", "가" * 90000], ids=["blank", "secret", "byte-limit"]
)
def test_secret_blank_or_oversized_output_rejected(text):

    request = AIRequest(provider="openai", model="model", consent=True)
    with (
        patch(
            "submission.semantic_client.generate_text", return_value=TextCompletion(suggestion=text)
        ),
        pytest.raises(CloudError, match="cloud_invalid_response"),
    ):
        complete(request, "instructions", "{}", SecretStr("test-key"))


def test_semantic_busy_shares_rewrite_lock():

    request = AIRequest(provider="openai", model="model", consent=True)
    with (
        INFERENCE,
        patch("submission.semantic_client.generate_text") as call,
        pytest.raises(CloudError, match="cloud_busy"),
    ):
        complete(request, "instructions", "{}", SecretStr("test-key"))
    call.assert_not_called()


def test_provider_envelope_invalid_is_safe():
    connection = MagicMock()
    connection.getresponse.return_value.status = 200
    connection.getresponse.return_value.read.return_value = b"private-invalid-json"
    request = AIRequest(provider="openai", model="model", consent=True)
    with (
        patch("submission.cloud_client.HTTPSConnection", return_value=connection),
        pytest.raises(CloudError, match="cloud_invalid_response"),
    ):
        complete(request, "instructions", "{}", SecretStr("test-key"))
