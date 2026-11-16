from typing import Final, assert_never

from pydantic import TypeAdapter, ValidationError

from submission.document_contracts import (
    CommonDocument,
    DocumentArtifact,
    ExtractionCoverage,
    StructuralCoverage,
)
from submission.evidence_contracts import (
    ArtifactInput,
    EvidenceError,
    EvidenceErrorCode,
    EvidenceMapRequest,
    PdfArtifactInput,
    SyntheticArtifactInput,
)
from submission.models import FrozenModel

MODEL_ADAPTER: Final = TypeAdapter(FrozenModel)


def reject_extra_fields(value: FrozenModel) -> None:
    try:
        value = MODEL_ADAPTER.validate_python(value, strict=True)
    except ValidationError:
        raise EvidenceError(EvidenceErrorCode.INVALID_INPUT) from None
    if value.model_fields_set - type(value).model_fields.keys() or value.model_extra:
        raise EvidenceError(EvidenceErrorCode.INVALID_INPUT)


def validate_artifact_models(artifact: DocumentArtifact) -> None:
    reject_extra_fields(artifact)
    for tool in artifact.conversion_chain:
        reject_extra_fields(tool)
    if artifact.renderer is not None:
        reject_extra_fields(artifact.renderer)


def validate_target_models(target: ArtifactInput) -> None:
    reject_extra_fields(target)
    reject_extra_fields(target.binding)
    reject_extra_fields(target.binding.source)
    validate_artifact_models(target.binding.artifact)
    match target:
        case PdfArtifactInput():
            pass
        case SyntheticArtifactInput():
            for page in target.pages:
                reject_extra_fields(page)
        case _:
            assert_never(target)


def validate_request_models(request: EvidenceMapRequest) -> None:
    reject_extra_fields(request)
    reject_extra_fields(request.citation)
    reject_extra_fields(request.citation.char_range)
    for claim in request.expected_target_ranges or ():
        reject_extra_fields(claim)
        reject_extra_fields(claim.char_range)


def validate_document_models(document: CommonDocument) -> None:
    reject_extra_fields(document)
    reject_extra_fields(document.source)
    for block in document.blocks:
        reject_extra_fields(block)
        reject_extra_fields(block.source_locator)
        reject_extra_fields(block.raw_char_range)
        for span in block.normalization_map:
            reject_extra_fields(span)
            reject_extra_fields(span.raw_range)
            reject_extra_fields(span.normalized_range)
        for span in block.source_spans:
            reject_extra_fields(span)
            reject_extra_fields(span.source_locator)
            reject_extra_fields(span.source_char_range)
            reject_extra_fields(span.block_char_range)
    for artifact in document.artifacts:
        validate_artifact_models(artifact)
    validate_document_metadata(document)


def validate_document_metadata(document: CommonDocument) -> None:
    reject_extra_fields(document.coverage)
    reject_extra_fields(document.page_count)
    match document.coverage:
        case ExtractionCoverage():
            pass
        case StructuralCoverage():
            for locator in document.coverage.omitted_locators:
                reject_extra_fields(locator)
        case _:
            assert_never(document.coverage)
    for diagnostic in (*document.warnings, *document.typed_errors):
        reject_extra_fields(diagnostic)
        if diagnostic.source_locator is not None:
            reject_extra_fields(diagnostic.source_locator)
    for mapping in document.mappings:
        reject_extra_fields(mapping)
        reject_extra_fields(mapping.source_char_range)
        for item in mapping.target_text_ranges:
            reject_extra_fields(item)
            reject_extra_fields(item.char_range)
    for reference in document.references:
        reject_extra_fields(reference)
        reject_extra_fields(reference.source_locator)
        if reference.target_locator is not None:
            reject_extra_fields(reference.target_locator)
