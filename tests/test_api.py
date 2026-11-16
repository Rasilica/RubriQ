from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest
from fastapi.testclient import TestClient

from submission.extraction import extract_pdf
from submission.main import create_app
from submission.models import ExtractedDocument, PdfInput, PdfLimits


def test_openapi_uses_rubriq_service_name() -> None:
    with TestClient(create_app()) as client:
        response = client.get("/openapi.json")
    assert response.json()["info"]["title"] == "RubriQ · 문서 준비"


def test_pair_upload_returns_real_page_text(text_pdf: bytes) -> None:
    # Given
    with TestClient(create_app()) as client:
        # When
        response = client.post(
            "/api/documents/extract",
            data={"project_name": "테스트"},
            files={
                "guide": ("guide.pdf", text_pdf, "application/pdf"),
                "report": ("report.pdf", text_pdf, "application/pdf"),
            },
        )
    # Then
    assert response.status_code == 200
    result = response.json()
    assert result["success"] is True
    assert result["data"]["ready"] is True
    assert result["data"]["report"]["pages"][1]["number"] == 2
    assert "Output:" in result["data"]["report"]["pages"][1]["text"]


def test_unreadable_input_does_not_claim_ready(text_pdf: bytes, blank_pdf: bytes) -> None:
    # Given
    with TestClient(create_app()) as client:
        # When
        response = client.post(
            "/api/documents/extract",
            data={"project_name": "test"},
            files={
                "guide": ("guide.pdf", text_pdf),
                "report": ("report.pdf", blank_pdf),
            },
        )
    # Then
    assert response.json()["data"]["ready"] is False
    assert response.json()["data"]["report"]["pages"][0]["error"] == "text_unavailable"


@pytest.mark.parametrize("name", ["", "   ", "x" * 121])
def test_invalid_project_name_is_rejected(name: str, text_pdf: bytes) -> None:
    # Given
    with TestClient(create_app()) as client:
        # When
        response = client.post(
            "/api/documents/extract",
            data={"project_name": name},
            files={
                "guide": ("guide.pdf", text_pdf),
                "report": ("report.pdf", text_pdf),
            },
        )
    # Then
    assert response.status_code == 422


def test_malformed_pdf_returns_safe_error(text_pdf: bytes) -> None:
    # Given
    with TestClient(create_app()) as client:
        # When
        response = client.post(
            "/api/documents/extract",
            data={"project_name": "test"},
            files={
                "guide": ("guide.pdf", text_pdf),
                "report": ("report.pdf", b"%PDF-1.7\nbroken"),
            },
        )
    # Then
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_pdf"
    assert response.json()["error"]["role"] == "report"


def test_size_limit_returns_413(text_pdf: bytes) -> None:
    # Given
    with TestClient(create_app(PdfLimits(max_bytes=10))) as client:
        # When
        response = client.post(
            "/api/documents/extract",
            data={"project_name": "test"},
            files={
                "guide": ("guide.pdf", text_pdf),
                "report": ("report.pdf", text_pdf),
            },
        )
    # Then
    assert response.status_code == 413


def test_missing_file_is_rejected(text_pdf: bytes) -> None:
    # Given
    with TestClient(create_app()) as client:
        # When
        response = client.post(
            "/api/documents/extract",
            data={"project_name": "test"},
            files={
                "guide": ("guide.pdf", text_pdf),
            },
        )
    # Then
    assert response.status_code == 422


def test_health_and_docs_are_available() -> None:
    # Given
    with TestClient(create_app()) as client:
        # When
        health = client.get("/health")
        docs = client.get("/docs")
        index = client.get("/", follow_redirects=False)
    # Then
    assert health.status_code == 200
    assert docs.status_code == 200
    assert index.status_code == 200
    assert 'href="/prepare"' in index.text


def test_streamed_body_limit_is_enforced_without_content_length() -> None:
    # Given
    def chunks() -> Iterator[bytes]:
        yield b"x" * 40000
        yield b"x" * 40000

    with TestClient(create_app(PdfLimits(max_bytes=10))) as client:
        # When
        response = client.post(
            "/api/documents/extract",
            content=chunks(),
            headers={
                "Content-Type": "multipart/form-data; boundary=sample",
            },
        )
    # Then
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "body_too_large"


def test_cross_origin_upload_is_rejected(text_pdf: bytes) -> None:
    # Given
    with TestClient(create_app()) as client:
        # When
        response = client.post(
            "/api/documents/extract",
            headers={"Origin": "https://evil.example"},
            data={"project_name": "test"},
            files={
                "guide": ("guide.pdf", text_pdf),
                "report": ("report.pdf", text_pdf),
            },
        )
    # Then
    assert response.status_code == 403


def test_concurrent_extraction_is_rejected_without_queue(
    text_pdf: bytes, monkeypatch: pytest.MonkeyPatch
) -> None:
    entered, release = Event(), Event()

    def slow(source: PdfInput, limits: PdfLimits) -> ExtractedDocument:
        entered.set()
        _ = release.wait(5)
        return extract_pdf(source, limits)

    monkeypatch.setattr("submission.main.extract_pdf", slow)
    files = {"guide": ("g.pdf", text_pdf), "report": ("r.pdf", text_pdf)}
    with TestClient(create_app()) as client, ThreadPoolExecutor(max_workers=1) as executor:
        pending = executor.submit(
            client.post, "/api/documents/extract", data={"project_name": "one"}, files=files
        )
        try:
            assert entered.wait(5)
            response = client.post(
                "/api/documents/extract", data={"project_name": "two"}, files=files
            )
            assert response.status_code == 409
            assert response.json()["error"]["code"] == "extraction_busy"
        finally:
            release.set()
        assert pending.result(timeout=10).status_code == 200


@pytest.mark.parametrize("path", ["/prepare", "/results", "/review", "/health"])
def test_pages_forbid_framing_and_foreign_resources(path: str) -> None:
    with TestClient(create_app()) as client:
        response = client.get(path)
    assert response.headers["x-frame-options"] == "DENY"
    policy = response.headers["content-security-policy"]
    assert "default-src 'self'" in policy
    assert "frame-ancestors 'none'" in policy


def test_swagger_keeps_cdn_access_but_cannot_be_framed() -> None:
    with TestClient(create_app()) as client:
        response = client.get("/docs")
    assert response.status_code == 200
    assert response.headers["content-security-policy"] == "frame-ancestors 'none'"
