from typing import final

from pydantic import TypeAdapter
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from submission.models import ErrorDetail, ErrorResponse
from submission.result_rate_limit import ResultRateLimit, ResultRatePolicy


@final
class LibraryMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app
        self.rate = ResultRateLimit(app, ResultRatePolicy(requests=120))

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request = Request(scope)
        path = request.url.path
        if not (
            path.startswith("/api/document-library")
            or (path.startswith("/api/document-pairs/") and path.endswith("/save"))
        ):
            await self.app(scope, receive, send)
            return

        async def private_send(message: Message) -> None:
            if message["type"] == "http.response.start":
                message = {
                    **message,
                    "headers": [
                        *(
                            header
                            for header in TypeAdapter(list[tuple[bytes, bytes]]).validate_python(
                                message.get("headers", [])
                            )
                            if header[0].lower() != b"cache-control"
                        ),
                        (b"cache-control", b"no-store"),
                    ],
                }
            await send(message)

        # Only admitted requests spend the shared window, so foreign pages cannot exhaust it.
        forbidden = request.headers.get("X-Local-Client") != "prepare"
        wait = 0 if forbidden else self.rate.retry_after()
        if forbidden or wait:
            await JSONResponse(
                ErrorResponse(
                    error=ErrorDetail(
                        code="library_rate_limited" if wait else "library_forbidden",
                        message="로컬 화면에서 잠시 후 다시 시도하세요.",
                    )
                ).model_dump(),
                status_code=429 if wait else 403,
                headers={"Retry-After": str(wait)} if wait else {},
            )(scope, receive, private_send)
            return
        await self.app(scope, receive, private_send)
