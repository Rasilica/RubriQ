from unittest.mock import patch

import pytest
from pydantic import SecretStr
from test_cloud_routes import prepared as cloud_prepared
from test_semantic_routes import check, confirm, extract, provider_response
from test_semantic_routes import setup as semantic_setup

from submission.cloud_contracts import Completion

prepared = cloud_prepared
setup = semantic_setup


def test_saved_rewrite_uses_vault_without_echo(prepared):
    client, data, headers, _, payload = prepared
    headers = {k: v for k, v in headers.items() if k != "X-AI-API-Key"}
    with (
        patch("submission.credentials.KeyringStore.get", return_value=SecretStr("saved-secret")),
        patch(
            "submission.cloud_routes.rewrite", return_value=Completion(suggestion="Revised")
        ) as call,
    ):
        response = client.post(
            f"/api/document-pairs/{data['session_id']}/report/cloud-rewrite",
            headers=headers,
            json={**payload, "use_saved_key": True},
        )
    assert response.status_code == 200
    assert call.call_args.args[3].get_secret_value() == "saved-secret"
    assert "saved-secret" not in response.text


@pytest.mark.parametrize("change", ["auth", "consent", "strict", "manual", "disabled"])
def test_rewrite_reads_vault_only_when_authorized_and_selected(prepared, change):
    client, data, headers, _, payload = prepared
    headers = {**headers, "X-AI-API-Key": ""}
    payload = {**payload, "use_saved_key": True}
    if change == "auth":
        headers = {**headers, "X-Session-Token": "wrong"}
    if change == "consent":
        payload = {**payload, "consent": False}
    if change == "strict":
        payload = {**payload, "use_saved_key": "true"}
    if change == "disabled":
        payload = {**payload, "use_saved_key": False}
    if change == "manual":
        headers = {**headers, "X-AI-API-Key": "manual-secret"}
    with (
        patch("submission.credentials.KeyringStore.get") as read,
        patch(
            "submission.cloud_routes.rewrite", return_value=Completion(suggestion="Revised")
        ) as call,
    ):
        response = client.post(
            f"/api/document-pairs/{data['session_id']}/report/cloud-rewrite",
            headers=headers,
            json=payload,
        )
    read.assert_not_called()
    if change == "manual":
        assert response.status_code == 200
        assert call.call_args.args[3].get_secret_value() == "manual-secret"
    else:
        assert response.status_code in {404, 422}
        call.assert_not_called()


def test_saved_semantic_requirements_and_check(setup):
    client, store, session, headers, now = setup
    saved_setup = client, store, session, {**headers, "X-AI-API-Key": ""}, now
    with (
        patch(
            "submission.credentials.KeyringStore.get", return_value=SecretStr("saved-secret")
        ) as read,
        patch("submission.semantic_service.complete", side_effect=provider_response) as call,
    ):
        draft_response = extract(saved_setup, use_saved_key=True)
        assert draft_response.status_code == 200
        confirmed = confirm(saved_setup, draft_response.json()["data"]).json()["data"]
        response = check(saved_setup, confirmed, use_saved_key=True)
    assert response.status_code == 200
    assert read.call_count == 2
    assert all(c.args[3].get_secret_value() == "saved-secret" for c in call.call_args_list)
    assert "saved-secret" not in response.text + draft_response.text


@pytest.mark.parametrize("change", ["auth", "consent", "strict", "manual"])
def test_semantic_vault_reads_follow_auth_consent_selection(setup, change):
    client, store, session, headers, now = setup
    headers = {**headers, "X-AI-API-Key": ""}
    payload = {"use_saved_key": True}
    if change == "auth":
        headers = {**headers, "X-Session-Token": "wrong"}
    if change == "consent":
        payload = {**payload, "consent": False}
    if change == "strict":
        payload = {**payload, "use_saved_key": "true"}
    if change == "manual":
        headers = {**headers, "X-AI-API-Key": "manual-secret"}
    with (
        patch("submission.credentials.KeyringStore.get") as read,
        patch("submission.semantic_service.complete", side_effect=provider_response) as call,
    ):
        response = extract((client, store, session, headers, now), **payload)
    read.assert_not_called()
    if change == "manual":
        assert response.status_code == 200
        assert call.call_args.args[3].get_secret_value() == "manual-secret"
    else:
        assert response.status_code in {404, 422}
        call.assert_not_called()
