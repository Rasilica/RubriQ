from typing import ClassVar, Final

from pydantic import BaseModel, ConfigDict
from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from submission.models import ErrorDetail, ErrorResponse

MULTIPART_ALLOWANCE: Final = 64 * 1024


class RequestChunk(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="ignore", strict=True)
    body: bytes = b""


class UploadGuard:
    app: ASGIApp
    max_body_bytes: int

    def __init__(self, app: ASGIApp, max_body_bytes: int) -> None:
        self.app = app
        self.max_body_bytes = max_body_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request = Request(scope)
        origin = request.headers.get("origin")
        if origin and origin != str(request.base_url).rstrip("/"):
            response = JSONResponse(
                ErrorResponse(
                    error=ErrorDetail(code="cross_origin", message="같은 로컬 주소에서 요청하세요.")
                ).model_dump(),
                status_code=403,
            )
            await response(scope, receive, send)
            return
        received = 0

        async def bounded_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(RequestChunk.model_validate(message).body)
                if received > self.max_body_bytes:
                    raise HTTPException(status_code=413)
            return message

        await self.app(scope, bounded_receive, send)
