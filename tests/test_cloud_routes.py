from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from submission.cloud_contracts import CloudCode, CloudError, Completion
from submission.main import create_app


@pytest.fixture
def prepared(text_pdf):
    with TestClient(create_app()) as client:
        data = client.post(
            "/api/document-pairs",
            data={"project_name": "cloud"},
            files={"guide": ("guide.pdf", text_pdf), "report": ("report.pdf", text_pdf)},
        ).json()["data"]
        headers = {
            "X-Session-Token": data["access_token"],
            "X-Local-Client": "prepare",
            "X-AI-API-Key": "canary-secret",
        }
        block = data["report"]["document"]["blocks"][0]
        payload = {
            "block_id": block["block_id"],
            "start": 1,
            "end": 5,
            "model": "model-1",
            "provider": "openai",
            "consent": True,
            "source_sha256": data["report"]["document"]["source"]["content_sha256"],
        }
        yield client, data, headers, block, payload


@pytest.mark.parametrize("provider", ["openai", "gemini", "anthropic"])
def test_cloud_selection_preserves_document(prepared, provider):
    client, data, headers, block, payload = prepared
    path = f"/api/document-pairs/{data['session_id']}"
    with patch(
        "submission.cloud_routes.rewrite", return_value=Completion(suggestion="Revised")
    ) as call:
        response = client.post(
            path + "/report/cloud-rewrite", headers=headers, json={**payload, "provider": provider}
        )
    assert response.status_code == 200
    result = response.json()["data"]
    assert result["provider"] == provider
    assert result["original"] == block["raw_text"][1:5]
    assert result["suggestion"] == "Revised"
    assert result["model"] == "model-1"
    assert result["source_sha256"] == payload["source_sha256"]
    assert call.call_args.args[2] == block["raw_text"][1:5]
    assert response.headers["cache-control"] == "no-store"
    assert client.get(path, headers=headers).json()["data"]["report"] == data["report"]
    assert "canary-secret" not in response.text


@pytest.mark.parametrize(
    ("change", "status"),
    [
        ({"consent": False}, 422),
        ({"consent": "true"}, 422),
        ({"source_sha256": "0" * 64}, 422),
        ({"block_id": "missing"}, 422),
        ({"start": -1}, 422),
        ({"end": 4001}, 422),
        ({"model": "../bad"}, 422),
        ({"provider": "other"}, 422),
        ({"original": "injected"}, 422),
    ],
)
def test_invalid_selection_never_dispatches(prepared, change, status):
    client, data, headers, _, payload = prepared
    with patch("submission.cloud_routes.rewrite") as call:
        response = client.post(
            f"/api/document-pairs/{data['session_id']}/report/cloud-rewrite",
            headers=headers,
            json={**payload, **change},
        )
    assert response.status_code == status
    call.assert_not_called()
    assert "canary-secret" not in response.text


@pytest.mark.parametrize(
    ("header", "value", "status"),
    [
        ("X-Session-Token", "wrong", 404),
        ("X-Local-Client", "", 403),
        ("X-AI-API-Key", "", 422),
        ("X-AI-API-Key", "x" * 513, 422),
        ("X-AI-API-Key", "secret with space", 422),
        ("X-AI-API-Key", "secret\nnewline", 422),
    ],
)
def test_invalid_headers_never_dispatch_or_echo(prepared, header, value, status):
    client, data, headers, _, payload = prepared
    with patch("submission.cloud_routes.rewrite") as call:
        response = client.post(
            f"/api/document-pairs/{data['session_id']}/report/cloud-rewrite",
            headers={**headers, header: value},
            json=payload,
        )
    assert response.status_code == status
    call.assert_not_called()
    assert "canary-secret" not in response.text
    if header == "X-AI-API-Key" and value:
        assert value not in response.text


def test_cloud_quota_counts_only_valid_admissions(prepared):
    client, data, headers, _, payload = prepared
    path = f"/api/document-pairs/{data['session_id']}/report/cloud-rewrite"
    with patch(
        "submission.cloud_routes.rewrite", return_value=Completion(suggestion="Revised")
    ) as call:
        for _ in range(11):
            assert (
                client.post(path, headers=headers, json={**payload, "consent": False}).status_code
                == 422
            )
        responses = [client.post(path, headers=headers, json=payload) for _ in range(11)]
    assert [r.status_code for r in responses] == [200] * 10 + [429]
    assert call.call_count == 10
    assert responses[-1].json()["error"]["code"] == "cloud_rate_limited"


def test_provider_failure_returns_safe_code(prepared):
    client, data, headers, _, payload = prepared
    with patch(
        "submission.cloud_routes.rewrite", side_effect=CloudError(CloudCode.AUTH_FAILED, 401)
    ):
        response = client.post(
            f"/api/document-pairs/{data['session_id']}/report/cloud-rewrite",
            headers=headers,
            json=payload,
        )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "cloud_auth_failed"
    assert "canary-secret" not in response.text
