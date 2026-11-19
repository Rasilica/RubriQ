import json

import pytest
from pydantic import ValidationError
from requirement_helpers import guide_document, response_payload

from submission.requirement_adapter import OfflineRequirementAdapter, prepare_requirement_request
from submission.requirement_contracts import RequirementDraft, RequirementLimits


def test_offline_pdf_fixture_produces_unconfirmed_cited_requirements() -> None:
    document = guide_document()
    adapter = OfflineRequirementAdapter(json.dumps(response_payload()))

    draft = adapter.extract(document)

    assert [item.classification for item in draft.requirements] == [
        "required",
        "required",
        "optional",
        "conditional",
        "required",
    ]
    assert [len(item.subconditions) for item in draft.requirements] == [2, 2, 0, 0, 1]
    assert draft.status == "needs_review"
    assert draft.fake
    assert not any(
        (draft.ai_called, draft.stored, draft.confirmed, draft.guarantees_all_requirements)
    )
    assert not draft.semantic_accuracy_verified
    assert all(item.application_status == "undetermined" for item in draft.requirements)
    assert draft.requirements[3].condition.citations[0].quote == "실제 개인정보를 입력에 사용한다면"
    assert draft.requirements[0].citations[0].source_locator.original_page_number == 1
    assert draft.source_id == document.source.source_id
    assert draft.document_version_id == document.source.document_version_id
    assert RequirementDraft.model_validate_json(draft.model_dump_json()) == draft
    with pytest.raises(ValidationError):
        draft.confirmed = True


def test_request_contains_versioned_schema_and_untrusted_document_data() -> None:
    document = guide_document()

    request = prepare_requirement_request(document)

    schema = json.loads(request.response_schema_json)
    assert schema["additionalProperties"] is False
    assert request.prompt_version == request.schema_version == "1"
    assert request.blocks[0].raw_text == document.blocks[0].raw_text
    assert "source_sha256" not in schema["properties"]
    assert not hasattr(request, "source_sha256")
    assert request.coordinate_basis == "block_raw_unicode"


def test_unconditional_draft_item_cannot_contain_condition() -> None:
    draft = OfflineRequirementAdapter(json.dumps(response_payload())).extract(guide_document())
    payload = json.loads(draft.model_dump_json())
    payload["requirements"][0]["condition"] = payload["requirements"][3]["condition"]

    with pytest.raises(ValidationError):
        RequirementDraft.model_validate_json(json.dumps(payload))


def test_schema_exposes_conditional_requirement_and_strict_citation_shape() -> None:
    request = prepare_requirement_request(guide_document())

    schema = json.loads(request.response_schema_json)

    reference = schema["properties"]["requirements"]["items"]["$ref"]
    alternatives = schema["$defs"][reference.removeprefix("#/$defs/")]["discriminator"]["mapping"]
    assert set(alternatives) == {"required", "optional", "conditional"}
    conditional = schema["$defs"]["ConditionalInput"]
    assert "condition" in conditional["required"]
    assert conditional["properties"]["condition"]["$ref"].startswith("#/$defs/")
    citation = schema["$defs"]["CitationInput"]
    assert set(citation["properties"]) == {"block_id", "char_range", "quote"}
    assert citation["additionalProperties"] is False


def test_request_instructions_state_limits_and_grouping_guidance() -> None:
    limits = RequirementLimits(max_requirements=7, max_subconditions=4)

    instructions = prepare_requirement_request(guide_document(), limits=limits).instructions

    assert "요구사항을 최대 5개" in instructions
    assert "하위조건을 요구사항마다 최대 4개" in instructions
    assert "하나의 요구사항으로 묶고" in instructions
    assert "30개" not in instructions


def test_request_instructions_ask_for_fewer_requirements_than_the_server_limit() -> None:
    default = prepare_requirement_request(
        guide_document(), limits=RequirementLimits(max_requirements=30, max_subconditions=10)
    ).instructions
    custom = prepare_requirement_request(
        guide_document(), limits=RequirementLimits(max_requirements=12)
    ).instructions

    assert "요구사항을 최대 25개" in default
    assert "요구사항을 최대 30개" not in default
    assert "요구사항을 최대 10개" in custom
    assert "하위조건을 요구사항마다 최대 10개" in default


def test_request_instructions_state_citation_limits_and_title_guidance() -> None:
    limits = RequirementLimits(max_citations=3, max_quote_characters=500)

    instructions = prepare_requirement_request(guide_document(), limits=limits).instructions

    assert "인용은 최대 3개" in instructions
    assert "quote는 최대 500자" in instructions
    assert "가장 대표적인 인용" in instructions
    assert "10개" not in instructions
    assert "10000자" not in instructions
