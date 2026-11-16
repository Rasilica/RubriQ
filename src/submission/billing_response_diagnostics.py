from pydantic import ValidationError

from submission import semantic_diagnostics as diagnostics
from submission.cloud_contracts import WireModel, WireUsage


class Incomplete(WireModel):
    reason: str | None = None


class Content(WireModel):
    type: str
    text: str | None = None


class Output(WireModel):
    type: str
    content: tuple[Content, ...] = ()


class Probe(WireModel):
    status: str
    incomplete_details: Incomplete | None = None
    output: tuple[Output, ...] = ()


class UsageProbe(WireModel):
    usage: WireUsage | None = None


def inspect_response(raw: bytes) -> None:
    diagnostics.mark("provider_response", "provider_envelope_invalid")
    diagnostics.provider_metadata(len(raw), None)
    try:
        counts = UsageProbe.model_validate_json(raw).usage
    except ValidationError:
        pass
    else:
        if counts is not None:
            diagnostics.usage(counts.input_tokens, counts.output_tokens)
    try:
        probe = Probe.model_validate_json(raw)
    except ValidationError:
        return
    reason, finish = classify(probe)
    diagnostics.mark("provider_response", reason)
    diagnostics.provider_metadata(len(raw), finish)


def classify(probe: Probe) -> tuple[diagnostics.Reason, diagnostics.Finish | None]:
    if probe.status == "incomplete" and probe.incomplete_details is not None:
        if probe.incomplete_details.reason == "max_output_tokens":
            return "output_truncated", "max_tokens"
        if probe.incomplete_details.reason == "content_filter":
            return "response_refused", "content_filter"
    if any(part.type == "refusal" for item in probe.output for part in item.content):
        return "response_refused", "content_filter"
    if any(item.type == "function_call" for item in probe.output):
        return "tool_call", "function_call"
    if probe.status != "completed":
        return "provider_envelope_invalid", None
    return completed_reason(probe), "stop"


def completed_reason(probe: Probe) -> diagnostics.Reason:
    parts = [part for item in probe.output if item.type == "message" for part in item.content]
    text = "".join(part.text or "" for part in parts if part.type == "output_text")
    if not text.strip():
        return "empty_output"
    if len(text.encode("utf-8", errors="replace")) > diagnostics.MAX_TEXT_BYTES:
        return "response_too_large"
    return "provider_envelope_invalid"
