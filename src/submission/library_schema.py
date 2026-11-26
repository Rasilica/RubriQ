import os
import sqlite3
import stat
import sys
from collections.abc import Generator
from contextlib import closing, contextmanager
from pathlib import Path
from typing import Final

from pydantic import TypeAdapter, ValidationError

from submission.file_flags import READ_FLAGS
from submission.library_contracts import LibraryCode, LibraryError, LibraryLimits

APPLICATION_ID: Final = 1112753714


def private_path(path: Path) -> None:
    if not path.is_absolute() or any(parent.is_symlink() for parent in (path, *path.parents)):
        raise LibraryError(LibraryCode.UNAVAILABLE)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if not owner_only(path.parent.stat()):
        raise LibraryError(LibraryCode.UNAVAILABLE)
    descriptor = os.open(path, os.O_CREAT | os.O_RDWR | READ_FLAGS, 0o600)
    with os.fdopen(descriptor, "rb") as stream:
        details = os.fstat(stream.fileno())
        if not stat.S_ISREG(details.st_mode) or not owner_only(details) or details.st_nlink != 1:
            raise LibraryError(LibraryCode.UNAVAILABLE)


def owner_only(details: os.stat_result) -> bool:
    # shortcut: Windows has no POSIX owner or mode bits; the user profile ACL applies there.
    if sys.platform == "win32":
        return True
    return details.st_uid == os.getuid() and not details.st_mode & 0o077


def schema(connection: sqlite3.Connection) -> None:
    version = TypeAdapter(tuple[int]).validate_python(
        connection.execute("PRAGMA user_version").fetchone()
    )[0]
    marker = TypeAdapter(tuple[int]).validate_python(
        connection.execute("PRAGMA application_id").fetchone()
    )[0]
    tables = TypeAdapter(tuple[tuple[str], ...]).validate_python(
        connection.execute(
            "SELECT name FROM sqlite_master WHERE type IN ('table','view')"
        ).fetchall()
    )
    if version == 0 and marker == 0 and not tables:
        _ = connection.execute(
            """CREATE TABLE snapshots (
            saved_id TEXT PRIMARY KEY, project_name TEXT NOT NULL, saved_at TEXT NOT NULL,
            manifest TEXT NOT NULL, digest TEXT NOT NULL UNIQUE,
            guide_original BLOB NOT NULL, guide_pdf BLOB NOT NULL,
            report_original BLOB NOT NULL, report_pdf BLOB NOT NULL)"""
        )
        _ = connection.execute("PRAGMA application_id=1112753714")
        _ = connection.execute("PRAGMA user_version=1")
    elif version != 1 or marker != APPLICATION_ID or tables != (("snapshots",),):
        raise LibraryError(LibraryCode.CORRUPT)
    columns = TypeAdapter(tuple[tuple[str], ...]).validate_python(
        connection.execute("SELECT name FROM pragma_table_info('snapshots')").fetchall()
    )
    if tuple(item[0] for item in columns) != (
        "saved_id",
        "project_name",
        "saved_at",
        "manifest",
        "digest",
        "guide_original",
        "guide_pdf",
        "report_original",
        "report_pdf",
    ):
        raise LibraryError(LibraryCode.CORRUPT)
    extras = TypeAdapter(tuple[tuple[str], ...]).validate_python(
        connection.execute(
            """SELECT name FROM sqlite_master WHERE type='trigger'
            OR (type='index' AND sql IS NOT NULL)"""
        ).fetchall()
    )
    if extras:
        raise LibraryError(LibraryCode.CORRUPT)


def bounds(connection: sqlite3.Connection, limits: LibraryLimits) -> tuple[int, int]:
    count = TypeAdapter(tuple[int]).validate_python(
        connection.execute("SELECT count(*) FROM snapshots").fetchone()
    )[0]
    if count > limits.max_snapshots:
        raise LibraryError(LibraryCode.CORRUPT)
    invalid = TypeAdapter(tuple[int]).validate_python(
        connection.execute(
            """SELECT count(*) FROM snapshots WHERE
        typeof(saved_id)!='text' OR length(saved_id) NOT BETWEEN 1 AND 128 OR
            length(CAST(saved_id AS BLOB))>128 OR
        typeof(project_name)!='text' OR length(project_name) NOT BETWEEN 1 AND 120 OR
            length(CAST(project_name AS BLOB))>480 OR
        typeof(saved_at)!='text' OR length(saved_at) NOT BETWEEN 1 AND 64 OR
            length(CAST(saved_at AS BLOB))>64 OR
        typeof(digest)!='text' OR length(digest)!=64 OR
            length(CAST(digest AS BLOB))!=64 OR
        typeof(manifest)!='text' OR typeof(guide_original)!='blob' OR
            typeof(guide_pdf)!='blob' OR typeof(report_original)!='blob' OR
            typeof(report_pdf)!='blob'"""
        ).fetchone()
    )[0]
    if invalid:
        raise LibraryError(LibraryCode.CORRUPT)
    sizes = TypeAdapter(tuple[tuple[int, int, int, int, int], ...]).validate_python(
        connection.execute(
            """SELECT length(CAST(manifest AS BLOB)),length(guide_original),length(guide_pdf),
            length(report_original),length(report_pdf) FROM snapshots"""
        ).fetchall()
    )
    total = sum(sum(row) for row in sizes)
    if (
        len(sizes) > limits.max_snapshots
        or total > limits.max_total_bytes
        or any(sum(row) > limits.max_snapshot_bytes for row in sizes)
        or any(value > 10 * 1024 * 1024 for row in sizes for value in row[1:])
    ):
        raise LibraryError(LibraryCode.CORRUPT)
    return len(sizes), total


@contextmanager
def database(path: Path) -> Generator[sqlite3.Connection]:
    try:
        private_path(path)
        with closing(sqlite3.connect(path, timeout=5)) as connection, connection:
            _ = connection.execute("PRAGMA secure_delete=ON")
            _ = connection.execute("BEGIN IMMEDIATE")
            schema(connection)
            yield connection
    except (OSError, sqlite3.Error, ValidationError):
        raise LibraryError(LibraryCode.UNAVAILABLE) from None
