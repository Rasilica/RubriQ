import json
from hashlib import sha256
from typing import assert_never

from pydantic import TypeAdapter, ValidationError

from submission.evidence_boundary import reject_extra_fields, validate_target_models
from submission.evidence_contracts import (
    DEFAULT_EVIDENCE_LIMITS,
    ArtifactBinding,
    ArtifactInput,
    ArtifactPage,
    ArtifactSnapshot,
    EvidenceError,
    EvidenceErrorCode,
    EvidenceLimits,
    PdfArtifactInput,
    SyntheticArtifactInput,
)
from submission.extraction import extract_pdf
from submission.models import DocumentRole, FrozenModel, PdfInput, PdfLimits, UploadError


def strict_model[Model: FrozenModel](value: Model) -> Model:
    reject_extra_fields(value)
    try:
        return type(value).model_validate(
            value.model_dump(exclude_computed_fields=True, warnings=False), strict=True
        )
    except ValidationError:
        raise EvidenceError(EvidenceErrorCode.INVALID_INPUT) from None


def make_synthetic_artifact(
    binding: ArtifactBinding, pages: tuple[ArtifactPage, ...]
) -> SyntheticArtifactInput:
    target = SyntheticArtifactInput(binding=binding, pages=pages)
    parsed = strict_model(target)
    validate_target_models(target)
    return parsed


def validate_binding(binding: ArtifactBinding) -> None:
    identifiers = (
        binding.source.source_id,
        binding.source.document_version_id,
        binding.source.filename,
        binding.artifact.artifact_id,
    )
    tools = binding.artifact.conversion_chain + (
        (binding.artifact.renderer,) if binding.artifact.renderer else ()
    )
    if any(not value.strip() for value in identifiers) or any(
        not tool.name.strip() or not tool.version.strip() for tool in tools
    ):
        raise EvidenceError(EvidenceErrorCode.INVALID_INPUT)
    if binding.artifact.parent_source_id != binding.source.source_id:
        raise EvidenceError(EvidenceErrorCode.SOURCE_MISMATCH)
    match binding.artifact.kind:
        case "original_pdf":
            if (
                binding.source.detected_format != "pdf"
                or binding.artifact.artifact_sha256 != binding.source.content_sha256
            ):
                raise EvidenceError(EvidenceErrorCode.ARTIFACT_MISMATCH)
        case "preview_pdf":
            pass
        case _:
            assert_never(binding.artifact.kind)


def validate_pages(pages: tuple[ArtifactPage, ...], limits: EvidenceLimits) -> None:
    if (
        not pages
        or len(pages) > limits.max_pages
        or sum(len(page.text) for page in pages) > limits.max_characters
    ):
        raise EvidenceError(EvidenceErrorCode.INPUT_LIMIT)
    for expected, page in enumerate(pages, 1):
        if page.number != expected:
            raise EvidenceError(EvidenceErrorCode.INVALID_INPUT)
        match page.status:
            case "readable":
                if not page.text:
                    raise EvidenceError(EvidenceErrorCode.INVALID_INPUT)
            case "text_unavailable" | "extraction_error":
                if page.text:
                    raise EvidenceError(EvidenceErrorCode.INVALID_INPUT)
            case _:
                assert_never(page.status)


def binding_digest(target: ArtifactInput) -> str:
    value = {"binding": target.binding.model_dump(mode="json"), "origin": target.origin}
    match target:
        case PdfArtifactInput():
            pass
        case SyntheticArtifactInput():
            value = {**value, "pages": [page.model_dump(mode="json") for page in target.pages]}
        case _:
            assert_never(target)
    try:
        encoded = json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    except UnicodeEncodeError:
        raise EvidenceError(EvidenceErrorCode.INVALID_INPUT) from None
    return sha256(encoded).hexdigest()


def inspect_pdf(target: PdfArtifactInput, limits: EvidenceLimits) -> ArtifactSnapshot:
    try:
        target = PdfArtifactInput.model_validate(
            {
                "binding": target.binding.model_dump(warnings=False),
                "pdf": target.pdf,
                "origin": target.origin,
            },
            strict=True,
        )
    except ValidationError:
        raise EvidenceError(EvidenceErrorCode.INVALID_INPUT) from None
    binding = strict_model(target.binding)
    validate_binding(binding)
    try:
        content = TypeAdapter(bytes).validate_python(target.pdf.content, strict=True)
        filename = TypeAdapter(str).validate_python(target.pdf.filename, strict=True)
        role = TypeAdapter(DocumentRole).validate_python(target.pdf.role, strict=True)
    except ValidationError:
        raise EvidenceError(EvidenceErrorCode.INVALID_INPUT) from None
    if role != binding.source.role:
        raise EvidenceError(EvidenceErrorCode.SOURCE_MISMATCH)
    if len(content) > limits.max_bytes:
        raise EvidenceError(EvidenceErrorCode.INPUT_LIMIT)
    if sha256(content).hexdigest() != binding.artifact.artifact_sha256:
        raise EvidenceError(EvidenceErrorCode.ARTIFACT_MISMATCH)
    match binding.artifact.kind:
        case "original_pdf":
            if binding.source.byte_size != len(content):
                raise EvidenceError(EvidenceErrorCode.SOURCE_MISMATCH)
        case "preview_pdf":
            pass
        case _:
            assert_never(binding.artifact.kind)
    try:
        extracted = extract_pdf(
            PdfInput(filename, content, role),
            PdfLimits(max_bytes=limits.max_bytes, max_pages=limits.max_pages),
        )
    except UploadError as error:
        code = (
            EvidenceErrorCode.INPUT_LIMIT
            if error.code in {"too_many_pages", "file_too_large"}
            else EvidenceErrorCode.INVALID_PDF
        )
        raise EvidenceError(code) from None
    pages = tuple(
        ArtifactPage(
            number=page.number,
            text=page.text,
            status="readable" if page.error is None else page.error,
        )
        for page in extracted.pages
    )
    validate_pages(pages, limits)
    return ArtifactSnapshot(
        binding_sha256=binding_digest(target),
        target_sha256=binding.artifact.artifact_sha256,
        pages=pages,
        physical_page_count=len(pages),
        physical_verified=not extracted.parser_warning,
        diagnostics=(("parser_warning",) if extracted.parser_warning else ())
        + (
            ("incomplete_target_coverage",)
            if any(page.status != "readable" for page in pages)
            else ()
        ),
        origin="real_pdf",
    )


def inspect_artifact(
    target: ArtifactInput, *, limits: EvidenceLimits = DEFAULT_EVIDENCE_LIMITS
) -> ArtifactSnapshot:
    limits = strict_model(limits)
    try:
        _ = TypeAdapter[ArtifactInput](ArtifactInput).validate_python(target, strict=True)
    except ValidationError:
        raise EvidenceError(EvidenceErrorCode.INVALID_INPUT) from None
    match target:
        case PdfArtifactInput():
            _ = strict_model(target.binding)
            validate_target_models(target)
            return inspect_pdf(target, limits)
        case SyntheticArtifactInput():
            parsed = strict_model(target)
            validate_target_models(target)
            target = parsed
            validate_binding(target.binding)
            validate_pages(target.pages, limits)
            return ArtifactSnapshot(
                binding_sha256=binding_digest(target),
                target_sha256=target.binding.artifact.artifact_sha256,
                pages=target.pages,
                physical_page_count=len(target.pages),
                physical_verified=False,
                diagnostics=("incomplete_target_coverage",)
                if any(page.status != "readable" for page in target.pages)
                else (),
                origin="synthetic",
            )
        case _:
            assert_never(target)
