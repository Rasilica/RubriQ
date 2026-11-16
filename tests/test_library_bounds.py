import sqlite3
from contextlib import closing
from dataclasses import replace
from pathlib import Path

import pytest

from submission.library_contracts import LibraryCode, LibraryError, LibraryLimits
from submission.library_store import LibraryStore
from submission.pair_store import Session
from tests.test_library import make_session


@pytest.fixture
def session(text_pdf: bytes) -> Session:
    return make_session(text_pdf)


@pytest.mark.parametrize(
    "mutation",
    [
        "UPDATE snapshots SET guide_original=CAST(guide_original AS TEXT)",
        "UPDATE snapshots SET guide_pdf=zeroblob(10485761)",
        "ALTER TABLE snapshots RENAME COLUMN guide_pdf TO wrong",
        "CREATE TRIGGER custom AFTER DELETE ON snapshots BEGIN SELECT 1; END",
    ],
)
def test_store_bounds_and_schema(tmp_path: Path, session: Session, mutation: str) -> None:
    store = LibraryStore(tmp_path / "library.sqlite3")
    saved = store.save(session, ())
    with closing(sqlite3.connect(store.path)) as connection, connection:
        _ = connection.execute(mutation)
    with pytest.raises(LibraryError, match=LibraryCode.CORRUPT):
        _ = store.load(saved.saved_id)


def test_pagination_and_existing_bounds(tmp_path: Path, session: Session) -> None:
    store = LibraryStore(tmp_path / "library.sqlite3")
    for index in range(21):
        _ = store.save(replace(session, project=str(index)), ())
    assert len(store.list(1).items) == 20
    assert len(store.list(2).items) == 1
    assert store.list(1).items[0].project_name == "20"
    smaller = LibraryStore(store.path, LibraryLimits(max_snapshots=20))
    with pytest.raises(LibraryError, match=LibraryCode.CORRUPT):
        _ = smaller.list(1)
    smaller = LibraryStore(store.path, LibraryLimits(max_total_bytes=1))
    with pytest.raises(LibraryError, match=LibraryCode.CORRUPT):
        _ = smaller.list(1)


def test_public_parent_rejected(tmp_path: Path, session: Session) -> None:
    parent = tmp_path / "public"
    parent.mkdir(mode=0o755)
    with pytest.raises(LibraryError, match=LibraryCode.UNAVAILABLE):
        _ = LibraryStore(parent / "library.sqlite3").save(session, ())
