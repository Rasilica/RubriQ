# /// script
# requires-python = ">=3.13"
# dependencies = []
# ///
# Run from API: PYTHONPATH=src .venv/bin/python -m tools.run_submission_check_demo
import json
import sys
from enum import StrEnum
from io import BytesIO
from pathlib import Path
from typing import assert_never

from pypdf import PdfReader, PdfWriter

from submission.evidence_artifacts import binding_digest
from submission.evidence_contracts import ArtifactBinding, PageSelection, PdfArtifactInput
from submission.extraction import extract_pdf
from submission.models import DocumentRole, FrozenModel, PdfInput
from submission.page_rule_contracts import (
    PageRuleInput,
    SubmissionCheckContext,
    SubmissionCheckResult,
)
from submission.pdf_adapter import adapt_pdf
from submission.report_check_contracts import ReportCheckContext, ReportCheckResponse
from submission.report_check_validation import criteria_fingerprint
from submission.submission_check import build_submission_check
from tools.run_evidence_mapping_demo import synthetic_target
from tools.run_report_check_demo import DemoReportName, demo_context


class DemoCase(StrEnum):
    NORMAL = "normal"
    MISSING = "missing"
    PARAPHRASED = "paraphrased"
    OVER_LIMIT = "over_limit"
    UNCONFIRMED_SCOPE = "unconfirmed_scope"
    PARTIAL_SCOPE = "partial_scope"
    EDITED_CRITERION = "edited_criterion"
    MISSING_ARTIFACT = "missing_artifact"
    SYNTHETIC = "synthetic"


class DemoResult(FrozenModel):
    case_name: DemoCase
    check: SubmissionCheckResult


def report_name(case: DemoCase) -> DemoReportName:
    match case:
        case DemoCase.MISSING:
            return DemoReportName.MISSING
        case DemoCase.PARAPHRASED:
            return DemoReportName.PARAPHRASED
        case (
            DemoCase.NORMAL
            | DemoCase.OVER_LIMIT
            | DemoCase.UNCONFIRMED_SCOPE
            | DemoCase.PARTIAL_SCOPE
            | DemoCase.EDITED_CRITERION
            | DemoCase.MISSING_ARTIFACT
            | DemoCase.SYNTHETIC
        ):
            return DemoReportName.NORMAL
        case _:
            assert_never(case)


def report_input(case: DemoCase) -> PdfInput:
    path = Path(__file__).resolve().parents[1] / "samples/pdf" / f"{report_name(case).value}.pdf"
    content = path.read_bytes()
    match case:
        case DemoCase.OVER_LIMIT:
            reader = PdfReader(BytesIO(content))
            writer = PdfWriter()
            for page in reader.pages:
                _ = writer.add_page(page)
            _ = writer.add_page(reader.pages[-1])
            output = BytesIO()
            _ = writer.write(output)
            return PdfInput("over-limit.pdf", output.getvalue(), DocumentRole.REPORT)
        case (
            DemoCase.NORMAL
            | DemoCase.MISSING
            | DemoCase.PARAPHRASED
            | DemoCase.UNCONFIRMED_SCOPE
            | DemoCase.PARTIAL_SCOPE
            | DemoCase.EDITED_CRITERION
            | DemoCase.MISSING_ARTIFACT
            | DemoCase.SYNTHETIC
        ):
            return PdfInput(path.name, content, DocumentRole.REPORT)
        case _:
            assert_never(case)


def check_context(case: DemoCase, source: PdfInput) -> ReportCheckContext:
    context = demo_context(report_name(case)).model_copy(
        update={"report": adapt_pdf(source, extract_pdf(source))}
    )
    match case:
        case DemoCase.EDITED_CRITERION:
            edited = context.criteria.items[4].model_copy(
                update={
                    "title": "보고서는 PDF 파일 전체가 3페이지 이하여야 합니다.",
                    "edited_fields": (),
                }
            )
            criteria = context.criteria.model_copy(
                update={"version": 2, "revision": 2, "items": (*context.criteria.items[:4], edited)}
            )
            return context.model_copy(update={"criteria": criteria})
        case (
            DemoCase.NORMAL
            | DemoCase.MISSING
            | DemoCase.PARAPHRASED
            | DemoCase.OVER_LIMIT
            | DemoCase.UNCONFIRMED_SCOPE
            | DemoCase.PARTIAL_SCOPE
            | DemoCase.MISSING_ARTIFACT
            | DemoCase.SYNTHETIC
        ):
            return context
        case _:
            assert_never(case)


def page_input(case: DemoCase, context: ReportCheckContext, source: PdfInput) -> PageRuleInput:
    target = PdfArtifactInput(
        binding=ArtifactBinding(source=context.report.source, artifact=context.report.artifacts[0]),
        pdf=source,
    )
    count = len(PdfReader(BytesIO(source.content)).pages)
    selection = PageSelection(
        binding_sha256=binding_digest(target),
        basis="original_pdf",
        included_pages=tuple(range(1, count + 1)),
        excluded_pages=(),
        scope_confirmed=True,
    )
    match case:
        case DemoCase.MISSING_ARTIFACT:
            return PageRuleInput(requirement_id="R5", target=None, selection=None)
        case DemoCase.SYNTHETIC:
            synthetic = synthetic_target(context.report, ("합성 페이지", "합성 페이지"))
            scope = selection.model_copy(
                update={
                    "binding_sha256": binding_digest(synthetic),
                    "basis": "declared_submission_pdf",
                    "declared_submission_sha256": synthetic.binding.artifact.artifact_sha256,
                }
            )
            return PageRuleInput(requirement_id="R5", target=synthetic, selection=scope)
        case DemoCase.UNCONFIRMED_SCOPE:
            selection = selection.model_copy(update={"scope_confirmed": False})
        case DemoCase.PARTIAL_SCOPE:
            selection = selection.model_copy(
                update={"included_pages": (2,), "excluded_pages": (1,)}
            )
        case (
            DemoCase.NORMAL
            | DemoCase.MISSING
            | DemoCase.PARAPHRASED
            | DemoCase.OVER_LIMIT
            | DemoCase.EDITED_CRITERION
        ):
            pass
        case _:
            assert_never(case)
    return PageRuleInput(requirement_id="R5", target=target, selection=selection)


def authored_response(case: DemoCase, context: ReportCheckContext) -> str:
    path = (
        Path(__file__).resolve().parents[1]
        / "samples/checks"
        / f"{report_name(case).value}-offline-response.json"
    )
    response = ReportCheckResponse.model_validate_json(
        path.read_text(encoding="utf-8"), strict=True
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


def run_case(case: DemoCase) -> DemoResult:
    source = report_input(case)
    context = check_context(case, source)
    return DemoResult(
        case_name=case,
        check=build_submission_check(
            SubmissionCheckContext(
                report_check=context, page_checks=(page_input(case, context, source),)
            ),
            authored_response(case, context),
        ),
    )


def run_demo() -> tuple[DemoResult, ...]:
    return tuple(run_case(case) for case in DemoCase)


if __name__ == "__main__":
    _ = sys.stdout.write(
        json.dumps(
            [result.model_dump(mode="json") for result in run_demo()], ensure_ascii=False, indent=2
        )
        + "\n"
    )
