from dataclasses import replace
from hashlib import sha256
from time import monotonic

import pytest
from docx_reader_helpers import make_docx
from fastapi.testclient import TestClient

from submission import expression_engine, pair_routes
from submission.expression_engine import check_expression
from submission.input_contracts import DocumentInput
from submission.main import create_app
from submission.models import DocumentRole
from submission.pair_contracts import EvidenceSelection, PairError, PairRuntime
from submission.pair_prepare import prepare_role
from submission.pair_store import PairStore


def role_for(text):
    content = make_docx(f"<w:p><w:r><w:t>{text}</w:t></w:r></w:p>")
    return prepare_role(
        DocumentInput("test.docx", content, DocumentRole.REPORT),
        PairRuntime(),
        monotonic() + 10,
    )


def selection_for(role, start=0, end=None):
    block = role.view.document.blocks[0]
    return EvidenceSelection(block_id=block.block_id, start=start, end=end or len(block.raw_text))


def test_real_upstream_counts_spans_unicode_and_immutable():
    text = "😀 결과는 완료되어진다. 문서에서의 근거를 가지고 있다."
    role = role_for(text)
    before = role.view.model_dump_json()
    result = check_expression(role, selection_for(role))
    assert result.llm_executed is False
    assert result.source_sha256 == sha256(role.original).hexdigest()
    assert {f.pattern_id for f in result.findings} >= {"A-8", "A-19", "A-7"}
    assert all(text[f.start : f.end] == f.original for f in result.findings)
    assert role.view.model_dump_json() == before
    assert {m.id: m.count for m in result.metrics}["double_passive_count"] == 2
    assert "risk" not in result.model_dump_json()


def test_quote_code_protection_and_partial_selection():
    text = "“완료되어진다.” 「문서에서의」 `가지고 있다` 완료되어진다."
    role = role_for(text)
    result = check_expression(role, selection_for(role))
    assert len(result.findings) == 1
    assert result.findings[0].start == text.rindex("되어진다")
    result = check_expression(role, selection_for(role, 2, 7))
    assert not result.findings


def test_report_words_do_not_imply_style_failure():
    role = role_for("정부에 의해 되레 손해를 봤다. 따라서 수치 1,200건을 기록한다.")
    result = check_expression(role, selection_for(role))
    assert not result.findings


def test_protected_quote_cannot_join_passive_match():
    role = role_for('정책에 의해 "인용" 받았다.')
    result = check_expression(role, selection_for(role))
    assert not result.findings
    assert {m.id: m.count for m in result.metrics}["by_passive_count"] == 0


def test_vendor_missing_and_modified_are_safe(tmp_path, monkeypatch):
    role = role_for("완료되어진다.")
    path = tmp_path / "missing.py"
    monkeypatch.setattr(expression_engine, "VENDOR_FILE", path)
    with pytest.raises(PairError, match="asset_unavailable"):
        check_expression(role, selection_for(role))
    path.write_text("raise RuntimeError('sensitive text')")
    with pytest.raises(PairError, match="asset_unavailable"):
        check_expression(role, selection_for(role))


def test_repeated_conclusion_requires_four_occurrences():
    for count in (1, 3, 4):
        role = role_for("결론적으로 값이 같다. " * count)
        result = check_expression(role, selection_for(role))
        assert len(result.findings) == (4 if count == 4 else 0)


def test_finding_limit_and_text_limit():
    role = role_for("되어진다. " * 150)
    result = check_expression(role, selection_for(role))
    assert len(result.findings) == 100
    assert any("100" in w for w in result.warnings)
    role = role_for("가" * 20001)
    with pytest.raises(PairError):
        check_expression(role, selection_for(role))


@pytest.mark.parametrize(
    ("start", "end", "block_id"), [(0, 1000, None), (2, 1, None), (0, 1, "missing")]
)
def test_bad_range(start, end, block_id):
    role = role_for("문서에서의 근거")
    selection = selection_for(role, start, end)
    if block_id:
        selection = selection.model_copy(update={"block_id": block_id})
    with pytest.raises(PairError):
        check_expression(role, selection)


def test_bad_original_hash_and_unavailable_document():
    role = role_for("문서에서의 근거")
    selection = selection_for(role)
    for damaged in (
        replace(role, original=b"changed"),
        replace(role, view=role.view.model_copy(update={"document": None})),
    ):
        with pytest.raises(PairError):
            check_expression(damaged, selection)


def test_invalid_block_source_binding():
    role = role_for("문서에서의 근거")
    document = role.view.document
    block = document.blocks[0]
    invalid = block.model_copy(
        update={
            "source_locator": block.source_locator.model_copy(update={"source_sha256": "0" * 64})
        }
    )
    damaged = replace(
        role,
        view=role.view.model_copy(
            update={"document": document.model_copy(update={"blocks": (invalid,)})}
        ),
    )
    with pytest.raises(PairError):
        check_expression(damaged, selection_for(role))


def test_session_expiry_and_role_unavailable(monkeypatch, text_pdf):
    now = [0.0]
    store = PairStore(clock=lambda: now[0], ttl=30)
    monkeypatch.setattr(pair_routes, "PairStore", lambda: store)
    with TestClient(create_app()) as client:
        pair = client.post(
            "/api/document-pairs",
            data={"project_name": "test"},
            files={"guide": ("g.pdf", b"bad"), "report": ("r.pdf", text_pdf)},
        ).json()["data"]
        path = f"/api/document-pairs/{pair['session_id']}"
        headers = {"X-Session-Token": pair["access_token"], "X-Local-Client": "prepare"}
        selection = {
            "block_id": pair["report"]["document"]["blocks"][0]["block_id"],
            "start": 0,
            "end": 5,
        }
        missing = client.post(path + "/guide/expression-check", json=selection, headers=headers)
        assert missing.status_code == 409
        assert missing.json()["error"]["code"] == "asset_unavailable"
        now[0] = 31
        expired = client.post(path + "/report/expression-check", json=selection, headers=headers)
        assert expired.status_code == 404


def test_diagnostic_failure_does_not_leak_path(monkeypatch, tmp_path, text_pdf):
    monkeypatch.setattr(expression_engine, "VENDOR_FILE", tmp_path / "private-secret-path.py")
    with TestClient(create_app()) as client:
        pair = client.post(
            "/api/document-pairs",
            data={"project_name": "test"},
            files={"guide": ("g.pdf", text_pdf), "report": ("r.pdf", text_pdf)},
        ).json()["data"]
        path = f"/api/document-pairs/{pair['session_id']}/report/expression-check"
        headers = {"X-Session-Token": pair["access_token"], "X-Local-Client": "prepare"}
        result = client.post(
            path,
            json={
                "block_id": pair["report"]["document"]["blocks"][0]["block_id"],
                "start": 0,
                "end": 5,
            },
            headers=headers,
        )
        assert result.status_code == 409
        assert "private-secret" not in result.text


def test_api_auth_delete_headers_and_safe_unavailable(text_pdf):
    with TestClient(create_app()) as client:
        pair = client.post(
            "/api/document-pairs",
            data={"project_name": "test"},
            files={"guide": ("g.pdf", text_pdf), "report": ("r.pdf", text_pdf)},
        ).json()["data"]
        path = f"/api/document-pairs/{pair['session_id']}"
        url = path + "/report/expression-check"
        headers = {"X-Session-Token": pair["access_token"], "X-Local-Client": "prepare"}
        selection = {
            "block_id": pair["report"]["document"]["blocks"][0]["block_id"],
            "start": 0,
            "end": 5,
        }
        assert client.post(url, json=selection).status_code == 403
        assert (
            client.post(url, json=selection, headers={"X-Local-Client": "prepare"}).status_code
            == 404
        )
        result = client.post(url, json=selection, headers=headers)
        assert result.status_code == 200
        assert result.headers["cache-control"] == "no-store"
        assert result.json()["data"]["llm_executed"] is False
        assert client.post(url, json={**selection, "end": -1}, headers=headers).status_code == 422
        assert (
            client.post(
                url, json=selection, headers={**headers, "Origin": "https://evil.example"}
            ).status_code
            == 403
        )
        assert client.delete(path, headers=headers).status_code == 200
        assert client.post(url, json=selection, headers=headers).status_code == 404


@pytest.mark.parametrize("stray", ["it's", 'a 5" panel'])
def test_unclosed_straight_quote_does_not_hide_later_findings(stray):
    text = f"{stray} 결과는 완료되어진다."
    role = role_for(text)
    result = check_expression(role, selection_for(role))
    assert [f.start for f in result.findings if f.pattern_id == "A-8"] == [text.index("되어진다")]


def test_closed_straight_quotes_stay_protected():
    role = role_for("'완료되어진다' \"완료되어진다\" 완료되어진다.")
    result = check_expression(role, selection_for(role))
    assert len([f for f in result.findings if f.pattern_id == "A-8"]) == 1
