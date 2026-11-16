import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from dataclasses import replace
from pathlib import Path
from time import monotonic

import pytest

import submission.library_store as library_module
from submission.input_contracts import DocumentInput
from submission.library_contracts import LibraryCode, LibraryError, LibraryLimits
from submission.library_store import LibraryStore
from submission.models import DocumentRole
from submission.pair_contracts import PairRuntime
from submission.pair_prepare import prepare_role
from submission.pair_store import PairStore, Session


def make_session(text_pdf: bytes) -> Session:
    return PairStore().create(
        "보관",
        prepare_role(
            DocumentInput("g.pdf", text_pdf, DocumentRole.GUIDE),
            PairRuntime(),
            monotonic() + 10,
        ),
        prepare_role(
            DocumentInput("r.pdf", text_pdf, DocumentRole.REPORT), PairRuntime(), monotonic() + 10
        ),
    )


@pytest.fixture
def session(text_pdf: bytes) -> Session:
    return make_session(text_pdf)


def test_corruption_rejected_before_restore(tmp_path: Path, session: Session) -> None:
    store = LibraryStore(tmp_path / "library.sqlite3")
    saved = store.save(session, ())
    with closing(sqlite3.connect(store.path)) as connection, connection:
        _ = connection.execute("UPDATE snapshots SET guide_original=?", (b"wrong",))
    with pytest.raises(LibraryError, match=LibraryCode.CORRUPT):
        _ = store.load(saved.saved_id)


@pytest.mark.parametrize(
    "mutation",
    [
        "UPDATE snapshots SET manifest='{}'",
        "UPDATE snapshots SET digest='bad'",
        "UPDATE snapshots SET project_name='wrong'",
        "PRAGMA user_version=999",
    ],
)
def test_metadata_corruption(tmp_path: Path, session: Session, mutation: str) -> None:
    store = LibraryStore(tmp_path / "library.sqlite3")
    saved = store.save(session, ())
    with closing(sqlite3.connect(store.path)) as connection, connection:
        _ = connection.execute(mutation)
    with pytest.raises(LibraryError):
        _ = store.load(saved.saved_id)


def test_transaction_error_preserves_previous(
    tmp_path: Path, session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = LibraryStore(tmp_path / "library.sqlite3")
    saved = store.save(session, ())

    def collision(_size: int | None = None) -> str:
        return saved.saved_id

    monkeypatch.setattr(library_module, "token_urlsafe", collision)
    with pytest.raises(LibraryError, match=LibraryCode.UNAVAILABLE):
        _ = store.save(replace(session, project="new"), ())
    assert store.load(saved.saved_id).guide == session.guide
    assert store.list(1).total == 1


def test_count_and_total_limits_preserve_previous(tmp_path: Path, session: Session) -> None:
    store = LibraryStore(tmp_path / "library.sqlite3", LibraryLimits(max_snapshots=1))
    saved = store.save(session, ())
    with pytest.raises(LibraryError, match=LibraryCode.LIMIT):
        _ = store.save(replace(session, project="new"), ())
    assert store.load(saved.saved_id).guide == session.guide
    limited = LibraryStore(tmp_path / "other.sqlite3", LibraryLimits(max_total_bytes=1))
    with pytest.raises(LibraryError, match=LibraryCode.LIMIT):
        _ = limited.save(session, ())
    assert limited.list(1).total == 0


def test_parallel_save_and_delete_read(tmp_path: Path, session: Session) -> None:
    store = LibraryStore(tmp_path / "library.sqlite3")
    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = tuple(executor.submit(store.save, session, ()) for _ in range(8))
        receipts = tuple(future.result() for future in futures)
    assert len({item.saved_id for item in receipts}) == 1
    assert sum(not item.already_saved for item in receipts) == 1
    saved_id = receipts[0].saved_id
    with ThreadPoolExecutor(max_workers=2) as executor:
        read = executor.submit(store.load, saved_id)
        delete = executor.submit(store.delete, saved_id)
        if read.exception() is None:
            assert read.result().guide == session.guide
        else:
            with pytest.raises(LibraryError, match=LibraryCode.NOT_FOUND):
                _ = read.result()
        assert delete.result() is None
    assert store.list(1).total == 0


def test_symlink_and_permissions(tmp_path: Path, session: Session) -> None:
    target = tmp_path / "target"
    _ = target.write_bytes(b"untouched")
    link = tmp_path / "link.sqlite3"
    link.symlink_to(target)
    with pytest.raises(LibraryError, match=LibraryCode.UNAVAILABLE):
        _ = LibraryStore(link).save(session, ())
    assert target.read_bytes() == b"untouched"
    path = tmp_path / "open.sqlite3"
    path.touch(mode=0o644)
    with pytest.raises(LibraryError, match=LibraryCode.UNAVAILABLE):
        _ = LibraryStore(path).save(session, ())


def test_unusable_and_wrong_hash_are_not_saved(tmp_path: Path, session: Session) -> None:
    store = LibraryStore(tmp_path / "library.sqlite3")
    bad = replace(session.guide, original=b"tamper")
    with pytest.raises(LibraryError, match=LibraryCode.CORRUPT):
        _ = store.save(replace(session, guide=bad), ())
    with pytest.raises(LibraryError):
        store.delete("missing")
    with pytest.raises(LibraryError):
        _ = store.list(0)
    assert not store.path.exists()


def test_failed_original_is_preserved_but_no_usable_pair_rejected(
    tmp_path: Path, session: Session
) -> None:
    failed = prepare_role(
        DocumentInput("bad.pdf", b"broken-original", DocumentRole.GUIDE),
        PairRuntime(),
        monotonic() + 10,
    )
    store = LibraryStore(tmp_path / "library.sqlite3")
    saved = store.save(replace(session, guide=failed), ())
    restored = store.load(saved.saved_id)
    assert restored.guide.original == b"broken-original"
    assert restored.guide.view.document is None
    with closing(sqlite3.connect(store.path)) as connection, connection:
        _ = connection.execute("UPDATE snapshots SET guide_original=?", (b"changed-original",))
    with pytest.raises(LibraryError, match=LibraryCode.CORRUPT):
        _ = store.load(saved.saved_id)
    failed_report = prepare_role(
        DocumentInput("bad.pdf", b"broken-original", DocumentRole.REPORT),
        PairRuntime(),
        monotonic() + 10,
    )
    with pytest.raises(LibraryError, match=LibraryCode.CORRUPT):
        _ = LibraryStore(tmp_path / "second.sqlite3").save(
            replace(session, guide=failed, report=failed_report), ()
        )


def test_roundtrip_restart_idempotent_and_delete(tmp_path: Path, text_pdf: bytes) -> None:
    first = prepare_role(
        DocumentInput("g.pdf", text_pdf, DocumentRole.GUIDE), PairRuntime(), monotonic() + 10
    )
    second = prepare_role(
        DocumentInput("r.pdf", text_pdf, DocumentRole.REPORT), PairRuntime(), monotonic() + 10
    )
    session = PairStore().create("보관 시험", first, second)
    path = tmp_path / "private" / "library.sqlite3"
    store = LibraryStore(path)
    saved = store.save(session, ())
    again = store.save(session, ())
    assert again.saved_id == saved.saved_id
    assert again.already_saved
    restarted = LibraryStore(path)
    restored = restarted.load(saved.saved_id)
    assert restored.guide == first
    assert restored.report == second
    assert restarted.list(1).total == 1
    assert path.stat().st_mode & 0o777 == 0o600
    restarted.delete(saved.saved_id)
    assert restarted.list(1).total == 0
    with pytest.raises(LibraryError):
        _ = restarted.load(saved.saved_id)


def test_limit_does_not_create_snapshot(tmp_path: Path, text_pdf: bytes) -> None:
    first = prepare_role(
        DocumentInput("g.pdf", text_pdf, DocumentRole.GUIDE), PairRuntime(), monotonic() + 10
    )
    second = prepare_role(
        DocumentInput("r.pdf", text_pdf, DocumentRole.REPORT), PairRuntime(), monotonic() + 10
    )
    store = LibraryStore(
        tmp_path / "private" / "library.sqlite3", LibraryLimits(max_snapshot_bytes=1)
    )
    with pytest.raises(LibraryError):
        _ = store.save(PairStore().create("large", first, second), ())
    assert store.list(1).total == 0
