from dataclasses import dataclass
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import Field

from submission.document_contracts import (
    DocumentArtifact,
    DocumentDiagnostic,
    DocumentSource,
    EvidenceMapping,
    ExtractionCoverage,
    ProcessingStatus,
    Sha256,
    SourceLocator,
    StructuralCoverage,
)
from submission.evidence_contracts import EvidenceModel
from submission.page_rule_contracts import SubmissionCheckResult
from submission.result_structure_contracts import StructuralViewerDocument, StructureScenario


class ResultCase(StrEnum):
    NORMAL = "normal"
    MISSING = "missing"
    OVER_LIMIT = "over_limit"
    UNCONFIRMED_SCOPE = "unconfirmed_scope"
    DOCX_STRUCTURE = "docx_structure"
    HWPX_STRUCTURE = "hwpx_structure"


class ResultErrorCode(StrEnum):
    NOT_FOUND = "result_not_found"
    UNAVAILABLE = "result_demo_unavailable"


class ResultError(Exception):
    code: ResultErrorCode

    def __init__(self, code: ResultErrorCode) -> None:
        super().__init__(code)
        self.code = code


class CaseSummary(EvidenceModel):
    case_id: ResultCase
    label: str
    description: str


class CaseCatalog(EvidenceModel):
    cases: tuple[CaseSummary, ...]


class ViewerPage(EvidenceModel):
    page_number: Annotated[int, Field(gt=0)]
    image_url: str
    width: Annotated[int, Field(gt=0)]
    height: Annotated[int, Field(gt=0)]


class ViewerBlock(EvidenceModel):
    block_id: str
    raw_text: str
    source_locator: SourceLocator


class ViewerDocument(EvidenceModel):
    source: DocumentSource
    artifact: DocumentArtifact
    representation: Literal["original_pdf"] = "original_pdf"
    page_count: Annotated[int, Field(gt=0)]
    pages: tuple[ViewerPage, ...]
    blocks: tuple[ViewerBlock, ...]
    original_url: str
    mappings: tuple[EvidenceMapping, ...]
    warnings: tuple[DocumentDiagnostic, ...]
    typed_errors: tuple[DocumentDiagnostic, ...]
    coverage: ExtractionCoverage | StructuralCoverage
    extraction_status: ProcessingStatus


class ViewerDocuments(EvidenceModel):
    guide: ViewerDocument
    report: Annotated[
        ViewerDocument | StructuralViewerDocument, Field(discriminator="representation")
    ]


class ResultDetail(CaseSummary):
    check: SubmissionCheckResult
    documents: ViewerDocuments
    structure_scenarios: tuple[StructureScenario, ...] = ()
    conversion_performed: Literal[False] = False


class ResultResponse[Data: EvidenceModel](EvidenceModel):
    success: Literal[True] = True
    data: Data


class RasterPage(EvidenceModel):
    page_number: Annotated[int, Field(gt=0, le=50)]
    image_path: str
    image_sha256: Sha256
    width: Annotated[int, Field(gt=0, le=10000)]
    height: Annotated[int, Field(gt=0, le=10000)]


class RasterDocument(EvidenceModel):
    document_id: Literal["guide", "normal", "missing", "over_limit"]
    pdf_path: str
    pdf_sha256: Sha256
    pages: Annotated[tuple[RasterPage, ...], Field(min_length=1, max_length=50)]


class RasterRenderer(EvidenceModel):
    name: Literal["pdftoppm"]
    version: Annotated[str, Field(min_length=1, max_length=200)]
    dpi: Literal[110]


class RasterManifest(EvidenceModel):
    schema_version: Literal["1"]
    renderer: RasterRenderer
    documents: Annotated[tuple[RasterDocument, ...], Field(min_length=4, max_length=4)]


@dataclass(frozen=True, slots=True)
class LoadedRaster:
    descriptor: RasterDocument
    pdf_bytes: bytes
    images: tuple[bytes, ...]
