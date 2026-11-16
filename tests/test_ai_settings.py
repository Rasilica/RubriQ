from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from submission.cloud_contracts import Provider
from submission.credentials import CredentialStore, CredentialUnavailableError, KeyringStore
from submission.main import create_app


class MemoryCredentials:
    """Mutable in-memory credential adapter for isolated route tests."""

    backend = "test-vault"

    def __init__(self):
        self.values = {}
        self.reads = 0

    def get(self, provider):
        self.reads += 1
        return self.values.get(provider)

    def set(self, provider, key):
        self.values = {**self.values, provider: key}

    def delete(self, provider):
        self.values = {name: key for name, key in self.values.items() if name != provider}


def test_keys_persist_across_apps_without_exposing_value():
    vault: CredentialStore = MemoryCredentials()
    headers = {"X-Local-Client": "prepare"}
    with TestClient(create_app(credential_store=vault)) as first:
        response = first.put(
            "/api/ai-settings/openai", headers=headers, json={"api_key": "test-private-value"}
        )
        assert response.status_code == 200
        assert "test-private-value" not in response.text
    with TestClient(create_app(credential_store=vault)) as second:
        response = second.get("/api/ai-settings", headers=headers)
        assert response.json()["data"]["providers"][1]["configured"] is True
        assert "test-private-value" not in response.text
        assert response.headers["cache-control"] == "no-store"
        assert second.delete("/api/ai-settings/openai", headers=headers).status_code == 200
    assert vault.get(Provider.OPENAI) is None


def test_settings_reject_unauthorized_before_reading():
    vault = MemoryCredentials()
    with TestClient(create_app(credential_store=vault)) as client:
        assert vault.reads == 0
        response = client.get("/api/ai-settings")
        assert response.status_code == 403
        assert vault.reads == 0


def test_untrusted_configured_backend_is_never_loaded(monkeypatch):
    monkeypatch.setenv("PYTHON_KEYRING_BACKEND", "malicious.plugin.Keyring")
    monkeypatch.setenv("KEYRING_PROPERTY_GET_PASSWORD", "malicious")
    monkeypatch.setattr("submission.credentials.sys.platform", "darwin")
    with (
        patch("keyring.get_keyring", side_effect=AssertionError("discovery invoked")),
        patch("keyring.backends.macOS.Keyring.priority", 5),
        patch("keyring.backends.macOS.Keyring.get_password", return_value="dummy") as read,
    ):
        vault = KeyringStore(service="rubriq-unit-test")
        assert vault.get(Provider.OPENAI).get_secret_value() == "dummy"
    read.assert_called_once_with("rubriq-unit-test", "openai")


def test_memory_adapter_replace_delete():
    vault = MemoryCredentials()
    vault.set(Provider.OPENAI, SecretStr("first"))
    vault.set(Provider.OPENAI, SecretStr("second"))
    assert vault.get(Provider.OPENAI).get_secret_value() == "second"
    vault.delete(Provider.OPENAI)
    assert vault.get(Provider.OPENAI) is None


@pytest.mark.parametrize("method", ["get", "put", "delete"])
def test_unavailable_store_fails_closed(method):
    vault = MemoryCredentials()
    with (
        patch.object(vault, "get", side_effect=CredentialUnavailableError),
        patch.object(vault, "set", side_effect=CredentialUnavailableError),
        patch.object(vault, "delete", side_effect=CredentialUnavailableError),
        TestClient(create_app(credential_store=vault)) as client,
    ):
        headers = {"X-Local-Client": "prepare"}
        if method == "get":
            response = client.get("/api/ai-settings", headers=headers)
            assert response.json()["data"]["available"] is False
        elif method == "put":
            response = client.put(
                "/api/ai-settings/openai", headers=headers, json={"api_key": "dummy-private"}
            )
            assert response.status_code == 503
        else:
            response = client.delete("/api/ai-settings/openai", headers=headers)
            assert response.status_code == 503
        assert "dummy-private" not in response.text


@pytest.mark.parametrize("key", ["", "with space", "with\nnewline", "x" * 513, 123])
def test_invalid_key_never_saved_or_echoed(key):
    vault = MemoryCredentials()
    with TestClient(create_app(credential_store=vault)) as client:
        response = client.put(
            "/api/ai-settings/openai", headers={"X-Local-Client": "prepare"}, json={"api_key": key}
        )
    assert response.status_code == 422
    assert vault.values == {}
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize(
    ("headers", "body", "status"),
    [
        ({"Origin": "https://attacker.invalid"}, b"{}", 403),
        ({"Host": "attacker.invalid"}, b"{}", 400),
        ({}, b"x" * 4097, 413),
        ({}, b"{invalid", 422),
    ],
)
def test_settings_guards_prevent_writes(headers, body, status):
    vault = MemoryCredentials()
    with TestClient(create_app(credential_store=vault)) as client:
        response = client.put(
            "/api/ai-settings/openai",
            content=body,
            headers={"X-Local-Client": "prepare", **headers},
        )
    assert response.status_code == status
    assert vault.values == {}
    assert response.headers["cache-control"] == "no-store"


def test_settings_rate_limit():
    with TestClient(create_app(credential_store=MemoryCredentials())) as client:
        responses = [
            client.get("/api/ai-settings", headers={"X-Local-Client": "prepare"}) for _ in range(61)
        ]
    assert [r.status_code for r in responses] == [200] * 60 + [429]


@pytest.mark.parametrize("operation", ["get", "set", "delete"])
def test_native_failure_is_sanitized(operation):
    vault = KeyringStore(service="rubriq-unit-test")
    args = (Provider.OPENAI, SecretStr("dummy")) if operation == "set" else (Provider.OPENAI,)
    with (
        patch("submission.credentials.native_backend", side_effect=RuntimeError("secret")),
        pytest.raises(CredentialUnavailableError) as error,
    ):
        getattr(vault, operation)(*args)
    assert "secret" not in str(error.value)


def test_unsupported_platform_fails_closed(monkeypatch):
    monkeypatch.setattr("submission.credentials.sys.platform", "unknown")
    with pytest.raises(CredentialUnavailableError):
        KeyringStore().get(Provider.OPENAI)


def test_native_priority_rejects_missing_os_support(monkeypatch):
    monkeypatch.setattr("submission.credentials.sys.platform", "darwin")
    with (
        patch("keyring.backends.macOS.Keyring.priority", 0),
        patch("keyring.backends.macOS.Keyring.get_password") as read,
        pytest.raises(CredentialUnavailableError),
    ):
        KeyringStore(service="rubriq-unit-test").get(Provider.OPENAI)
    read.assert_not_called()


def test_native_adapter_set_get_delete_use_only_explicit_service(monkeypatch):
    monkeypatch.setattr("submission.credentials.sys.platform", "darwin")
    vault = KeyringStore(service="rubriq-unit-test")
    with (
        patch("keyring.backends.macOS.Keyring.priority", 5),
        patch("keyring.backends.macOS.Keyring.get_password", return_value="dummy"),
        patch("keyring.backends.macOS.Keyring.set_password") as write,
        patch("keyring.backends.macOS.Keyring.delete_password") as delete,
    ):
        vault.set(Provider.OPENAI, SecretStr("dummy"))
        vault.delete(Provider.OPENAI)
    write.assert_called_once_with("rubriq-unit-test", "openai", "dummy")
    delete.assert_called_once_with("rubriq-unit-test", "openai")
