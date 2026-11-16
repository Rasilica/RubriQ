from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from submission.main import create_app
from submission.ollama_contracts import OllamaCode, OllamaError, OllamaModels


@pytest.fixture
def prepared(text_pdf):
    with TestClient(create_app()) as client:
        response = client.post(
            "/api/document-pairs",
            data={"project_name": "rewrite"},
            files={
                "guide": ("guide.pdf", text_pdf),
                "report": ("report.pdf", text_pdf),
            },
        )
        data = response.json()["data"]
        headers = {"X-Session-Token": data["access_token"], "X-Local-Client": "prepare"}
        block = data["report"]["document"]["blocks"][0]
        yield client, data, headers, block


def test_rewrite_returns_only_server_selected_text_and_preserves_document(prepared):
    client, data, headers, block = prepared
    path = f"/api/document-pairs/{data['session_id']}"
    with patch("submission.ollama_routes.rewrite", return_value="Suggested") as inference:
        response = client.post(
            path + "/report/ollama-rewrite",
            headers=headers,
            json={
                "block_id": block["block_id"],
                "start": 1,
                "end": 5,
                "model": "local:latest",
            },
        )
    assert response.status_code == 200
    result = response.json()["data"]
    assert result["original"] == block["raw_text"][1:5]
    inference.assert_called_once_with("local:latest", block["raw_text"][1:5])
    assert result["suggestion"] == "Suggested"
    assert result["llm_executed"] is True
    assert response.headers["cache-control"] == "no-store"
    assert client.get(path, headers=headers).json()["data"]["report"] == data["report"]


@pytest.mark.parametrize(
    "kind", ["missing_client", "wrong_token", "wrong_block", "bounds", "extra_text"]
)
def test_rejected_rewrites_never_contact_ollama(prepared, kind):
    client, data, headers, block = prepared
    payload = {"block_id": block["block_id"], "start": 0, "end": 5, "model": "local"}
    expected = 422
    if kind == "missing_client":
        headers = {"X-Session-Token": data["access_token"]}
        expected = 403
    elif kind == "wrong_token":
        headers = {**headers, "X-Session-Token": "wrong"}
        expected = 404
    elif kind == "wrong_block":
        payload = {**payload, "block_id": "absent"}
    elif kind == "bounds":
        payload = {**payload, "end": 4001}
    else:
        payload = {**payload, "original": "injected"}
    with patch("submission.ollama_routes.rewrite") as inference:
        response = client.post(
            f"/api/document-pairs/{data['session_id']}/report/ollama-rewrite",
            headers=headers,
            json=payload,
        )
    assert response.status_code == expected
    inference.assert_not_called()


def test_models_require_lease_and_return_no_store(prepared):
    client, data, headers, _ = prepared
    path = "/api/document-pairs/ollama/models?session_id=" + data["session_id"]
    with patch(
        "submission.ollama_routes.list_models", return_value=OllamaModels(models=())
    ) as call:
        assert client.get(path).status_code == 403
        assert client.get(path, headers={**headers, "X-Session-Token": "bad"}).status_code == 404
        response = client.get(path, headers=headers)
    call.assert_called_once()
    assert response.json()["data"] == {"provider": "ollama", "models": []}
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize("endpoint", ["models", "rewrite"])
def test_safe_provider_failure(prepared, endpoint):
    client, data, headers, block = prepared
    with patch(
        "submission.ollama_routes." + ("list_models" if endpoint == "models" else "rewrite"),
        side_effect=OllamaError(OllamaCode.UNAVAILABLE),
    ):
        if endpoint == "models":
            result = client.get(
                "/api/document-pairs/ollama/models?session_id=" + data["session_id"],
                headers=headers,
            )
        else:
            result = client.post(
                f"/api/document-pairs/{data['session_id']}/report/ollama-rewrite",
                headers=headers,
                json={"block_id": block["block_id"], "start": 0, "end": 5, "model": "local"},
            )
    assert result.status_code == 503
    assert result.json()["error"]["code"] == "ollama_unavailable"
