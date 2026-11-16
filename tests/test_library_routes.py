from pathlib import Path

from docx_reader_helpers import make_docx
from fastapi.testclient import TestClient

from submission.library_contracts import LibraryPage, SavedReceipt
from submission.library_store import LibraryStore
from submission.main import create_app
from submission.pair_contracts import PairEnvelope, SessionView


def upload(client: TestClient, content: bytes) -> SessionView:
    response = client.post(
        "/api/document-pairs",
        data={"project_name": "보관"},
        files={
            "guide": ("guide.pdf", content),
            "report": ("report.pdf", content),
        },
    )
    assert response.status_code == 200
    return PairEnvelope[SessionView].model_validate_json(response.content, extra="ignore").data


def test_restart_open_no_conversion_and_delete_keeps_open(tmp_path: Path, text_pdf: bytes) -> None:
    path = tmp_path / "library.sqlite3"
    local = {"X-Local-Client": "prepare"}
    with TestClient(create_app(library_path=path)) as client:
        view = upload(client, text_pdf)
        saved = client.post(
            f"/api/document-pairs/{view.session_id}/save",
            headers={**local, "X-Session-Token": view.access_token or ""},
        )
        assert saved.status_code == 200
        receipt = PairEnvelope[SavedReceipt].model_validate_json(saved.content).data
        assert saved.headers["cache-control"] == "no-store"
    with TestClient(create_app(library_path=path)) as client:
        response = client.get("/api/document-library", headers=local)
        listing = PairEnvelope[LibraryPage].model_validate_json(response.content).data
        assert listing.total == 1
        assert "raw_text" not in response.text
        opened = client.post(f"/api/document-library/{receipt.saved_id}/open", headers=local)
        restored = (
            PairEnvelope[SessionView].model_validate_json(opened.content, extra="ignore").data
        )
        assert restored.session_id != view.session_id
        assert restored.access_token != view.access_token
        assert restored.guide == view.guide
        assert restored.saved_id == receipt.saved_id
        assert restored.saved_environment
        assert restored.current_environment
        assert (
            client.delete(f"/api/document-library/{receipt.saved_id}", headers=local).status_code
            == 200
        )
        headers = {"X-Session-Token": restored.access_token or ""}
        assert (
            client.get(
                f"/api/document-pairs/{restored.session_id}/guide/pdf", headers=headers
            ).content
            == text_pdf
        )
        assert (
            client.post(f"/api/document-library/{receipt.saved_id}/open", headers=local).status_code
            == 404
        )


def test_header_origin_token_rate_no_store(tmp_path: Path, text_pdf: bytes) -> None:
    path = tmp_path / "library.sqlite3"
    with TestClient(create_app(library_path=path)) as client:
        assert client.get("/api/document-library").status_code == 403
        assert client.get("/api/document-library").headers["cache-control"] == "no-store"
        local = {"X-Local-Client": "prepare"}
        assert (
            client.get(
                "/api/document-library", headers={**local, "Origin": "https://external.invalid"}
            ).status_code
            == 403
        )
        assert (
            client.get(
                "/api/document-library", headers={**local, "Host": "external.invalid"}
            ).status_code
            == 400
        )
        view = upload(client, text_pdf)
        assert (
            client.post(f"/api/document-pairs/{view.session_id}/save", headers=local).status_code
            == 404
        )
        assert client.get("/api/document-library?page=0", headers=local).status_code == 422
        responses = [client.get("/api/document-library", headers=local) for _ in range(120)]
        assert responses[-1].status_code == 429
        assert responses[-1].headers["cache-control"] == "no-store"
        assert not path.exists()


def test_partial_conversion_failed_and_scanned_saved(tmp_path: Path, blank_pdf: bytes) -> None:
    with TestClient(create_app(library_path=tmp_path / "library.sqlite3")) as client:
        docx = make_docx("<w:p><w:r><w:t>원문 보존</w:t></w:r></w:p>")
        response = client.post(
            "/api/document-pairs",
            data={"project_name": "부분"},
            files={
                "guide": ("g.docx", docx),
                "report": ("r.pdf", blank_pdf),
            },
        )
        view = PairEnvelope[SessionView].model_validate_json(response.content, extra="ignore").data
        assert view.guide.rendering_status == "failed"
        response = client.post(
            f"/api/document-pairs/{view.session_id}/save",
            headers={
                "X-Local-Client": "prepare",
                "X-Session-Token": view.access_token or "",
            },
        )
        receipt = PairEnvelope[SavedReceipt].model_validate_json(response.content).data
        response = client.post(
            f"/api/document-library/{receipt.saved_id}/open", headers={"X-Local-Client": "prepare"}
        )
        opened = (
            PairEnvelope[SessionView].model_validate_json(response.content, extra="ignore").data
        )
        assert opened.guide == view.guide
        assert opened.report == view.report


def test_missing_and_corrupt_and_full_sessions(tmp_path: Path, text_pdf: bytes) -> None:
    local = {"X-Local-Client": "prepare"}
    with TestClient(create_app(library_path=tmp_path / "library.sqlite3")) as client:
        assert client.post("/api/document-library/missing/open", headers=local).status_code == 404
        view = upload(client, text_pdf)
        response = client.post(
            f"/api/document-pairs/{view.session_id}/save",
            headers={**local, "X-Session-Token": view.access_token or ""},
        )
        saved = PairEnvelope[SavedReceipt].model_validate_json(response.content).data
        for _ in range(3):
            assert (
                client.post(
                    f"/api/document-library/{saved.saved_id}/open", headers=local
                ).status_code
                == 200
            )
        assert (
            client.post(f"/api/document-library/{saved.saved_id}/open", headers=local).status_code
            == 409
        )


def test_failed_guide_save_reopen(tmp_path: Path, text_pdf: bytes) -> None:
    path = tmp_path / "library.sqlite3"
    local = {"X-Local-Client": "prepare"}
    with TestClient(create_app(library_path=path)) as client:
        response = client.post(
            "/api/document-pairs",
            data={"project_name": "부분 보관"},
            files={
                "guide": ("g.pdf", b"failed uploaded original"),
                "report": ("r.pdf", text_pdf),
            },
        )
        view = PairEnvelope[SessionView].model_validate_json(response.content, extra="ignore").data
        response = client.post(
            f"/api/document-pairs/{view.session_id}/save",
            headers={**local, "X-Session-Token": view.access_token or ""},
        )
        saved = PairEnvelope[SavedReceipt].model_validate_json(response.content).data
        assert LibraryStore(path).load(saved.saved_id).guide.original == b"failed uploaded original"
        response = client.post(f"/api/document-library/{saved.saved_id}/open", headers=local)
        opened = (
            PairEnvelope[SessionView].model_validate_json(response.content, extra="ignore").data
        )
        assert opened.guide == view.guide
        assert opened.report == view.report
