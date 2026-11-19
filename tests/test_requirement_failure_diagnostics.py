import copy
import json
import logging

import pytest
from fastapi.responses import JSONResponse
from requirement_helpers import guide_document, response_payload

from submission.requirement_adapter import build_requirement_draft
from submission.requirement_contracts import RequirementLimits
from submission.semantic_chunks import merge_requirement_completions
from submission.semantic_routes import invoke

MODEL_TEXT_MARKER = "MARKER-model-text"


def _citation(payload):
    return payload["requirements"][0]["citations"][0]


def _bad_block(payload):
    _citation(payload)["block_id"] = MODEL_TEXT_MARKER


def _bad_range(payload):
    _citation(payload)["char_range"] = {"start": 987653, "end": 987654}


def _bad_quote(payload):
    _citation(payload)["quote"] = MODEL_TEXT_MARKER


def _duplicate(payload):
    payload["requirements"][1]["requirement_id"] = payload["requirements"][0]["requirement_id"]


def _two_citations(payload):
    item = payload["requirements"][0]
    item["citations"] = [item["citations"][0], item["citations"][0]]


def _keep(_payload):
    return None


CITATION = "ai_invalid_citation"
LIMIT = "ai_response_limit"
CASES = [
    (_bad_block, {}, "citation_block_missing", CITATION),
    (_bad_range, {}, "citation_range_invalid", CITATION),
    (_bad_quote, {}, "citation_quote_mismatch", CITATION),
    (_duplicate, {}, "requirement_id_duplicate", "ai_duplicate_id"),
    (_keep, {"max_requirements": 2}, "requirement_count", LIMIT),
    (_keep, {"max_subconditions": 1}, "subcondition_count", LIMIT),
    (_keep, {"max_text_characters": 3}, "requirement_text_length", LIMIT),
    (_two_citations, {"max_citations": 1}, "requirement_citation_count", LIMIT),
    (_keep, {"max_quote_characters": 2}, "requirement_quote_length", LIMIT),
]


def _run(raw, limits, caplog):
    with caplog.at_level(logging.WARNING):
        response = invoke(
            lambda: build_requirement_draft(
                guide_document(), raw, limits=RequirementLimits(**limits)
            )
        )
    assert isinstance(response, JSONResponse)
    assert response.status_code == 422
    return json.loads(response.body), response.body.decode()


def _assert_private(caplog, body_text):
    for private in (MODEL_TEXT_MARKER, "987653", "987654"):
        assert private not in caplog.text
        assert private not in body_text


@pytest.mark.parametrize(("mutate", "limits", "branch", "code"), CASES)
def test_requirement_contract_branch_is_recorded(mutate, limits, branch, code, caplog):
    payload = copy.deepcopy(response_payload())
    mutate(payload)
    body, text = _run(json.dumps(payload), limits, caplog)
    assert body["error"]["code"] == code
    diagnostic = body["error"]["diagnostic"]
    assert set(diagnostic) == {"id", "stage", "reason"}
    assert diagnostic["stage"] == "requirement_validation"
    reason = "citation_invalid" if code == CITATION else "requirement_contract_invalid"
    assert diagnostic["reason"] == reason
    assert f'"branch":"{branch}"' in caplog.text
    assert f"stage=requirement_validation reason={reason}" in caplog.text
    _assert_private(caplog, text)


def test_count_branch_logs_only_integers(caplog):
    raw = json.dumps(response_payload())
    _run(raw, {"max_requirements": 2}, caplog)
    assert '"count":' in caplog.text
    assert '"limit":2' in caplog.text


@pytest.mark.parametrize(
    "raw",
    ["{" + MODEL_TEXT_MARKER, '{"unknown":"' + MODEL_TEXT_MARKER + '"}'],
)
def test_schema_branch_is_recorded_without_values(raw, caplog):
    body, text = _run(raw, {}, caplog)
    assert body["error"]["diagnostic"]["stage"] == "requirement_validation"
    assert '"branch":"requirement_schema"' in caplog.text
    _assert_private(caplog, text)


def test_response_size_branch_is_recorded(caplog):
    _run(json.dumps(response_payload()), {"max_response_bytes": 10}, caplog)
    assert '"branch":"requirement_response_size"' in caplog.text
    assert '"limit":10' in caplog.text


def test_merge_count_branch_is_recorded(caplog):
    raw = json.dumps(response_payload())
    with caplog.at_level(logging.WARNING):
        response = invoke(
            lambda: merge_requirement_completions(
                guide_document(), [raw, raw], RequirementLimits(max_requirements=2)
            )
        )
    assert isinstance(response, JSONResponse)
    assert response.status_code == 422
    assert json.loads(response.body)["error"]["diagnostic"]["stage"] == "requirement_validation"
    assert '"branch":"merge_count"' in caplog.text


def test_input_side_error_keeps_code_and_has_no_branch(caplog):
    document = guide_document()
    with caplog.at_level(logging.WARNING):
        response = invoke(
            lambda: build_requirement_draft(
                document, "{}", limits=RequirementLimits(max_input_characters=1)
            )
        )
    assert json.loads(response.body)["error"]["code"] == "ai_input_limit"
    assert '"branch":"unknown"' in caplog.text
