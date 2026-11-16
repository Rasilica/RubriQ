import json
from unittest.mock import patch

import pytest
import test_semantic_routes
from billing_json_helpers import responses_body
from pydantic import SecretStr
from test_billing_client import billing_connection
from test_citation_reference_wire import request
from test_semantic_routes import check, confirm, extract, provider_response

from submission.cloud_client import INFERENCE
from submission.cloud_contracts import CloudError, Provider, TextCompletion
from submission.semantic_client import complete
from submission.semantic_contracts import AIRequest

semantic_setup = test_semantic_routes.setup


def test_billing_reference_citation_on_actual_report_route(semantic_setup):
    connection = billing_connection({})

    def response_bytes(_size):
        body = json.loads(connection.request.call_args.kwargs["body"])
        outgoing = json.loads(body["input"])
        response = json.loads(provider_response(None, None, body["input"], None).suggestion)
        if "report_source_id" in outgoing:
            block = outgoing["blocks"][0]
            response["items"][0]["evidence"] = [
                {
                    "citation": {"citation_ref": block["citation_refs"][0]["citation_ref"]},
                    "evidence_role": "content",
                    "relation": "근거",
                }
            ]
        else:
            assert all("citation_refs" not in block for block in outgoing["blocks"])
        return json.dumps(responses_body(json.dumps(response))).encode()

    connection.getresponse.return_value.read.side_effect = response_bytes
    with patch("submission.cloud_client.HTTPSConnection", return_value=connection):
        draft = extract(semantic_setup, provider="billingai").json()["data"]
        confirmed = confirm(semantic_setup, draft).json()["data"]
        response = check(semantic_setup, confirmed, provider="billingai", model="gpt-6-luna")
    assert response.status_code == 200
    result = response.json()["data"]["result"]
    citation = result["items"][0]["evidence"][0]["citation"]
    _, store, session, _, _ = semantic_setup
    with store.lease(session.identifier, session.token) as current:
        block = next(
            block for block in current.report.view.document.blocks if block.raw_text.strip()
        )
    assert citation["block_id"] == block.block_id
    assert citation["quote"] == block.raw_text
    assert citation["char_range"] == {"start": 0, "end": len(block.raw_text)}
    assert result["reviewed_block_ids"] == result["submitted_block_ids"]
    assert "citation_ref" not in json.dumps(result)
    assert connection.request.call_count == 2
    assert not INFERENCE.locked()


@pytest.mark.parametrize("provider", [*Provider, "ollama"])
def test_reference_mode_is_only_billing_report(provider):
    target = {
        "billingai": "generate_json",
        "ollama": "generate",
    }.get(provider, "generate_text")
    result = "{}" if provider == "ollama" else TextCompletion(suggestion="{}")
    with patch(f"submission.semantic_client.{target}", return_value=result) as call:
        complete(
            AIRequest(provider=provider, model="model", consent=True),
            "",
            request(),
            SecretStr("test-key"),
        )
    index = 1 if provider in (Provider.BILLINGAI, "ollama") else 2
    outgoing = json.loads(call.call_args.args[index])
    assert ("citation_refs" in outgoing["blocks"][0]) == (provider == Provider.BILLINGAI)


def test_reference_expansion_still_obeys_output_byte_limit_and_releases_lock():
    response = json.dumps(
        {"items": [{"evidence": [{"citation": {"citation_ref": "q0"}} for _ in range(30)]}]}
    )
    assert len(response.encode()) < 262144
    with (
        patch(
            "submission.semantic_client.generate_json",
            return_value=TextCompletion(suggestion=response),
        ),
        pytest.raises(CloudError, match="cloud_invalid_response"),
    ):
        complete(
            AIRequest(provider="billingai", model="model", consent=True),
            "",
            request("한" * 10000),
            SecretStr("test-key"),
        )
    assert not INFERENCE.locked()


def test_reference_expansion_cannot_bypass_secret_output_guard():
    response = json.dumps({"items": [{"evidence": [{"citation": {"citation_ref": "q0"}}]}]})
    with (
        patch(
            "submission.semantic_client.generate_json",
            return_value=TextCompletion(suggestion=response),
        ),
        pytest.raises(CloudError, match="cloud_invalid_response") as error,
    ):
        complete(
            AIRequest(provider="billingai", model="model", consent=True),
            "",
            request("한글 test-key 원문"),
            SecretStr("test-key"),
        )
    assert "test-key" not in str(error.value)
    assert not INFERENCE.locked()


@pytest.mark.parametrize("failure", ["unknown", "extra", "scope"])
def test_invalid_reference_or_scope_is_rejected_without_committing_result(semantic_setup, failure):
    connection = billing_connection({})

    def response_bytes(_size):
        body = json.loads(connection.request.call_args.kwargs["body"])
        outgoing = json.loads(body["input"])
        response = json.loads(provider_response(None, None, body["input"], None).suggestion)
        if "report_source_id" in outgoing:
            citation = {"citation_ref": "not-submitted" if failure == "unknown" else "q0"}
            if failure == "extra":
                citation = {**citation, "quote": "untrusted"}
            response["items"][0]["evidence"] = [
                {
                    "citation": citation,
                    "evidence_role": "content",
                    "relation": "근거",
                }
            ]
            if failure == "scope":
                response["reviewed_block_ids"] = ["q0"]
        return json.dumps(responses_body(json.dumps(response))).encode()

    connection.getresponse.return_value.read.side_effect = response_bytes
    with patch("submission.cloud_client.HTTPSConnection", return_value=connection):
        draft = extract(semantic_setup, provider="billingai").json()["data"]
        confirmed = confirm(semantic_setup, draft).json()["data"]
        response = check(semantic_setup, confirmed, provider="billingai")
    assert response.status_code == 422
    _, store, session, _, _ = semantic_setup
    with store.lease(session.identifier, session.token) as current:
        assert current.semantic_state.check is None
    assert not INFERENCE.locked()
