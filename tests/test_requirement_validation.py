import json
from typing import Literal, assert_never

import pytest
from requirement_helpers import guide_document, response_payload

from submission.requirement_adapter import build_requirement_draft
from submission.requirement_contracts import (
    RequirementError,
    RequirementErrorCode,
    RequirementLimits,
)


@pytest.mark.parametrize("field", ["source_id", "document_version_id", "source_sha256"])
def test_response_identity_of_another_guide_is_overwritten_by_server(field: str) -> None:
    payload = {**response_payload(), field: "0" * 64}

    draft = build_requirement_draft(guide_document(), json.dumps(payload))

    assert getattr(draft, field) == getattr(
        guide_document().source, field.replace("source_sha256", "content_sha256")
    )


@pytest.mark.parametrize("level", ["requirement", "subcondition", "condition"])
def test_every_citation_level_rejects_invented_quotes(
    level: Literal["requirement", "subcondition", "condition"],
) -> None:
    payload = response_payload()
    match level:
        case "requirement":
            citation = payload["requirements"][0]["citations"][0]
        case "subcondition":
            citation = payload["requirements"][0]["subconditions"][0]["citations"][0]
        case "condition":
            citation = payload["requirements"][3]["condition"]["citations"][0]
        case _:
            assert_never(level)
    citation["quote"] = "SECRET invented requirement"

    with pytest.raises(RequirementError) as caught:
        build_requirement_draft(guide_document(), json.dumps(payload))

    assert caught.value.code is RequirementErrorCode.INVALID_CITATION
    assert "SECRET" not in str(caught.value)


@pytest.mark.parametrize("raw", ["{SECRET", "null", "[]", '{"unknown":"SECRET"}', "[" * 1000])
def test_malformed_responses_have_safe_typed_errors(raw: str) -> None:
    with pytest.raises(RequirementError) as caught:
        build_requirement_draft(guide_document(), raw)

    assert caught.value.code is RequirementErrorCode.INVALID_RESPONSE
    assert "SECRET" not in str(caught.value)


def test_response_size_is_bounded_before_parsing() -> None:
    with pytest.raises(RequirementError) as caught:
        build_requirement_draft(
            guide_document(), " " * 101, limits=RequirementLimits(max_response_bytes=100)
        )

    assert caught.value.code is RequirementErrorCode.RESPONSE_LIMIT
