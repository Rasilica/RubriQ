import json
from typing import Literal, assert_never

import pytest
from requirement_helpers import guide_document, response_payload

from submission.document_contracts import ProcessingStatus
from submission.models import DocumentRole
from submission.requirement_adapter import build_requirement_draft, prepare_requirement_request
from submission.requirement_contracts import (
    RequirementError,
    RequirementErrorCode,
    RequirementLimits,
)


@pytest.mark.parametrize(
    "status", [ProcessingStatus.FAILED, ProcessingStatus.NOT_STARTED, ProcessingStatus.UNSUPPORTED]
)
def test_unreadable_extraction_is_rejected(status: ProcessingStatus) -> None:
    document = guide_document().model_copy(update={"extraction_status": status})
    with pytest.raises(RequirementError) as caught:
        prepare_requirement_request(document)
    assert caught.value.code is RequirementErrorCode.INVALID_GUIDE


def test_report_is_rejected_as_a_guide() -> None:
    document = guide_document()
    report = document.model_copy(
        update={"source": document.source.model_copy(update={"role": DocumentRole.REPORT})}
    )
    with pytest.raises(RequirementError) as caught:
        prepare_requirement_request(report)
    assert caught.value.code is RequirementErrorCode.INVALID_GUIDE


def test_whitespace_only_guide_is_rejected() -> None:
    document = guide_document()
    document = document.model_copy(
        update={"blocks": (document.blocks[0].model_copy(update={"raw_text": " \n\t"}),)}
    )
    with pytest.raises(RequirementError) as caught:
        prepare_requirement_request(document)
    assert caught.value.code is RequirementErrorCode.INVALID_GUIDE


@pytest.mark.parametrize(
    "limits", [RequirementLimits(max_blocks=1), RequirementLimits(max_input_characters=5)]
)
def test_request_input_limits_do_not_truncate(limits: RequirementLimits) -> None:
    with pytest.raises(RequirementError) as caught:
        prepare_requirement_request(guide_document(), limits=limits)
    assert caught.value.code is RequirementErrorCode.INPUT_LIMIT


def test_duplicate_source_block_ids_are_rejected() -> None:
    document = guide_document()
    document = document.model_copy(update={"blocks": (document.blocks[0], document.blocks[0])})
    with pytest.raises(RequirementError) as caught:
        prepare_requirement_request(document)
    assert caught.value.code is RequirementErrorCode.DUPLICATE_ID


def test_block_hash_must_match_document() -> None:
    document = guide_document()
    block = document.blocks[0]
    changed = block.model_copy(
        update={
            "source_locator": block.source_locator.model_copy(update={"source_sha256": "0" * 64})
        }
    )
    with pytest.raises(RequirementError) as caught:
        prepare_requirement_request(document.model_copy(update={"blocks": (changed,)}))
    assert caught.value.code is RequirementErrorCode.SOURCE_MISMATCH


@pytest.mark.parametrize("level", ["requirement", "subcondition"])
def test_duplicate_response_ids_are_rejected(level: Literal["requirement", "subcondition"]) -> None:
    payload = response_payload()
    first = payload["requirements"][0]
    match level:
        case "requirement":
            payload["requirements"][1]["requirement_id"] = first["requirement_id"]
        case "subcondition":
            first["subconditions"][1]["subcondition_id"] = first["subconditions"][0][
                "subcondition_id"
            ]
        case _:
            assert_never(level)
    with pytest.raises(RequirementError) as caught:
        build_requirement_draft(guide_document(), json.dumps(payload))
    assert caught.value.code is RequirementErrorCode.DUPLICATE_ID


@pytest.mark.parametrize(
    "limits",
    [
        RequirementLimits(max_requirements=1),
        RequirementLimits(max_subconditions=1),
        RequirementLimits(max_text_characters=1),
        RequirementLimits(max_quote_characters=1),
    ],
)
def test_custom_item_limits_reject_whole_response(limits: RequirementLimits) -> None:
    with pytest.raises(RequirementError) as caught:
        build_requirement_draft(guide_document(), json.dumps(response_payload()), limits=limits)
    assert caught.value.code is RequirementErrorCode.RESPONSE_LIMIT


def test_custom_citation_limit_rejects_whole_response() -> None:
    payload = response_payload()
    item = payload["requirements"][0]
    item["citations"] = [item["citations"][0]] * 2
    with pytest.raises(RequirementError) as caught:
        build_requirement_draft(
            guide_document(), json.dumps(payload), limits=RequirementLimits(max_citations=1)
        )
    assert caught.value.code is RequirementErrorCode.RESPONSE_LIMIT


@pytest.mark.parametrize("raw", ["😀" * 30, "\ud800"])
def test_invalid_or_large_utf8_response_is_safe(raw: str) -> None:
    with pytest.raises(RequirementError) as caught:
        build_requirement_draft(
            guide_document(), raw, limits=RequirementLimits(max_response_bytes=100)
        )
    assert caught.value.code in {
        RequirementErrorCode.RESPONSE_LIMIT,
        RequirementErrorCode.INVALID_RESPONSE,
    }


def test_partial_guide_keeps_coverage_and_uncertainty() -> None:
    document = guide_document().model_copy(update={"extraction_status": ProcessingStatus.PARTIAL})
    draft = build_requirement_draft(document, json.dumps(response_payload()))
    assert draft.source_extraction_status == "partial"
    assert draft.coverage == document.coverage
    assert draft.warnings == document.warnings
    assert draft.typed_errors == document.typed_errors
    assert draft.status == "needs_review"


def test_empty_response_is_an_unconfirmed_draft_with_diagnostic() -> None:
    payload = {**response_payload(), "requirements": []}
    draft = build_requirement_draft(guide_document(), json.dumps(payload))
    assert draft.requirements == ()
    assert draft.diagnostics == ("no_requirements_returned",)
    assert not draft.confirmed


def _pad_with_empty_blocks(document, count):
    template = document.blocks[0]
    empties = tuple(
        template.model_copy(update={"block_id": f"empty-{index}", "raw_text": ""})
        for index in range(count)
    )
    return document.model_copy(update={"blocks": (*document.blocks, *empties)})


def test_empty_blocks_do_not_count_toward_block_limit() -> None:
    document = guide_document()
    sent = len(document.blocks)
    padded = _pad_with_empty_blocks(document, 5)
    limits = RequirementLimits(max_blocks=sent)  # exactly max_blocks non-empty is allowed
    prepare_requirement_request(padded, limits=limits)


def test_non_empty_blocks_over_block_limit_are_rejected_despite_empties() -> None:
    document = guide_document()
    padded = _pad_with_empty_blocks(document, 5)
    limits = RequirementLimits(max_blocks=len(document.blocks) - 1)
    with pytest.raises(RequirementError) as caught:
        prepare_requirement_request(padded, limits=limits)
    assert caught.value.code is RequirementErrorCode.INPUT_LIMIT


def test_response_between_target_and_limit_is_accepted() -> None:
    payload = response_payload()
    first = payload["requirements"][0]
    payload["requirements"] = [
        {**first, "requirement_id": f"R{n}", "subconditions": []} for n in range(1, 29)
    ]

    draft = build_requirement_draft(guide_document(), json.dumps(payload))

    assert len(draft.requirements) == 28
