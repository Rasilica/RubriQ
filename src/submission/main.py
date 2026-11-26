import os
from collections.abc import Awaitable, Callable
from pathlib import Path
from threading import Lock
from typing import Annotated, Final

from fastapi import FastAPI, File, Form, Request, UploadFile, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from starlette.exceptions import HTTPException
from starlette.middleware.trustedhost import TrustedHostMiddleware

from submission.credential_middleware import CredentialMiddleware
from submission.credential_routes import install_credentials
from submission.credentials import CredentialStore, KeyringStore
from submission.extraction import DEFAULT_LIMITS, extract_pdf
from submission.guard import MULTIPART_ALLOWANCE, UploadGuard
from submission.landing_routes import install_landing
from submission.models import (
    DocumentRole,
    ErrorDetail,
    ErrorResponse,
    HealthResponse,
    PairResponse,
    PdfInput,
    PdfLimits,
    PreparedPair,
    UploadError,
)
from submission.pair_contracts import PairRuntime
from submission.pair_routes import install_pairs, load_runtime
from submission.result_routes import install_results
from submission.review_routes import install_review

FRAME_POLICY: Final = "frame-ancestors 'none'"
PAGE_POLICY: Final = (
    "default-src 'self'; img-src 'self' blob: data:; object-src 'none'; "
    f"base-uri 'none'; form-action 'self'; {FRAME_POLICY}"
)


def create_app(
    limits: PdfLimits = DEFAULT_LIMITS,
    *,
    pair_runtime: PairRuntime | None = None,
    library_path: Path | None = None,
    credential_store: CredentialStore | None = None,
    demo: bool | None = None,
) -> FastAPI:
    app = FastAPI(
        title="RubriQ · 문서 준비",
        version="0.1.0",
        description=(
            "안내문·보고서 PDF 한 쌍을 업로드해 페이지별 텍스트를 확인합니다. "
            "AI가 제안한 안내문 요구사항을 사용자가 확인·확정한 뒤 보고서를 검사할 수 있습니다. "
            "준비 결과는 명시적으로 로컬 보관할 수 있습니다. "
            "선택한 원문 구간의 한국어 표현은 일부 규칙으로 로컬 점검할 수 있습니다. "
            "설치된 로컬 Ollama 모델에 선택 문구의 윤문 제안을 요청할 수 있습니다. "
            "사용자 API 키와 전송 동의로 Gemini·OpenAI·Anthropic·빌링AI를 호출할 수 있습니다. "
            f"파일당 {limits.max_bytes} bytes, {limits.max_pages}페이지까지 지원합니다. "
            "페이지 번호는 파일상 1부터 시작하며, 텍스트가 없는 페이지는 확인이 필요합니다."
            " complete는 모든 페이지의 텍스트 반환과 파서 경고 부재를 뜻하며, "
            "글자·표·읽기 순서의 정확성을 보장하는 값이 아닙니다."
        ),
    )
    app.add_middleware(UploadGuard, max_body_bytes=2 * limits.max_bytes + MULTIPART_ALLOWANCE)
    app.add_middleware(
        TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "testserver"]
    )

    @app.middleware("http")
    async def security_headers(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        response = await call_next(request)
        # Swagger UI loads its assets from a CDN, so docs only forbid framing.
        docs = request.url.path.startswith(("/docs", "/redoc"))
        response.headers["Content-Security-Policy"] = FRAME_POLICY if docs else PAGE_POLICY
        response.headers["X-Frame-Options"] = "DENY"
        return response

    @app.exception_handler(HTTPException)
    async def http_error_handler(_request: Request, error: HTTPException) -> JSONResponse:
        code = (
            "body_too_large"
            if error.status_code == status.HTTP_413_CONTENT_TOO_LARGE
            else "http_error"
        )
        message = (
            "전체 업로드 크기 한도를 초과했습니다."
            if error.status_code == status.HTTP_413_CONTENT_TOO_LARGE
            else "요청을 처리할 수 없습니다."
        )
        return JSONResponse(
            ErrorResponse(error=ErrorDetail(code=code, message=message)).model_dump(),
            status_code=error.status_code,
        )

    @app.exception_handler(UploadError)
    async def upload_error_handler(_request: Request, error: UploadError) -> JSONResponse:
        return JSONResponse(
            ErrorResponse(
                error=ErrorDetail(code=error.code, message=error.message, role=error.role)
            ).model_dump(),
            status_code=error.status_code,
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(
        _request: Request, _error: RequestValidationError
    ) -> JSONResponse:
        return JSONResponse(
            ErrorResponse(
                error=ErrorDetail(
                    code="invalid_request", message="프로젝트명과 PDF 두 개를 확인하세요."
                )
            ).model_dump(),
            status_code=422,
        )

    @app.get("/health")
    def health() -> HealthResponse:
        return HealthResponse()

    extraction = Lock()

    @app.post("/api/documents/extract", response_model=PairResponse)
    def prepare_pair(
        project_name: Annotated[str, Form(min_length=1, max_length=120)],
        guide: Annotated[UploadFile, File(description="텍스트 안내문 PDF")],
        report: Annotated[UploadFile, File(description="텍스트 보고서 PDF")],
    ) -> PairResponse:
        if not project_name.strip():
            raise UploadError("invalid_project_name", "프로젝트명을 입력하세요.")
        if not extraction.acquire(blocking=False):
            raise UploadError(
                "extraction_busy", "다른 문서를 읽는 중입니다. 잠시 후 다시 시도하세요."
            )
        try:
            return extract_pair(project_name.strip(), guide, report)
        finally:
            extraction.release()

    def extract_pair(project_name: str, guide: UploadFile, report: UploadFile) -> PairResponse:
        guide_document = extract_pdf(
            PdfInput(
                guide.filename or "guide.pdf",
                guide.file.read(limits.max_bytes + 1),
                DocumentRole.GUIDE,
            ),
            limits,
        )
        report_document = extract_pdf(
            PdfInput(
                report.filename or "report.pdf",
                report.file.read(limits.max_bytes + 1),
                DocumentRole.REPORT,
            ),
            limits,
        )
        return PairResponse(
            data=PreparedPair(
                project_name=project_name,
                guide=guide_document,
                report=report_document,
            )
        )

    credentials = credential_store if credential_store is not None else KeyringStore()
    app.add_middleware(CredentialMiddleware)
    install_credentials(app, credentials)
    install_landing(app)
    install_review(app)
    install_results(app)
    install_pairs(
        app,
        pair_runtime if pair_runtime is not None else load_runtime(),
        library_path,
        credentials,
        demo=os.environ.get("RUBRIQ_MODE") == "demo" if demo is None else demo,
    )
    return app


app = create_app()
