import os
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path
from threading import Lock
from typing import Annotated

import anyio
from fastapi import APIRouter, FastAPI, File, Form, Header, Request, Response, UploadFile
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError

from submission.cloud_routes import install_cloud_routes
from submission.credentials import CredentialStore, KeyringStore
from submission.document_contracts import ContractError
from submission.evidence_contracts import BoundEvidenceMapping, EvidenceError
from submission.expression_routes import install_expression_routes
from submission.input_contracts import DocumentInput
from submission.library_routes import install_library
from submission.models import DocumentRole, ErrorDetail, ErrorResponse
from submission.ollama_routes import install_ollama_routes
from submission.pair_assets import evidence, render_page, validated_pdf
from submission.pair_contracts import (
    Deleted,
    EvidenceSelection,
    PairEnvelope,
    PairError,
    PairErrorCode,
    PairRuntime,
    SessionView,
)
from submission.pair_middleware import PairMiddleware
from submission.pair_process import run_preparation
from submission.pair_store import PairStore
from submission.result_rate_limit import ResultRateLimit, ResultRatePolicy
from submission.semantic_contracts import SemanticError
from submission.semantic_routes import install_semantic_routes

type Token = Annotated[str, Header(alias="X-Session-Token", max_length=128)]


def load_runtime() -> PairRuntime:
    path = os.environ.get("DOCUMENT_PAIR_RUNTIME_FILE")
    if path is None:
        return PairRuntime()
    with Path(path).open("rb") as stream:
        return PairRuntime.model_validate_json(stream.read(1024 * 1024))


def attach_lifetime(app: FastAPI, store: PairStore) -> None:
    previous = app.router.lifespan_context

    async def cleanup() -> None:
        while True:
            await anyio.sleep(10)
            store.cleanup()

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncGenerator[None]:
        async with previous(application), anyio.create_task_group() as group:
            _ = group.start_soon(cleanup)
            try:
                yield
            finally:
                group.cancel_scope.cancel()
                store.clear()

    app.router.lifespan_context = lifespan


def pair_error_status(code: PairErrorCode) -> int:
    return {
        PairErrorCode.NOT_FOUND: 404,
        PairErrorCode.BUSY: 409,
        PairErrorCode.FAILED: 422,
        PairErrorCode.LIMIT: 409,
        PairErrorCode.UNAVAILABLE: 409,
        PairErrorCode.INVALID: 422,
        PairErrorCode.TIMEOUT: 408,
    }[code]


def install_pairs(
    app: FastAPI,
    runtime: PairRuntime,
    library_path: Path | None = None,
    credentials: CredentialStore | None = None,
) -> None:
    credentials = credentials if credentials is not None else KeyringStore()
    store = PairStore()
    admission = Lock()
    attach_lifetime(app, store)
    app.add_middleware(PairMiddleware)
    router = APIRouter(prefix="/api/document-pairs")

    @app.exception_handler(PairError)
    async def failed(_request: Request, error: PairError) -> JSONResponse:
        return JSONResponse(
            ErrorResponse(
                error=ErrorDetail(
                    code=error.code,
                    message="문서를 불러올 수 없습니다. 상태를 확인하고 다시 시도하세요.",
                )
            ).model_dump(),
            status_code=pair_error_status(error.code),
        )

    @app.exception_handler(SemanticError)
    async def semantic_failed(_request: Request, error: SemanticError) -> JSONResponse:
        return JSONResponse(
            ErrorResponse(
                error=ErrorDetail(code=error.code, message="AI 요청을 확인하세요.")
            ).model_dump(),
            status_code=error.status,
        )

    @router.post("")
    def prepare(
        project_name: Annotated[str, Form(min_length=1, max_length=120)],
        guide: Annotated[UploadFile, File()],
        report: Annotated[UploadFile, File()],
    ) -> PairEnvelope[SessionView]:
        if not project_name.strip():
            raise PairError(PairErrorCode.INVALID)
        if not admission.acquire(blocking=False):
            raise PairError(PairErrorCode.BUSY)
        try:
            first, second = run_preparation(
                DocumentInput(
                    guide.filename or "guide",
                    guide.file.read(10 * 1024 * 1024 + 1),
                    DocumentRole.GUIDE,
                ),
                DocumentInput(
                    report.filename or "report",
                    report.file.read(10 * 1024 * 1024 + 1),
                    DocumentRole.REPORT,
                ),
                runtime,
            )
            if not (first.available or second.available):
                raise PairError(PairErrorCode.FAILED)
            session = store.create(project_name.strip(), first, second)
            return PairEnvelope(data=session.view(include_token=True))
        finally:
            admission.release()

    install_ollama_routes(router, store)
    ai_quota = ResultRateLimit(router, ResultRatePolicy(requests=10))
    install_cloud_routes(router, store, ai_quota, credentials)
    install_semantic_routes(router, store, ai_quota, credentials)
    install_session_routes(router, runtime, store)
    install_expression_routes(router, store)
    app.include_router(router)
    install_library(app, store, runtime, library_path)
    static = Path(__file__).parent / "static/prepare"
    app.mount("/prepare-assets", StaticFiles(directory=static, check_dir=False))

    @app.get("/prepare", include_in_schema=False)
    def prepare_page() -> Response:
        return Response((static / "index.html").read_bytes(), media_type="text/html")


def install_session_routes(router: APIRouter, runtime: PairRuntime, store: PairStore) -> None:
    @router.get("/{session_id}")
    def detail(session_id: str, token: Token = "") -> PairEnvelope[SessionView]:
        with store.lease(session_id, token) as session:
            return PairEnvelope(data=session.view())

    @router.delete("/{session_id}")
    def delete(session_id: str, token: Token = "") -> PairEnvelope[Deleted]:
        store.delete(session_id, token)
        return PairEnvelope(data=Deleted())

    @router.get("/{session_id}/{role}/pdf")
    def pdf(session_id: str, role: DocumentRole, token: Token = "") -> Response:
        with store.lease(session_id, token) as session:
            return Response(validated_pdf(session.role(role)), media_type="application/pdf")

    @router.get("/{session_id}/{role}/pages/{page}.png")
    def page_image(session_id: str, role: DocumentRole, page: int, token: Token = "") -> Response:
        with store.lease(session_id, token) as session:
            key = f"{role}/{page}"
            cached = next((data for name, data in session.images if name == key), None)
            if cached is None:
                cached = render_page(session.role(role), page, runtime.pdftoppm)
                store.cache(session_id, token, key, cached)
            return Response(cached, media_type="image/png")

    @router.post("/{session_id}/{role}/evidence")
    def map_selection(
        session_id: str,
        role: DocumentRole,
        selection: EvidenceSelection,
        token: Token = "",
    ) -> PairEnvelope[BoundEvidenceMapping]:
        with store.lease(session_id, token) as session:
            try:
                return PairEnvelope(data=evidence(session.role(role), selection))
            except (EvidenceError, ContractError, ValidationError):
                raise PairError(PairErrorCode.INVALID) from None
