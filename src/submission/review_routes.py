from pathlib import Path
from typing import Final

from fastapi import APIRouter, FastAPI, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool

from submission.models import ErrorDetail, ErrorResponse, FrozenModel
from submission.review_contracts import (
    CreatedSession,
    CreateRequest,
    ReviewError,
    ReviewErrorCode,
    ReviewResponse,
    ReviewSession,
    RevisionRequest,
    WorkingCopyRequest,
)
from submission.review_store import ReviewStore

MAX_REVIEW_BODY: Final = 256 * 1024


def request_token(request: Request) -> str:
    if request.headers.get("x-review-request") != "1":
        raise ReviewError(ReviewErrorCode.REVIEW_REQUEST_REQUIRED, 403)
    return request.headers.get("x-review-token", "")


async def read_body[Model: FrozenModel](request: Request, model: type[Model]) -> Model:
    _ = request_token(request)
    if (
        request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        != "application/json"
    ):
        raise ReviewError(ReviewErrorCode.JSON_REQUIRED, 415)
    raw = b""
    async for chunk in request.stream():
        if len(raw) + len(chunk) > MAX_REVIEW_BODY:
            raise ReviewError(ReviewErrorCode.BODY_TOO_LARGE, 413)
        raw += chunk
    try:
        return model.model_validate_json(raw, strict=True)
    except (ValidationError, ValueError):
        raise ReviewError(ReviewErrorCode.INVALID_REVIEW_REQUEST) from None


def install_review(app: FastAPI) -> None:
    store = ReviewStore()
    router = APIRouter(prefix="/api/review-sessions")

    @app.exception_handler(ReviewError)
    async def review_error(_request: Request, error: ReviewError) -> JSONResponse:
        return JSONResponse(
            ErrorResponse(
                error=ErrorDetail(
                    code=error.code, message="요구사항 검토 요청을 확인하고 다시 시도하세요."
                )
            ).model_dump(),
            status_code=error.status_code,
            headers={"Cache-Control": "no-store"},
        )

    @router.post("", status_code=201)
    async def create(request: Request, response: Response) -> ReviewResponse[CreatedSession]:
        response.headers["Cache-Control"] = "no-store"
        _ = await read_body(request, CreateRequest)
        return ReviewResponse(data=await run_in_threadpool(store.create))

    @router.get("/{session_id}")
    def get(session_id: str, request: Request, response: Response) -> ReviewResponse[ReviewSession]:
        response.headers["Cache-Control"] = "no-store"
        return ReviewResponse(data=store.get(session_id, request_token(request)))

    @router.put("/{session_id}/working-copy")
    async def save(
        session_id: str, request: Request, response: Response
    ) -> ReviewResponse[ReviewSession]:
        response.headers["Cache-Control"] = "no-store"
        body = await read_body(request, WorkingCopyRequest)
        return ReviewResponse(data=store.save(session_id, request_token(request), body))

    @router.post("/{session_id}/confirm")
    async def confirm(
        session_id: str, request: Request, response: Response
    ) -> ReviewResponse[ReviewSession]:
        response.headers["Cache-Control"] = "no-store"
        body = await read_body(request, RevisionRequest)
        return ReviewResponse(
            data=store.confirm(session_id, request_token(request), body.expected_revision)
        )

    app.include_router(router)
    static = Path(__file__).parent / "static/review"
    app.mount(
        "/review-assets", StaticFiles(directory=static, check_dir=False), name="review-assets"
    )

    @app.get("/review", include_in_schema=False)
    def review_page() -> FileResponse:
        return FileResponse(static / "index.html")
