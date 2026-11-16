from pathlib import Path

from fastapi.testclient import TestClient
from test_ai_settings import MemoryCredentials

from submission.main import create_app

LOCAL = {"X-Local-Client": "prepare"}
CROSS_SITE = {"Sec-Fetch-Site": "cross-site", "Sec-Fetch-Mode": "no-cors"}


def test_rejected_requests_do_not_spend_the_shared_limit(tmp_path: Path) -> None:
    app = create_app(credential_store=MemoryCredentials(), library_path=tmp_path / "lib.sqlite3")
    with TestClient(app) as client:
        for path, limit in (("/api/ai-settings", 60), ("/api/document-library", 120)):
            for _ in range(limit + 1):
                assert client.get(path).status_code == 403
            assert client.get(path, headers=LOCAL).status_code == 200
        for _ in range(31):
            assert client.post("/api/document-pairs", headers=CROSS_SITE).status_code == 403
        assert client.post("/api/document-pairs").status_code == 422


def test_cross_site_navigation_to_prepare_is_allowed() -> None:
    with TestClient(create_app()) as client:
        headers = {"Sec-Fetch-Site": "cross-site", "Sec-Fetch-Mode": "navigate"}
        assert client.get("/prepare", headers=headers).status_code == 200
