from concurrent.futures import ThreadPoolExecutor

from fastapi import FastAPI
from fastapi.testclient import TestClient

from submission.main import create_app
from submission.result_rate_limit import ResultRateLimit, ResultRatePolicy


def test_rate_limit_when_window_exhausted_rejects_then_resets():
    now = [100.0]
    app = FastAPI()
    app.add_middleware(
        ResultRateLimit, policy=ResultRatePolicy(requests=2, seconds=60), clock=lambda: now[0]
    )
    client = TestClient(app)
    assert client.get("/results").status_code == 404
    assert client.get("/result-assets/missing.css").status_code == 404
    limited = client.get("/api/result-demos")
    assert limited.status_code == 429
    assert limited.json()["error"]["code"] == "result_rate_limited"
    assert limited.headers["retry-after"] == "60"
    assert limited.headers["cache-control"] == "no-store"
    assert limited.headers["x-content-type-options"] == "nosniff"
    assert client.get("/health").status_code == 404
    assert client.get("/results-other").status_code == 404
    assert client.get("/api/result-demos-other").status_code == 404
    now[0] = 159.5
    assert client.get("/results").headers["retry-after"] == "1"
    now[0] = 160.0
    assert client.get("/results").status_code == 404


def test_rate_limit_when_apps_are_independent_has_separate_budget():
    clients = []
    for _ in range(2):
        app = FastAPI()
        app.add_middleware(ResultRateLimit, policy=ResultRatePolicy(requests=1, seconds=60))
        clients.append(TestClient(app))
    assert clients[0].get("/api/result-demos/normal").status_code == 404
    assert clients[0].get("/api/result-demos/normal").status_code == 429
    assert clients[1].get("/api/result-demos/normal").status_code == 404


def test_rate_limit_when_installed_in_real_app_leaves_health_available():
    client = TestClient(create_app())
    for _ in range(600):
        assert client.get("/api/result-demos").status_code == 200
    assert client.get("/api/result-demos").status_code == 429
    assert client.get("/health").status_code == 200


def test_rate_limit_when_concurrent_admission_never_exceeds_window():
    app = FastAPI()
    limiter = ResultRateLimit(app, policy=ResultRatePolicy(requests=5, seconds=60), clock=lambda: 0)
    with ThreadPoolExecutor(max_workers=8) as executor:
        results = tuple(executor.map(lambda _: limiter.retry_after(), range(30)))
    assert results.count(0) == 5
    assert results.count(60) == 25


def test_rate_limit_when_lifespan_scope_passes_through():
    app = FastAPI()
    app.add_middleware(ResultRateLimit)
    with TestClient(app) as client:
        assert client.get("/health").status_code == 404
