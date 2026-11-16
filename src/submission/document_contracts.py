from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal, NewType, Self

from pydantic import Field, computed_field, model_validator

from submission.models import DocumentRole, FrozenModel

SourceId = NewType("SourceId", str)
ArtifactId = NewType("ArtifactId", str)
BlockId = NewType("BlockId", str)
type Sha256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
type PageNumber = Annotated[int, Field(gt=0)]


class ContractErrorCode(StrEnum):
    INVALID_CHARACTER_RANGE = "invalid_character_range"
    SOURCE_IDENTITY_MISMATCH = "source_identity_mismatch"
    MISSING_PAGES = "missing_pages"
    PAGE_SEQUENCE_MISMATCH = "page_sequence_mismatch"
    INVALID_BLOCK_IDENTITY = "invalid_block_identity"
    BLOCK_TEXT_MISMATCH = "block_text_mismatch"
    MISSING_PDF_PAGE = "missing_pdf_page"
    INVALID_SOURCE_REFERENCE = "invalid_source_reference"


class ContractError(ValueError):
    code: ContractErrorCode

    def __init__(self, code: ContractErrorCode) -> None:
        super().__init__(code)
        self.code = code


class ProcessingStatus(StrEnum):
    NOT_STARTED = "not_started"
    COMPLETE = "complete"
    PARTIAL = "partial"
    FAILED = "failed"
    UNSUPPORTED = "unsupported"


class CharacterRange(FrozenModel):
    """Half-open Python Unicode offsets; the containing field defines their text basis."""

    start: Annotated[int, Field(ge=0)]
    end: Annotated[int, Field(ge=0)]

    @model_validator(mode="after")
    def ordered_boundaries(self) -> Self:
        if self.end < self.start:
            raise ContractError(ContractErrorCode.INVALID_CHARACTER_RANGE)
        return self


class SourceLocator(FrozenModel):
    source_sha256: Sha256
    path: Annotated[str, Field(min_length=1)]
    original_page_number: PageNumber | None


class NormalizationSpan(FrozenModel):
    raw_range: CharacterRange
    normalized_range: CharacterRange


class SourceTextSpan(FrozenModel):
    source_locator: SourceLocator
    source_char_range: CharacterRange
    block_char_range: CharacterRange
    source_coordinate_basis: Literal[
        "source_node_unicode",
        "source_node_tail_unicode",
        "synthetic_control_unicode",
        "hwp_paragraph_unicode",
    ] = "source_node_unicode"


class DocumentSource(FrozenModel):
    source_id: SourceId
    role: DocumentRole
    filename: str
    content_sha256: Sha256
    byte_size: Annotated[int, Field(gt=0)]
    declared_extension: str
    detected_format: Literal["pdf", "docx", "hwpx", "hwp"]
    format_version: str | None = None
    document_version_id: str


class DocumentBlock(FrozenModel):
    block_id: BlockId
    kind: Literal["extraction_block", "paragraph", "table_cell", "footnote", "header", "footer"]
    raw_text: str
    normalized_text: str
    normalization_version: str
    normalization_map: tuple[NormalizationSpan, ...]
    source_locator: SourceLocator
    raw_char_range: CharacterRange
    raw_coordinate_basis: Literal[
        "extracted_page_unicode",
        "source_node_unicode",
        "docx_paragraph_unicode",
        "hwpx_paragraph_unicode",
        "hwp_paragraph_unicode",
    ]
    source_fragment_index: Annotated[int, Field(gt=0)] | None = None
    source_spans: tuple[SourceTextSpan, ...] = ()
    parent_block_id: BlockId | None = None
    reading_order: Annotated[int, Field(ge=0)]


class ToolDescriptor(FrozenModel):
    name: str
    version: str
    options: tuple[str, ...] = ()


class DocumentArtifact(FrozenModel):
    artifact_id: ArtifactId
    artifact_sha256: Sha256
    kind: Literal["original_pdf", "preview_pdf"]
    parent_source_id: SourceId
    conversion_chain: tuple[ToolDescriptor, ...] = ()
    storage_location: str | None = None
    renderer: ToolDescriptor | None = None
    font_manifest_hash: Sha256 | None = None
    operating_system: str | None = None
    created_at: datetime | None = None


class DocumentDiagnostic(FrozenModel):
    code: Literal[
        "text_unavailable",
        "extraction_error",
        "parser_warning",
        "unsupported_element",
        "unsupported_part",
        "invalid_reference",
        "invalid_structure",
        "empty_content",
    ]
    page_number: PageNumber | None
    source_locator: SourceLocator | None = None


class ExtractionCoverage(FrozenModel):
    scope: Literal["pypdf_text_layer"]
    total_pages: Annotated[int, Field(gt=0)]
    processed_pages: tuple[PageNumber, ...]
    unreadable_pages: tuple[PageNumber, ...]
    guarantees_all_content: Literal[False] = False


class StructuralCoverage(FrozenModel):
    scope: Literal["docx_ooxml_structure", "hwpx_xml_structure", "hwp5_structure"]
    processed_parts: tuple[str, ...]
    omitted_locators: tuple[SourceLocator, ...]
    guarantees_all_content: Literal[False] = False


class SourceReference(FrozenModel):
    kind: Literal["footnote", "header", "footer"]
    source_locator: SourceLocator
    source_block_id: BlockId | None
    source_char_offset: Annotated[int, Field(ge=0)] | None
    target_locator: SourceLocator | None
    status: Literal["resolved", "unresolved"]


class ArtifactTextRange(FrozenModel):
    page_number: PageNumber
    char_range: CharacterRange


class EvidenceMapping(FrozenModel):
    source_block_id: BlockId
    source_char_range: CharacterRange
    target_artifact_id: ArtifactId
    target_page_numbers: tuple[PageNumber, ...]
    target_text_ranges: tuple[ArtifactTextRange, ...]
    original_page_numbers: tuple[PageNumber, ...] | None
    mapping_status: Literal[
        "identity", "verified_anchor", "verified_original", "ambiguous", "unmapped", "mismatch"
    ]
    verification_method: str | None = None
    verified_by: str | None = None
    verified_at: datetime | None = None


class PageCountAssessment(FrozenModel):
    basis: Literal["original_pdf", "verified_original_layout", "declared_submission_pdf", "unknown"]
    artifact_sha256: Sha256 | None
    artifact_page_count: Annotated[int, Field(gt=0)] | None
    included_pages: tuple[PageNumber, ...] | None = None
    excluded_pages: tuple[PageNumber, ...] | None = None
    count: Annotated[int, Field(ge=0)] | None = None
    status: Literal["verified", "deferred", "not_applicable"]
    reason_code: str


class CommonDocument(FrozenModel):
    contract_version: Literal["1"] = "1"
    source: DocumentSource
    blocks: tuple[DocumentBlock, ...]
    artifacts: tuple[DocumentArtifact, ...]
    coverage: Annotated[ExtractionCoverage | StructuralCoverage, Field(discriminator="scope")]
    extraction_status: ProcessingStatus
    rendering_status: ProcessingStatus
    warnings: tuple[DocumentDiagnostic, ...]
    typed_errors: tuple[DocumentDiagnostic, ...]
    mappings: tuple[EvidenceMapping, ...]
    page_count: PageCountAssessment
    references: tuple[SourceReference, ...] = ()
    ai_called: Literal[False] = False
    stored: Literal[False] = False

    @computed_field
    @property
    def content_review_available(self) -> bool:
        return any(block.raw_text for block in self.blocks)

    @computed_field
    @property
    def display_artifact_available(self) -> bool:
        return bool(self.artifacts)

    @computed_field
    @property
    def page_count_verification_available(self) -> bool:
        return self.page_count.status == "verified" and self.page_count.count is not None
