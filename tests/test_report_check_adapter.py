import json

from report_check_helpers import context, payload

from submission.report_check_adapter import OfflineReportCheckAdapter, prepare_report_check_request


def test_offline_replay_when_real_pdf_and_confirmed_snapshot():
    # Given: real PDF extraction and the T04b confirmation path.
    ctx = context()
    before = ctx.model_dump_json()
    # When: a caller supplies a complete, source-bound response.
    result = OfflineReportCheckAdapter(json.dumps(payload(ctx))).check(ctx)
    # Then: exclusions are authoritative and caller input remains immutable.
    assert result.items[3].applicability == "not_applicable"
    assert result.items[3].judgment is None
    assert result.items[2].needs_attention is False
    assert result.ai_called is False
    assert ctx.model_dump_json() == before
    assert result.report_coverage == ctx.report.coverage


def test_request_when_prepared_exposes_exact_submitted_scope():
    # Given
    ctx = context()
    # When
    request = prepare_report_check_request(ctx)
    # Then
    assert tuple(block.block_id for block in request.blocks) == tuple(
        payload(ctx)["reviewed_block_ids"]
    )
    assert request.criteria_sha256 == payload(ctx)["criteria_sha256"]
