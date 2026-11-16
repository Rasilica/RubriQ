from pathlib import Path
from typing import assert_never

from submission.document_contracts import CommonDocument
from submission.evidence_artifacts import binding_digest
from submission.evidence_contracts import ArtifactBinding, PageSelection, PdfArtifactInput
from submission.extraction import extract_pdf
from submission.models import DocumentRole, PdfInput
from submission.page_rule_contracts import PageRuleInput, SubmissionCheckContext
from submission.pdf_adapter import adapt_pdf
from submission.report_check_contracts import ReportCheckContext, ReportCheckResponse
from submission.report_check_validation import criteria_fingerprint
from submission.result_assets import SAMPLES, bounded_read, load_raster, report_document_id
from submission.result_contracts import (
    CaseSummary,
    LoadedRaster,
    ResultCase,
    ResultDetail,
    ViewerBlock,
    ViewerDocument,
    ViewerDocuments,
    ViewerPage,
)
from submission.result_structure import structure_document, structure_viewer
from submission.result_structure_check import structure_response
from submission.result_structure_mapping import structure_scenarios
from submission.review_contracts import WorkingCopyRequest
from submission.review_logic import confirm_session, save_working_copy
from submission.review_store import demo_session
from submission.submission_check import build_submission_check


def case_summary(case: ResultCase) -> CaseSummary:
    match case:
        case ResultCase.DOCX_STRUCTURE:
            label, description = (
                "DOCX 구조 · 합성 예시",
                "원본 쪽번호 없이 구조·인용·미지원 요소를 확인하는 합성 개발 자료",
            )
        case ResultCase.HWPX_STRUCTURE:
            label, description = (
                "HWPX 구조 · 합성 예시",
                "중첩 표·각주·머리말·꼬리말과 미지원 요소를 확인하는 합성 개발 자료",
            )
        case ResultCase.NORMAL:
            label, description = "정상 보고서", "근거와 전체 2페이지 상한을 확인하는 고정 예시"
        case ResultCase.MISSING:
            label, description = "필수 근거 누락", "일부 필수 하위 조건의 근거가 없는 고정 예시"
        case ResultCase.OVER_LIMIT:
            label, description = (
                "페이지 상한 초과",
                "실제 3페이지 PDF가 2페이지 상한을 초과하는 예시",
            )
        case ResultCase.UNCONFIRMED_SCOPE:
            label, description = (
                "페이지 범위 미확정",
                "포함 범위 미확정으로 페이지 판정을 보류하는 예시",
            )
        case _:
            assert_never(case)
    return CaseSummary(case_id=case, label=label, description=description)


def common_document(raster: LoadedRaster, role: DocumentRole) -> CommonDocument:
    source = PdfInput(Path(raster.descriptor.pdf_path).name, raster.pdf_bytes, role)
    return adapt_pdf(source, extract_pdf(source))


def report_context(guide: CommonDocument, report: CommonDocument) -> ReportCheckContext:
    session = demo_session("fixed-result-demo")
    items = tuple(
        item.model_dump(exclude={"edited_fields"})
        | (
            {"application_status": "does_not_apply", "application_reason": "합성 문장만 사용"}
            if item.requirement_id == "R4"
            else {}
        )
        for item in session.items
    )
    request = WorkingCopyRequest.model_validate({"expected_revision": 0, "items": items})
    confirmed = confirm_session(save_working_copy(session, request), 1, 20)
    return ReportCheckContext(
        guide=guide,
        report=report,
        original_draft=confirmed.original_draft,
        criteria=confirmed.versions[0],
    )


def viewer_document(
    case: ResultCase, raster: LoadedRaster, document: CommonDocument
) -> ViewerDocument:
    base = f"/api/result-demos/{case.value}/documents/{document.source.role.value}"
    return ViewerDocument(
        source=document.source,
        artifact=document.artifacts[0],
        page_count=len(raster.descriptor.pages),
        pages=tuple(
            ViewerPage(
                page_number=page.page_number,
                image_url=f"{base}/pages/{page.page_number}.png",
                width=page.width,
                height=page.height,
            )
            for page in raster.descriptor.pages
        ),
        blocks=tuple(
            ViewerBlock(
                block_id=block.block_id,
                raw_text=block.raw_text,
                source_locator=block.source_locator,
            )
            for block in document.blocks
        ),
        original_url=f"{base}/original.pdf",
        mappings=document.mappings,
        warnings=document.warnings,
        typed_errors=document.typed_errors,
        coverage=document.coverage,
        extraction_status=document.extraction_status,
    )


def check_input(
    case: ResultCase, raster: LoadedRaster, context: ReportCheckContext
) -> PageRuleInput:
    target = PdfArtifactInput(
        binding=ArtifactBinding(source=context.report.source, artifact=context.report.artifacts[0]),
        pdf=PdfInput(Path(raster.descriptor.pdf_path).name, raster.pdf_bytes, DocumentRole.REPORT),
    )
    selection = PageSelection(
        binding_sha256=binding_digest(target),
        basis="original_pdf",
        included_pages=tuple(range(1, len(raster.descriptor.pages) + 1)),
        excluded_pages=(),
        scope_confirmed=case != ResultCase.UNCONFIRMED_SCOPE,
    )
    return PageRuleInput(requirement_id="R5", target=target, selection=selection)


def authored_response(case: ResultCase, context: ReportCheckContext) -> str:
    name = "missing" if case == ResultCase.MISSING else "normal"
    response = ReportCheckResponse.model_validate_json(
        bounded_read(SAMPLES / f"checks/{name}-offline-response.json", 1_000_000), strict=True
    )
    return response.model_copy(
        update={
            "criteria_sha256": criteria_fingerprint(context),
            "report_source_id": context.report.source.source_id,
            "report_document_version_id": context.report.source.document_version_id,
            "report_source_sha256": context.report.source.content_sha256,
            "reviewed_block_ids": tuple(block.block_id for block in context.report.blocks),
        }
    ).model_dump_json()


def build_result_demo(case: ResultCase) -> ResultDetail:
    guide_raster = load_raster("guide")
    if case in (ResultCase.DOCX_STRUCTURE, ResultCase.HWPX_STRUCTURE):
        return build_structure_demo(case, guide_raster)
    report_raster = load_raster(report_document_id(case))
    guide = common_document(guide_raster, DocumentRole.GUIDE)
    report = common_document(report_raster, DocumentRole.REPORT)
    context = report_context(guide, report)
    summary = case_summary(case)
    check = build_submission_check(
        SubmissionCheckContext(
            report_check=context, page_checks=(check_input(case, report_raster, context),)
        ),
        authored_response(case, context),
    )
    return ResultDetail(
        case_id=case,
        label=summary.label,
        description=summary.description,
        check=check,
        documents=ViewerDocuments(
            guide=viewer_document(case, guide_raster, guide),
            report=viewer_document(case, report_raster, report),
        ),
    )


def build_structure_demo(case: ResultCase, guide_raster: LoadedRaster) -> ResultDetail:
    guide = common_document(guide_raster, DocumentRole.GUIDE)
    report = structure_document(case)
    context = report_context(guide, report)
    summary = case_summary(case)
    return ResultDetail(
        case_id=case,
        label=summary.label,
        description=summary.description,
        check=build_submission_check(
            SubmissionCheckContext(
                report_check=context,
                page_checks=(PageRuleInput(requirement_id="R5", target=None, selection=None),),
            ),
            structure_response(context),
        ),
        documents=ViewerDocuments(
            guide=viewer_document(case, guide_raster, guide),
            report=structure_viewer(report),
        ),
        structure_scenarios=structure_scenarios(report),
    )
