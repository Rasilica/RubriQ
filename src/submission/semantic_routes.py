from collections.abc import Callable
from time import monotonic
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from pydantic import SecretStr, ValidationError

from submission import semantic_diagnostics as diagnostics
from submission.cloud_contracts import CloudError
from submission.cloud_routes import ApiKey
from submission.credentials import CredentialStore, KeyringStore
from submission.models import ErrorDetail, ErrorResponse
from submission.ollama_contracts import OllamaError
from submission.ollama_routes import Client, Token
from submission.pair_contracts import PairEnvelope
from submission.pair_store import PairStore
from submission.report_check_contracts import ReportCheckError
from submission.requirement_contracts import RequirementError
from submission.result_rate_limit import ResultRateLimit, ResultRatePolicy
from submission.review_contracts import ReviewError
from submission.semantic_contracts import (
    CheckRequest,
    CheckView,
    CriteriaRequest,
    DraftView,
    RequirementsRequest,
    SemanticCode,
    SemanticError,
)
from submission.semantic_service import Credentials, SemanticService


def credentials(token: Token = "", client: Client = "", api_key: ApiKey = "") -> Credentials:
    if client != "prepare":
        raise SemanticError(SemanticCode.FORBIDDEN, 403)
    return Credentials(token=token, key=SecretStr(api_key))


def invoke[T](action: Callable[[], T]) -> PairEnvelope[T] | JSONResponse:
    with diagnostics.scope():
        return _invoke(action)


def _invoke[T](action: Callable[[], T]) -> PairEnvelope[T] | JSONResponse:
    started = monotonic()
    include_diagnostic = False
    try:
        return PairEnvelope(data=action())
    except (CloudError, OllamaError) as error:
        code, status = str(error.code), error.status
        include_diagnostic = True
    except SemanticError as error:
        code, status = str(error.code), error.status
    except ReviewError as error:
        code, status = str(error.code), error.status_code
    except (RequirementError, ReportCheckError) as error:
        diagnostics.contract_failure(error.code)
        code, status = "ai_" + str(error.code), 422
        include_diagnostic = True
    except ValidationError:
        code, status = "ai_invalid_response", 502
        include_diagnostic = True
        diagnostics.mark("result_build", "result_invalid")
    body = ErrorResponse(
        error=ErrorDetail(
            code=code,
            message="AI 검토를 완료하지 못했습니다. 문서·기준·모델 상태를 확인하세요.",
        )
    ).model_dump()
    diagnostic = diagnostics.failure(status, started) if include_diagnostic else None
    if diagnostic is not None:
        body["error"]["diagnostic"] = diagnostic.model_dump()
    return JSONResponse(body, status_code=status)


def install_semantic_routes(
    router: APIRouter,
    store: PairStore,
    quota: ResultRateLimit | None = None,
    credential_store: CredentialStore | None = None,
) -> None:
    service = SemanticService(
        store,
        quota or ResultRateLimit(router, ResultRatePolicy(requests=10)),
        credential_store if credential_store is not None else KeyringStore(),
    )

    @router.post("/{session_id}/ai/requirements", response_model=PairEnvelope[DraftView])
    def requirements(
        session_id: str,
        request: RequirementsRequest,
        auth: Annotated[Credentials, Depends(credentials)],
    ) -> PairEnvelope[DraftView] | JSONResponse:
        return invoke(lambda: service.requirements(session_id, request, auth))

    @router.post("/{session_id}/ai/criteria", response_model=PairEnvelope[DraftView])
    def criteria(
        session_id: str,
        request: CriteriaRequest,
        auth: Annotated[Credentials, Depends(credentials)],
    ) -> PairEnvelope[DraftView] | JSONResponse:
        return invoke(lambda: service.criteria(session_id, request, auth))

    @router.get("/{session_id}/ai/criteria", response_model=PairEnvelope[DraftView])
    def current_criteria(
        session_id: str,
        draft_id: Annotated[str, Query(min_length=1, max_length=128)],
        auth: Annotated[Credentials, Depends(credentials)],
    ) -> PairEnvelope[DraftView] | JSONResponse:
        return invoke(lambda: service.current_criteria(session_id, draft_id, auth))

    @router.post("/{session_id}/ai/check", response_model=PairEnvelope[CheckView])
    def check(
        session_id: str,
        request: CheckRequest,
        auth: Annotated[Credentials, Depends(credentials)],
    ) -> PairEnvelope[CheckView] | JSONResponse:
        return invoke(lambda: service.check(session_id, request, auth))
