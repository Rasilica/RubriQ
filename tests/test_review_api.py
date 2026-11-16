from copy import deepcopy

import pytest
from fastapi.testclient import TestClient

from submission.main import create_app


def session(client):
    response = client.post("/api/review-sessions", json={}, headers={"X-Review-Request": "1"})
    assert response.status_code == 201
    data = response.json()["data"]
    headers = {"X-Review-Request": "1", "X-Review-Token": data["session_token"]}
    return data, headers, "/api/review-sessions/" + data["session_id"]


def editable(data):
    return [
        {key: value for key, value in item.items() if key != "edited_fields"}
        for item in data["items"]
    ]


@pytest.mark.parametrize("status", ["applies", "does_not_apply"])
def test_conditional_decision_requires_reason(status):
    with TestClient(create_app()) as client:
        data, headers, url = session(client)
        items = editable(data)
        items[3]["application_status"] = status
        response = client.put(
            url + "/working-copy", json={"expected_revision": 0, "items": items}, headers=headers
        )
        assert response.status_code == 422


def test_review_save_confirm_preserves_provenance_and_versions():
    with TestClient(create_app()) as client:
        data, headers, url = session(client)
        assert (
            client.post(
                url + "/confirm", json={"expected_revision": 0}, headers=headers
            ).status_code
            == 422
        )
        items = editable(data)
        items[0]["title"] = "수정된 제목"
        items[3]["application_status"] = "does_not_apply"
        items[3]["application_reason"] = "개인정보를 사용하지 않음"
        response = client.put(
            url + "/working-copy", json={"expected_revision": 0, "items": items}, headers=headers
        )
        assert response.status_code == 200
        saved = response.json()["data"]
        assert saved["revision"] == 1
        assert saved["original_draft"] == data["original_draft"]
        assert saved["items"][0]["edited_fields"] == ["title"]
        confirmed = client.post(
            url + "/confirm", json={"expected_revision": 1}, headers=headers
        ).json()["data"]
        assert len(confirmed["versions"]) == 1
        assert confirmed["confirmed_revision"] == 1
        assert (
            client.post(url + "/confirm", json={"expected_revision": 1}, headers=headers).json()[
                "data"
            ]
            == confirmed
        )
        items[0]["title"] = "또 수정"
        edited = client.put(
            url + "/working-copy", json={"expected_revision": 1, "items": items}, headers=headers
        ).json()["data"]
        assert edited["confirmed_revision"] is None
        assert edited["versions"] == confirmed["versions"]
        assert (
            client.put(
                url + "/working-copy",
                json={"expected_revision": 1, "items": items},
                headers=headers,
            ).status_code
            == 409
        )


def test_review_input_authority_and_token_boundaries():
    with TestClient(create_app()) as client:
        data, headers, url = session(client)
        _, other_headers, _ = session(client)
        assert client.get(url, headers=other_headers).status_code == 404
        assert client.get(url).status_code == 403
        for field, value in [
            ("requirement_id", "forged"),
            ("source_id", "forged"),
            ("edited_fields", ["title"]),
        ]:
            items = deepcopy(editable(data))
            items[0][field] = value
            assert (
                client.put(
                    url + "/working-copy",
                    json={"expected_revision": 0, "items": items},
                    headers=headers,
                ).status_code
                == 422
            )
        assert client.post("/api/review-sessions", json={}).status_code == 403
        assert (
            client.post(
                "/api/review-sessions", content="{}", headers={"X-Review-Request": "1"}
            ).status_code
            == 415
        )
        assert (
            client.post(
                "/api/review-sessions",
                json={},
                headers={"X-Review-Request": "1", "Origin": "https://invalid.example"},
            ).status_code
            == 403
        )
