import os
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, FastAPI, Header, Query, Request
from fastapi.responses import JSONResponse

from submission.library_contracts import LibraryCode, LibraryError, LibraryPage, SavedReceipt
from submission.library_middleware import LibraryMiddleware
from submission.library_store import LibraryStore
from submission.library_validation import environment
from submission.models import ErrorDetail, ErrorResponse
from submission.pair_contracts import Deleted, PairEnvelope, PairRuntime, SavedOrigin, SessionView
from submission.pair_store import PairStore

type Token = Annotated[str, Header(alias="X-Session-Token", max_length=128)]


def library_path() -> Path:
    configured = os.environ.get("DOCUMENT_LIBRARY_FILE")
    return (
        Path(configured)
        if configured
        else Path(__file__).parents[2] / ".runtime/library/documents.sqlite3"
    )


def install_library(
    app: FastAPI, store: PairStore, runtime: PairRuntime, path: Path | None
) -> None:
    library = LibraryStore(path if path is not None else library_path())
    current = environment(runtime)
    app.add_middleware(LibraryMiddleware)
    router = APIRouter()

    @app.exception_handler(LibraryError)
    async def failed(_request: Request, error: LibraryError) -> JSONResponse:
        return JSONResponse(
            ErrorResponse(
                error=ErrorDetail(
                    code=error.code,
                    message="보관 문서를 처리하지 못했습니다. 상태를 확인하고 다시 시도하세요.",
                )
            ).model_dump(),
            status_code={
                LibraryCode.NOT_FOUND: 404,
                LibraryCode.CORRUPT: 409,
                LibraryCode.LIMIT: 409,
                LibraryCode.UNAVAILABLE: 503,
            }[error.code],
        )

    @router.post("/api/document-pairs/{session_id}/save")
    def save(session_id: str, token: Token = "") -> PairEnvelope[SavedReceipt]:
        with store.lease(session_id, token) as session:
            return PairEnvelope(data=library.save(session, session.saved_environment or current))

    @router.get("/api/document-library")
    def listing(page: Annotated[int, Query(ge=1, le=1_000_000)] = 1) -> PairEnvelope[LibraryPage]:
        return PairEnvelope(data=library.list(page))

    @router.post("/api/document-library/{saved_id}/open")
    def reopen(saved_id: str) -> PairEnvelope[SessionView]:
        saved = library.load(saved_id)
        session = store.create(
            saved.summary.project_name,
            saved.guide,
            saved.report,
            semantic_archive=saved.semantic_archive,
            origin=SavedOrigin(
                saved_id=saved.summary.saved_id,
                saved_at=saved.summary.saved_at,
                saved_environment=saved.environment,
                current_environment=current,
            ),
        )
        return PairEnvelope(data=session.view(include_token=True))

    @router.delete("/api/document-library/{saved_id}")
    def delete(saved_id: str) -> PairEnvelope[Deleted]:
        library.delete(saved_id)
        return PairEnvelope(data=Deleted())

    app.include_router(router)
