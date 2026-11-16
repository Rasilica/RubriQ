from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event

import pytest
from fastapi.testclient import TestClient

from submission.input_contracts import DocumentInput
from submission.main import create_app
from submission.pair_contracts import PairRuntime, PreparedRole
from submission.pair_process import run_preparation
from submission.pair_routes import load_runtime
from tests.test_pair_assets import PNG, raster_binary
from tests.test_pair_routes import SessionResponse


def test_page_cache_errors_safe_selection_and_origin(tmp_path: Path, text_pdf: bytes) -> None:
    runtime = PairRuntime(pdftoppm=raster_binary(tmp_path))
    with TestClient(create_app(pair_runtime=runtime)) as client:
        response = client.post(
            "/api/document-pairs",
            data={"project_name": "one"},
            files={"guide": ("g.pdf", text_pdf), "report": ("r.pdf", text_pdf)},
        )
        data = SessionResponse.model_validate_json(response.content).data
        headers = {"X-Session-Token": data.access_token}
        path = f"/api/document-pairs/{data.session_id}"
        assert client.get(path + "/guide/pages/1.png", headers=headers).content == PNG
        assert runtime.pdftoppm is not None
        runtime.pdftoppm.unlink()
        assert client.get(path + "/guide/pages/1.png", headers=headers).content == PNG
        assert client.get(path + "/guide/pages/2.png", headers=headers).status_code == 409
        assert client.get(path + "/guide/pages/0.png", headers=headers).status_code == 404
        assert (
            client.post(
                path + "/guide/evidence",
                headers=headers,
                json={"block_id": "missing", "start": 0, "end": 2},
            ).status_code
            == 422
        )
        assert client.get(path, headers={"Origin": "https://other.example"}).status_code == 403
        assert client.get("/prepare").status_code == 200


def test_pair_admission_has_no_queue(text_pdf: bytes, monkeypatch: pytest.MonkeyPatch) -> None:
    entered, release = Event(), Event()

    def slow(
        guide: DocumentInput, report: DocumentInput, runtime: PairRuntime
    ) -> tuple[PreparedRole, PreparedRole]:
        entered.set()
        _ = release.wait(5)
        return run_preparation(guide, report, runtime)

    monkeypatch.setattr("submission.pair_routes.run_preparation", slow)
    with TestClient(create_app()) as client, ThreadPoolExecutor(max_workers=1) as executor:
        files = {"guide": ("g.pdf", text_pdf), "report": ("r.pdf", text_pdf)}
        pending = executor.submit(
            client.post, "/api/document-pairs", data={"project_name": "one"}, files=files
        )
        try:
            assert entered.wait(5)
            response = client.post("/api/document-pairs", data={"project_name": "two"}, files=files)
            assert response.status_code == 409
            assert response.json()["error"]["code"] == "preparation_busy"
        finally:
            release.set()
        assert pending.result(timeout=10).status_code == 200


def test_validation_and_rate_have_no_store() -> None:
    with TestClient(create_app()) as client:
        for _ in range(30):
            response = client.post("/api/document-pairs")
            assert response.status_code == 422
            assert response.headers["cache-control"] == "no-store"
        response = client.post("/api/document-pairs")
        assert response.status_code == 429
        assert response.headers["cache-control"] == "no-store"


def test_runtime_manifest(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "runtime.json"
    _ = path.write_text(PairRuntime().model_dump_json())
    monkeypatch.setenv("DOCUMENT_PAIR_RUNTIME_FILE", str(path))
    assert load_runtime() == PairRuntime()
