from enum import StrEnum
from typing import Annotated, ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field

from submission.evidence_selection import EvidenceSelection
from submission.models import FrozenModel

type ModelName = Annotated[
    str, Field(min_length=1, max_length=200, pattern=r"^[a-zA-Z0-9][a-zA-Z0-9._:/-]*$")
]


class OllamaCode(StrEnum):
    UNAVAILABLE = "ollama_unavailable"
    INVALID_RESPONSE = "ollama_invalid_response"
    MODEL_UNAVAILABLE = "ollama_model_unavailable"
    BUSY = "ollama_busy"
    FORBIDDEN = "ollama_forbidden"
    TIMEOUT = "ollama_timeout"


class OllamaError(Exception):
    def __init__(self, code: OllamaCode, status: int = 503) -> None:
        super().__init__(code)
        self.code: OllamaCode = code
        self.status: int = status


class OllamaModel(FrozenModel):
    name: ModelName


class OllamaModels(FrozenModel):
    provider: Literal["ollama"] = "ollama"
    models: tuple[OllamaModel, ...]


class RewriteRequest(EvidenceSelection):
    model: ModelName


class RewriteResult(EvidenceSelection):
    provider: Literal["ollama"] = "ollama"
    model: ModelName
    source_sha256: str
    original: str
    suggestion: Annotated[str, Field(min_length=1, max_length=8000)]
    llm_executed: Literal[True] = True
    warnings: tuple[str, ...] = (
        "로컬 LLM의 수정 제안입니다. 사실·수치·인용 보존을 보장하지 않으므로 원문과 비교하세요.",
        "원문은 변경되지 않았습니다. AI 작성 여부나 정확성을 판정하지 않습니다.",
    )


class RemoteMetadata(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="ignore", strict=True)
    remote_host: str = ""
    remote_model: str = ""


class ShowResponse(RemoteMetadata):
    capabilities: tuple[str, ...]


class ModelSummary(RemoteMetadata):
    name: ModelName


class TagsResponse(RemoteMetadata):
    models: Annotated[tuple[ModelSummary, ...], Field(max_length=100)]


class ChatMessage(RemoteMetadata):
    role: Literal["assistant"]
    content: Annotated[str, Field(min_length=1, max_length=262144)]
    tool_calls: Annotated[tuple[()], Field(max_length=0)] = ()


class ChatResponse(RemoteMetadata):
    model: ModelName
    done_reason: Literal["stop"]
    message: ChatMessage
    done: Literal[True]
