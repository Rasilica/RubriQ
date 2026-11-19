import json
import logging
from collections.abc import Generator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, replace
from time import monotonic
from typing import Annotated, ClassVar, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from submission.report_check_contracts import ReportCheckErrorCode
from submission.requirement_contracts import RequirementErrorCode

type Stage = Literal[
    "transport",
    "provider_response",
    "output_validation",
    "json_decode",
    "report_validation",
    "requirement_validation",
    "result_build",
]
type Reason = Literal[
    "upstream_http",
    "tls_failed",
    "timeout",
    "transport_failed",
    "provider_envelope_invalid",
    "output_truncated",
    "response_refused",
    "tool_call",
    "empty_output",
    "response_too_large",
    "unsafe_output",
    "malformed_json",
    "report_contract_invalid",
    "requirement_contract_invalid",
    "citation_invalid",
    "result_invalid",
]
type Finish = Literal[
    "stop",
    "length",
    "content_filter",
    "tool_calls",
    "function_call",
    "STOP",
    "MAX_TOKENS",
    "SAFETY",
    "end_turn",
    "max_tokens",
]


class Diagnostic(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="forbid")
    id: Annotated[str, Field(pattern=r"^[a-f0-9]{32}$")]
    stage: Stage
    reason: Reason


type ContractBranch = Literal[
    "schema_invalid",
    "source_binding",
    "criteria_binding",
    "scope_duplicate",
    "scope_unsubmitted",
    "scope_cite_unreviewed",
    "identity_items",
    "identity_subconditions",
    "citation_block_missing",
    "citation_range_invalid",
    "citation_quote_mismatch",
    "citation_quote",
    "requirement_response_size",
    "requirement_encoding",
    "requirement_schema",
    "requirement_source_binding",
    "requirement_id_duplicate",
    "requirement_count",
    "subcondition_count",
    "requirement_text_length",
    "requirement_citation_count",
    "requirement_quote_length",
    "merge_count",
    "unknown",
]
type ContractCode = ReportCheckErrorCode | RequirementErrorCode
SCHEMA_FIELDS = frozenset(
    {
        "schema_version",
        "criteria_sha256",
        "report_source_id",
        "report_document_version_id",
        "report_source_sha256",
        "reviewed_block_ids",
        "items",
        "requirement_id",
        "proposed_judgment",
        "reason",
        "evidence",
        "subconditions",
        "subcondition_id",
        "citation",
        "evidence_role",
        "relation",
        "block_id",
        "char_range",
        "source_id",
        "document_version_id",
        "source_sha256",
        "requirements",
        "title",
        "classification",
        "condition",
        "description",
        "citations",
        "start",
        "end",
        "quote",
    }
)
SCHEMA_ERROR_TYPES = frozenset(
    {
        "missing",
        "extra_forbidden",
        "string_type",
        "string_too_short",
        "string_too_long",
        "string_pattern_mismatch",
        "literal_error",
        "tuple_type",
        "too_long",
        "too_short",
        "int_type",
        "greater_than_equal",
        "greater_than",
        "less_than_equal",
        "less_than",
        "model_type",
        "model_attributes_type",
        "json_invalid",
        "value_error",
    }
)


@dataclass(frozen=True)
class SchemaIssue:
    type: str
    path: tuple[str | int, ...]


@dataclass(frozen=True)
class ContractDetail:
    code: ContractCode
    branch: ContractBranch
    issues: tuple[SchemaIssue, ...] = ()
    count: int | None = None
    limit: int | None = None


def contract_failure(
    code: ContractCode,
    branch: ContractBranch = "unknown",
    error: ValidationError | None = None,
    *,
    count: int | None = None,
    limit: int | None = None,
) -> None:
    if not ACTIVE.get():
        return
    issues = (
        ()
        if error is None
        else tuple(
            SchemaIssue(
                type=entry["type"] if entry["type"] in SCHEMA_ERROR_TYPES else "unknown",
                path=tuple(
                    part
                    if isinstance(part, str) and part in SCHEMA_FIELDS
                    else min(max(part, 0), 2000)
                    if isinstance(part, int)
                    else "extra"
                    for part in entry["loc"][:12]
                ),
            )
            for entry in error.errors(
                include_url=False, include_context=False, include_input=False
            )[:5]
        )
    )
    current = TRACE.get()
    detail = ContractDetail(code, branch, issues, count, limit)
    if current is not None and branch == "unknown" and current.detail is not None:
        return
    is_requirement = isinstance(code, RequirementErrorCode)
    stage: Stage = "requirement_validation" if is_requirement else "report_validation"
    if code.value == "invalid_citation":
        mark(stage, "citation_invalid")
    else:
        mark(stage, "requirement_contract_invalid" if is_requirement else "report_contract_invalid")
    current = TRACE.get()
    if current is not None:
        _ = TRACE.set(replace(current, detail=detail))


def detail_json(detail: ContractDetail | None) -> str:
    if detail is None:
        return "null"
    counts = {} if detail.count is None else {"count": detail.count, "limit": detail.limit}
    return json.dumps(
        {
            "code": detail.code.value,
            "branch": detail.branch,
            "issues": [{"type": issue.type, "path": issue.path} for issue in detail.issues],
            **counts,
        },
        separators=(",", ":"),
    )


@dataclass(frozen=True)
class Trace:
    stage: Stage
    reason: Reason
    detail: ContractDetail | None = None
    upstream_status: int | None = None
    response_bytes: int | None = None
    finish: Finish | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None


ACTIVE: ContextVar[bool] = ContextVar("semantic_diagnostic_active", default=False)
TRACE: ContextVar[Trace | None] = ContextVar("semantic_diagnostic", default=None)
LOGGER = logging.getLogger(__name__)


@contextmanager
def scope() -> Generator[None]:
    active = ACTIVE.set(True)
    token = TRACE.set(None)
    try:
        yield
    finally:
        TRACE.reset(token)
        ACTIVE.reset(active)


def mark(stage: Stage, reason: Reason) -> None:
    if not ACTIVE.get():
        return
    previous = TRACE.get()
    _ = TRACE.set(
        Trace(stage, reason) if previous is None else replace(previous, stage=stage, reason=reason)
    )


def transport_status(status: int) -> None:
    current = TRACE.get()
    if current is not None:
        _ = TRACE.set(replace(current, upstream_status=status))


def provider_metadata(response_bytes: int, finish: Finish | None) -> None:
    current = TRACE.get()
    if current is not None:
        _ = TRACE.set(replace(current, response_bytes=response_bytes, finish=finish))


MAX_TEXT_BYTES = 262144


class ProbeMessage(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, strict=True)
    content: str | None = None
    refusal: str | None = None
    tool_calls: tuple[object, ...] | None = None
    function_call: object = None


class ProbeChoice(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, strict=True)
    finish_reason: str | None = None
    message: ProbeMessage = ProbeMessage()


class Probe(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, strict=True)
    choices: tuple[ProbeChoice, ...] = ()


class SafeUsage(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, strict=True)
    prompt_tokens: Annotated[int, Field(ge=0)] | None = None
    completion_tokens: Annotated[int, Field(ge=0)] | None = None


class UsageProbe(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, strict=True)
    usage: SafeUsage | None = None


def billing_usage(raw: bytes) -> None:
    try:
        counts = UsageProbe.model_validate_json(raw).usage
    except ValidationError:
        return
    if counts is not None:
        usage(counts.prompt_tokens, counts.completion_tokens)


def billing_response(raw: bytes) -> None:
    current = TRACE.get()
    if current is None:
        return
    billing_usage(raw)
    current = TRACE.get()
    if current is None:
        return
    _ = TRACE.set(
        replace(
            current,
            stage="provider_response",
            reason="provider_envelope_invalid",
            response_bytes=len(raw),
        )
    )
    try:
        result = Probe.model_validate_json(raw, strict=True)
    except ValidationError:
        return
    if len(result.choices) != 1:
        return
    choice = result.choices[0]
    mark("provider_response", billing_reason(choice))
    current = TRACE.get()
    finish = allowed_finish(choice.finish_reason)
    if current is not None:
        _ = TRACE.set(replace(current, finish=finish))


def allowed_finish(value: str | None) -> Finish | None:
    match value:
        case "stop" | "length" | "content_filter" | "tool_calls" | "function_call":
            return value
        case _:
            return None


def billing_reason(choice: ProbeChoice) -> Reason:
    if choice.finish_reason == "length":
        return "output_truncated"
    if choice.message.refusal or choice.finish_reason == "content_filter":
        return "response_refused"
    if (
        choice.message.tool_calls
        or choice.message.function_call
        or choice.finish_reason in {"tool_calls", "function_call"}
    ):
        return "tool_call"
    content = choice.message.content
    if content is not None:
        if not content.strip():
            return "empty_output"
        if len(content.encode("utf-8", errors="replace")) > MAX_TEXT_BYTES:
            return "response_too_large"
    return "provider_envelope_invalid"


def usage(input_tokens: int | None, output_tokens: int | None) -> None:
    current = TRACE.get()
    if current is not None:
        _ = TRACE.set(replace(current, input_tokens=input_tokens, output_tokens=output_tokens))


def failure(status: int, started: float) -> Diagnostic | None:
    current = TRACE.get()
    if current is None:
        return None
    diagnostic = Diagnostic(id=uuid4().hex, stage=current.stage, reason=current.reason)
    message = "semantic_failure id=%s stage=%s reason=%s status=%s upstream_status=%s bytes=%s finish=%s elapsed_ms=%s input_tokens=%s output_tokens=%s contract_detail=%s"  # noqa: E501
    LOGGER.warning(
        message,
        diagnostic.id,
        current.stage,
        current.reason,
        status,
        current.upstream_status,
        current.response_bytes,
        current.finish,
        max(0, round((monotonic() - started) * 1000)),
        current.input_tokens,
        current.output_tokens,
        detail_json(current.detail),
    )
    return diagnostic
