from typing import Annotated, Literal

from pydantic import Field

from submission.models import FrozenModel


class ExpressionFinding(FrozenModel):
    pattern_id: str
    label: str
    start: Annotated[int, Field(ge=0)]
    end: Annotated[int, Field(gt=0)]
    original: str
    explanation: str
    suggestion: str | None = None


class ExpressionMetric(FrozenModel):
    id: str
    label: str
    count: Annotated[int, Field(ge=0)]


class ExpressionResult(FrozenModel):
    engine: Literal["im-not-ai-local"] = "im-not-ai-local"
    revision: str = "2f3d943d08056b612a92e12bfb72ea94dd2acd18"
    scope: Literal["selected_text"] = "selected_text"
    source_sha256: str
    block_id: str
    start: int
    end: int
    findings: tuple[ExpressionFinding, ...]
    metrics: tuple[ExpressionMetric, ...]
    warnings: tuple[str, ...]
    llm_executed: Literal[False] = False
