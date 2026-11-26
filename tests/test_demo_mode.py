from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from submission.main import create_app

SAMPLES = Path(__file__).resolve().parents[1] / "samples/pdf"
LOCAL = {"X-Local-Client": "prepare"}


@pytest.fixture
def demo(tmp_path):
    app = create_app(demo=True, library_path=tmp_path.resolve() / "library/documents.sqlite3")
    with TestClient(app) as client:
        yield client


def prepare(client, report="missing", guide="guide"):
    files = {
        role: (f"{name}.pdf", (SAMPLES / f"{name}.pdf").read_bytes(), "application/pdf")
        for role, name in (("guide", guide), ("report", report))
    }
    response = client.post(
        "/api/document-pairs", data={"project_name": "demo"}, files=files, headers=LOCAL
    )
    assert response.status_code == 200, response.text
    return response.json()["data"]


def call(client, session, path, body):
    return client.post(
        f"/api/document-pairs/{session['session_id']}/ai/{path}",
        headers={**LOCAL, "X-Session-Token": session["access_token"]},
        json=body,
    )


def request(session, **extra):
    return {
        "provider": "demo",
        "model": "offline-example",
        "consent": True,
        "guide_sha256": session["guide"]["document"]["source"]["content_sha256"],
        **extra,
    }


def confirmed(client, session, change=lambda item: item):
    draft = call(client, session, "requirements", request(session)).json()["data"]
    items = []
    for drafted in draft["items"]:
        item = {key: value for key, value in drafted.items() if key != "edited_fields"}
        if item["classification"] == "conditional":
            item |= {"application_status": "does_not_apply", "application_reason": "해당 없음"}
        items.append(change(item))
    response = call(
        client,
        session,
        "criteria",
        {"draft_id": draft["draft_id"], "expected_revision": draft["revision"], "items": items},
    )
    assert response.status_code == 200, response.text
    return response.json()["data"]


def check(client, session, criteria):
    return call(
        client,
        session,
        "check",
        request(
            session,
            draft_id=criteria["draft_id"],
            criteria_sha256=criteria["criteria_sha256"],
            report_sha256=session["report"]["document"]["source"]["content_sha256"],
        ),
    )


@pytest.mark.parametrize("report", ["normal", "missing", "paraphrased"])
def test_demo_checks_every_sample_report(demo, report):
    session = prepare(demo, report)

    response = check(demo, session, confirmed(demo, session))

    assert response.status_code == 200, response.text
    assert response.json()["data"]["provider"] == "demo"
    assert response.json()["data"]["result"]["items"]


def test_demo_defers_item_the_saved_answer_does_not_cover(demo):
    session = prepare(demo)
    criteria = confirmed(
        demo,
        session,
        lambda item: (
            item | {"application_status": "applies", "application_reason": "적용"}
            if item["classification"] == "conditional"
            else item
        ),
    )

    response = check(demo, session, criteria)

    assert response.status_code == 200, response.text
    judged = {i["requirement_id"]: i for i in response.json()["data"]["result"]["items"]}
    assert judged["R4"]["judgment"] == "deferred"


def test_demo_accepts_excluded_item(demo):
    session = prepare(demo)
    criteria = confirmed(
        demo,
        session,
        lambda item: (
            item | {"included": False, "exclusion_reason": "제외"}
            if item["requirement_id"] == "R1"
            else item
        ),
    )

    assert check(demo, session, criteria).status_code == 200


def test_demo_rejects_other_guide(demo):
    session = prepare(demo, guide="normal")

    response = call(demo, session, "requirements", request(session))

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "ai_demo_sample_only"


def test_demo_rejects_real_provider(demo):
    session = prepare(demo)

    response = call(demo, session, "requirements", request(session, provider="ollama"))

    assert response.json()["error"]["code"] == "ai_demo_mode_mismatch"


def test_real_mode_rejects_demo_provider():
    with TestClient(create_app(demo=False)) as client:
        session = prepare(client)
        response = call(client, session, "requirements", request(session))
        page = client.get("/prepare").text

    assert response.json()["error"]["code"] == "ai_demo_mode_mismatch"
    assert "data-demo" not in page


def test_demo_page_announces_that_no_ai_runs(demo):
    page = demo.get("/prepare").text

    assert 'data-demo="true"' in page
    assert "실제 AI가 아닙니다" in page


def test_environment_variable_selects_demo(monkeypatch):
    monkeypatch.setenv("RUBRIQ_MODE", "demo")
    with TestClient(create_app()) as client:
        assert 'data-demo="true"' in client.get("/prepare").text
