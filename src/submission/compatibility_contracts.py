from enum import StrEnum
from pathlib import Path
from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from submission.document_contracts import DocumentArtifact, DocumentDiagnostic, Sha256
from submission.models import FrozenModel

type ShortText = Annotated[str, Field(min_length=1, max_length=200)]


class CompatibilityErrorCode(StrEnum):
    DUPLICATE = "duplicate_case"
    SPLIT = "family_split_leakage"
    LIMIT = "input_limit"
    IO = "input_io"
    HASH = "hash_mismatch"
    REFERENCE = "reference_not_independent"
    REVIEW = "stale_layout_review"
    USAGE = "usage: MANIFEST OUTPUT [RUNTIME]"


class CompatibilityError(Exception):
    code: str

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class MaterialFile(FrozenModel):
    path: Path
    sha256: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]


class ExpectedAnchor(FrozenModel):
    quote: Annotated[str, Field(min_length=1, max_length=2000)]
    locator_path: Annotated[str, Field(min_length=1, max_length=2000)] | None = None


class LayoutReview(FrozenModel):
    reviewer: ShortText
    source_sha256: Sha256
    reference_sha256: Sha256
    preview_sha256: Sha256
    outcome: Literal["matches", "differences"]
    notes: Annotated[str, Field(max_length=2000)]


class CompatibilityCase(FrozenModel):
    case_id: Annotated[str, Field(pattern=r"^[a-zA-Z0-9_-]{1,60}$")]
    family_id: ShortText
    split: Literal["development", "evaluation"]
    provenance: Literal["authored", "synthetic"]
    format: Literal["pdf", "docx", "hwp", "hwpx"]
    authoring_app: ShortText
    authoring_version: ShortText
    fonts: Annotated[tuple[ShortText, ...], Field(max_length=100)]
    source: MaterialFile | None
    reference: MaterialFile | None
    reference_origin: Literal["authoring_app_export", "service_preview"] = "authoring_app_export"
    anchors: Annotated[tuple[ExpectedAnchor, ...], Field(max_length=100)] = ()
    layout_review: LayoutReview | None = None


class CompatibilityManifest(FrozenModel):
    schema_version: Literal[1] = 1
    cases: Annotated[tuple[CompatibilityCase, ...], Field(min_length=1, max_length=100)]

    @model_validator(mode="after")
    def unique_cases_and_family_split(self) -> Self:
        if len({case.case_id for case in self.cases}) != len(self.cases):
            raise CompatibilityError(CompatibilityErrorCode.DUPLICATE)
        splits: dict[str, str] = {}
        for case in self.cases:
            if case.family_id in splits and splits[case.family_id] != case.split:
                raise CompatibilityError(CompatibilityErrorCode.SPLIT)
            splits[case.family_id] = case.split
        return self


class AnchorReport(FrozenModel):
    quote: str
    locator_path: str | None
    source_matches: int
    reference_pages: tuple[int, ...]
    preview_pages: tuple[int, ...]
    mapping_reasons: tuple[str, ...]


class CaseReport(FrozenModel):
    case_id: str
    family_id: str
    split: str
    provenance: str
    format: str
    authoring_app: str
    authoring_version: str
    fonts: tuple[str, ...]
    status: Literal["material_missing", "review_pending", "review_recorded", "invalid"]
    error: str | None = None
    source_sha256: str | None = None
    reference_sha256: str | None = None
    preview_sha256: str | None = None
    reference_pages: int | None = None
    preview_pages: int | None = None
    extraction_status: str | None = None
    rendering_status: str | None = None
    omitted_paths: tuple[str, ...] = ()
    diagnostics: tuple[DocumentDiagnostic, ...] = ()
    warnings: tuple[str, ...] = ()
    artifacts: tuple[DocumentArtifact, ...] = ()
    anchors: tuple[AnchorReport, ...] = ()
    expected_anchors: tuple[ExpectedAnchor, ...] = ()
    layout_review: LayoutReview | None = None
    actual_acceptance: Literal[False] = False


class CompatibilityReport(FrozenModel):
    schema_version: Literal[1] = 1
    cases: tuple[CaseReport, ...]
    support_certified: Literal[False] = False
