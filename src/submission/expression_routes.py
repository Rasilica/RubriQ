from typing import Annotated

from fastapi import APIRouter, Header
from fastapi.responses import JSONResponse

from submission.expression_contracts import ExpressionResult
from submission.expression_engine import check_expression
from submission.models import DocumentRole, ErrorDetail, ErrorResponse
from submission.pair_contracts import EvidenceSelection, PairEnvelope
from submission.pair_store import PairStore


def install_expression_routes(router: APIRouter, store: PairStore) -> None:
    @router.post(
        "/{session_id}/{role}/expression-check", response_model=PairEnvelope[ExpressionResult]
    )
    def expression_check(
        session_id: str,
        role: DocumentRole,
        selection: EvidenceSelection,
        token: Annotated[str, Header(alias="X-Session-Token", max_length=128)] = "",
        client: Annotated[str, Header(alias="X-Local-Client", max_length=64)] = "",
    ) -> PairEnvelope[ExpressionResult] | JSONResponse:
        if client != "prepare":
            return JSONResponse(
                ErrorResponse(
                    error=ErrorDetail(
                        code="expression_forbidden", message="로컬 문서 화면에서 다시 시도하세요."
                    )
                ).model_dump(),
                status_code=403,
            )
        with store.lease(session_id, token) as session:
            return PairEnvelope(data=check_expression(session.role(role), selection))
