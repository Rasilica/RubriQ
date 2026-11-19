import json

import pytest
from pydantic import ValidationError
from report_check_helpers import context, payload

from submission.report_check_adapter import prepare_report_check_request
from submission.report_check_contracts import (
    ReportCheckError,
    ReportCheckErrorCode,
    ReportCheckModelResponse,
    ReportCheckResponse,
)
from submission.report_check_validation import validate_response
from submission.semantic_wire import wire_document


def mixed_context():
    ctx = context()
    items = tuple(
        item.model_copy(update={"included": False, "exclusion_reason": "검사 제외"})
        if item.requirement_id == "R2"
        else item
        for item in ctx.criteria.items
    )
    return ctx.model_copy(update={"criteria": ctx.criteria.model_copy(update={"items": items})})


def test_expected_items_selects_included_applicable_items_and_preserves_order():
    ctx = mixed_context()
    before = ctx.model_dump_json()

    request = prepare_report_check_request(ctx)

    assert [(item.requirement_id, item.subcondition_ids) for item in request.expected_items] == [
        ("R1", ("R1-S1", "R1-S2")),
        ("R3", ()),
        ("R5", ("R5-S1",)),
    ]
    assert request.criteria == ctx.criteria
    assert request.original_requirements == ctx.original_draft.requirements
    assert ctx.model_dump_json() == before
    response = ReportCheckResponse.model_validate(payload(ctx))
    validate_response(ctx, response)
    assert tuple(item.requirement_id for item in response.items) == tuple(
        item.requirement_id for item in request.expected_items
    )


def test_expected_items_can_be_empty_with_included_nonapplicable_criterion():
    ctx = context()
    items = tuple(
        item
        if item.classification == "conditional"
        else item.model_copy(update={"included": False, "exclusion_reason": "검사 제외"})
        for item in ctx.criteria.items
    )
    ctx = ctx.model_copy(update={"criteria": ctx.criteria.model_copy(update={"items": items})})

    request = prepare_report_check_request(ctx)

    assert request.expected_items == ()
    assert request.model_dump(mode="json")["expected_items"] == []
    validate_response(ctx, ReportCheckResponse.model_validate(payload(ctx)))


@pytest.mark.parametrize(
    ("included", "application", "expected_ids"),
    [
        (True, "applies", ("R1", "R2", "R3", "R4", "R5")),
        (False, "undetermined", ("R1", "R2", "R3", "R5")),
    ],
)
def test_conditional_selection_matches_validator(included, application, expected_ids):
    ctx = context()
    items = tuple(
        item.model_copy(
            update={
                "included": included,
                "application_status": application,
                "application_reason": "조건 확인" if included else None,
                "exclusion_reason": None if included else "검사 제외",
            }
        )
        if item.classification == "conditional"
        else item
        for item in ctx.criteria.items
    )
    ctx = ctx.model_copy(update={"criteria": ctx.criteria.model_copy(update={"items": items})})

    request = prepare_report_check_request(ctx)

    assert tuple(item.requirement_id for item in request.expected_items) == expected_ids
    response = ReportCheckResponse.model_validate(payload(ctx))
    validate_response(ctx, response)
    assert tuple(item.requirement_id for item in response.items) == expected_ids


def test_expected_items_and_nested_identifiers_are_immutable():
    request = prepare_report_check_request(context())

    assert isinstance(request.expected_items, tuple)
    assert isinstance(request.expected_items[0].subcondition_ids, tuple)
    with pytest.raises(ValidationError, match="frozen"):
        request.expected_items[0].requirement_id = "changed"
    with pytest.raises(ValidationError, match="frozen"):
        request.expected_items[0].subcondition_ids = ()
    with pytest.raises(ValidationError, match="frozen"):
        request.expected_items = ()


def test_wire_preserves_expected_ids_and_response_contract():
    request = prepare_report_check_request(mixed_context())
    serialized = request.model_dump_json()
    prepared = json.loads(wire_document(serialized).prepare(serialized))

    assert prepared["expected_items"] == request.model_dump(mode="json")["expected_items"]
    assert prepared["criteria"] == request.criteria.model_dump(mode="json")
    assert prepared["blocks"][0]["block_id"] == "b0"
    schema = json.loads(request.response_schema_json)
    assert schema == ReportCheckModelResponse.model_json_schema()
    assert "expected_items" not in schema["properties"]
    assert set(schema["$defs"]["CitationInput"]["properties"]) == {
        "block_id",
        "quote",
        "char_range",
    }


def test_expected_metadata_does_not_relax_response_identity_validation():
    ctx = mixed_context()
    request = prepare_report_check_request(ctx)
    response = ReportCheckResponse.model_validate(payload(ctx))
    assert len(request.expected_items) > 1

    with pytest.raises(ReportCheckError) as error:
        validate_response(ctx, response.model_copy(update={"items": response.items[::-1]}))

    assert error.value.code == ReportCheckErrorCode.INVALID_IDENTITY
