import json

import pytest
from requirement_helpers import guide_document, response_payload
from test_semantic_chunks import requirement_chunk, with_blocks

from submission.requirement_adapter import build_requirement_draft
from submission.requirement_contracts import RequirementError, RequirementErrorCode
from submission.semantic_chunks import merge_requirement_completions
from submission.semantic_service import REQUIREMENT_LIMITS

IDENTITY = ("source_id", "document_version_id", "source_sha256")


def _without_identity(payload):
    return json.dumps({k: v for k, v in payload.items() if k not in IDENTITY})


def _assert_server_identity(draft, document):
    assert draft.source_id == document.source.source_id
    assert draft.document_version_id == document.source.document_version_id
    assert draft.source_sha256 == document.source.content_sha256


def test_response_without_identity_fields_builds_draft_with_guide_identity():
    document = guide_document()

    draft = build_requirement_draft(document, _without_identity(response_payload()))

    _assert_server_identity(draft, document)
    assert draft.requirements


@pytest.mark.parametrize("bad_hash", ["0" * 63, "f" * 64, "not-a-hash"])
def test_miscopied_identity_is_ignored_and_server_values_used(bad_hash):
    document = guide_document()
    payload = {**response_payload(), "source_sha256": bad_hash, "source_id": "other"}

    draft = build_requirement_draft(document, json.dumps(payload))

    _assert_server_identity(draft, document)


def test_unknown_top_level_field_is_still_rejected():
    payload = {**json.loads(_without_identity(response_payload())), "extra": 1}

    with pytest.raises(RequirementError) as caught:
        build_requirement_draft(guide_document(), json.dumps(payload))

    assert caught.value.code is RequirementErrorCode.INVALID_RESPONSE


def test_chunks_without_identity_merge_into_full_guide_identity():
    guide = with_blocks(guide_document(), ["가나다" * 10] * 2)
    raws = [_without_identity(json.loads(requirement_chunk(guide, i))) for i in range(2)]

    merged = merge_requirement_completions(guide, raws, REQUIREMENT_LIMITS)
    draft = build_requirement_draft(guide, merged)

    _assert_server_identity(draft, guide)
    assert len(draft.requirements) == 2
