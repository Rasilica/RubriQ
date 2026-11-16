from pathlib import Path
from typing import ClassVar

from pydantic import BaseModel, ConfigDict

from submission.extraction import extract_pdf
from submission.models import DocumentRole, PdfInput


class FixtureModel(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="ignore")


class Citation(FixtureModel):
    page: int
    quote: str


class PageLimit(FixtureModel):
    inclusion_source: Citation


class Requirement(FixtureModel):
    id: str
    source: Citation
    non_applicability_source: Citation | None = None
    page_limit: PageLimit | None = None


class Result(FixtureModel):
    requirement_id: str
    evidence: tuple[Citation, ...]
    applicability_evidence: tuple[Citation, ...] = ()
    non_evidence_heading: Citation | None = None


class Report(FixtureModel):
    document_id: str
    reviewed_pages: tuple[int, ...]
    results: tuple[Result, ...]


class Truth(FixtureModel):
    requirements: tuple[Requirement, ...]
    reports: tuple[Report, ...]


def test_authored_truth_locations_exist_in_actual_pdf_extraction() -> None:
    # Given
    samples = Path(__file__).resolve().parents[1] / "samples"
    truth = Truth.model_validate_json((samples / "truth.json").read_text(encoding="utf-8"))
    guide_input = PdfInput(
        "guide.pdf", (samples / "pdf/guide.pdf").read_bytes(), DocumentRole.GUIDE
    )
    # When
    guide = extract_pdf(guide_input)
    reports = {
        report.document_id: extract_pdf(
            PdfInput(
                f"{report.document_id}.pdf",
                (samples / f"pdf/{report.document_id}.pdf").read_bytes(),
                DocumentRole.REPORT,
            )
        )
        for report in truth.reports
    }
    # Then
    assert guide.complete
    for requirement in truth.requirements:
        citations = (requirement.source,)
        if requirement.non_applicability_source is not None:
            citations += (requirement.non_applicability_source,)
        if requirement.page_limit is not None:
            citations += (requirement.page_limit.inclusion_source,)
        for citation in citations:
            assert citation.quote in guide.pages[citation.page - 1].text
    requirement_ids = {requirement.id for requirement in truth.requirements}
    for report in truth.reports:
        document = reports[report.document_id]
        assert document.complete
        assert report.reviewed_pages == tuple(page.number for page in document.pages)
        assert {result.requirement_id for result in report.results} == requirement_ids
        for result in report.results:
            citations = result.evidence + result.applicability_evidence
            if result.non_evidence_heading is not None:
                citations += (result.non_evidence_heading,)
            for citation in citations:
                assert citation.page in report.reviewed_pages
                assert citation.quote in document.pages[citation.page - 1].text
