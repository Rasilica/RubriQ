from typing import Final, final

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from submission.guard import RequestChunk, UploadGuard
from submission.models import ErrorDetail, ErrorResponse
from submission.result_rate_limit import ResultRateLimit, ResultRatePolicy

MAX_SETTINGS_BODY: Final = 4096


@final
class CredentialMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app
        self.rate = ResultRateLimit(app, ResultRatePolicy(requests=60))

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        if not Request(scope).url.path.startswith("/api/ai-settings"):
            await self.app(scope, receive, send)
            return
        request = Request(scope)

        async def private_send(message: Message) -> None:
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

        # Only admitted requests spend the shared window, so foreign pages cannot exhaust it.
        forbidden = request.headers.get("X-Local-Client") != "prepare"
        wait = 0 if forbidden else self.rate.retry_after()
        if forbidden or wait:
            await JSONResponse(
                ErrorResponse(
                    error=ErrorDetail(
                        code="credentials_rate_limited" if wait else "credentials_forbidden",
                        message="로컬 설정 화면에서 잠시 후 다시 시도하세요.",
                    )
                ).model_dump(),
                status_code=429 if wait else 403,
            )(scope, receive, private_send)
            return
        chunks = await bounded_body(receive)
        if chunks is None:
            await JSONResponse(
                ErrorResponse(
                    error=ErrorDetail(
                        code="body_too_large",
                        message="요청 크기 한도를 초과했습니다.",
                    )
                ).model_dump(),
                status_code=413,
            )(scope, receive, private_send)
            return

        async def body() -> Message:
            return {"type": "http.request", "body": bytes(chunks), "more_body": False}

        await UploadGuard(self.app, MAX_SETTINGS_BODY)(scope, body, private_send)


async def bounded_body(receive: Receive) -> bytes | None:
    """Bound streamed input before JSON decoding; None means the limit was exceeded."""
    chunks = bytearray()
    while True:
        message = await receive()
        if message["type"] != "http.request":
            return b""
        chunks.extend(RequestChunk.model_validate(message).body)
        if len(chunks) > MAX_SETTINGS_BODY:
            return None
        if not message.get("more_body", False):
            return bytes(chunks)
