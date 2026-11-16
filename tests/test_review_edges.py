from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from test_review_api import editable, session

from submission.main import create_app
from submission.review_contracts import ReviewError, WorkingCopyRequest
from submission.review_store import ReviewStore


def test_token_errors_and_streamed_body_are_safe():
    with TestClient(create_app()) as client:
        data, headers, url = session(client)
        for token in [b"\xff", b"x" * 10000, b""]:
            response = client.get(
                url, headers=[(b"x-review-request", b"1"), (b"x-review-token", token)]
            )
            assert response.status_code == 404
            assert data["session_token"] not in response.text
        large = client.post(
            "/api/review-sessions",
            content=iter([b" " * 131072] * 3),
            headers={"X-Review-Request": "1", "Content-Type": "application/json"},
        )
        assert large.status_code == 413
        invalid = client.post(
            "/api/review-sessions",
            content="secret-not-json",
            headers={"X-Review-Request": "1", "Content-Type": "application/json"},
        )
        assert invalid.status_code == 422
        assert "secret-not-json" not in invalid.text
        assert client.get(url, headers=headers).headers["cache-control"] == "no-store"


@pytest.mark.parametrize(
    "change", ["sub_id", "reorder", "missing", "exclusion", "condition", "whitespace"]
)
def test_invalid_working_copies_leave_revision_unchanged(change):
    with TestClient(create_app()) as client:
        data, headers, url = session(client)
        items = editable(data)
        if change == "sub_id":
            items[0]["subconditions"][0]["subcondition_id"] = "fake"
        elif change == "reorder":
            items = list(reversed(items))
        elif change == "missing":
            items = items[:-1]
        elif change == "exclusion":
            items[0]["included"] = False
        elif change == "condition":
            items[0]["classification"] = "conditional"
        else:
            items[0]["title"] = "  "
        assert (
            client.put(
                url + "/working-copy",
                json={"expected_revision": 0, "items": items},
                headers=headers,
            ).status_code
            == 422
        )
        assert client.get(url, headers=headers).json()["data"]["revision"] == 0


def test_condition_change_resets_decision_and_exclusion_confirms():
    with TestClient(create_app()) as client:
        data, headers, url = session(client)
        items = editable(data)
        items[3]["condition_description"] = "변경된 조건"
        items[3]["application_status"] = "applies"
        items[3]["application_reason"] = "확인함"
        saved = client.put(
            url + "/working-copy", json={"expected_revision": 0, "items": items}, headers=headers
        ).json()["data"]
        assert saved["items"][3]["application_status"] == "undetermined"
        assert saved["items"][3]["application_reason"] is None
        items = editable(saved)
        items[3]["included"] = False
        items[3]["exclusion_reason"] = "별도 확인 예정"
        assert (
            client.put(
                url + "/working-copy",
                json={"expected_revision": 1, "items": items},
                headers=headers,
            ).status_code
            == 200
        )
        assert (
            client.post(
                url + "/confirm", json={"expected_revision": 2}, headers=headers
            ).status_code
            == 200
        )


def test_bounded_store_expiry_capacity_and_instance_isolation():
    now = [0.0]
    store = ReviewStore(clock=lambda: now[0], max_sessions=1, ttl_seconds=1)
    created = store.create()
    with pytest.raises(ReviewError, match="session_limit"):
        store.create()
    with pytest.raises(ReviewError, match="session_unavailable"):
        ReviewStore().get(created.session_id, created.session_token)
    now[0] = 2.0
    with pytest.raises(ReviewError, match="session_unavailable"):
        store.get(created.session_id, created.session_token)
    assert store.create().session_id != created.session_id


def test_concurrent_revision_and_version_limit():
    store = ReviewStore(max_versions=1)
    created = store.create()
    items = editable(created.model_dump(mode="json"))
    items[3]["included"] = False
    items[3]["exclusion_reason"] = "별도 확인"
    request = WorkingCopyRequest.model_validate({"expected_revision": 0, "items": items})

    def save():
        try:
            return store.save(created.session_id, created.session_token, request).revision
        except ReviewError as error:
            return error.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = tuple(pool.map(lambda _: save(), range(2)))
    assert set(outcomes) == {1, "stale_revision"}
    first = store.confirm(created.session_id, created.session_token, 1)
    assert first.versions[0].items[3].included is False
    _ = store.save(
        created.session_id,
        created.session_token,
        request.model_copy(update={"expected_revision": 1}),
    )
    with pytest.raises(ReviewError, match="version_limit"):
        store.confirm(created.session_id, created.session_token, 2)


def test_all_excluded_cannot_confirm():
    store = ReviewStore()
    created = store.create()
    items = [
        {**item, "included": False, "exclusion_reason": "제외"}
        for item in editable(created.model_dump(mode="json"))
    ]
    _ = store.save(
        created.session_id,
        created.session_token,
        WorkingCopyRequest.model_validate({"expected_revision": 0, "items": items}),
    )
    with pytest.raises(ReviewError, match="empty_criteria"):
        store.confirm(created.session_id, created.session_token, 1)


def test_app_instances_and_boundary_body_size():
    with TestClient(create_app()) as first, TestClient(create_app()) as second:
        _, headers, url = session(first)
        assert second.get(url, headers=headers).status_code == 404
        body_headers = {"X-Review-Request": "1", "Content-Type": "application/json"}
        exact = first.post(
            "/api/review-sessions", content=b"{}" + b" " * (262144 - 2), headers=body_headers
        )
        assert exact.status_code == 201
        assert exact.headers["cache-control"] == "no-store"
        excess = first.post(
            "/api/review-sessions", content=b"{}" + b" " * (262144 - 1), headers=body_headers
        )
        assert excess.status_code == 413


@pytest.mark.parametrize(
    "failure", ["missing_pdf", "missing_response", "invalid_response", "invalid_pdf"]
)
def test_demo_failure_is_safe_and_does_not_consume_capacity(monkeypatch, failure):
    original_bytes = Path.read_bytes
    original_text = Path.read_text
    private_path = "private-demo-path"

    def read_bytes(path):
        if path.name == "guide.pdf":
            if failure == "missing_pdf":
                raise FileNotFoundError(private_path)
            if failure == "invalid_pdf":
                return b"private-corrupt-pdf"
        return original_bytes(path)

    def read_text(path, *args, **kwargs):
        if path.name == "guide-offline-response.json":
            if failure == "missing_response":
                raise FileNotFoundError(private_path)
            if failure == "invalid_response":
                return "private-invalid-json"
        return original_text(path, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(Path, "read_bytes", read_bytes)
        patch.setattr(Path, "read_text", read_text)
        store = ReviewStore(max_sessions=1)
        with pytest.raises(ReviewError, match="demo_unavailable"):
            store.create()
        with TestClient(create_app()) as client:
            response = client.post(
                "/api/review-sessions", json={}, headers={"X-Review-Request": "1"}
            )
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "demo_unavailable"
        assert "private" not in response.text
        assert response.headers["cache-control"] == "no-store"
    assert len(store.create().items) == 5
