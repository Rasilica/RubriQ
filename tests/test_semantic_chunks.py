import json

import pytest
from report_check_helpers import context, evidence, payload
from requirement_helpers import guide_document, response_payload

from submission.report_check_contracts import (
    ReportCheckError,
    ReportCheckErrorCode,
    ReportCheckResponse,
)
from submission.report_check_validation import with_cited_blocks_reviewed
from submission.requirement_contracts import RequirementError, RequirementErrorCode
from submission.requirement_validation import sent_block_count
from submission.semantic_chunks import (
    JUDGMENT_PRECEDENCE,
    MAX_CHECK_CHUNKS,
    MAX_REQUIREMENT_CHUNKS,
    ChunkOverflowError,
    check_chunk_contexts,
    merge_check_completions,
    merge_judgment,
    merge_requirement_completions,
    plan_chunks,
    requirement_chunk_documents,
)
from submission.semantic_context import CHECK_LIMITS
from submission.semantic_service import REQUIREMENT_LIMITS


def with_blocks(document, texts):
    template = document.blocks[0]
    blocks = tuple(
        template.model_copy(
            update={"block_id": f"p1-b{i}", "raw_text": text, "normalized_text": text}
        )
        for i, text in enumerate(texts, 1)
    )
    return document.model_copy(update={"blocks": blocks})


def test_plan_chunks_when_fits_returns_one_slice():
    assert plan_chunks([3, 3, 3], capacity=10, max_count=10, max_chunks=2) == ((0, 3),)


def test_plan_chunks_when_over_capacity_splits_consecutively_without_splitting_items():
    assert plan_chunks([6, 5, 5, 6], capacity=10, max_count=10, max_chunks=4) == (
        (0, 1),
        (1, 3),
        (3, 4),
    )


def test_plan_chunks_when_count_cap_binds_splits_by_count():
    assert plan_chunks([1, 1, 1], capacity=100, max_count=2, max_chunks=2) == ((0, 2), (2, 3))


@pytest.mark.parametrize(
    ("sizes", "capacity", "max_chunks"),
    [([11], 10, 5), ([6, 6, 6], 10, 2), ([1], 0, 5), ([1], -3, 5)],
)
def test_plan_chunks_when_impossible_raises(sizes, capacity, max_chunks):
    with pytest.raises(ChunkOverflowError):
        plan_chunks(sizes, capacity=capacity, max_count=10, max_chunks=max_chunks)


def test_merge_judgment_precedence_is_documented_order():
    assert JUDGMENT_PRECEDENCE == (
        "evidence_found",
        "partially_satisfied",
        "explicit_noncompliance",
        "deferred",
        "evidence_missing",
    )


@pytest.mark.parametrize("other", JUDGMENT_PRECEDENCE)
def test_merge_judgment_evidence_found_beats_everything(other):
    assert merge_judgment([other, "evidence_found"]) == "evidence_found"
    assert merge_judgment(["evidence_found", other]) == "evidence_found"


@pytest.mark.parametrize("other", ["explicit_noncompliance", "deferred", "evidence_missing"])
def test_merge_judgment_partial_beats_weaker(other):
    assert merge_judgment([other, "partially_satisfied"]) == "partially_satisfied"


def test_merge_judgment_deferred_does_not_become_missing():
    assert merge_judgment(["evidence_missing", "deferred"]) == "deferred"
    assert merge_judgment(["deferred", "evidence_missing"]) == "deferred"


def test_merge_judgment_noncompliance_beats_missing_and_deferred():
    assert merge_judgment(["evidence_missing", "explicit_noncompliance"]) == (
        "explicit_noncompliance"
    )
    assert merge_judgment(["deferred", "explicit_noncompliance"]) == "explicit_noncompliance"


def test_merge_judgment_missing_only_when_all_missing():
    assert merge_judgment(["evidence_missing", "evidence_missing"]) == "evidence_missing"


def test_merge_judgment_single_value_is_identity():
    for value in JUDGMENT_PRECEDENCE:
        assert merge_judgment([value]) == value


def chunk_fixture():
    ctx = context()
    report = with_blocks(ctx.report, ["가" * 10, "나" * 10, "다" * 10])
    ctx = ctx.model_copy(update={"report": report})

    def part(blocks):
        return ctx.model_copy(update={"report": report.model_copy(update={"blocks": blocks})})

    return ctx, (part(report.blocks[:2]), part(report.blocks[2:]))


def chunk_raw(chunk, **changes):
    body = payload(chunk)
    body.update(changes)
    return json.dumps(body)


def cite(chunk, index):
    block = chunk.report.blocks[index]
    return {
        "citation": {
            "block_id": block.block_id,
            "char_range": {"start": 0, "end": len(block.raw_text)},
            "quote": block.raw_text,
        },
        "evidence_role": "content",
        "relation": "근거",
    }


def merge(ctx, chunks, raws):
    return json.loads(merge_check_completions(ctx, chunks, raws, CHECK_LIMITS))


def test_merge_check_when_evidence_only_in_second_chunk_uses_that_chunk():
    ctx, chunks = chunk_fixture()
    first = payload(chunks[0])
    second = payload(chunks[1])
    second["items"][0].update(
        proposed_judgment="evidence_found", reason="둘째 근거", evidence=[cite(chunks[1], 0)]
    )
    merged = merge(ctx, chunks, [json.dumps(first), json.dumps(second)])
    item = merged["items"][0]
    assert item["proposed_judgment"] == "evidence_found"
    assert item["reason"] == "둘째 근거"
    assert item["evidence"] == [cite(chunks[1], 0)]
    assert merged["reviewed_block_ids"] == ["p1-b1", "p1-b2", "p1-b3"]
    assert merged["items"][1]["proposed_judgment"] == "evidence_missing"


def test_merge_check_reason_comes_from_first_winning_chunk_and_subconditions_merge():
    ctx, chunks = chunk_fixture()
    first, second = payload(chunks[0]), payload(chunks[1])
    first["items"][0]["subconditions"][0].update(
        proposed_judgment="evidence_found", reason="첫째", evidence=[cite(chunks[0], 0)]
    )
    second["items"][0]["subconditions"][0].update(
        proposed_judgment="evidence_found", reason="둘째", evidence=[cite(chunks[1], 0)]
    )
    sub = merge(ctx, chunks, [json.dumps(first), json.dumps(second)])["items"][0]["subconditions"]
    assert sub[0]["reason"] == "첫째"
    assert [e["citation"]["block_id"] for e in sub[0]["evidence"]] == ["p1-b1", "p1-b3"]
    assert sub[1]["proposed_judgment"] == "evidence_missing"


def test_merge_check_dedupes_and_caps_evidence_at_ten():
    ctx, chunks = chunk_fixture()
    first, second = payload(chunks[0]), payload(chunks[1])
    same = cite(chunks[0], 0)
    first["items"][0].update(proposed_judgment="evidence_found", evidence=[same] * 3)
    second["items"][0].update(proposed_judgment="evidence_found", evidence=[cite(chunks[1], 0)])
    merged_one = merge(ctx, chunks, [json.dumps(first), json.dumps(second)])["items"][0]
    assert len(merged_one["evidence"]) == 2
    many = [{**cite(chunks[0], 0), "relation": f"관계{n}"} for n in range(8)]
    first["items"][0]["evidence"] = many
    second["items"][0]["evidence"] = [
        {**cite(chunks[1], 0), "relation": f"관계{n}"} for n in range(8)
    ]
    merged = merge(ctx, chunks, [json.dumps(first), json.dumps(second)])["items"][0]["evidence"]
    assert len(merged) == 10
    assert merged[:8] == many


def test_merge_check_omitted_item_in_one_chunk_is_ignored_and_in_all_chunks_fails_identity():
    ctx, chunks = chunk_fixture()
    first, second = payload(chunks[0]), payload(chunks[1])
    second["items"][1].update(proposed_judgment="evidence_found", evidence=[cite(chunks[1], 0)])
    first["items"].pop(1)
    merged = merge(ctx, chunks, [json.dumps(first), json.dumps(second)])
    assert merged["items"][1]["proposed_judgment"] == "evidence_found"
    second["items"].pop(1)
    absent = merge(ctx, chunks, [json.dumps(first), json.dumps(second)])
    assert len(absent["items"]) == len(first["items"])


def test_merge_check_rejects_scope_and_header_violations():
    ctx, chunks = chunk_fixture()
    first, second = payload(chunks[0]), payload(chunks[1])
    leaked = {**second, "reviewed_block_ids": ["p1-b1"]}
    with pytest.raises(ReportCheckError) as scope:
        merge(ctx, chunks, [json.dumps(first), json.dumps(leaked)])
    assert scope.value.code == ReportCheckErrorCode.INVALID_SCOPE


def test_check_chunk_contexts_when_fits_returns_original_context():
    ctx = context()
    assert check_chunk_contexts(ctx, CHECK_LIMITS) == (ctx,)


def with_report(ctx, texts):
    return ctx.model_copy(update={"report": with_blocks(ctx.report, texts)})


def test_check_chunk_contexts_when_over_budget_returns_disjoint_consecutive_slices():
    ctx = with_report(context(), ["가" * 25000] * 4)
    chunks = check_chunk_contexts(ctx, CHECK_LIMITS)
    assert len(chunks) > 1
    ids = [block.block_id for chunk in chunks for block in chunk.report.blocks]
    assert ids == [block.block_id for block in ctx.report.blocks]
    assert all(chunk.guide == ctx.guide and chunk.criteria == ctx.criteria for chunk in chunks)


@pytest.mark.parametrize(
    "texts",
    [["가" * 60000], ["가" * 20000] * (MAX_CHECK_CHUNKS * 3 + 1)],
)
def test_check_chunk_contexts_when_unplannable_raises_input_limit(texts):
    with pytest.raises(ReportCheckError) as error:
        check_chunk_contexts(with_report(context(), texts), CHECK_LIMITS)
    assert error.value.code == ReportCheckErrorCode.INPUT_LIMIT


def test_requirement_chunks_when_fits_returns_same_document():
    guide = guide_document()
    assert requirement_chunk_documents(guide, REQUIREMENT_LIMITS) == (guide,)


def test_requirement_chunks_split_and_cap():
    guide = guide_document()
    docs = requirement_chunk_documents(with_blocks(guide, ["가" * 15000] * 3), REQUIREMENT_LIMITS)
    assert len(docs) == 3
    assert MAX_REQUIREMENT_CHUNKS == 3
    with pytest.raises(RequirementError) as error:
        requirement_chunk_documents(with_blocks(guide, ["가" * 15000] * 4), REQUIREMENT_LIMITS)
    assert error.value.code == RequirementErrorCode.INPUT_LIMIT
    with pytest.raises(RequirementError):
        requirement_chunk_documents(with_blocks(guide, ["가" * 20001]), REQUIREMENT_LIMITS)


def requirement_chunk(document, quote_block, requirement_count=1):
    block = document.blocks[quote_block]
    base = response_payload()
    template = base["requirements"][0]
    citation = {
        "block_id": block.block_id,
        "char_range": {"start": 0, "end": 3},
        "quote": block.raw_text[:3],
    }
    requirements = [
        {
            **template,
            "requirement_id": "R1" if n == 0 else f"R{n + 1}",
            "citations": [citation],
            "subconditions": [
                {"subcondition_id": f"R{n + 1}-S1", "description": "하위", "citations": [citation]}
            ],
        }
        for n in range(requirement_count)
    ]
    return json.dumps({**base, "requirements": requirements})


def test_merge_requirements_renumbers_ids_and_verifies_citations():
    guide = with_blocks(guide_document(), ["가나다" * 10] * 3)
    raws = [requirement_chunk(guide, i, 2) for i in range(3)]
    merged = json.loads(merge_requirement_completions(guide, raws, REQUIREMENT_LIMITS))
    ids = [r["requirement_id"] for r in merged["requirements"]]
    assert ids == [f"R{n}" for n in range(1, 7)]
    subs = [s["subcondition_id"] for r in merged["requirements"] for s in r["subconditions"]]
    assert subs == [f"R{n}-S1" for n in range(1, 7)]


def test_merge_requirements_when_over_max_requirements_fails_no_partial():
    guide = with_blocks(guide_document(), ["가나다" * 10] * 2)
    raws = [requirement_chunk(guide, i, 16) for i in range(2)]
    with pytest.raises(RequirementError) as error:
        merge_requirement_completions(guide, raws, REQUIREMENT_LIMITS)
    assert error.value.code == RequirementErrorCode.RESPONSE_LIMIT


def test_sent_block_count_is_what_chunks_split():
    guide = with_blocks(guide_document(), ["가", " ", "나"])
    assert sent_block_count(guide) == 2


def test_merge_check_when_chunk_cites_own_block_missing_from_reviewed_counts_it_reviewed():
    ctx, chunks = chunk_fixture()
    first, second = payload(chunks[0]), payload(chunks[1])
    second["reviewed_block_ids"] = []
    second["items"][0].update(proposed_judgment="evidence_found", evidence=[cite(chunks[1], 0)])
    merged = merge(ctx, chunks, [json.dumps(first), json.dumps(second)])
    assert merged["reviewed_block_ids"] == ["p1-b1", "p1-b2", "p1-b3"]


@pytest.mark.parametrize("target", ["other_chunk", "guide", "invented"])
def test_merge_check_when_chunk_cites_block_it_was_not_sent_rejects(target):
    ctx, chunks = chunk_fixture()
    first, second = payload(chunks[0]), payload(chunks[1])
    entry = cite(chunks[0], 0)
    if target == "guide":
        entry["citation"]["block_id"] = ctx.guide.blocks[0].block_id
    elif target == "invented":
        entry["citation"]["block_id"] = "absent"
    second["reviewed_block_ids"] = []
    second["items"][0]["evidence"] = [entry]
    with pytest.raises(ReportCheckError) as scope:
        merge(ctx, chunks, [json.dumps(first), json.dumps(second)])
    assert scope.value.code == ReportCheckErrorCode.INVALID_SCOPE


def test_with_cited_blocks_reviewed_orders_dedupes_and_does_not_mutate():
    ctx = context()
    raw = payload(ctx)
    ids = [b.block_id for b in ctx.report.blocks if b.raw_text.strip()]
    assert len(ids) >= 2
    base = evidence(ctx)["citation"]
    cites = [{**evidence(ctx), "citation": {**base, "block_id": i}} for i in ids]
    raw["items"][0]["evidence"] = [cites[1], cites[0], cites[1]]
    raw["reviewed_block_ids"] = [ids[1]]
    response = ReportCheckResponse.model_validate_json(json.dumps(raw))
    result = with_cited_blocks_reviewed(response, ids)
    assert result.reviewed_block_ids[:2] == (ids[0], ids[1])
    assert len(set(result.reviewed_block_ids)) == len(result.reviewed_block_ids)
    assert response.reviewed_block_ids == (ids[1],)
    assert result is not response
    assert with_cited_blocks_reviewed(result, ids) is result
