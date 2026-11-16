import hashlib
import shutil
from functools import partial

import pytest
from fastapi.testclient import TestClient

from submission import result_demo, result_routes
from submission.main import create_app
from submission.result_assets import SAMPLES, load_raster


def test_result_catalog_when_requested_contains_only_fixed_cases():
    # Given
    client = TestClient(create_app())
    # When
    response = client.get("/api/result-demos")
    # Then
    assert response.status_code == 200
    assert [item["case_id"] for item in response.json()["data"]["cases"]] == [
        "normal",
        "missing",
        "over_limit",
        "unconfirmed_scope",
        "docx_structure",
        "hwpx_structure",
    ]
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"


@pytest.mark.parametrize(
    ("case", "status"),
    [
        ("normal", "compliant"),
        ("missing", "compliant"),
        ("over_limit", "noncompliant"),
        ("unconfirmed_scope", "deferred"),
    ],
)
def test_result_detail_when_fixed_case_binds_actual_documents(case, status):
    # Given
    client = TestClient(create_app())
    # When
    response = client.get(f"/api/result-demos/{case}")
    # Then
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["check"]["items"][4]["page_rule"]["status"] == status
    assert data["check"]["items"][2]["needs_attention"] is False
    assert data["check"]["items"][3]["effective_judgment"] is None
    assert data["check"]["items"][4]["semantic"]["judgment"] == "deferred"
    assert data["check"]["semantic"]["criteria_version"] == 1
    document = data["documents"]["report"]
    pdf = client.get(f"/api/result-demos/{case}/documents/report/original.pdf")
    assert hashlib.sha256(pdf.content).hexdigest() == document["source"]["content_sha256"]
    image = client.get(document["pages"][0]["image_url"])
    assert image.content.startswith(b"\x89PNG\r\n\x1a\n")
    assert image.headers["content-type"] == "image/png"
    assert pdf.headers["cache-control"] == "no-store"


@pytest.mark.parametrize(
    "path",
    [
        "/api/result-demos/unknown",
        "/api/result-demos/normal/documents/unknown/original.pdf",
        "/api/result-demos/normal/documents/report/pages/0.png",
        "/api/result-demos/normal/documents/report/pages/999.png",
    ],
)
def test_result_when_unknown_resource_returns_safe_not_found(path):
    # Given
    client = TestClient(create_app())
    # When
    response = client.get(path)
    # Then
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "result_not_found"


def test_result_when_cross_origin_is_rejected():
    # Given
    client = TestClient(create_app())
    # When
    response = client.get("/api/result-demos", headers={"Origin": "https://example.test"})
    # Then
    assert response.status_code == 403


@pytest.mark.parametrize("path", ["/results", "/result-assets/results.css"])
def test_result_static_when_requested_has_safe_headers(path):
    client = TestClient(create_app())
    response = client.get(path)
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"


@pytest.mark.parametrize(
    "path", ["/api/result-demos/normal", "/api/result-demos/normal/documents/report/original.pdf"]
)
def test_result_when_assets_missing_returns_safe_unavailable(tmp_path, monkeypatch, path):
    loader = partial(load_raster, samples=tmp_path)
    monkeypatch.setattr(result_demo, "load_raster", loader)
    monkeypatch.setattr(result_routes, "load_raster", loader)
    client = TestClient(create_app())
    response = client.get(path)
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "result_demo_unavailable"
    assert str(tmp_path) not in response.text
    assert response.headers["cache-control"] == "no-store"


def test_result_when_authored_response_is_invalid_returns_safe_unavailable(tmp_path, monkeypatch):
    (tmp_path / "checks").mkdir()
    (tmp_path / "checks/normal-offline-response.json").write_text("private-sentinel")
    monkeypatch.setattr(result_demo, "SAMPLES", tmp_path)
    client = TestClient(create_app())
    response = client.get("/api/result-demos/normal")
    assert response.status_code == 503
    assert "private-sentinel" not in response.text


@pytest.mark.parametrize("number", ["abc", "-1", "\u0661", "51", "3"])
def test_result_when_page_number_invalid_returns_not_found(number):
    client = TestClient(create_app())
    response = client.get(f"/api/result-demos/normal/documents/report/pages/{number}.png")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "result_not_found"


def test_result_when_original_guide_and_last_report_page_requested_match_manifest():
    client = TestClient(create_app())
    guide = load_raster("guide")
    report = load_raster("over_limit")
    guide_response = client.get("/api/result-demos/over_limit/documents/guide/original.pdf")
    page_response = client.get("/api/result-demos/over_limit/documents/report/pages/3.png")
    assert guide_response.content == guide.pdf_bytes
    assert page_response.content == report.images[2]


def test_result_when_corrupted_file_restored_recovers_and_health_stays_available(
    tmp_path, monkeypatch
):
    shutil.copytree(SAMPLES / "result-demos", tmp_path / "result-demos")
    shutil.copytree(SAMPLES / "pdf", tmp_path / "pdf")
    path = tmp_path / "pdf/normal.pdf"
    original = path.read_bytes()
    monkeypatch.setattr(result_routes, "load_raster", partial(load_raster, samples=tmp_path))
    client = TestClient(create_app())
    url = "/api/result-demos/normal/documents/report/original.pdf"
    path.write_bytes(b"corrupted")
    assert client.get(url).status_code == 503
    assert client.get("/health").status_code == 200
    path.write_bytes(original)
    response = client.get(url)
    assert response.status_code == 200
    assert response.content == original
