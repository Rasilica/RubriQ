from typing import Literal

from submission.document_contracts import (
    DocumentBlock,
    DocumentDiagnostic,
    DocumentSource,
    PageCountAssessment,
    ProcessingStatus,
    SourceReference,
    StructuralCoverage,
)
from submission.evidence_contracts import BoundEvidenceMapping, EvidenceModel
from submission.requirement_contracts import VerifiedCitation


class StructuralViewerDocument(EvidenceModel):
    representation: Literal["source_structure"] = "source_structure"
    source: DocumentSource
    blocks: tuple[DocumentBlock, ...]
    artifact: None = None
    page_count: None = None
    pages: tuple[()] = ()
    original_url: None = None
    mappings: tuple[()] = ()
    coverage: StructuralCoverage
    warnings: tuple[DocumentDiagnostic, ...]
    typed_errors: tuple[DocumentDiagnostic, ...]
    extraction_status: ProcessingStatus
    rendering_status: ProcessingStatus
    page_count_assessment: PageCountAssessment
    references: tuple[SourceReference, ...]
    provenance: Literal["synthetic_development_fixture"] = "synthetic_development_fixture"


class StructureScenario(EvidenceModel):
    case_name: Literal["ambiguous", "unmapped", "mismatch"]
    label: str
    citation: VerifiedCitation
    result: BoundEvidenceMapping
    provenance: Literal["synthetic_mapping_demonstration"] = "synthetic_mapping_demonstration"
    conversion_performed: Literal[False] = False
