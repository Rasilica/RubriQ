import json
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from report_check_helpers import context
from requirement_helpers import guide_document, response_payload

from submission.cloud_contracts import TextCompletion
from submission.main import create_app
from submission.models import DocumentRole
from submission.pair_contracts import PreparedRole, RoleView
from submission.pair_store import PairStore
from submission.semantic_client import PROVIDER_TIMEOUT
from submission.semantic_service import CHECK_LIMITS, REQUIREMENT_LIMITS


@pytest.fixture
def setup():
    now = [0.0]
    store = PairStore(clock=lambda: now[0], ttl=600)
    guide = guide_document()
    report = context().report
    samples = Path(__file__).resolve().parents[1] / "samples/pdf"
    roles = tuple(
        PreparedRole(
            RoleView(
                role=role,
                document=doc,
                extraction_status=doc.extraction_status,
                rendering_status=doc.extraction_status,
            ),
            (samples / name).read_bytes(),
        )
        for role, doc, name in (
            (DocumentRole.GUIDE, guide, "guide.pdf"),
            (DocumentRole.REPORT, report, "normal.pdf"),
        )
    )
    session = store.create("semantic", *roles)
    headers = {
        "X-Session-Token": session.token,
        "X-Local-Client": "prepare",
        "X-AI-API-Key": "test-key",
    }
    with (
        patch("submission.pair_routes.PairStore", return_value=store),
        TestClient(create_app()) as client,
    ):
        yield client, store, session, headers, now


def provider_response(_request, _instructions, raw, _key):
    data = json.loads(raw)
    if "criteria_sha256" not in data:
        return TextCompletion(suggestion=json.dumps(response_payload()))
    return TextCompletion(
        suggestion=json.dumps(
            {
                "schema_version": "1",
                "criteria_sha256": data["criteria_sha256"],
                "report_source_id": data["report_source_id"],
                "report_document_version_id": data["report_document_version_id"],
                "report_source_sha256": data["report_source_sha256"],
                "reviewed_block_ids": [block["block_id"] for block in data["blocks"]],
                "items": [
                    {
                        "requirement_id": item["requirement_id"],
                        "proposed_judgment": "evidence_missing",
                        "reason": "근거 미확인",
                        "evidence": [],
                        "subconditions": [
                            {
                                "subcondition_id": sub["subcondition_id"],
                                "proposed_judgment": "evidence_missing",
                                "reason": "미확인",
                                "evidence": [],
                            }
                            for sub in item["subconditions"]
                        ],
                    }
                    for item in data["criteria"]["items"]
                    if item["included"] and item["application_status"] == "applies"
                ],
            }
        )
    )


def extract(setup, **overrides):
    client, _, session, headers, _ = setup
    return client.post(
        f"/api/document-pairs/{session.identifier}/ai/requirements",
        headers=headers,
        json={
            "provider": "openai",
            "model": "model-1",
            "consent": True,
            "guide_sha256": session.guide.view.document.source.content_sha256,
            **overrides,
        },
    )


def confirm(setup, draft, **overrides):
    client, _, session, headers, _ = setup
    items = [
        {key: value for key, value in item.items() if key != "edited_fields"}
        for item in draft["items"]
    ]
    for item in items:
        if item["classification"] == "conditional":
            item.update(application_status="does_not_apply", application_reason="개인 제출")
    return client.post(
        f"/api/document-pairs/{session.identifier}/ai/criteria",
        headers=headers,
        json={
            "draft_id": draft["draft_id"],
            "expected_revision": draft["revision"],
            "items": items,
            **overrides,
        },
    )


def check(setup, draft, **overrides):
    client, _, session, headers, _ = setup
    return client.post(
        f"/api/document-pairs/{session.identifier}/ai/check",
        headers=headers,
        json={
            "provider": "openai",
            "model": "model-1",
            "consent": True,
            "draft_id": draft["draft_id"],
            "criteria_sha256": draft["criteria_sha256"] or "0" * 64,
            "guide_sha256": session.guide.view.document.source.content_sha256,
            "report_sha256": session.report.view.document.source.content_sha256,
            **overrides,
        },
    )


def test_confirmed_flow_when_live_provider_returns_valid_json(setup):
    # Given: session-bound real extracted documents and a wire-boundary provider stand-in.
    with patch("submission.semantic_service.complete", side_effect=provider_response):
        draft = extract(setup).json()["data"]
        confirmed = confirm(setup, draft).json()["data"]
        # When: the user checks the report after explicit confirmation.
        response = check(setup, confirmed)
    # Then: exact criteria and exclusions are applied without offline/fake stamps.
    assert response.status_code == 200
    result = response.json()["data"]["result"]
    assert result["items"][3]["applicability"] == "not_applicable"
    assert result["criteria_sha256"] == confirmed["criteria_sha256"]
    assert result["ai_called"] is True
    assert result["semantic_accuracy_verified"] is False
    assert not {"fake", "response_label", "adapter_id", "demo"} & result.keys()
    assert draft["confirmed"] is False
    assert confirmed["confirmed"] is True
    assert draft["ai_called"] is True
    assert confirmed["ai_called"] is True


@pytest.mark.parametrize(
    "headers",
    [{}, {"X-Local-Client": "prepare"}, {"X-Session-Token": "wrong", "X-Local-Client": "prepare"}],
)
def test_no_provider_call_when_auth_missing(setup, headers):
    client, _, session, _, _ = setup
    with patch("submission.semantic_service.complete") as call:
        response = client.post(
            f"/api/document-pairs/{session.identifier}/ai/requirements",
            headers=headers,
            json={
                "provider": "openai",
                "model": "model",
                "consent": True,
                "guide_sha256": session.guide.view.document.source.content_sha256,
            },
        )
    assert response.status_code in {403, 404}
    call.assert_not_called()


@pytest.mark.parametrize(
    "overrides", [{"consent": False}, {"guide_sha256": "0" * 64}, {"model": "https://bad"}]
)
def test_no_provider_call_when_request_invalid(setup, overrides):
    with patch("submission.semantic_service.complete") as call:
        response = extract(setup, **overrides)
    assert response.status_code in {409, 422}
    call.assert_not_called()


@pytest.mark.parametrize("bad", ["not json", "quote", "source"])
def test_no_state_when_provider_json_or_citation_invalid(setup, bad):
    payload = response_payload()
    if bad == "quote":
        payload["requirements"][0]["citations"][0]["quote"] = "hallucinated"
    if bad == "source":
        payload["source_sha256"] = "0" * 64
    with patch(
        "submission.semantic_service.complete",
        return_value=TextCompletion(
            suggestion="not json" if bad == "not json" else json.dumps(payload),
        ),
    ):
        response = extract(setup)
    assert response.status_code == 422
    _, store, session, _, _ = setup
    with store.lease(session.identifier, session.token) as current:
        assert current.semantic_state is None


def test_report_call_refused_when_criteria_unconfirmed(setup):
    with patch("submission.semantic_service.complete", side_effect=provider_response) as call:
        draft = extract(setup).json()["data"]
        response = check(setup, draft)
    assert response.status_code == 409
    assert call.call_count == 1


@pytest.mark.parametrize(
    "overrides",
    [
        {"report_sha256": "0" * 64},
        {"guide_sha256": "0" * 64},
        {"criteria_sha256": "0" * 64},
        {"draft_id": "old"},
    ],
)
def test_no_report_call_when_snapshot_stale(setup, overrides):
    with patch("submission.semantic_service.complete", side_effect=provider_response) as call:
        draft = confirm(setup, extract(setup).json()["data"]).json()["data"]
        response = check(setup, draft, **overrides)
    assert response.status_code == 409
    assert call.call_count == 1


def test_confirmation_requires_exclusion_reason_and_conditional_choice(setup):
    with patch("submission.semantic_service.complete", side_effect=provider_response):
        draft = extract(setup).json()["data"]
    items = [
        {key: value for key, value in item.items() if key != "edited_fields"}
        for item in draft["items"]
    ]
    unresolved = confirm(setup, draft, items=items)
    assert unresolved.status_code == 422
    items[0]["included"] = False
    excluded = confirm(setup, draft, items=items)
    assert excluded.status_code == 422


def test_edit_creates_new_fingerprint_and_stale_revision_rejected(setup):
    with patch("submission.semantic_service.complete", side_effect=provider_response):
        draft = extract(setup).json()["data"]
    confirmed = confirm(setup, draft).json()["data"]
    stale_edit = {**draft, "items": [{**item, "title": "stale edit"} for item in draft["items"]]}
    assert confirm(setup, stale_edit).status_code == 409
    edited = {
        **confirmed,
        "items": [{**item, "title": "수정된 기준"} for item in confirmed["items"]],
    }
    changed = confirm(setup, edited).json()["data"]
    assert changed["criteria_sha256"] != confirmed["criteria_sha256"]
    assert changed["items"][0]["edited_fields"] == ["title"]


@pytest.mark.parametrize("operation", ["delete", "expire", "clear"])
def test_late_provider_completion_discarded_when_session_ends(setup, operation):
    _, store, session, _, now = setup

    def late(*args):
        if operation == "delete":
            store.delete(session.identifier, session.token)
        elif operation == "expire":
            now[0] = 601
            store.cleanup()
        else:
            store.clear()
        return provider_response(*args)

    with patch("submission.semantic_service.complete", side_effect=late):
        response = extract(setup)
    assert response.status_code == 404
    replacement = store.create("fresh", session.guide, session.report)
    assert replacement.semantic_state is None


def test_partial_review_does_not_claim_missing(setup):
    def partial(*args):
        result = provider_response(*args)
        body = json.loads(result.suggestion)
        if "reviewed_block_ids" in body:
            body["reviewed_block_ids"] = []
        return TextCompletion(suggestion=json.dumps(body))

    with patch("submission.semantic_service.complete", side_effect=partial):
        draft = confirm(setup, extract(setup).json()["data"]).json()["data"]
        response = check(setup, draft)
    assert response.status_code == 200
    item = response.json()["data"]["result"]["items"][0]
    assert item["judgment"] == "deferred"
    assert all("incomplete_review_scope" in sub["reason_codes"] for sub in item["subconditions"])


def test_rate_limit_prevents_eleventh_provider_call(setup):
    with patch("submission.semantic_service.complete", side_effect=provider_response) as call:
        for _ in range(10):
            assert extract(setup).status_code == 200
        response = extract(setup)
    assert response.status_code == 429
    assert call.call_count == 10


def test_new_draft_invalidates_previous_confirmation(setup):
    with patch("submission.semantic_service.complete", side_effect=provider_response):
        old = confirm(setup, extract(setup).json()["data"]).json()["data"]
        new = extract(setup).json()["data"]
        response = check(setup, old)
    assert new["draft_id"] != old["draft_id"]
    assert new["confirmed"] is False
    assert response.status_code == 409


@pytest.mark.parametrize("index", [0, 3])
def test_changed_conditional_criteria_can_confirm_when_application_explicit(setup, index):
    # Given: either a required item or an existing condition is edited.
    with patch("submission.semantic_service.complete", side_effect=provider_response):
        draft = extract(setup).json()["data"]
    items = [
        {key: value for key, value in item.items() if key != "edited_fields"}
        for item in draft["items"]
    ]
    for item in items:
        if item["classification"] == "conditional":
            item.update(application_status="does_not_apply", application_reason="개인")
    items[index].update(
        classification="conditional",
        condition_description="수정된 적용 조건",
        application_status="applies",
        application_reason="해당 조건을 확인함",
    )
    # When: the user explicitly confirms the edited condition and its applicability.
    response = confirm(setup, draft, items=items)
    # Then: confirmation persists the edited meaning and explicit choice.
    assert response.status_code == 200
    result = response.json()["data"]
    assert result["confirmed"] is True
    assert result["items"][index]["condition_description"] == "수정된 적용 조건"
    assert result["items"][index]["application_status"] == "applies"


def test_check_rejects_hallucinated_report_quote(setup):
    def hallucinated(*args):
        result = provider_response(*args)
        body = json.loads(result.suggestion)
        if "reviewed_block_ids" in body:
            data = json.loads(args[2])
            block = data["blocks"][0]
            body["items"][0]["evidence"] = [
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
        return TextCompletion(suggestion=json.dumps(body))

    with patch("submission.semantic_service.complete", side_effect=hallucinated):
        draft = confirm(setup, extract(setup).json()["data"]).json()["data"]
        response = check(setup, draft)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "ai_invalid_citation"


def test_late_check_discarded_when_criteria_changes(setup):
    _, store, session, _, _ = setup
    with patch("submission.semantic_service.complete", side_effect=provider_response):
        draft = confirm(setup, extract(setup).json()["data"]).json()["data"]

    def late(*args):
        with store.lease(session.identifier, session.token) as current:
            store.semantic_commit(
                session.identifier, session.token, current.semantic_revision, current.semantic_state
            )
        return provider_response(*args)

    with patch("submission.semantic_service.complete", side_effect=late):
        response = check(setup, draft)
    assert response.status_code == 409


def test_guide_over_budget_rejected_without_provider_call(setup):

    _, _, session, _, _ = setup
    count = len(session.guide.view.document.blocks)
    with (
        patch(
            "submission.semantic_service.REQUIREMENT_LIMITS",
            REQUIREMENT_LIMITS.model_copy(update={"max_blocks": count - 1}),
        ),
        patch("submission.semantic_service.complete") as call,
    ):
        response = extract(setup)
    assert response.status_code == 422
    call.assert_not_called()


def test_report_over_combined_block_budget_rejected_without_call(setup):

    with patch("submission.semantic_service.complete", side_effect=provider_response):
        draft = confirm(setup, extract(setup).json()["data"]).json()["data"]
    with (
        patch(
            "submission.semantic_service.CHECK_LIMITS",
            CHECK_LIMITS.model_copy(update={"max_blocks": 1}),
        ),
        patch("submission.semantic_service.complete") as call,
    ):
        response = check(setup, draft)
    assert response.status_code == 422
    call.assert_not_called()


def test_cloud_key_missing_rejected_without_provider_call(setup):
    client, store, session, headers, now = setup
    without_key = {key: value for key, value in headers.items() if key != "X-AI-API-Key"}
    with patch("submission.semantic_service.complete") as call:
        response = extract((client, store, session, without_key, now))
    assert response.status_code == 422
    call.assert_not_called()


def test_report_exact_evidence_is_bound_to_server_source(setup):
    def cited(*args):
        result = provider_response(*args)
        body = json.loads(result.suggestion)
        if "reviewed_block_ids" in body:
            block = json.loads(args[2])["blocks"][0]
            body["items"][2].update(
                proposed_judgment="evidence_found",
                evidence=[
                    {
                        "citation": {
                            "block_id": block["block_id"],
                            "char_range": {"start": 0, "end": len(block["raw_text"])},
                            "quote": block["raw_text"],
                        },
                        "evidence_role": "content",
                        "relation": "관련 본문",
                    }
                ],
            )
        return TextCompletion(suggestion=json.dumps(body))

    with patch("submission.semantic_service.complete", side_effect=cited):
        draft = confirm(setup, extract(setup).json()["data"]).json()["data"]
        response = check(setup, draft)
    assert response.status_code == 200
    item = response.json()["data"]["result"]["items"][2]
    assert item["judgment"] == "evidence_found"
    citation = item["evidence"][0]
    assert citation["citation"]["verification"] == "exact_quote"
    assert citation["semantic_relation_verified"] is False
    assert (
        citation["citation"]["source_locator"]["source_sha256"]
        == setup[2].report.view.document.source.content_sha256
    )


def test_no_provider_call_when_session_expires_before_call_could_finish(setup):
    *_, now = setup
    now[0] = 600 - PROVIDER_TIMEOUT + 1

    with patch("submission.semantic_service.complete") as call:
        response = extract(setup)

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "ai_session_expiring"
    assert call.call_count == 0
