from typing import Annotated

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import Field, SecretStr

from submission.cloud_contracts import CloudError, Provider
from submission.credentials import CredentialStore, CredentialUnavailableError, validate_key
from submission.models import ErrorDetail, ErrorResponse, FrozenModel
from submission.pair_contracts import PairEnvelope


class KeyUpdate(FrozenModel):
    api_key: Annotated[SecretStr, Field(min_length=1, max_length=512)]


class ProviderSetting(FrozenModel):
    provider: Provider
    configured: bool


class SettingsView(FrozenModel):
    available: bool
    backend: str
    providers: tuple[ProviderSetting, ...]


def settings_error(code: str, status: int) -> JSONResponse:
    return JSONResponse(
        ErrorResponse(
            error=ErrorDetail(
                code=code,
                message="안전한 OS 키 저장소를 확인하세요. 직접 입력으로도 사용할 수 있습니다.",
            )
        ).model_dump(),
        status_code=status,
    )


def install_credentials(app: FastAPI, store: CredentialStore) -> None:
    @app.get("/api/ai-settings", response_model=PairEnvelope[SettingsView])
    def settings() -> PairEnvelope[SettingsView]:
        try:
            providers = tuple(
                ProviderSetting(provider=p, configured=store.get(p) is not None) for p in Provider
            )
        except CredentialUnavailableError:
            return PairEnvelope(
                data=SettingsView(
                    available=False,
                    backend=store.backend,
                    providers=tuple(
                        ProviderSetting(provider=p, configured=False) for p in Provider
                    ),
                )
            )
        return PairEnvelope(
            data=SettingsView(
                available=True,
                backend=store.backend,
                providers=providers,
            )
        )

    @app.put("/api/ai-settings/{provider}", response_model=PairEnvelope[ProviderSetting])
    def save(provider: Provider, update: KeyUpdate) -> PairEnvelope[ProviderSetting] | JSONResponse:
        try:
            store.set(provider, validate_key(update.api_key))
        except CredentialUnavailableError:
            return settings_error("credentials_unavailable", 503)
        except CloudError as error:
            return settings_error(error.code, error.status)
        return PairEnvelope(data=ProviderSetting(provider=provider, configured=True))

    @app.delete("/api/ai-settings/{provider}", response_model=PairEnvelope[ProviderSetting])
    def delete(provider: Provider) -> PairEnvelope[ProviderSetting] | JSONResponse:
        try:
            store.delete(provider)
        except CredentialUnavailableError:
            return settings_error("credentials_unavailable", 503)
        return PairEnvelope(data=ProviderSetting(provider=provider, configured=False))
