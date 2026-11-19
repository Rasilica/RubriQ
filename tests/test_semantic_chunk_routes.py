import json
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from report_check_helpers import context
from requirement_helpers import guide_document, response_payload
from test_semantic_routes import check, confirm, extract, provider_response

from submission.cloud_contracts import CloudCode, CloudError, TextCompletion, Usage
from submission.main import create_app
from submission.models import DocumentRole
from submission.pair_contracts import PreparedRole, RoleView
from submission.pair_store import PairStore
from submission.report_check_adapter import prepare_report_check_request
from submission.semantic_context import CHECK_LIMITS
from submission.semantic_service import context as real_context

PDFS = Path(__file__).resolve().parents[1] / "samples/pdf"
NEEDLE = "NEEDLE"
USAGE = Usage(input_tokens=1, output_tokens=2)


def with_blocks(document, texts):
    template = document.blocks[0]
    blocks = tuple(
        template.model_copy(
            update={"block_id": f"p1-b{i}", "raw_text": text, "normalized_text": text}
        )
        for i, text in enumerate(texts, 1)
    )
    return document.model_copy(update={"blocks": blocks})


@contextmanager
def environment(*, guide=None, report=None):
    store = PairStore(clock=lambda: 0.0, ttl=600)
    docs = (
        (DocumentRole.GUIDE, guide or guide_document(), "guide.pdf"),
        (DocumentRole.REPORT, report or context().report, "normal.pdf"),
    )
    roles = tuple(
        PreparedRole(
            RoleView(
                role=role,
                document=doc,
                extraction_status=doc.extraction_status,
                rendering_status=doc.extraction_status,
            ),
            (PDFS / name).read_bytes(),
        )
        for role, doc, name in docs
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
        yield client, store, session, headers, [0.0]


def long_report(texts):
    return with_blocks(context().report, texts)


def confirmed_draft(env):
    with patch("submission.semantic_service.complete", side_effect=provider_response):
        return confirm(env, extract(env).json()["data"]).json()["data"]


def needle_provider(*args):
    result = provider_response(*args)
    body = json.loads(result.suggestion)
    data = json.loads(args[2])
    if "reviewed_block_ids" not in body:
        return TextCompletion(suggestion=result.suggestion, usage=USAGE)
    block = next((b for b in data["blocks"] if NEEDLE in b["raw_text"]), None)
    if block is not None:
        start = block["raw_text"].index(NEEDLE)
        found = {
            "proposed_judgment": "evidence_found",
            "reason": "본문에서 발견",
            "evidence": [
                {
                    "citation": {
                        "block_id": block["block_id"],
                        "char_range": {"start": start, "end": start + len(NEEDLE)},
                        "quote": NEEDLE,
                    },
                    "evidence_role": "content",
                    "relation": "근거",
                }
            ],
        }
        body["items"][0].update(found)
        for sub in body["items"][0]["subconditions"]:
            sub.update(found)
    return TextCompletion(suggestion=json.dumps(body), usage=USAGE)


def test_check_when_report_fits_makes_one_call_with_unchanged_payload():
    with environment() as env:
        draft = confirmed_draft(env)
        _, store, session, _, _ = env
        with patch("submission.semantic_service.complete", side_effect=provider_response) as call:
            response = check(env, draft)
        assert response.status_code == 200
        assert call.call_count == 1
        with store.lease(session.identifier, session.token) as current:
            ctx = real_context(current, current.semantic_state)
        prepared = prepare_report_check_request(ctx, limits=CHECK_LIMITS)
        expected = json.dumps(
            {
                **prepared.model_dump(mode="json"),
                "guide_blocks": [
                    {"block_id": b.block_id, "raw_text": b.raw_text}
                    for b in ctx.guide.blocks
                    if b.raw_text.strip()
                ],
            },
            ensure_ascii=False,
        )
        assert call.call_args.args[2] == expected
        assert response.json()["data"]["request_count"] == 1


def test_check_when_over_budget_splits_into_budgeted_chunks_and_merges():
    texts = ["가" * 25000, "나" * 25000, f"{NEEDLE}" + "다" * 25000, "라" * 25000]
    with environment(report=long_report(texts)) as env:
        draft = confirmed_draft(env)
        with patch("submission.semantic_service.complete", side_effect=needle_provider) as call:
            response = check(env, draft)
        assert response.status_code == 200
        assert call.call_count == 2
        payloads = [json.loads(c.args[2]) for c in call.call_args_list]
        guide_ids = [b["block_id"] for b in payloads[0]["guide_blocks"]]
        assert all([b["block_id"] for b in p["guide_blocks"]] == guide_ids for p in payloads)
        assert all(p["criteria"] == payloads[0]["criteria"] for p in payloads)
        slices = [[b["block_id"] for b in p["blocks"]] for p in payloads]
        assert slices == [["p1-b1", "p1-b2"], ["p1-b3", "p1-b4"]]
        for p in payloads:
            size = sum(len(b["raw_text"]) for b in p["blocks"]) + sum(
                len(b["raw_text"]) for b in p["guide_blocks"]
            )
            assert size <= CHECK_LIMITS.max_input_characters
        data = response.json()["data"]
        item = data["result"]["items"][0]
        assert item["judgment"] == "evidence_found"
        assert item["reason"] == "본문에서 발견"
        assert item["evidence"][0]["citation"]["block_id"] == "p1-b3"
        assert data["result"]["reviewed_block_ids"] == ["p1-b1", "p1-b2", "p1-b3", "p1-b4"]
        assert data["request_count"] == 2
        assert data["usage"] == {"input_tokens": 2, "output_tokens": 4}


def test_check_when_too_many_chunks_needed_rejects_without_provider_call():
    with environment(report=long_report(["가" * 40000] * 6)) as env:
        draft = confirmed_draft(env)
        with patch("submission.semantic_service.complete") as call:
            response = check(env, draft)
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "ai_input_limit"
        call.assert_not_called()


def test_check_when_single_block_exceeds_budget_rejects_without_provider_call():
    with environment(report=long_report(["가" * 60001])) as env:
        draft = confirmed_draft(env)
        with patch("submission.semantic_service.complete") as call:
            response = check(env, draft)
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "ai_input_limit"
        call.assert_not_called()


def test_check_when_second_chunk_call_fails_returns_error_and_stores_nothing():
    texts = ["가" * 25000, "나" * 25000, "다" * 25000, "라" * 25000]
    with environment(report=long_report(texts)) as env:
        _, store, session, _, _ = env
        draft = confirmed_draft(env)
        calls = []

        def flaky(*args):
            calls.append(args)
            if len(calls) == 2:
                raise CloudError(CloudCode.INVALID_RESPONSE, 502)
            return provider_response(*args)

        with patch("submission.semantic_service.complete", side_effect=flaky):
            response = check(env, draft)
        assert response.status_code == 502
        assert len(calls) == 2
        with store.lease(session.identifier, session.token) as current:
            assert current.semantic_state.check is None


def test_check_consults_rate_limit_per_chunk_call():
    texts = ["가" * 25000, "나" * 25000, "다" * 25000, "라" * 25000]
    with environment(report=long_report(texts)) as env:
        _, store, session, _, _ = env
        with patch("submission.semantic_service.complete", side_effect=provider_response):
            for _ in range(8):
                assert extract(env).status_code == 200
            draft = confirm(env, extract(env).json()["data"]).json()["data"]
            with patch(
                "submission.semantic_service.complete", side_effect=provider_response
            ) as call:
                response = check(env, draft)
        assert response.status_code == 429
        assert call.call_count == 1
        with store.lease(session.identifier, session.token) as current:
            assert current.semantic_state.check is None


def requirement_provider(*args):
    data = json.loads(args[2])
    block = data["blocks"][0]
    base = response_payload()
    citation = {
        "block_id": block["block_id"],
        "char_range": {"start": 0, "end": 3},
        "quote": block["raw_text"][:3],
    }
    return TextCompletion(
        suggestion=json.dumps(
            {
                **base,
                "requirements": [
                    {
                        **base["requirements"][0],
                        "requirement_id": "R1",
                        "title": f"요구 {block['block_id']}",
                        "citations": [citation],
                        "subconditions": [
                            {
                                "subcondition_id": "R1-S1",
                                "description": "하위",
                                "citations": [citation],
                            }
                        ],
                    }
                ],
            }
        )
    )


def test_requirements_when_guide_over_budget_chunks_and_renumbers():
    guide = with_blocks(guide_document(), ["가나다" * 5000] * 3)
    with environment(guide=guide) as env:
        with patch(
            "submission.semantic_service.complete", side_effect=requirement_provider
        ) as call:
            response = extract(env)
        assert response.status_code == 200
        assert call.call_count == 3
        items = response.json()["data"]["requirements"]
        assert [i["requirement_id"] for i in items] == ["R1", "R2", "R3"]
        assert [i["title"] for i in items] == ["요구 p1-b1", "요구 p1-b2", "요구 p1-b3"]
        assert items[2]["subconditions"][0]["subcondition_id"] == "R3-S1"
        assert items[2]["citations"][0]["verification"] == "exact_quote"


def test_requirements_when_four_chunks_needed_rejects_without_provider_call():
    guide = with_blocks(guide_document(), ["가나다" * 5000] * 4)
    with environment(guide=guide) as env, patch("submission.semantic_service.complete") as call:
        response = extract(env)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "ai_input_limit"
    call.assert_not_called()


def test_requirements_when_merged_count_exceeds_limit_fails_without_state():
    guide = with_blocks(guide_document(), ["가나다" * 5000] * 2)
    base = response_payload()

    def many(*args):
        block = json.loads(args[2])["blocks"][0]
        citation = {
            "block_id": block["block_id"],
            "char_range": {"start": 0, "end": 3},
            "quote": block["raw_text"][:3],
        }
        return TextCompletion(
            suggestion=json.dumps(
                {
                    **base,
                    "requirements": [
                        {
                            **base["requirements"][0],
                            "requirement_id": f"R{n}",
                            "citations": [citation],
                            "subconditions": [],
                        }
                        for n in range(1, 17)
                    ],
                }
            )
        )

    with environment(guide=guide) as env:
        _, store, session, _, _ = env
        with patch("submission.semantic_service.complete", side_effect=many) as call:
            response = extract(env)
        assert response.status_code == 422
        assert call.call_count == 2
        with store.lease(session.identifier, session.token) as current:
            assert current.semantic_state is None


def test_requirements_when_guide_fits_makes_single_call():
    with (
        environment() as env,
        patch("submission.semantic_service.complete", side_effect=provider_response) as call,
    ):
        assert extract(env).status_code == 200
    assert call.call_count == 1


def test_requirements_when_chunked_each_call_is_told_its_share_of_the_limit():
    guide = with_blocks(guide_document(), ["가나다" * 5000] * 3)
    with (
        environment(guide=guide) as env,
        patch("submission.semantic_service.complete", side_effect=requirement_provider) as call,
    ):
        assert extract(env).status_code == 200
    assert call.call_count == 3
    for args in call.call_args_list:
        assert "요구사항을 최대 8개" in args.args[1]
        assert "하위조건을 요구사항마다 최대 10개" in args.args[1]


def test_requirements_when_guide_fits_instructions_state_target_below_limit():
    with (
        environment() as env,
        patch("submission.semantic_service.complete", side_effect=provider_response) as call,
    ):
        assert extract(env).status_code == 200
    assert "요구사항을 최대 25개" in call.call_args.args[1]
