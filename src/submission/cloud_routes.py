from hashlib import sha256
from typing import Annotated

from fastapi import APIRouter, Header
from fastapi.responses import JSONResponse
from pydantic import SecretStr

from submission.cloud_client import rewrite
from submission.cloud_contracts import CloudCode, CloudError, CloudRequest, CloudResult
from submission.credentials import CredentialStore, KeyringStore, resolve_key
from submission.models import DocumentRole, ErrorDetail, ErrorResponse
from submission.ollama_routes import MAX_SELECTION, Client, Token
from submission.pair_contracts import PairEnvelope, PairError, PairErrorCode, PreparedRole
from submission.pair_store import PairStore
from submission.result_rate_limit import ResultRateLimit, ResultRatePolicy

type ApiKey = Annotated[str, Header(alias="X-AI-API-Key")]


def selected_rewrite(
    role: PreparedRole, selection: CloudRequest, key: SecretStr, quota: ResultRateLimit
) -> CloudResult:
    document = role.view.document
    if document is None or sha256(role.original).hexdigest() != document.source.content_sha256:
        raise PairError(PairErrorCode.UNAVAILABLE)
    if selection.source_sha256 != document.source.content_sha256:
        raise PairError(PairErrorCode.INVALID)
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
    if quota.retry_after():
        raise CloudError(CloudCode.RATE_LIMITED, 429)
    completion = rewrite(selection.provider, selection.model, original, key)
    return CloudResult(
        provider=selection.provider,
        model=selection.model,
        source_sha256=selection.source_sha256,
        block_id=selection.block_id,
        start=selection.start,
        end=selection.end,
        original=original,
        suggestion=completion.suggestion,
        usage=completion.usage,
    )


def install_cloud_routes(
    router: APIRouter,
    store: PairStore,
    quota: ResultRateLimit | None = None,
    credentials: CredentialStore | None = None,
) -> None:
    credentials = credentials if credentials is not None else KeyringStore()
    quota = quota or ResultRateLimit(router, ResultRatePolicy(requests=10))

    @router.post("/{session_id}/{role}/cloud-rewrite", response_model=PairEnvelope[CloudResult])
    def suggest(  # noqa: PLR0913
        session_id: str,
        role: DocumentRole,
        selection: CloudRequest,
        *,
        token: Token = "",
        client: Client = "",
        api_key: ApiKey = "",
    ) -> PairEnvelope[CloudResult] | JSONResponse:
        try:
            if client != "prepare":
                raise CloudError(CloudCode.FORBIDDEN, 403)  # noqa: TRY301
            with store.lease(session_id, token) as session:
                if not selection.consent:
                    raise CloudError(CloudCode.CONSENT_REQUIRED, 422)  # noqa: TRY301
                key = resolve_key(
                    selection.provider,
                    SecretStr(api_key),
                    use_saved=selection.use_saved_key,
                    store=credentials,
                )
                return PairEnvelope(
                    data=selected_rewrite(session.role(role), selection, key, quota)
                )
        except CloudError as error:
            return JSONResponse(
                ErrorResponse(
                    error=ErrorDetail(
                        code=error.code,
                        message=(
                            "클라우드 요청을 완료하지 못했습니다. 키·모델·연결 상태를 확인하세요."
                        ),
                    )
                ).model_dump(),
                status_code=error.status,
            )
