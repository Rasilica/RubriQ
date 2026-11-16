import json
from unittest.mock import patch

import pytest
import test_cloud_routes
import test_semantic_routes
from billing_json_helpers import responses_body
from test_billing_client import billing_body, billing_connection
from test_semantic_routes import check, confirm, extract, provider_response

from submission.cloud_client import INFERENCE

prepared = test_cloud_routes.prepared
semantic_setup = test_semantic_routes.setup


def test_billing_rewrite_route_when_selected_text_sent(prepared):
    # Given: a real uploaded document and mocked HTTPS connection only.
    client, data, headers, block, payload = prepared
    connection = billing_connection(billing_body())
    path = f"/api/document-pairs/{data['session_id']}"
    # When: the user requests a BillingAI rewrite.
    with patch("submission.cloud_client.HTTPSConnection", return_value=connection):
        response = client.post(
            path + "/report/cloud-rewrite",
            headers=headers,
            json={**payload, "provider": "billingai", "model": "gpt-5-4"},
        )
    # Then: the response preserves the document and sends only the selection.
    assert response.status_code == 200
    result = response.json()["data"]
    assert result["provider"] == "billingai"
    assert result["original"] == block["raw_text"][1:5]
    assert result["suggestion"] == "Revised"
    body = json.loads(connection.request.call_args.kwargs["body"])
    assert body["messages"][1]["content"] == block["raw_text"][1:5]
    assert client.get(path, headers=headers).json()["data"]["report"] == data["report"]
    assert response.headers["cache-control"] == "no-store"
    assert "canary-secret" not in response.text


def test_billing_extract_confirm_check_when_transport_returns_valid_json(semantic_setup):
    # Given: real semantic routes with only the outgoing HTTPS connection replaced.
    connection = billing_connection({})

    def response_bytes(_size):
        request = json.loads(connection.request.call_args.kwargs["body"])
        content = provider_response(None, None, request["input"], None)
        return json.dumps(responses_body(content.suggestion)).encode()

    connection.getresponse.return_value.read.side_effect = response_bytes
    # When: the user extracts requirements, confirms them, and checks the report.
    with patch("submission.cloud_client.HTTPSConnection", return_value=connection) as transport:
        draft_response = extract(semantic_setup, provider="billingai", model="gpt-5-4")
        assert draft_response.status_code == 200
        draft = draft_response.json()["data"]
        confirmed_response = confirm(semantic_setup, draft)
        assert confirmed_response.status_code == 200
        confirmed = confirmed_response.json()["data"]
        response = check(semantic_setup, confirmed, provider="billingai", model="gpt-5-4")
    # Then: both cloud calls execute through the fixed endpoint and bind confirmed criteria.
    assert response.status_code == 200
    result = response.json()["data"]["result"]
    assert draft["provider"] == "billingai"
    assert draft["usage"] == {"input_tokens": 12, "output_tokens": 34}
    assert result["criteria_sha256"] == confirmed["criteria_sha256"]
    assert result["ai_called"] is True
    assert result["semantic_accuracy_verified"] is False
    assert connection.request.call_count == 2
    assert transport.call_count == 2
    for request in connection.request.call_args_list:
        body = json.loads(request.kwargs["body"])
        assert request.args == ("POST", "/api/v1/responses")
        assert request.kwargs["headers"]["Authorization"] == "Bearer test-key"
        assert body["model"] == "gpt-5-4"
        assert body["max_output_tokens"] == 8192
        assert body["text"] == {"format": {"type": "json_object"}}
        assert "store" not in body
        assert "previous_response_id" not in body
        assert body["stream"] is False
        assert b"test-key" not in request.kwargs["body"]
    assert "test-key" not in response.text


@pytest.mark.parametrize(
    "overrides",
    [{"model": "openai/gpt-5-4"}, {"model": "https://bad"}, {"consent": False}],
)
def test_billing_invalid_inputs_never_connect(prepared, semantic_setup, overrides):
    # Given: invalid model names or absent consent on both request contracts.
    client, data, headers, _, payload = prepared
    # When: rewrite and extraction requests are submitted.
    with patch("submission.cloud_client.HTTPSConnection") as transport:
        rewrite_response = client.post(
            f"/api/document-pairs/{data['session_id']}/report/cloud-rewrite",
            headers=headers,
            json={**payload, "provider": "billingai", **overrides},
        )
        extraction_response = extract(semantic_setup, provider="billingai", **overrides)
    # Then: validation rejects them before credentials can leave the process.
    assert rewrite_response.status_code == 422
    assert extraction_response.status_code == 422
    transport.assert_not_called()


@pytest.mark.parametrize(
    ("status", "code"),
    [(401, "cloud_auth_failed"), (429, "cloud_rate_limited"), (302, "cloud_unavailable")],
)
def test_billing_http_failure_is_safe_on_real_routes(prepared, semantic_setup, status, code):
    # Given: the provider responds with an auth, quota, or redirect failure.
    client, data, headers, _, payload = prepared
    connection = billing_connection({})
    connection.getresponse.return_value.status = status
    # When: rewrite and extraction traverse their real services.
    with patch("submission.cloud_client.HTTPSConnection", return_value=connection):
        response = client.post(
            f"/api/document-pairs/{data['session_id']}/report/cloud-rewrite",
            headers=headers,
            json={**payload, "provider": "billingai"},
        )
        extraction_response = extract(semantic_setup, provider="billingai")
    # Then: both return safe error codes without response body or credential leakage.
    assert response.json()["error"]["code"] == code
    assert extraction_response.json()["error"]["code"] == code
    assert "canary-secret" not in response.text
    assert "test-key" not in extraction_response.text
    connection.getresponse.return_value.read.assert_not_called()
    assert not INFERENCE.locked()


def test_billing_quota_and_busy_lock_when_admissions_exhausted(prepared):
    # Given: a real rewrite route sharing the existing inference lock.
    client, data, headers, _, payload = prepared
    connection = billing_connection(billing_body())
    path = f"/api/document-pairs/{data['session_id']}/report/cloud-rewrite"
    request = {**payload, "provider": "billingai"}
    # When: one busy admission is followed by enough successful requests to exhaust quota.
    with patch("submission.cloud_client.HTTPSConnection", return_value=connection) as transport:
        with INFERENCE:
            busy = client.post(path, headers=headers, json=request)
        transport.assert_not_called()
        responses = [client.post(path, headers=headers, json=request) for _ in range(10)]
    # Then: existing admission quota and lock semantics apply to BillingAI too.
    assert busy.status_code == 409
    assert busy.json()["error"]["code"] == "cloud_busy"
    assert [response.status_code for response in responses] == [200] * 9 + [429]
    assert connection.request.call_count == 9


@pytest.mark.parametrize(
    "text", [" ", "canary-secret test-key", "x" * 262145], ids=["blank", "key-echo", "output-limit"]
)
def test_billing_invalid_output_is_safe_on_real_routes(prepared, semantic_setup, text):
    # Given: HTTP success contains invalid text or an echoed test credential.
    client, data, headers, _, payload = prepared
    connection = billing_connection(billing_body(text))
    # When: rewrite and extraction process the provider response.
    with patch("submission.cloud_client.HTTPSConnection", return_value=connection):
        response = client.post(
            f"/api/document-pairs/{data['session_id']}/report/cloud-rewrite",
            headers=headers,
            json={**payload, "provider": "billingai"},
        )
        connection.getresponse.return_value.read.return_value = json.dumps(
            responses_body(text)
        ).encode()
        extraction_response = extract(semantic_setup, provider="billingai")
    # Then: callers see only sanitized errors, with no semantic state committed.
    for failure in (response, extraction_response):
        assert failure.status_code == 502
        assert failure.json()["error"]["code"] == "cloud_invalid_response"
        assert "canary-secret" not in failure.text
        assert "test-key" not in failure.text
    _, store, session, _, _ = semantic_setup
    with store.lease(session.identifier, session.token) as current:
        assert current.semantic_state is None


@pytest.mark.parametrize(
    ("invalid", "status", "reason"),
    [
        ("[]", 502, "malformed_json"),
        ("{} trailing", 502, "malformed_json"),
        ('{"items":', 502, "malformed_json"),
        ("{}", 422, "report_contract_invalid"),
        ("citation", 422, "citation_invalid"),
    ],
)
def test_billing_check_failure_preserves_confirmed_state_and_can_retry(
    semantic_setup, invalid, status, reason
):
    connection = billing_connection({})

    def response_bytes(_size):
        request = json.loads(connection.request.call_args.kwargs["body"])
        payload = request["input"]
        result = provider_response(None, None, payload, None)
        return json.dumps(responses_body(result.suggestion)).encode()

    connection.getresponse.return_value.read.side_effect = response_bytes
    with patch("submission.cloud_client.HTTPSConnection", return_value=connection):
        draft = extract(semantic_setup, provider="billingai").json()["data"]
        confirmed = confirm(semantic_setup, draft).json()["data"]
        _, store, session, _, _ = semantic_setup
        with store.lease(session.identifier, session.token) as current:
            before = current.semantic_state
            revision = current.semantic_revision
        if invalid == "citation":

            def invalid_bytes(size):
                envelope = json.loads(response_bytes(size))
                content = json.loads(envelope["output"][1]["content"][0]["text"])
                request = json.loads(connection.request.call_args.kwargs["body"])
                block = json.loads(request["input"])["blocks"][0]
                content["items"][0]["evidence"] = [
                    {
                        "citation": {
                            "block_id": block["block_id"],
                            "char_range": {"start": 0, "end": 1},
                            "quote": "invented",
                        },
                        "evidence_role": "content",
                        "relation": "claim",
                    }
                ]
                return json.dumps(responses_body(json.dumps(content))).encode()

            connection.getresponse.return_value.read.side_effect = invalid_bytes
        else:
            connection.getresponse.return_value.read.side_effect = None
            connection.getresponse.return_value.read.return_value = json.dumps(
                responses_body(invalid)
            ).encode()
        response = check(semantic_setup, confirmed, provider="billingai")
        assert response.status_code == status
        assert response.json()["error"]["diagnostic"]["reason"] == reason
        assert connection.request.call_count == 2
        assert not INFERENCE.locked()
        with store.lease(session.identifier, session.token) as current:
            assert current.semantic_state == before
            assert current.semantic_state.check is None
            assert current.semantic_revision == revision
        connection.getresponse.return_value.read.side_effect = response_bytes
        retry = check(semantic_setup, confirmed, provider="billingai")
    assert retry.status_code == 200
    assert connection.request.call_count == 3
    assert retry.json()["data"]["result"]["criteria_sha256"] == confirmed["criteria_sha256"]
