import json

import pytest
from report_check_helpers import context, payload
from requirement_helpers import guide_document, single_response

from submission.hwp_reader_contracts import HwpNode, HwpTree
from submission.hwp_reader_projection import project_tree
from submission.hwp_reader_validation import validate_tree
from submission.report_check_adapter import (
    INSTRUCTIONS as CHECK_INSTRUCTIONS,
)
from submission.report_check_adapter import (
    build_report_check,
    prepare_report_check_request,
)
from submission.report_check_contracts import ReportCheckError
from submission.requirement_adapter import INSTRUCTIONS as REQUIREMENT_INSTRUCTIONS
from submission.requirement_adapter import prepare_requirement_request
from submission.requirement_contracts import CitationInput, RequirementError
from submission.requirement_validation import sent_block_count, verify_citation
from submission.semantic_chunks import (
    check_chunk_contexts,
    merge_check_completions,
    requirement_chunk_documents,
)
from submission.semantic_context import CHECK_LIMITS
from submission.semantic_service import REQUIREMENT_LIMITS


def figure_of(block, suffix="fig"):
    return block.model_copy(
        update={
            "block_id": f"{block.block_id}-{suffix}",
            "kind": "figure",
            "raw_text": "",
            "normalized_text": "",
            "normalization_map": (),
            "source_spans": (),
            "raw_char_range": block.raw_char_range.model_copy(update={"start": 0, "end": 0}),
        }
    )


def with_figure(document, after=0):
    blocks = list(document.blocks)
    blocks.insert(after + 1, figure_of(blocks[after]))
    return document.model_copy(update={"blocks": tuple(blocks)})


def test_requirement_payload_without_figures_has_no_kind_key():
    request = prepare_requirement_request(guide_document())
    dumped = json.loads(request.model_dump_json())
    assert all(set(block) == {"block_id", "raw_text"} for block in dumped["blocks"])


def test_requirement_request_sends_figure_with_kind_and_empty_text():
    guide = with_figure(guide_document())
    request = prepare_requirement_request(guide)
    figures = [json.loads(b.model_dump_json()) for b in request.blocks if b.kind]
    assert figures == [
        {"block_id": guide.blocks[1].block_id, "raw_text": "", "kind": "figure"}
    ]
    assert len(request.blocks) == sent_block_count(guide)


def test_instructions_explain_figures_in_both_adapters():
    for text in (REQUIREMENT_INSTRUCTIONS, CHECK_INSTRUCTIONS):
        assert "kind가 figure인 블록" in text
        assert "인용하지 마세요" in text


def test_citing_a_figure_block_fails():
    guide = with_figure(guide_document())
    figure = guide.blocks[1]
    for quote in ("a", "그림"):
        citation = CitationInput(
            block_id=figure.block_id, char_range={"start": 0, "end": len(quote)}, quote=quote
        )
        with pytest.raises(RequirementError):
            verify_citation(citation, guide.blocks)


def test_report_check_sends_figure_kind():
    ctx = context()
    ctx = ctx.model_copy(update={"report": with_figure(ctx.report)})
    request = prepare_report_check_request(ctx)
    assert [b.kind for b in request.blocks].count("figure") == 1


def test_report_check_succeeds_when_figure_not_listed_as_reviewed():
    ctx = context()
    ctx = ctx.model_copy(update={"report": with_figure(ctx.report)})
    result = build_report_check(ctx, json.dumps(payload(ctx)))
    assert result.items


def test_listing_a_figure_as_reviewed_is_dropped():
    ctx = context()
    ctx = ctx.model_copy(update={"report": with_figure(ctx.report)})
    figure_id = ctx.report.blocks[1].block_id
    reply = payload(ctx)
    reply["reviewed_block_ids"].append(figure_id)
    result = build_report_check(ctx, json.dumps(reply))
    assert figure_id not in result.reviewed_block_ids
    assert result.reviewed_block_ids == tuple(payload(ctx)["reviewed_block_ids"])


def test_listing_an_invented_block_as_reviewed_is_still_rejected():
    ctx = context()
    ctx = ctx.model_copy(update={"report": with_figure(ctx.report)})
    reply = payload(ctx)
    reply["reviewed_block_ids"].append("invented-block")
    with pytest.raises(ReportCheckError):
        build_report_check(ctx, json.dumps(reply))


def test_chunked_merge_drops_figure_ids_but_rejects_other_chunk_ids():
    ctx = context()
    ctx = ctx.model_copy(update={"report": with_figure(ctx.report)})
    tight = CHECK_LIMITS.model_copy(
        update={"max_blocks": sent_block_count(ctx.guide) + sent_block_count(ctx.report) - 1}
    )
    chunks = check_chunk_contexts(ctx, tight)
    assert len(chunks) > 1
    figure_id = ctx.report.blocks[1].block_id
    raws = []
    for chunk in chunks:
        reply = payload(chunk)
        ids = [b.block_id for b in chunk.report.blocks if b.kind == "figure"]
        reply["reviewed_block_ids"] = [*reply["reviewed_block_ids"], *ids]
        raws.append(json.dumps(reply))
    assert any(figure_id in raw for raw in raws)
    merged = json.loads(merge_check_completions(ctx, chunks, raws, CHECK_LIMITS))
    assert figure_id not in merged["reviewed_block_ids"]
    other = next(b.block_id for b in chunks[1].report.blocks if b.raw_text)
    bad = json.loads(raws[0])
    bad["reviewed_block_ids"].append(other)
    with pytest.raises(ReportCheckError):
        merge_check_completions(ctx, chunks, [json.dumps(bad), *raws[1:]], CHECK_LIMITS)


def test_chunk_planning_keeps_figures_and_counts_only_text_for_review():
    ctx = context()
    ctx = ctx.model_copy(update={"report": with_figure(ctx.report)})
    assert check_chunk_contexts(ctx, CHECK_LIMITS) == (ctx,)
    tight = CHECK_LIMITS.model_copy(
        update={"max_blocks": sent_block_count(ctx.guide) + sent_block_count(ctx.report) - 1}
    )
    chunks = check_chunk_contexts(ctx, tight)
    assert len(chunks) > 1
    kept = [b for chunk in chunks for b in chunk.report.blocks]
    expected = [b.block_id for b in ctx.report.blocks if b.raw_text or b.kind == "figure"]
    assert [b.block_id for b in kept] == expected


def test_requirement_chunking_unchanged_without_overflow():
    guide = with_figure(guide_document())
    assert requirement_chunk_documents(guide, REQUIREMENT_LIMITS) == (guide,)


def test_single_response_helper_still_binds():
    guide = guide_document()
    assert single_response(guide, guide.blocks[0].raw_text[:5])


def hwp_source():
    return guide_document().source.model_copy(update={"detected_format": "hwp"})


def hwp_tree(nodes):
    return HwpTree(parts=("BodyText/Section0",), nodes=nodes, omitted=(), references=())


def test_hwp_projection_marks_figure_and_keeps_extraction_partial():
    sample_source = hwp_source()
    root = "BodyText/Section0/paragraph[0]"
    figure = f"{root}/control[2]"
    tree = hwp_tree(
        (
            HwpNode(path=root, kind="paragraph", text="앞", parent=None, fragment=1, start=0),
            HwpNode(path=figure, kind="figure", text="", parent=None, fragment=None, start=0),
            HwpNode(
                path=f"{figure}/paragraph[0]",
                kind="paragraph",
                text="그림 설명",
                parent=figure,
                fragment=1,
                start=0,
            ),
        )
    )
    document = validate_tree(tree, project_tree(tree, sample_source))
    assert [b.kind for b in document.blocks] == ["paragraph", "figure", "paragraph"]
    assert document.blocks[2].parent_block_id == document.blocks[1].block_id
    assert [w.code for w in document.warnings] == ["figure_content_unread"]
    assert document.extraction_status == "partial"


def test_figure_with_text_is_rejected_by_validation():
    sample_source = hwp_source()
    figure = "BodyText/Section0/paragraph[0]/control[0]"
    tree = hwp_tree(
        (HwpNode(path=figure, kind="figure", text="x", parent=None, fragment=None, start=0),)
    )
    with pytest.raises(Exception, match="output_invalid"):
        validate_tree(tree, project_tree(tree, sample_source))
