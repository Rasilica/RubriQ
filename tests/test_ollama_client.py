import json
from unittest.mock import MagicMock, patch

import pytest

from submission.ollama_client import INFERENCE, list_models, rewrite
from submission.ollama_contracts import OllamaError


def response(payload):
    result = MagicMock()
    result.status = 200
    result.read.return_value = json.dumps(payload).encode()
    return result


def test_local_rewrite_uses_bounded_chat():
    connection = MagicMock()
    connection.getresponse.side_effect = [
        response({"models": [{"name": "local:latest"}]}),
        response({"capabilities": ["completion"]}),
        response(
            {
                "model": "local:latest",
                "done_reason": "stop",
                "message": {"role": "assistant", "content": "Revised"},
                "done": True,
            }
        ),
    ]
    with patch("submission.ollama_client.HTTPConnection", return_value=connection):
        result = rewrite("local:latest", "Original")
    assert result == "Revised"
    payload = json.loads(connection.request.call_args.kwargs["body"])
    assert payload["messages"][1] == {"role": "user", "content": "Original"}
    assert payload["stream"] is False
    assert payload["options"]["num_predict"] == 1024
    assert "tools" not in payload


@pytest.mark.parametrize("metadata", [{"remote_host": "https://ollama.com"}, {"remote_model": "x"}])
def test_remote_metadata_rejected_before_text_sent(metadata):
    connection = MagicMock()
    connection.getresponse.side_effect = [
        response({"models": [{"name": "alias:latest"}]}),
        response({**metadata, "capabilities": ["completion"]}),
    ]
    with (
        patch("submission.ollama_client.HTTPConnection", return_value=connection),
        pytest.raises(OllamaError),
    ):
        rewrite("alias:latest", "PRIVATE")
    assert connection.request.call_count == 2
    assert "PRIVATE" not in str(connection.request.call_args_list)


def test_list_excludes_cloud_and_remote_models():
    connection = MagicMock()
    connection.getresponse.return_value = response(
        {
            "models": [
                {"name": "local:latest"},
                {"name": "x:cloud"},
                {"name": "alias", "remote_host": "https://ollama.com"},
            ]
        }
    )
    with patch("submission.ollama_client.HTTPConnection", return_value=connection):
        models = list_models()
    assert [item.name for item in models.models] == ["local:latest"]


@pytest.mark.parametrize(
    ("status", "content"), [(302, b"{}"), (200, b"x" * (1024 * 1024 + 1)), (200, b"bad")]
)
def test_bad_transport_response_is_safe(status, content):
    connection = MagicMock()
    reply = connection.getresponse.return_value
    reply.status, reply.read.return_value = status, content
    with (
        patch("submission.ollama_client.HTTPConnection", return_value=connection),
        pytest.raises(OllamaError),
    ):
        list_models()
    assert reply.read.call_args is None or reply.read.call_args.args == (1024 * 1024 + 1,)


@pytest.mark.parametrize(
    "payload",
    [
        {"models": [{"name": "local"}] * 101},
        {"models": [{"name": "local", "remote_host": 123}]},
    ],
)
def test_malformed_or_excessive_model_list_rejected(payload):
    connection = MagicMock()
    connection.getresponse.return_value = response(payload)
    with (
        patch("submission.ollama_client.HTTPConnection", return_value=connection),
        pytest.raises(OllamaError),
    ):
        list_models()


@pytest.mark.parametrize(
    "payload",
    [
        {"message": {"role": "assistant", "content": " "}, "done": True},
        {"message": {"role": "assistant", "content": "x" * 8001}, "done": True},
        {"message": {"role": "assistant", "content": "x", "tool_calls": [{}]}, "done": True},
        {"message": {"role": "assistant", "content": "x"}, "done": False},
        {"message": {"role": "assistant", "content": "x"}, "done": True, "remote_host": "cloud"},
    ],
)
def test_invalid_chat_output_rejected(payload):
    connection = MagicMock()
    connection.getresponse.side_effect = [
        response({"models": [{"name": "local"}]}),
        response({"capabilities": ["completion"]}),
        response({"model": "local", "done_reason": "stop", **payload}),
    ]
    with (
        patch("submission.ollama_client.HTTPConnection", return_value=connection),
        pytest.raises(OllamaError),
    ):
        rewrite("local", "Original")


def test_unknown_model_does_not_send_selection():
    connection = MagicMock()
    connection.getresponse.return_value = response({"models": []})
    with (
        patch("submission.ollama_client.HTTPConnection", return_value=connection),
        pytest.raises(OllamaError),
    ):
        rewrite("absent", "PRIVATE")
    assert connection.request.call_count == 1


def test_concurrent_inference_is_rejected_without_queue():
    with (
        INFERENCE,
        patch("submission.ollama_client.HTTPConnection") as connection,
        pytest.raises(OllamaError) as error,
    ):
        rewrite("local", "Original")
    assert error.value.status == 409
    connection.assert_not_called()


def test_unavailable_transport_returns_safe_error():
    with (
        patch("submission.ollama_client.HTTPConnection", side_effect=OSError("private path")),
        pytest.raises(OllamaError) as error,
    ):
        list_models()
    assert str(error.value) == "ollama_unavailable"


@pytest.mark.parametrize(
    "metadata",
    [
        {"done_reason": "length"},
        {"done_reason": "unknown"},
        {"model": "different"},
    ],
)
def test_incomplete_or_mismatched_completion_is_rejected(metadata):
    connection = MagicMock()
    connection.getresponse.side_effect = [
        response({"models": [{"name": "local"}]}),
        response({"capabilities": ["completion"]}),
        response(
            {
                "model": "local",
                "done_reason": "stop",
                "done": True,
                "message": {"role": "assistant", "content": "Unfinished"},
                **metadata,
            }
        ),
    ]
    with (
        patch("submission.ollama_client.HTTPConnection", return_value=connection),
        pytest.raises(OllamaError) as error,
    ):
        rewrite("local", "Original")
    assert str(error.value) == "ollama_invalid_response"


def test_transport_timeout_is_reported_as_timeout():
    with (
        patch("submission.ollama_client.HTTPConnection", side_effect=TimeoutError),
        pytest.raises(OllamaError) as error,
    ):
        list_models()
    assert str(error.value) == "ollama_timeout"
    assert error.value.status == 504
