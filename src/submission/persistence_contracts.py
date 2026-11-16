from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import Field, model_validator

from submission.document_contracts import DocumentSource, ToolDescriptor
from submission.evidence_contracts import ArtifactBinding, EvidenceModel
from submission.page_rule_contracts import (
    PageRuleErrorCode,
    SubmissionCheckContext,
    SubmissionCheckLimits,
    SubmissionCheckResult,
)


class PersistenceErrorCode(StrEnum):
    INVALID_INPUT = "invalid_input"
    INPUT_LIMIT = "input_limit"
    NOT_FOUND = "not_found"
    UNSUPPORTED_SCHEMA = "unsupported_schema"
    CORRUPT_STORE = "corrupt_store"
    STORAGE_ERROR = "storage_error"


class PersistenceError(ValueError):
    code: PersistenceErrorCode

    def __init__(self, code: PersistenceErrorCode) -> None:
        super().__init__(code.value)
        self.code = code


class PersistenceLimits(EvidenceModel):
    max_total_bytes: Annotated[int, Field(gt=0, le=100_000_000)] = 30_000_000
    max_manifest_bytes: Annotated[int, Field(gt=0, le=20_000_000)] = 5_000_000
    max_payloads: Annotated[int, Field(gt=0, le=1000)] = 100
    timeout_seconds: Annotated[float, Field(gt=0, le=30, allow_inf_nan=False)] = 5.0
    max_runs: Annotated[int, Field(gt=0, le=100_000)] = 1000
    max_stored_bytes: Annotated[int, Field(gt=0, le=10_000_000_000)] = 1_000_000_000


class OriginalPayload(EvidenceModel):
    source: DocumentSource
    content: bytes


class ArtifactPayload(EvidenceModel):
    binding: ArtifactBinding
    content: bytes


class ExecutionSettings(EvidenceModel):
    toolchain: Annotated[tuple[ToolDescriptor, ...], Field(max_length=100)]
    check_limits: SubmissionCheckLimits = SubmissionCheckLimits()


class PersistenceRequest(EvidenceModel):
    context: SubmissionCheckContext
    originals: tuple[OriginalPayload, ...]
    artifacts: tuple[ArtifactPayload, ...]
    response_json: str
    settings: ExecutionSettings


class RunSummary(EvidenceModel):
    run_id: Annotated[str, Field(min_length=1, max_length=100)]
    project_id: Annotated[str, Field(min_length=1, max_length=200, pattern=r"\S")]
    sequence: Annotated[int, Field(gt=0)]
    created_at: datetime
    status: Literal["succeeded", "failed"]
    predecessor_run_id: str | None
    elapsed_ms: Annotated[float, Field(ge=0, allow_inf_nan=False)]


class StoredRun(RunSummary):
    schema_version: Literal["1"] = "1"
    request: PersistenceRequest
    result: SubmissionCheckResult | None
    failure_code: PageRuleErrorCode | None
    durable: Literal[True] = True

    @model_validator(mode="after")
    def terminal_consistency(self) -> "StoredRun":
        success = self.status == "succeeded"
        offset = self.created_at.utcoffset()
        if (
            success != (self.result is not None)
            or success == (self.failure_code is not None)
            or offset is None
            or offset.total_seconds() != 0
        ):
            raise PersistenceError(PersistenceErrorCode.INVALID_INPUT)
        return self
