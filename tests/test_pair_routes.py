from docx_reader_helpers import make_docx
from fastapi.testclient import TestClient
from pydantic import BaseModel

from submission.main import create_app


class BlockView(BaseModel):
    block_id: str


class DocumentView(BaseModel):
    blocks: tuple[BlockView, ...]


class RoleView(BaseModel):
    document: DocumentView


class SessionView(BaseModel):
    session_id: str
    access_token: str
    guide: RoleView


class SessionResponse(BaseModel):
    data: SessionView


def test_upload_pdf_pair_and_private_assets(text_pdf: bytes) -> None:
    with TestClient(create_app()) as client:
        response = client.post(
            "/api/document-pairs",
            data={"project_name": "한국어 과제"},
            files={"guide": ("guide.pdf", text_pdf), "report": ("report.pdf", text_pdf)},
        )
        assert response.status_code == 200
        data = SessionResponse.model_validate_json(response.content).data
        path = f"/api/document-pairs/{data.session_id}"
        headers = {"X-Session-Token": data.access_token}
        assert client.get(path).status_code == 404
        assert client.get(path, headers=headers).status_code == 200
        assert client.get(path + "/guide/pdf", headers=headers).content == text_pdf
        block = data.guide.document.blocks[0]
        mapping = client.post(
            path + "/guide/evidence",
            headers=headers,
            json={"block_id": block.block_id, "start": 0, "end": 7},
        )
        assert mapping.status_code == 200
        assert mapping.json()["data"]["mapping"]["mapping_status"] == "identity"
        assert mapping.headers["cache-control"] == "no-store"
        assert client.delete(path, headers=headers).status_code == 200
        assert client.get(path, headers=headers).status_code == 404


def test_one_bad_role_preserves_other(text_pdf: bytes) -> None:
    with TestClient(create_app()) as client:
        response = client.post(
            "/api/document-pairs",
            data={"project_name": "test"},
            files={"guide": ("bad.pdf", b"invalid"), "report": ("report.pdf", text_pdf)},
        )
        assert response.status_code == 200
        assert response.json()["data"]["guide"]["extraction_status"] == "failed"
        assert response.json()["data"]["report"]["artifact_kind"] == "original_pdf"


def test_both_bad_returns_safe_error() -> None:
    with TestClient(create_app()) as client:
        response = client.post(
            "/api/document-pairs",
            data={"project_name": "test"},
            files={"guide": ("a.pdf", b"bad"), "report": ("b.pdf", b"bad")},
        )
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "pair_failed"


def test_empty_unrendered_documents_do_not_create_session() -> None:
    empty = make_docx("<w:p/>")
    with TestClient(create_app()) as client:
        response = client.post(
            "/api/document-pairs",
            data={"project_name": "empty"},
            files={"guide": ("g.docx", empty), "report": ("r.docx", empty)},
        )
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "pair_failed"


def test_scanned_pdf_preview_still_creates_session(blank_pdf: bytes) -> None:
    with TestClient(create_app()) as client:
        response = client.post(
            "/api/document-pairs",
            data={"project_name": "scanned"},
            files={"guide": ("g.pdf", blank_pdf), "report": ("r.pdf", blank_pdf)},
        )
        assert response.status_code == 200
        assert response.json()["data"]["guide"]["artifact_kind"] == "original_pdf"
