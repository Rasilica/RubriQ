from hashlib import sha256
from typing import Annotated, Final

from fastapi import APIRouter, Header, Query
from fastapi.responses import JSONResponse

from submission.models import DocumentRole, ErrorDetail, ErrorResponse
from submission.ollama_client import list_models, rewrite
from submission.ollama_contracts import (
    OllamaCode,
    OllamaError,
    OllamaModels,
    RewriteRequest,
    RewriteResult,
)
from submission.pair_contracts import PairEnvelope, PairError, PairErrorCode, PreparedRole
from submission.pair_store import PairStore

MAX_SELECTION: Final = 4000

type Token = Annotated[str, Header(alias="X-Session-Token", max_length=128)]
type Client = Annotated[str, Header(alias="X-Local-Client", max_length=64)]


def failure(error: OllamaError) -> JSONResponse:
    return JSONResponse(
        ErrorResponse(
            error=ErrorDetail(
                code=error.code,
                message="로컬 Ollama와 설치된 모델을 확인한 뒤 다시 시도하세요.",
            )
        ).model_dump(),
        status_code=error.status,
    )


def selected_rewrite(role: PreparedRole, selection: RewriteRequest) -> RewriteResult:
    document = role.view.document
    if document is None or sha256(role.original).hexdigest() != document.source.content_sha256:
        raise PairError(PairErrorCode.UNAVAILABLE)
    block = next((item for item in document.blocks if item.block_id == selection.block_id), None)
    if (
        block is None
        or not 0 <= selection.start < selection.end <= len(block.raw_text)
        or selection.end - selection.start > MAX_SELECTION
    ):
        raise PairError(PairErrorCode.INVALID)
    if block.source_locator.source_sha256 != document.source.content_sha256:
        raise PairError(PairErrorCode.UNAVAILABLE)
    original = block.raw_text[selection.start : selection.end]
    return RewriteResult(
        model=selection.model,
        source_sha256=document.source.content_sha256,
        block_id=selection.block_id,
        start=selection.start,
        end=selection.end,
        original=original,
        suggestion=rewrite(selection.model, original),
    )


def install_ollama_routes(router: APIRouter, store: PairStore) -> None:
    @router.get("/ollama/models", response_model=PairEnvelope[OllamaModels])
    def models(
        session_id: Annotated[str, Query(min_length=1, max_length=128)],
        token: Token = "",
        client: Client = "",
    ) -> PairEnvelope[OllamaModels] | JSONResponse:
        if client != "prepare":
            return failure(OllamaError(OllamaCode.FORBIDDEN, 403))
        with store.lease(session_id, token):
            try:
                return PairEnvelope(data=list_models())
            except OllamaError as error:
                return failure(error)

    @router.post("/{session_id}/{role}/ollama-rewrite", response_model=PairEnvelope[RewriteResult])
    def suggest(
        session_id: str,
        role: DocumentRole,
        selection: RewriteRequest,
        token: Token = "",
        client: Client = "",
    ) -> PairEnvelope[RewriteResult] | JSONResponse:
        if client != "prepare":
            return failure(OllamaError(OllamaCode.FORBIDDEN, 403))
        with store.lease(session_id, token) as session:
            try:
                return PairEnvelope(data=selected_rewrite(session.role(role), selection))
            except OllamaError as error:
                return failure(error)
