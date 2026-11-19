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
from submission.semantic_service import context as real_context


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
    if "expected_items" not in data:
        return TextCompletion(suggestion=json.dumps(response_payload()))
    return TextCompletion(
        suggestion=json.dumps(
            {
                "schema_version": "1",
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


@pytest.mark.parametrize("bad", ["not json", "quote"])
def test_no_state_when_provider_json_or_citation_invalid(setup, bad):
    payload = response_payload()
    if bad == "quote":
        payload["requirements"][0]["citations"][0]["quote"] = "hallucinated"
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


def test_guide_with_unsendable_block_rejected_without_provider_call(setup):
    with (
        patch(
            "submission.semantic_service.REQUIREMENT_LIMITS",
            REQUIREMENT_LIMITS.model_copy(update={"max_input_characters": 1}),
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


def test_billing_ai_call_refused_when_session_ends_before_its_longer_timeout(setup):
    *_, now = setup
    now[0] = 600 - 200  # 200 s left: enough for PROVIDER_TIMEOUT, not for the billing timeout

    with patch("submission.semantic_service.complete") as call:
        response = extract(setup, provider="billingai")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "ai_session_expiring"
    assert call.call_count == 0


def test_direct_provider_call_proceeds_with_200_seconds_left(setup):
    *_, now = setup
    now[0] = 600 - 200

    with patch("submission.semantic_service.complete", side_effect=provider_response) as call:
        response = extract(setup)

    assert response.status_code == 200
    assert call.call_count >= 1


def _padded_context(real_context):
    def wrapper(session, state):
        ctx = real_context(session, state)

        def pad(document):
            empties = tuple(
                document.blocks[0].model_copy(update={"block_id": f"empty-{i}", "raw_text": " "})
                for i in range(5)
            )
            return document.model_copy(update={"blocks": (*document.blocks, *empties)})

        return ctx.model_copy(update={"guide": pad(ctx.guide), "report": pad(ctx.report)})

    return wrapper


def test_combined_block_budget_ignores_empty_blocks(setup):
    with patch("submission.semantic_service.complete", side_effect=provider_response):
        draft = confirm(setup, extract(setup).json()["data"]).json()["data"]
    _, _, session, _, _ = setup
    docs = (session.guide.view.document, session.report.view.document)
    sent = sum(1 for d in docs for b in d.blocks if b.raw_text.strip())
    # Over the block cap the report is now split into two calls instead of rejected.
    for budget, expected_calls in ((sent, 1), (sent - 1, 2)):
        with (
            patch("submission.semantic_service.context", _padded_context(real_context)),
            patch(
                "submission.semantic_service.CHECK_LIMITS",
                CHECK_LIMITS.model_copy(update={"max_blocks": budget}),
            ),
            patch(
                "submission.semantic_service.complete", side_effect=provider_response
            ) as call,
        ):
            assert check(setup, draft).status_code == 200
            assert call.call_count == expected_calls


def _with_blocks(document, count, text="짧은 문단"):
    extra = tuple(
        document.blocks[0].model_copy(update={"block_id": f"bulk-{i}", "raw_text": f"{text} {i}"})
        for i in range(count)
    )
    return document.model_copy(update={"blocks": (*document.blocks, *extra)})


def test_guide_with_hundreds_of_short_blocks_is_accepted(setup):
    guide = _with_blocks(setup[2].guide.view.document, 450)
    with (
        patch("submission.semantic_service.document", return_value=guide),
        patch("submission.semantic_service.complete", side_effect=provider_response) as call,
    ):
        response = extract(setup)
    assert response.status_code == 200
    assert call.call_count == 1


def test_guide_over_character_budget_still_rejected_without_call(setup):
    guide = _with_blocks(setup[2].guide.view.document, 1, text="가" * 20001)
    with (
        patch("submission.semantic_service.document", return_value=guide),
        patch("submission.semantic_service.complete") as call,
    ):
        response = extract(setup)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "ai_input_limit"
    call.assert_not_called()


def test_check_with_1500_short_blocks_is_accepted(setup):
    with patch("submission.semantic_service.complete", side_effect=provider_response):
        draft = confirm(setup, extract(setup).json()["data"]).json()["data"]

    def bulky(session, state):
        ctx = real_context(session, state)
        return ctx.model_copy(
            update={
                "guide": _with_blocks(ctx.guide, 750),
                "report": _with_blocks(ctx.report, 750),
            }
        )

    with (
        patch("submission.semantic_service.context", bulky),
        patch("submission.semantic_service.complete", side_effect=provider_response) as call,
    ):
        response = check(setup, draft)
    assert response.status_code == 200
    assert call.call_count == 1


def test_check_over_character_budget_still_rejected_without_call(setup):
    with patch("submission.semantic_service.complete", side_effect=provider_response):
        draft = confirm(setup, extract(setup).json()["data"]).json()["data"]

    def huge(session, state):
        ctx = real_context(session, state)
        return ctx.model_copy(update={"report": _with_blocks(ctx.report, 1, text="가" * 60001)})

    with (
        patch("submission.semantic_service.context", huge),
        patch("submission.semantic_service.complete") as call,
    ):
        response = check(setup, draft)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "ai_input_limit"
    call.assert_not_called()


def test_requirement_request_does_not_ask_model_for_identity(setup):
    with patch("submission.semantic_service.complete", side_effect=provider_response) as call:
        assert extract(setup).status_code == 200
    _request, instructions, payload, _key = call.call_args.args
    sent = json.loads(payload)
    assert not {"source_id", "document_version_id", "source_sha256"} & sent.keys()
    schema = json.loads(sent["response_schema_json"])
    assert not {"source_id", "document_version_id", "source_sha256"} & schema["properties"].keys()
    assert "해시" not in instructions
    assert "식별자" not in instructions
