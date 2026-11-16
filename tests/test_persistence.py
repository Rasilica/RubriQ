import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path

import pytest
from page_rule_helpers import context, page_input, response

from submission.document_contracts import ToolDescriptor
from submission.evidence_contracts import ArtifactBinding
from submission.page_rule_contracts import SubmissionCheckContext
from submission.persistence import PersistenceStore
from submission.persistence_contracts import (
    ArtifactPayload,
    ExecutionSettings,
    OriginalPayload,
    PersistenceError,
    PersistenceErrorCode,
    PersistenceLimits,
    PersistenceRequest,
)


@pytest.fixture
def request_data():
    return make_request()


def make_request():
    ctx = context()
    samples = Path(__file__).resolve().parents[1] / "samples/pdf"
    originals = tuple(
        OriginalPayload(source=doc.source, content=(samples / doc.source.filename).read_bytes())
        for doc in (ctx.guide, ctx.report)
    )
    return PersistenceRequest(
        context=SubmissionCheckContext(report_check=ctx, page_checks=(page_input(ctx),)),
        originals=originals,
        artifacts=tuple(
            ArtifactPayload(
                binding=ArtifactBinding(source=original.source, artifact=artifact),
                content=original.content,
            )
            for original, doc in zip(originals, (ctx.guide, ctx.report), strict=True)
            for artifact in doc.artifacts
        ),
        response_json=response(),
        settings=ExecutionSettings(toolchain=(ToolDescriptor(name="offline", version="1"),)),
    )


def test_reopen_restores_exact_snapshot_and_payloads(tmp_path, request_data):
    # Given a complete real PDF request.
    path = tmp_path / "runs.sqlite3"
    with PersistenceStore(path) as store:
        saved = store.execute("project", request_data)
    # When a new store opens the committed database.
    with PersistenceStore(path) as store:
        restored = store.get_run(saved.run_id)
    # Then the complete immutable typed snapshot and binary bytes survive.
    assert restored == saved
    assert restored.request == request_data
    assert restored.status == "succeeded"
    assert restored.result is not None
    assert restored.result.stored is False
    assert restored.durable is True


def test_failed_retry_preserves_latest_success_and_history(tmp_path, request_data):
    # Given a successful run.
    with PersistenceStore(tmp_path / "runs.sqlite3") as store:
        first = store.execute("project", request_data)
        # When the following attempt has an invalid semantic response.
        failed = store.execute("project", request_data.model_copy(update={"response_json": "bad"}))
        # Then the failed attempt is retained without replacing the success.
        assert failed.status == "failed"
        assert failed.result is None
        assert failed.failure_code is not None
        assert failed.predecessor_run_id == first.run_id
        assert failed.sequence == 2
        assert store.latest_success("project") == first
        assert [run.run_id for run in store.list_runs("project")] == [first.run_id, failed.run_id]


@pytest.mark.parametrize(
    "part",
    ["original", "artifact", "missing", "duplicate", "extra", "nested", "coercion", "target"],
)
def test_invalid_payload_or_forged_model_is_rejected(tmp_path, request_data, part):
    original = request_data.originals[0]
    artifact = request_data.artifacts[0]
    changes = {
        "original": {
            "originals": (
                original.model_copy(update={"content": b"bad"}),
                *request_data.originals[1:],
            )
        },
        "artifact": {
            "artifacts": (
                artifact.model_copy(update={"content": b"bad"}),
                *request_data.artifacts[1:],
            )
        },
        "missing": {"artifacts": ()},
        "duplicate": {"originals": (*request_data.originals, original)},
        "extra": {"unexpected": "secret"},
        "nested": {"settings": request_data.settings.model_copy(update={"unexpected": "secret"})},
        "coercion": {
            "originals": (
                original.model_copy(
                    update={
                        "source": original.source.model_copy(
                            update={"byte_size": str(original.source.byte_size)}
                        )
                    }
                ),
                *request_data.originals[1:],
            )
        },
        "target": {
            "context": request_data.context.model_copy(
                update={
                    "page_checks": (
                        request_data.context.page_checks[0].model_copy(
                            update={
                                "target": request_data.context.page_checks[0].target.model_copy(
                                    update={
                                        "pdf": request_data.context.page_checks[
                                            0
                                        ].target.pdf.__class__(
                                            "normal.pdf", b"bad", original.source.role
                                        )
                                    }
                                )
                            }
                        ),
                    )
                }
            )
        },
    }
    with PersistenceStore(tmp_path / "runs.db") as store:
        with pytest.raises(PersistenceError) as error:
            store.execute("project", request_data.model_copy(update=changes[part]))
        assert error.value.code == PersistenceErrorCode.INVALID_INPUT
        assert store.list_runs("project") == ()


@pytest.mark.parametrize(
    "limit", ["max_total_bytes", "max_manifest_bytes", "max_payloads", "max_stored_bytes"]
)
def test_input_limits_leave_no_partial_run(tmp_path, request_data, limit):
    limits = PersistenceLimits.model_validate({limit: 1})
    with PersistenceStore(tmp_path / "runs.db", limits=limits) as store:
        with pytest.raises(PersistenceError) as error:
            store.execute("project", request_data)
        assert error.value.code == PersistenceErrorCode.INPUT_LIMIT
        assert store.list_runs("project") == ()


def test_capacity_rejection_preserves_existing_result(tmp_path, request_data):
    with PersistenceStore(tmp_path / "runs.db", limits=PersistenceLimits(max_runs=1)) as store:
        saved = store.execute("project", request_data)
        with pytest.raises(PersistenceError) as error:
            store.execute("other", request_data)
        assert error.value.code == PersistenceErrorCode.INPUT_LIMIT
        assert store.get_run(saved.run_id) == saved


def test_sql_failure_rolls_back_manifest_and_blobs(tmp_path, request_data):
    path = tmp_path / "runs.db"
    with PersistenceStore(path) as store:
        saved = store.execute("project", request_data)
        with closing(sqlite3.connect(path)) as connection, connection:
            connection.execute(
                "CREATE TRIGGER disk_failure BEFORE INSERT ON blobs "
                "BEGIN SELECT RAISE(ABORT, 'disk failure'); END"
            )
        with pytest.raises(PersistenceError) as error:
            store.execute("project", request_data)
        assert error.value.code == PersistenceErrorCode.STORAGE_ERROR
        assert store.latest_success("project") == saved
        assert len(store.list_runs("project")) == 1
        with closing(sqlite3.connect(path)) as connection:
            assert connection.execute("SELECT count(*) FROM blobs").fetchone()[0] == 2


@pytest.mark.parametrize("table", ["blobs", "runs"])
def test_corrupt_bytes_or_manifest_fails_closed(tmp_path, request_data, table):
    path = tmp_path / "runs.db"
    with PersistenceStore(path) as store:
        saved = store.execute("project", request_data)
        with closing(sqlite3.connect(path)) as connection, connection:
            if table == "blobs":
                connection.execute("UPDATE blobs SET content=?", (b"broken",))
            else:
                connection.execute("UPDATE runs SET manifest=?", ("{}",))
        with pytest.raises(PersistenceError) as error:
            store.get_run(saved.run_id)
        assert error.value.code == PersistenceErrorCode.CORRUPT_STORE


def test_unknown_schema_is_not_overwritten(tmp_path):
    path = tmp_path / "runs.db"
    with closing(sqlite3.connect(path)) as connection:
        connection.execute("PRAGMA user_version=99")
    before = path.read_bytes()
    with pytest.raises(PersistenceError) as error:
        PersistenceStore(path)
    assert error.value.code == PersistenceErrorCode.UNSUPPORTED_SCHEMA
    assert path.read_bytes() == before


def test_parallel_writers_receive_unique_ordered_attempts(tmp_path, request_data):
    path = tmp_path / "runs.db"
    with PersistenceStore(path) as store, ThreadPoolExecutor(max_workers=4) as executor:
        runs = tuple(executor.map(lambda _: store.execute("project", request_data), range(4)))
        history = store.list_runs("project")
    assert sorted(run.sequence for run in runs) == [1, 2, 3, 4]
    assert tuple(run.predecessor_run_id for run in history) == (
        None,
        *(run.run_id for run in history[:-1]),
    )


def test_empty_project_and_missing_run_are_explicit(tmp_path):
    with PersistenceStore(tmp_path / "runs.db") as store:
        assert store.latest_success("none") is None
        assert store.list_runs("none") == ()
        with pytest.raises(PersistenceError) as error:
            store.get_run("missing")
        assert error.value.code == PersistenceErrorCode.NOT_FOUND
        with pytest.raises(PersistenceError) as error:
            store.list_runs(" ")
        assert error.value.code == PersistenceErrorCode.INVALID_INPUT
