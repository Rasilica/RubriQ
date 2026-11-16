from typing import final

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from submission.models import ErrorDetail, ErrorResponse
from submission.result_rate_limit import ResultRateLimit, ResultRatePolicy


@final
class PairMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app
        self.requests = ResultRateLimit(app, ResultRatePolicy(requests=600))
        self.uploads = ResultRateLimit(app, ResultRatePolicy(requests=30))

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request = Request(scope)
        if not request.url.path.startswith(("/api/document-pairs", "/prepare")):
            await self.app(scope, receive, send)
            return
        if (
            request.headers.get("Sec-Fetch-Site") == "cross-site"
            and request.headers.get("Sec-Fetch-Mode") != "navigate"
        ):
            await JSONResponse(
                ErrorResponse(
                    error=ErrorDetail(
                        code="pair_forbidden", message="로컬 화면에서만 사용할 수 있습니다."
                    )
                ).model_dump(),
                status_code=403,
                headers={"Cache-Control": "no-store"},
            )(scope, receive, send)
            return
        wait = self.requests.retry_after()
        if request.url.path == "/api/document-pairs" and request.method == "POST":
            wait = max(wait, self.uploads.retry_after())
        if wait:
            await JSONResponse(
                ErrorResponse(
                    error=ErrorDetail(
                        code="pair_rate_limited",
                        message="요청이 많습니다. 잠시 후 다시 시도하세요.",
                    )
                ).model_dump(),
                status_code=429,
                headers={
                    "Cache-Control": "no-store",
                    "Retry-After": str(wait),
                },
            )(scope, receive, send)
            return

        async def secured_send(message: Message) -> None:
            if message["type"] == "http.response.start":
                message = {
                    **message,
                    "headers": [
                        *message.get("headers", []),
                        (b"cache-control", b"no-store"),
                        (b"x-content-type-options", b"nosniff"),
                    ],
                }
            await send(message)

        await self.app(scope, receive, secured_send)
