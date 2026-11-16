from enum import StrEnum
from typing import Annotated, ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field

from submission.evidence_selection import EvidenceSelection
from submission.models import FrozenModel

type ModelName = Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,199}$")]
type Passage = Annotated[str, Field(min_length=1, max_length=8000)]
type GeneratedText = Annotated[str, Field(min_length=1, max_length=262144)]
type TokenCount = Annotated[int, Field(ge=0)]


class Provider(StrEnum):
    GEMINI = "gemini"
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    BILLINGAI = "billingai"


class CloudCode(StrEnum):
    UNAVAILABLE = "cloud_unavailable"
    TLS_FAILED = "cloud_tls_failed"
    INVALID_RESPONSE = "cloud_invalid_response"
    AUTH_FAILED = "cloud_auth_failed"
    RATE_LIMITED = "cloud_rate_limited"
    TIMEOUT = "cloud_timeout"
    BUSY = "cloud_busy"
    FORBIDDEN = "cloud_forbidden"
    KEY_INVALID = "cloud_key_invalid"
    CONSENT_REQUIRED = "cloud_consent_required"


class CloudError(Exception):
    def __init__(self, code: CloudCode, status: int = 503) -> None:
        super().__init__(code)
        self.code: CloudCode = code
        self.status: int = status


class CloudRequest(EvidenceSelection):
    provider: Provider
    model: ModelName
    consent: Annotated[bool, Field(strict=True)] = False
    use_saved_key: Annotated[bool, Field(strict=True)] = False
    source_sha256: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]


class Usage(FrozenModel):
    input_tokens: TokenCount | None = None
    output_tokens: TokenCount | None = None


class TextCompletion(FrozenModel):
    suggestion: GeneratedText
    usage: Usage = Usage()


class Completion(FrozenModel):
    suggestion: Passage
    usage: Usage = Usage()


class CloudResult(EvidenceSelection):
    provider: Provider
    model: ModelName
    source_sha256: str
    original: str
    suggestion: Passage
    usage: Usage
    llm_executed: Literal[True] = True
    warnings: tuple[str, ...] = (
        "클라우드 AI의 수정 제안입니다. 사실·수치·인용 보존을 보장하지 않으므로 원문과 비교하세요.",
        "원문은 변경되지 않았습니다. AI 작성 여부나 정확성을 판정하지 않습니다.",
    )


class WireModel(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="ignore", strict=True)


class WireUsage(WireModel):
    input_tokens: TokenCount | None = None
    output_tokens: TokenCount | None = None
    promptTokenCount: TokenCount | None = None  # noqa: N815
    candidatesTokenCount: TokenCount | None = None  # noqa: N815


class GeminiPart(FrozenModel):
    text: GeneratedText
    thought: Literal[False] = False
    thoughtSignature: Annotated[str, Field(max_length=100_000)] | None = None  # noqa: N815


class GeminiContent(WireModel):
    parts: Annotated[tuple[GeminiPart, ...], Field(min_length=1)]


class GeminiSafety(WireModel):
    blocked: Literal[False] = False


class GeminiFeedback(WireModel):
    blockReason: None = None  # noqa: N815
    safetyRatings: tuple[GeminiSafety, ...] = ()  # noqa: N815


class GeminiCandidate(WireModel):
    finishReason: Literal["STOP"]  # noqa: N815
    content: GeminiContent
    safetyRatings: tuple[GeminiSafety, ...] = ()  # noqa: N815


class GeminiResponse(WireModel):
    candidates: Annotated[tuple[GeminiCandidate, ...], Field(min_length=1, max_length=1)]
    promptFeedback: GeminiFeedback | None = None  # noqa: N815
    usageMetadata: WireUsage = WireUsage()  # noqa: N815


class OpenAIText(WireModel):
    type: Literal["output_text"]
    text: GeneratedText


class OpenAIMessage(WireModel):
    type: Literal["message"]
    role: Literal["assistant"]
    status: Literal["completed"]
    content: Annotated[tuple[OpenAIText, ...], Field(min_length=1)]


class OpenAIReasoning(WireModel):
    type: Literal["reasoning"]


class OpenAIResponse(WireModel):
    status: Literal["completed"]
    error: None = None
    incomplete_details: None = None
    output: Annotated[
        tuple[Annotated[OpenAIMessage | OpenAIReasoning, Field(discriminator="type")], ...],
        Field(min_length=1),
    ]
    usage: WireUsage = WireUsage()


class AnthropicText(WireModel):
    type: Literal["text"]
    text: GeneratedText


class AnthropicResponse(WireModel):
    stop_reason: Literal["end_turn"]
    content: Annotated[tuple[AnthropicText, ...], Field(min_length=1)]
    usage: WireUsage = WireUsage()


class BillingAIMessage(WireModel):
    role: Literal["assistant"]
    content: GeneratedText
    refusal: None = None
    tool_calls: tuple[()] | None = None
    function_call: None = None


class BillingAIChoice(WireModel):
    finish_reason: Literal["stop"]
    message: BillingAIMessage


class BillingAIUsage(WireModel):
    prompt_tokens: TokenCount | None = None
    completion_tokens: TokenCount | None = None


class BillingAIResponse(WireModel):
    choices: Annotated[tuple[BillingAIChoice, ...], Field(min_length=1, max_length=1)]
    usage: BillingAIUsage = BillingAIUsage()
