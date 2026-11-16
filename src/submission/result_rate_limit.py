from collections.abc import Callable
from dataclasses import dataclass
from math import ceil
from threading import Lock
from time import monotonic
from typing import Annotated, Final, final

from pydantic import Field
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from submission.evidence_contracts import EvidenceModel
from submission.models import ErrorDetail, ErrorResponse


class ResultRatePolicy(EvidenceModel):
    requests: Annotated[int, Field(gt=0)] = 600
    seconds: Annotated[int, Field(gt=0)] = 60


DEFAULT_RATE_POLICY: Final = ResultRatePolicy()


@dataclass(frozen=True, slots=True)
class RateWindow:
    started_at: float
    count: int


@final
class ResultRateLimit:
    """Replace one immutable window under a lock; no client identifiers are retained."""

    def __init__(
        self,
        app: ASGIApp,
        policy: ResultRatePolicy = DEFAULT_RATE_POLICY,
        *,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        self.app = app
        self.policy = policy
        self.clock = clock
        self._window = RateWindow(started_at=clock(), count=0)
        self._lock = Lock()

    def retry_after(self) -> int:
        with self._lock:
            now = self.clock()
            window = self._window
            if now - window.started_at >= self.policy.seconds:
                window = RateWindow(started_at=now, count=0)
            if window.count >= self.policy.requests:
                return max(1, ceil(self.policy.seconds - (now - window.started_at)))
            self._window = RateWindow(started_at=window.started_at, count=window.count + 1)
            return 0

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path = Request(scope).url.path
        scoped = path == "/results" or any(
            path == prefix or path.startswith(prefix + "/")
            for prefix in ("/api/result-demos", "/result-assets")
        )
        wait = self.retry_after() if scoped else 0
        if wait:
            response = JSONResponse(
                ErrorResponse(
                    error=ErrorDetail(
                        code="result_rate_limited",
                        message="요청이 많습니다. 잠시 후 다시 시도하세요.",
                    )
                ).model_dump(),
                status_code=429,
                headers={
                    "Cache-Control": "no-store",
                    "X-Content-Type-Options": "nosniff",
                    "Retry-After": str(wait),
                },
            )
            await response(scope, receive, send)
            return
        await self.app(scope, receive, send)
