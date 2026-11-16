import pytest
from fastapi.testclient import TestClient

from submission.main import create_app


def test_introduction_and_workbench_are_linked_without_losing_docs() -> None:
    with TestClient(create_app()) as client:
        introduction = client.get("/")
        workbench = client.get("/prepare")
        docs = client.get("/docs")
    assert introduction.status_code == 200
    assert introduction.headers["content-type"].startswith("text/html")
    assert introduction.headers["cache-control"] == "no-store"
    assert 'href="/prepare"' in introduction.text
    assert 'href="/"' in workbench.text
    assert docs.status_code == 200


@pytest.mark.parametrize(
    "path",
    [
        "/landing-assets/landing.css",
        "/landing-assets/landing.mjs",
        "/brand-assets/theme.css",
        "/brand-assets/motion.mjs",
    ],
)
def test_visual_assets_are_available(path: str) -> None:
    with TestClient(create_app()) as client:
        response = client.get(path)
    assert response.status_code == 200
    assert response.content


def test_brand_static_mount_does_not_expose_project_files() -> None:
    with TestClient(create_app()) as client:
        response = client.get("/brand-assets/%2e%2e/%2e%2e/main.py")
    assert response.status_code == 404


@pytest.mark.parametrize("path", ["/", "/prepare", "/review", "/results"])
def test_rubriq_identity_is_consistent_on_user_routes(path: str) -> None:
    with TestClient(create_app()) as client:
        response = client.get(path)
    assert response.status_code == 200
    assert "RubriQ" in response.text.split("</title>")[0]
    assert 'href="/brand-assets/rubriq-mark.svg"' in response.text
    assert 'src="/brand-assets/rubriq-mark.svg"' in response.text


def test_workflow_examples_explain_actual_actions_without_fake_controls() -> None:
    with TestClient(create_app()) as client:
        response = client.get("/")
        logo = client.get("/brand-assets/rubriq-mark.svg")
    steps = response.text.split('id="steps"')[1].split("</section>")[0]
    assert steps.count('class="workflow-preview') == 3
    assert "과제 안내문.pdf" in steps
    assert "원문에서 선택한 문구" in steps
    assert "보관한 준비 결과" in steps
    assert "화면 예시" in steps
    assert "step-illustration" not in steps
    assert "<button" not in steps
    assert logo.status_code == 200
    assert "image/svg+xml" in logo.headers["content-type"]
