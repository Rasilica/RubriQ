import json

import pytest
from requirement_helpers import guide_document, response_payload

from submission.requirement_adapter import build_requirement_draft
from submission.requirement_contracts import RequirementError, RequirementErrorCode


@pytest.mark.parametrize(
    ("start", "end"), [(True, 146), ("118", 146), (-1, 146), (147, 146), (118, False), (118.5, 146)]
)
def test_range_must_have_ordered_nonnegative_strict_integers(start, end) -> None:
    payload = response_payload()
    payload["requirements"][0]["citations"][0]["char_range"] = {"start": start, "end": end}
    with pytest.raises(RequirementError) as caught:
        build_requirement_draft(guide_document(), json.dumps(payload))
    assert caught.value.code is RequirementErrorCode.INVALID_RESPONSE


@pytest.mark.parametrize(
    "change",
    [
        {"block_id": "missing"},
        {"quote": "altered"},
        {"char_range": {"start": 118, "end": 118}},
        {"char_range": {"start": 118, "end": 9999}},
        {"char_range": {"start": 117, "end": 145}},
    ],
)
def test_citation_requires_existing_block_and_exact_local_slice(change) -> None:
    payload = response_payload()
    cite = payload["requirements"][0]["citations"][0]
    payload = {
        **payload,
        "requirements": [
            {**payload["requirements"][0], "citations": [{**cite, **change}]},
            *payload["requirements"][1:],
        ],
    }
    with pytest.raises(RequirementError) as caught:
        build_requirement_draft(guide_document(), json.dumps(payload))
    assert caught.value.code is RequirementErrorCode.INVALID_CITATION


@pytest.mark.parametrize(
    "change",
    [
        {"source_locator": {"path": "invented", "original_page_number": 3}},
        {"source_sha256": "0" * 64},
        {"page": 5},
        {"quote": " "},
    ],
)
def test_provider_cannot_supply_locations_or_empty_quotes(change) -> None:
    payload = response_payload()
    cite = payload["requirements"][0]["citations"][0]
    payload = {
        **payload,
        "requirements": [
            {**payload["requirements"][0], "citations": [{**cite, **change}]},
            *payload["requirements"][1:],
        ],
    }
    with pytest.raises(RequirementError) as caught:
        build_requirement_draft(guide_document(), json.dumps(payload))
    assert caught.value.code is RequirementErrorCode.INVALID_RESPONSE


@pytest.mark.parametrize(
    "change",
    [
        {"classification": "conditional", "condition": None},
        {"classification": "optional", "condition": {"description": "invented", "citations": []}},
        {"classification": "unknown"},
        {"title": " "},
        {"citations": []},
        {"application_status": "applies"},
        {"confirmed": True},
        {"requirement_id": " "},
    ],
)
def test_response_cannot_bypass_classification_or_confirmation_contract(change) -> None:
    payload = response_payload()
    payload = {
        **payload,
        "requirements": [
            {**payload["requirements"][0], **change},
            *payload["requirements"][1:],
        ],
    }
    with pytest.raises(RequirementError) as caught:
        build_requirement_draft(guide_document(), json.dumps(payload))
    assert caught.value.code is RequirementErrorCode.INVALID_RESPONSE


@pytest.mark.parametrize("change", [{"schema_version": "2"}, {"ai_called": True}])
def test_response_rejects_version_and_unknown_envelope_fields(change) -> None:
    with pytest.raises(RequirementError) as caught:
        build_requirement_draft(guide_document(), json.dumps({**response_payload(), **change}))
    assert caught.value.code is RequirementErrorCode.INVALID_RESPONSE
