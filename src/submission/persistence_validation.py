from hashlib import sha256
from typing import Final, assert_never

from pydantic import TypeAdapter, ValidationError

from submission.document_contracts import ArtifactId
from submission.evidence_artifacts import binding_digest
from submission.evidence_contracts import ArtifactBinding, PdfArtifactInput, SyntheticArtifactInput
from submission.page_rule_contracts import SubmissionCheckLimits
from submission.persistence_codec import admitted, canonical, encode
from submission.persistence_contracts import (
    ArtifactPayload,
    PersistenceError,
    PersistenceErrorCode,
    PersistenceLimits,
    PersistenceRequest,
    StoredRun,
)
from submission.report_check_validation import criteria_fingerprint

MAX_OPTIONS: Final = 100
type LimitTree = int | dict[str, LimitTree]
LIMIT_TREE: Final = TypeAdapter[LimitTree](LimitTree)


def bounded_settings(value: LimitTree, ceiling: LimitTree) -> bool:
    match value:
        case dict():
            ceilings = TypeAdapter(dict[str, LimitTree]).validate_python(ceiling, strict=True)
            return all(bounded_settings(child, ceilings[key]) for key, child in value.items())
        case int():
            return 0 < value <= TypeAdapter(int).validate_python(ceiling, strict=True)
        case _:
            assert_never(value)


def admit_request(request: PersistenceRequest, limits: PersistenceLimits) -> PersistenceRequest:
    try:
        value = admitted(TypeAdapter(PersistenceRequest).validate_python(request, strict=True))
    except (ValidationError, TypeError, ValueError, RecursionError):
        raise PersistenceError(PersistenceErrorCode.INVALID_INPUT) from None
    payloads = (*value.originals, *value.artifacts)
    if (
        len(payloads) > limits.max_payloads
        or sum(len(item.content) for item in payloads) > limits.max_total_bytes
        or len(value.response_json.encode()) > limits.max_manifest_bytes
    ):
        raise PersistenceError(PersistenceErrorCode.INPUT_LIMIT)
    blobs: dict[str, bytes] = {}
    if len(canonical(encode(value, blobs)).encode()) > limits.max_manifest_bytes:
        raise PersistenceError(PersistenceErrorCode.INPUT_LIMIT)
    if sum(map(len, blobs.values())) > limits.max_total_bytes:
        raise PersistenceError(PersistenceErrorCode.INPUT_LIMIT)
    if any(len(tool.options) > MAX_OPTIONS for tool in value.settings.toolchain):
        raise PersistenceError(PersistenceErrorCode.INPUT_LIMIT)
    if not bounded_settings(
        LIMIT_TREE.validate_python(encode(value.settings.check_limits, {})),
        LIMIT_TREE.validate_python(encode(SubmissionCheckLimits(), {})),
    ):
        raise PersistenceError(PersistenceErrorCode.INPUT_LIMIT)
    validate_bindings(value)
    return value


def validate_bindings(request: PersistenceRequest) -> None:
    ctx = request.context.report_check
    documents = (ctx.guide, ctx.report)
    originals = {item.source.source_id: item for item in request.originals}
    expected_sources = {doc.source.source_id: doc.source for doc in documents}
    if len(originals) != len(request.originals) or set(originals) != set(expected_sources):
        raise PersistenceError(PersistenceErrorCode.INVALID_INPUT)
    for source_id, original in originals.items():
        if (
            original.source != expected_sources[source_id]
            or sha256(original.content).hexdigest() != original.source.content_sha256
            or len(original.content) != original.source.byte_size
        ):
            raise PersistenceError(PersistenceErrorCode.INVALID_INPUT)
    artifacts = {item.binding.artifact.artifact_id: item for item in request.artifacts}
    expected_bindings = {
        artifact.artifact_id: ArtifactBinding(source=doc.source, artifact=artifact)
        for doc in documents
        for artifact in doc.artifacts
    }
    for check in request.context.page_checks:
        if isinstance(check.target, PdfArtifactInput):
            binding = check.target.binding
            existing = expected_bindings.get(binding.artifact.artifact_id)
            if existing is not None and existing != binding:
                raise PersistenceError(PersistenceErrorCode.INVALID_INPUT)
            expected_bindings[binding.artifact.artifact_id] = binding
    if len(artifacts) != len(request.artifacts) or set(artifacts) != set(expected_bindings):
        raise PersistenceError(PersistenceErrorCode.INVALID_INPUT)
    for artifact_id, artifact in artifacts.items():
        if (
            artifact.binding != expected_bindings[artifact_id]
            or artifact.binding.source != expected_sources.get(artifact.binding.source.source_id)
            or artifact.binding.artifact.parent_source_id != artifact.binding.source.source_id
            or sha256(artifact.content).hexdigest() != artifact.binding.artifact.artifact_sha256
        ):
            raise PersistenceError(PersistenceErrorCode.INVALID_INPUT)
    validate_targets(request, artifacts)


def validate_targets(
    request: PersistenceRequest, artifacts: dict[ArtifactId, ArtifactPayload]
) -> None:
    for check in request.context.page_checks:
        match check.target:
            case None:
                continue
            case PdfArtifactInput() as target:
                payload = artifacts.get(target.binding.artifact.artifact_id)
                if (
                    payload is None
                    or target.binding != payload.binding
                    or target.pdf.content != payload.content
                ):
                    raise PersistenceError(PersistenceErrorCode.INVALID_INPUT)
                if target.pdf.role != target.binding.source.role:
                    raise PersistenceError(PersistenceErrorCode.INVALID_INPUT)
            case SyntheticArtifactInput() as target:
                sources = (
                    request.context.report_check.guide.source,
                    request.context.report_check.report.source,
                )
                if (
                    target.binding.source not in sources
                    or target.binding.artifact.parent_source_id != target.binding.source.source_id
                ):
                    raise PersistenceError(PersistenceErrorCode.INVALID_INPUT)
            case _:
                assert_never(check.target)


def validate_result(run: StoredRun) -> None:
    result = run.result
    if result is None:
        return
    ctx = run.request.context.report_check
    semantic = result.semantic
    if (
        semantic.criteria_sha256 != criteria_fingerprint(ctx)
        or semantic.criteria_version != ctx.criteria.version
        or semantic.criteria_revision != ctx.criteria.revision
        or semantic.report_source_id != ctx.report.source.source_id
        or semantic.report_document_version_id != ctx.report.source.document_version_id
        or semantic.report_source_sha256 != ctx.report.source.content_sha256
        or tuple(item.criterion for item in semantic.items) != ctx.criteria.items
        or tuple(item.original_requirement for item in semantic.items)
        != ctx.original_draft.requirements
        or tuple(item.semantic for item in result.items) != semantic.items
        or tuple(item.requirement_id for item in semantic.items)
        != tuple(item.requirement_id for item in ctx.criteria.items)
        or any(
            item.page_rule is not None
            and item.page_rule.requirement_id != item.semantic.requirement_id
            for item in result.items
        )
    ):
        raise PersistenceError(PersistenceErrorCode.CORRUPT_STORE)
    targets = {item.requirement_id: item.target for item in run.request.context.page_checks}
    for item in result.items:
        page = item.page_rule
        if (page is not None) != (item.semantic.requirement_id in targets):
            raise PersistenceError(PersistenceErrorCode.CORRUPT_STORE)
        if page is None:
            continue
        rule = page.rule
        target = targets.get(item.semantic.requirement_id)
        fingerprint = sha256(
            canonical(
                {
                    "original": encode(item.semantic.original_requirement, {}),
                    "criterion": encode(item.semantic.criterion, {}),
                }
            ).encode()
        ).hexdigest()
        if rule is not None and (
            rule.criteria_sha256 != semantic.criteria_sha256
            or rule.criterion_sha256 != fingerprint
            or rule.requirement_id != item.semantic.requirement_id
            or rule.guide_source_sha256 != ctx.guide.source.content_sha256
            or rule.guide_document_version_id != ctx.guide.source.document_version_id
        ):
            raise PersistenceError(PersistenceErrorCode.CORRUPT_STORE)
        if page.assessment is not None and (
            target is None or page.assessment.binding_sha256 != binding_digest(target)
        ):
            raise PersistenceError(PersistenceErrorCode.CORRUPT_STORE)
