from enum import StrEnum
from typing import Annotated, ClassVar, Final, Literal

from pydantic import ConfigDict, Field

from submission.document_contracts import (
    ArtifactTextRange,
    CommonDocument,
    DocumentArtifact,
    DocumentSource,
    EvidenceMapping,
    PageCountAssessment,
    Sha256,
    SourceId,
    SourceLocator,
)
from submission.models import FrozenModel, PdfInput
from submission.requirement_contracts import CitationInput


class EvidenceErrorCode(StrEnum):
    INVALID_INPUT = "invalid_input"
    INPUT_LIMIT = "input_limit"
    INVALID_PDF = "invalid_pdf"
    SOURCE_MISMATCH = "source_mismatch"
    ARTIFACT_MISMATCH = "artifact_mismatch"
    INVALID_CITATION = "invalid_citation"
    INVALID_RANGE = "invalid_range"
    INVALID_SELECTION = "invalid_selection"
    CANDIDATE_LIMIT = "candidate_limit"


class EvidenceError(ValueError):
    code: EvidenceErrorCode

    def __init__(self, code: EvidenceErrorCode) -> None:
        super().__init__(code.value)
        self.code = code


class EvidenceModel(FrozenModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="forbid", strict=True)


class EvidenceLimits(EvidenceModel):
    max_bytes: Annotated[int, Field(gt=0)] = 10 * 1024 * 1024
    max_pages: Annotated[int, Field(gt=0)] = 50
    max_characters: Annotated[int, Field(gt=0)] = 200_000
    max_candidates: Annotated[int, Field(gt=0)] = 1000
    max_claims: Annotated[int, Field(gt=0)] = 100
    max_blocks: Annotated[int, Field(gt=0)] = 2000


DEFAULT_EVIDENCE_LIMITS: Final = EvidenceLimits()


class ArtifactBinding(EvidenceModel):
    source: DocumentSource
    artifact: DocumentArtifact


class ArtifactPage(EvidenceModel):
    number: Annotated[int, Field(gt=0)]
    text: str
    status: Literal["readable", "text_unavailable", "extraction_error"] = "readable"


class PdfArtifactInput(EvidenceModel):
    binding: ArtifactBinding
    pdf: PdfInput
    origin: Literal["real_pdf"] = "real_pdf"


class SyntheticArtifactInput(EvidenceModel):
    binding: ArtifactBinding
    pages: tuple[ArtifactPage, ...]
    origin: Literal["synthetic"] = "synthetic"


type ArtifactInput = PdfArtifactInput | SyntheticArtifactInput


class ArtifactSnapshot(EvidenceModel):
    binding_sha256: Sha256
    target_sha256: Sha256
    pages: tuple[ArtifactPage, ...]
    physical_page_count: Annotated[int, Field(gt=0)]
    physical_verified: bool
    diagnostics: tuple[Literal["parser_warning", "incomplete_target_coverage"], ...]
    origin: Literal["real_pdf", "synthetic"]


class EvidenceMapContext(EvidenceModel):
    document: CommonDocument
    target: ArtifactInput


class EvidenceMapRequest(EvidenceModel):
    citation: CitationInput
    expected_target_ranges: tuple[ArtifactTextRange, ...] | None = None


class BoundEvidenceMapping(EvidenceModel):
    binding_sha256: Sha256
    source_id: SourceId
    source_sha256: Sha256
    document_version_id: str
    target_artifact_sha256: Sha256
    snapshot_origin: Literal["real_pdf", "synthetic"]
    source_locator: SourceLocator
    mapping: EvidenceMapping
    candidates: tuple[tuple[ArtifactTextRange, ...], ...]
    reason_code: Literal[
        "exact_identity",
        "exact_anchor",
        "layout_whitespace_anchor",
        "repeated_anchor",
        "anchor_absent",
        "range_mismatch",
        "incomplete_target_coverage",
    ]
    conversion_verified: Literal[False] = False
    original_layout_verified: Literal[False] = False


class PageSelection(EvidenceModel):
    binding_sha256: Sha256
    basis: Literal["original_pdf", "declared_submission_pdf", "verified_original_layout", "unknown"]
    included_pages: tuple[int, ...] | None
    excluded_pages: tuple[int, ...] | None
    scope_confirmed: bool
    declared_submission_sha256: Sha256 | None = None


class BoundPageCountAssessment(EvidenceModel):
    binding_sha256: Sha256
    assessment: PageCountAssessment
