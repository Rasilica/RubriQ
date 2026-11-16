"""OS credentials only: no automatic backend discovery or plaintext fallback."""

import sys
from typing import Final, Protocol, final, runtime_checkable

from keyring.backend import KeyringBackend
from keyring.errors import KeyringError
from pydantic import ConfigDict, SecretStr, TypeAdapter

from submission.cloud_contracts import CloudCode, CloudError, Provider

MAX_KEY_LENGTH: Final = 512
MIN_KEY_CHAR: Final = 33
MAX_KEY_CHAR: Final = 126


class CredentialUnavailableError(Exception):
    """The OS vault is unsupported, locked, or rejected an operation."""


class CredentialStore(Protocol):
    @property
    def backend(self) -> str: ...

    def get(self, provider: Provider) -> SecretStr | None: ...

    def set(self, provider: Provider, key: SecretStr) -> None: ...

    def delete(self, provider: Provider) -> None: ...


@runtime_checkable
class NativeBackend(Protocol):
    def get_password(self, service: str, username: str) -> str | None: ...

    def set_password(self, service: str, username: str, password: str) -> None: ...

    def delete_password(self, service: str, username: str) -> None: ...


def supported(backend: KeyringBackend) -> NativeBackend:
    if backend.priority <= 0:
        raise CredentialUnavailableError
    return TypeAdapter(
        NativeBackend, config=ConfigDict(arbitrary_types_allowed=True)
    ).validate_python(backend)


def native_backend() -> NativeBackend:
    # Explicit builtins bypass keyring's plugin/config discovery. Bypass the base
    # initializer too: it permits arbitrary KEYRING_PROPERTY_* attribute overrides.
    if sys.platform == "darwin":
        from keyring.backends.macOS import Keyring  # noqa: PLC0415

        backend = Keyring.__new__(Keyring)
        backend.keychain = None
        return supported(backend)
    if sys.platform == "win32":
        from keyring.backends.Windows import WinVaultKeyring  # noqa: PLC0415

        return supported(WinVaultKeyring.__new__(WinVaultKeyring))
    if sys.platform.startswith("linux"):
        from keyring.backends.SecretService import Keyring  # noqa: PLC0415

        return supported(Keyring.__new__(Keyring))
    raise CredentialUnavailableError


@final
class KeyringStore:
    def __init__(self, service: str = "org.rubriq.api-keys") -> None:
        self.service = service

    @property
    def backend(self) -> str:
        return {
            "darwin": "macOS Keychain",
            "win32": "Windows Credential Manager",
            "linux": "Secret Service",
        }.get(sys.platform, "unavailable")

    def get(self, provider: Provider) -> SecretStr | None:
        try:
            value = native_backend().get_password(self.service, provider.value)
        except (KeyringError, ImportError, RuntimeError, OSError):
            raise CredentialUnavailableError from None
        return SecretStr(value) if value else None

    def set(self, provider: Provider, key: SecretStr) -> None:
        _ = validate_key(key)
        try:
            native_backend().set_password(self.service, provider.value, key.get_secret_value())
        except (KeyringError, ImportError, RuntimeError, OSError):
            raise CredentialUnavailableError from None

    def delete(self, provider: Provider) -> None:
        try:
            backend = native_backend()
            if backend.get_password(self.service, provider.value) is not None:
                backend.delete_password(self.service, provider.value)
        except (KeyringError, ImportError, RuntimeError, OSError):
            raise CredentialUnavailableError from None


def validate_key(key: SecretStr) -> SecretStr:
    value = key.get_secret_value()
    if not 1 <= len(value) <= MAX_KEY_LENGTH or any(
        not MIN_KEY_CHAR <= ord(char) <= MAX_KEY_CHAR for char in value
    ):
        raise CloudError(CloudCode.KEY_INVALID, 422)
    return key


def resolve_key(
    provider: Provider, manual: SecretStr, *, use_saved: bool, store: CredentialStore
) -> SecretStr:
    if manual.get_secret_value() or not use_saved:
        return validate_key(manual)
    try:
        saved = store.get(provider)
    except CredentialUnavailableError:
        raise CloudError(CloudCode.UNAVAILABLE) from None
    return validate_key(saved or SecretStr(""))
