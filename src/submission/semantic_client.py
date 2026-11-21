from typing import Final, assert_never

from pydantic import JsonValue, SecretStr, TypeAdapter, ValidationError

from submission import semantic_diagnostics as diagnostics
from submission.billing_json_client import TIMEOUT_SECONDS as BILLING_TIMEOUT
from submission.billing_json_client import generate_json
from submission.citation_reference_wire import ReferenceWire, reference_wire
from submission.cloud_client import INFERENCE, generate_text
from submission.cloud_contracts import CloudCode, CloudError, Provider, TextCompletion
from submission.ollama_client import generate
from submission.semantic_contracts import AIRequest
from submission.semantic_wire import MAX_OUTPUT_BYTES, wire_document

PROVIDER_TIMEOUT: Final = 180
COMMON_INSTRUCTIONS: Final = (
    " 응답은 코드 블록이나 설명 없이 JSON 객체 하나만 반환하세요. response_schema_json을 따르세요. "
)
REFERENCE_INSTRUCTIONS: Final = (
    " reviewed_block_ids는 검토한 blocks의 bN ID이며 qN 인용 참조와 다릅니다. "
    "citation에는 blocks.citation_refs의 citation_ref 하나만 반환하세요. "
    "각 참조는 원문 블록 전체 또는 연속 구간이며 문장 단위를 보장하지 않습니다. "
    "quote와 문자 좌표는 서버가 원문에서 복원하므로 직접 만들거나 고치지 마세요."
)
LEGACY_INSTRUCTIONS: Final = (
    " citation에는 block_id, quote, char_range 세 필드만 사용하세요. "
    "인용 block_id는 blocks의 짧은 ID를 쓰세요. "
    "unicode_length는 원문 Unicode 길이입니다. "
    "가능하면 짧은 블록 전체를 그대로 인용하세요."
)


def provider_timeout(provider: Provider | str) -> float:
    return BILLING_TIMEOUT if provider == Provider.BILLINGAI else PROVIDER_TIMEOUT


def complete(request: AIRequest, instructions: str, payload: str, key: SecretStr) -> TextCompletion:
    if not INFERENCE.acquire(blocking=False):
        raise CloudError(CloudCode.BUSY, 409)
    try:
        wire = (
            reference_wire(payload)
            if request.provider == Provider.BILLINGAI
            else wire_document(payload)
        )
        wire_payload = wire.prepare(payload)
        wire_instructions = (
            instructions
            + COMMON_INSTRUCTIONS
            + (REFERENCE_INSTRUCTIONS if isinstance(wire, ReferenceWire) else LEGACY_INSTRUCTIONS)
        )
        diagnostics.mark("transport", "upstream_http")
        match request.provider:
            case "ollama":
                result = TextCompletion(
                    suggestion=generate(
                        request.model,
                        wire_payload,
                        instructions=wire_instructions,
                        max_tokens=8192,
                        timeout=PROVIDER_TIMEOUT,
                    )
                )
            case Provider.BILLINGAI:
                result = generate_json(request.model, wire_payload, wire_instructions, key)
            case Provider.GEMINI | Provider.OPENAI | Provider.ANTHROPIC:
                result = generate_text(
                    request.provider,
                    request.model,
                    wire_payload,
                    key,
                    instructions=wire_instructions,
                    max_tokens=8192,
                    timeout=PROVIDER_TIMEOUT,
                )
            case _:
                assert_never(request.provider)
        diagnostics.usage(result.usage.input_tokens, result.usage.output_tokens)
        validate_output(result.suggestion, key, request.provider)
        if result.suggestion.lstrip().startswith("{"):
            diagnostics.mark("json_decode", "malformed_json")
            result = result.model_copy(update={"suggestion": wire.restore(result.suggestion)})
        validate_output(result.suggestion, key, request.provider)
    except (ValidationError, UnicodeEncodeError):
        raise CloudError(CloudCode.INVALID_RESPONSE, 502) from None
    else:
        return result
    finally:
        INFERENCE.release()


def validate_size(text: str) -> None:
    if len(text.encode("utf-8")) > MAX_OUTPUT_BYTES:
        diagnostics.mark("output_validation", "response_too_large")
        raise CloudError(CloudCode.INVALID_RESPONSE, 502)


def validate_output(text: str, key: SecretStr, provider: Provider | str) -> None:
    diagnostics.mark("output_validation", "empty_output")
    secret = key.get_secret_value()
    if secret and secret in text:
        diagnostics.mark("output_validation", "unsafe_output")
        raise CloudError(CloudCode.INVALID_RESPONSE, 502)
    if not text.strip():
        raise CloudError(CloudCode.INVALID_RESPONSE, 502)
    validate_size(text)
    if provider == Provider.BILLINGAI:
        diagnostics.mark("json_decode", "malformed_json")
        _ = TypeAdapter(dict[str, JsonValue]).validate_json(text, strict=True)
