from pathlib import Path
from typing import Final, assert_never, override

from fastapi import APIRouter, FastAPI, Request, Response
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError
from starlette.types import Scope

from submission.document_contracts import ContractError
from submission.evidence_contracts import EvidenceError
from submission.input_contracts import InputValidationError
from submission.models import DocumentRole, ErrorDetail, ErrorResponse, UploadError
from submission.page_rule_contracts import PageRuleError
from submission.requirement_contracts import RequirementError
from submission.result_assets import bounded_read, load_raster, report_document_id
from submission.result_contracts import (
    CaseCatalog,
    ResultCase,
    ResultDetail,
    ResultError,
    ResultErrorCode,
    ResultResponse,
)
from submission.result_demo import build_result_demo, case_summary
from submission.result_rate_limit import ResultRateLimit
from submission.review_contracts import ReviewError

HEADERS: Final = {"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"}
MAX_PAGE_NUMBER: Final = 50
MAX_PAGE_DIGITS: Final = 2


class ResultStaticFiles(StaticFiles):
    @override
    async def get_response(self, path: str, scope: Scope) -> Response:
        response = await super().get_response(path, scope)
        response.headers.update(HEADERS)
        return response


def parse_case(value: str) -> ResultCase:
    try:
        return ResultCase(value)
    except ValueError:
        raise ResultError(ResultErrorCode.NOT_FOUND) from None


def document_id(case: str, role: str) -> str:
    parsed_case = parse_case(case)
    try:
        parsed_role = DocumentRole(role)
    except ValueError:
        raise ResultError(ResultErrorCode.NOT_FOUND) from None
    match parsed_role:
        case DocumentRole.GUIDE:
            return "guide"
        case DocumentRole.REPORT:
            if parsed_case in (ResultCase.DOCX_STRUCTURE, ResultCase.HWPX_STRUCTURE):
                raise ResultError(ResultErrorCode.NOT_FOUND)
            return report_document_id(parsed_case)
        case _:
            assert_never(parsed_role)


def page_index(number: str) -> int:
    if not number.isascii() or not number.isdecimal() or len(number) > MAX_PAGE_DIGITS:
        raise ResultError(ResultErrorCode.NOT_FOUND)
    index = int(number)
    if index < 1 or index > MAX_PAGE_NUMBER:
        raise ResultError(ResultErrorCode.NOT_FOUND)
    return index


def error_status(code: ResultErrorCode) -> int:
    match code:
        case ResultErrorCode.NOT_FOUND:
            return 404
        case ResultErrorCode.UNAVAILABLE:
            return 503
        case _:
            assert_never(code)


def install_results(app: FastAPI) -> None:
    app.add_middleware(ResultRateLimit)
    router = APIRouter(prefix="/api/result-demos")

    @app.exception_handler(ResultError)
    async def result_error(_request: Request, error: ResultError) -> JSONResponse:
        return JSONResponse(
            ErrorResponse(
                error=ErrorDetail(code=error.code, message="고정 결과 예시를 불러올 수 없습니다.")
            ).model_dump(),
            status_code=error_status(error.code),
            headers=HEADERS,
        )

    @router.get("")
    def catalog(response: Response) -> ResultResponse[CaseCatalog]:
        response.headers.update(HEADERS)
        return ResultResponse(
            data=CaseCatalog(cases=tuple(case_summary(case) for case in ResultCase))
        )

    @router.get("/{case_id}")
    def detail(case_id: str, response: Response) -> ResultResponse[ResultDetail]:
        response.headers.update(HEADERS)
        case = parse_case(case_id)
        try:
            return ResultResponse(data=build_result_demo(case))
        except (
            OSError,
            InputValidationError,
            EvidenceError,
            UnicodeError,
            ValidationError,
            ContractError,
            UploadError,
            RequirementError,
            ReviewError,
            PageRuleError,
        ):
            raise ResultError(ResultErrorCode.UNAVAILABLE) from None

    @router.get("/{case_id}/documents/{role}/original.pdf")
    def original(case_id: str, role: str) -> Response:
        raster = load_raster(document_id(case_id, role))
        return Response(raster.pdf_bytes, media_type="application/pdf", headers=HEADERS)

    @router.get("/{case_id}/documents/{role}/pages/{number}.png")
    def page(case_id: str, role: str, number: str) -> Response:
        identifier = document_id(case_id, role)
        index = page_index(number)
        raster = load_raster(identifier)
        if index > len(raster.images):
            raise ResultError(ResultErrorCode.NOT_FOUND)
        return Response(raster.images[index - 1], media_type="image/png", headers=HEADERS)

    app.include_router(router)
    static = Path(__file__).parent / "static/results"
    app.mount(
        "/result-assets", ResultStaticFiles(directory=static, check_dir=False), name="result-assets"
    )

    @app.get("/results", include_in_schema=False)
    def result_page() -> Response:
        return Response(
            bounded_read(static / "index.html"), media_type="text/html", headers=HEADERS
        )
