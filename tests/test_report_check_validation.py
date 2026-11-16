import json

import pytest
from report_check_helpers import context, evidence, payload

from submission.document_contracts import CharacterRange, ProcessingStatus
from submission.models import DocumentRole
from submission.report_check_adapter import build_report_check, prepare_report_check_request
from submission.report_check_contracts import ReportCheckError, ReportCheckLimits


@pytest.mark.parametrize(
    "field",
    ["report_source_id", "report_document_version_id", "report_source_sha256", "criteria_sha256"],
)
def test_response_when_source_or_snapshot_is_stale_rejects(field):
    # Given
    ctx = context()
    raw = {**payload(ctx), field: "0" * 64}
    # When
    with pytest.raises(ReportCheckError) as error:
        build_report_check(ctx, json.dumps(raw))
    # Then
    assert error.value.code in {"source_mismatch", "criteria_mismatch"}


@pytest.mark.parametrize(
    "change",
    [
        "duplicate_scope",
        "unknown_scope",
        "unreviewed_cite",
        "missing_item",
        "reordered_item",
        "missing_sub",
        "duplicate_sub",
        "quote",
        "range",
        "unknown_cite",
    ],
)
def test_response_when_identity_or_citation_invalid_rejects(change):
    # Given
    ctx = context()
    raw = payload(ctx)
    cite = evidence(ctx)
    raw["items"][2]["evidence"] = [cite]
    if change == "duplicate_scope":
        raw["reviewed_block_ids"] *= 2
    elif change == "unknown_scope":
        raw["reviewed_block_ids"] += ["absent"]
    elif change == "unreviewed_cite":
        raw["reviewed_block_ids"] = []
    elif change == "missing_item":
        raw["items"].pop()
    elif change == "reordered_item":
        raw["items"].reverse()
    elif change == "missing_sub":
        raw["items"][0]["subconditions"].pop()
    elif change == "duplicate_sub":
        raw["items"][0]["subconditions"][1] = raw["items"][0]["subconditions"][0]
    elif change == "quote":
        cite["citation"]["quote"] += "위조"
    elif change == "range":
        cite["citation"]["char_range"]["end"] += 1000
    else:
        cite["citation"]["block_id"] = "absent"
    # When
    with pytest.raises(ReportCheckError) as error:
        build_report_check(ctx, json.dumps(raw))
    # Then
    assert error.value.code in {"invalid_scope", "invalid_identity", "invalid_citation"}


@pytest.mark.parametrize(
    "change",
    [
        "role",
        "failed",
        "empty",
        "duplicate_block",
        "locator_hash",
        "guide_role",
        "draft_hash",
        "criteria_version",
        "criteria_revision",
        "criteria_id",
        "criteria_sub_id",
        "original_locator",
        "original_quote",
    ],
)
def test_context_when_provenance_invalid_is_rejected(change):
    # Given
    ctx = context()
    if change == "role":
        ctx = ctx.model_copy(
            update={
                "report": ctx.report.model_copy(
                    update={
                        "source": ctx.report.source.model_copy(update={"role": DocumentRole.GUIDE})
                    }
                )
            }
        )
    elif change == "failed":
        ctx = ctx.model_copy(
            update={
                "report": ctx.report.model_copy(
                    update={"extraction_status": ProcessingStatus.FAILED}
                )
            }
        )
    elif change == "empty":
        ctx = ctx.model_copy(update={"report": ctx.report.model_copy(update={"blocks": ()})})
    elif change == "duplicate_block":
        ctx = ctx.model_copy(
            update={"report": ctx.report.model_copy(update={"blocks": ctx.report.blocks * 2})}
        )
    elif change == "locator_hash":
        first = ctx.report.blocks[0]
        first = first.model_copy(
            update={
                "source_locator": first.source_locator.model_copy(
                    update={"source_sha256": "0" * 64}
                )
            }
        )
        ctx = ctx.model_copy(
            update={
                "report": ctx.report.model_copy(update={"blocks": (first, *ctx.report.blocks[1:])})
            }
        )
    elif change == "guide_role":
        ctx = ctx.model_copy(update={"guide": ctx.report})
    elif change == "draft_hash":
        ctx = ctx.model_copy(
            update={
                "original_draft": ctx.original_draft.model_copy(update={"source_sha256": "0" * 64})
            }
        )
    elif change in {"criteria_version", "criteria_revision"}:
        ctx = ctx.model_copy(
            update={
                "criteria": ctx.criteria.model_copy(
                    update={"version" if change == "criteria_version" else "revision": -1}
                )
            }
        )
    elif change in {"criteria_id", "criteria_sub_id"}:
        first = ctx.criteria.items[0]
        updates = (
            {"requirement_id": "changed"} if change == "criteria_id" else {"subconditions": ()}
        )
        ctx = ctx.model_copy(
            update={
                "criteria": ctx.criteria.model_copy(
                    update={"items": (first.model_copy(update=updates), *ctx.criteria.items[1:])}
                )
            }
        )
    else:
        first = ctx.original_draft.requirements[0]
        citation = first.citations[0]
        update = (
            {"quote": "위조"}
            if change == "original_quote"
            else {"source_locator": citation.source_locator.model_copy(update={"path": "forged"})}
        )
        first = first.model_copy(update={"citations": (citation.model_copy(update=update),)})
        ctx = ctx.model_copy(
            update={
                "original_draft": ctx.original_draft.model_copy(
                    update={"requirements": (first, *ctx.original_draft.requirements[1:])}
                )
            }
        )
    # When
    with pytest.raises(ReportCheckError):
        prepare_report_check_request(ctx)
    # Then: no request escapes the boundary.


def test_quote_when_unicode_and_nonzero_source_offset_uses_block_coordinates():
    # Given
    ctx = context()
    first = ctx.report.blocks[0].model_copy(
        update={"raw_text": "한😀é 반복 반복", "raw_char_range": CharacterRange(start=100, end=111)}
    )
    ctx = ctx.model_copy(update={"report": ctx.report.model_copy(update={"blocks": (first,)})})
    raw = payload(ctx)
    cite = evidence(ctx)
    cite["citation"].update(char_range={"start": 8, "end": 10}, quote="반복")
    raw["items"][2].update(proposed_judgment="evidence_found", evidence=[cite])
    # When
    result = build_report_check(ctx, json.dumps(raw))
    # Then
    verified = result.items[2].evidence[0].citation
    assert verified.char_range.start == 8
    assert verified.quote == "반복"
    assert verified.source_locator == first.source_locator
    assert result.items[2].evidence[0].semantic_relation_verified is False


@pytest.mark.parametrize(
    "limits", [ReportCheckLimits(max_blocks=1), ReportCheckLimits(max_input_characters=1)]
)
def test_context_when_input_exceeds_limits_rejects(limits):
    # Given
    ctx = context()
    # When
    with pytest.raises(ReportCheckError):
        prepare_report_check_request(ctx, limits=limits)
    # Then: input is rejected rather than silently truncated.


def test_context_when_criteria_text_exceeds_budget_is_rejected():
    # Given: each document fits; edited criterion text exceeds the remaining input budget.
    ctx = context()
    criterion = ctx.criteria.items[0].model_copy(update={"title": "가" * 2000})
    ctx = ctx.model_copy(
        update={
            "criteria": ctx.criteria.model_copy(
                update={"items": (criterion, *ctx.criteria.items[1:])}
            )
        }
    )
    limit = max(
        sum(len(block.raw_text) for block in document.blocks)
        for document in (ctx.guide, ctx.report)
    )
    # When
    with pytest.raises(ReportCheckError) as error:
        prepare_report_check_request(ctx, limits=ReportCheckLimits(max_input_characters=limit))
    # Then
    assert error.value.code == "input_limit"
