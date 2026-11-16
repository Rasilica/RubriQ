from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from secrets import token_urlsafe
from typing import final

from pydantic import TypeAdapter, ValidationError

from submission.library_contracts import (
    LibraryCode,
    LibraryError,
    LibraryLimits,
    LibraryPage,
    SavedPair,
    SavedReceipt,
    SavedSummary,
    SnapshotManifest,
)
from submission.library_schema import bounds, database
from submission.library_validation import check, validate_role
from submission.models import DocumentRole
from submission.pair_contracts import PreparedRole
from submission.pair_store import Session
from submission.report_check_contracts import ReportCheckError
from submission.requirement_contracts import RequirementError
from submission.semantic_archive import capture, validate_archive


def encode(manifest: SnapshotManifest) -> str:
    return manifest.model_dump_json(
        exclude_computed_fields=True,
        exclude={"semantic_archive"} if manifest.semantic_archive is None else set(),
    )


def digest(manifest: SnapshotManifest) -> str:
    return sha256(encode(manifest).encode()).hexdigest()


def make_manifest(session: Session, environment: tuple[str, ...]) -> SnapshotManifest:
    validate_role(session.guide, DocumentRole.GUIDE)
    validate_role(session.report, DocumentRole.REPORT)
    check(session.guide.available or session.report.available)
    archive = capture(session)
    try:
        validate_archive(archive, session.guide, session.report)
    except (ReportCheckError, RequirementError):
        raise LibraryError(LibraryCode.CORRUPT) from None
    return SnapshotManifest(
        semantic_archive=archive,
        project_name=session.project,
        guide=session.guide.view,
        report=session.report.view,
        environment=environment,
        hashes=tuple(sha256(value).hexdigest() for value in payloads(session)),
    )


def payloads(session: Session) -> tuple[bytes, bytes, bytes, bytes]:
    return (
        session.guide.original,
        session.guide.pdf or b"",
        session.report.original,
        session.report.pdf or b"",
    )


@final
class LibraryStore:
    def __init__(self, path: Path, limits: LibraryLimits | None = None) -> None:
        self.path = path
        self.limits = limits or LibraryLimits()

    def save(self, session: Session, environment: tuple[str, ...]) -> SavedReceipt:
        if session.size > self.limits.max_snapshot_bytes:
            raise LibraryError(LibraryCode.LIMIT)
        manifest = make_manifest(session, environment)
        encoded = encode(manifest)
        size = len(encoded.encode()) + sum(len(value) for value in payloads(session))
        identity = digest(manifest)
        if size > self.limits.max_snapshot_bytes:
            raise LibraryError(LibraryCode.LIMIT)
        with database(self.path) as connection:
            count, total = bounds(connection, self.limits)
            rows = TypeAdapter(tuple[tuple[str, str, datetime], ...]).validate_python(
                connection.execute(
                    "SELECT saved_id,project_name,saved_at FROM snapshots WHERE digest=?",
                    (identity,),
                ).fetchall()
            )
            if rows:
                identifier, project, saved_at = rows[0]
                return SavedReceipt(
                    saved_id=identifier,
                    project_name=project,
                    saved_at=saved_at,
                    already_saved=True,
                    has_semantic_archive=manifest.semantic_archive is not None,
                    has_check=manifest.semantic_archive is not None
                    and manifest.semantic_archive.check is not None,
                )
            if count >= self.limits.max_snapshots or total + size > self.limits.max_total_bytes:
                raise LibraryError(LibraryCode.LIMIT)
            summary = SavedReceipt(
                saved_id=token_urlsafe(24),
                project_name=session.project,
                saved_at=datetime.now(UTC),
                already_saved=False,
                has_semantic_archive=manifest.semantic_archive is not None,
                has_check=manifest.semantic_archive is not None
                and manifest.semantic_archive.check is not None,
            )
            _ = connection.execute(
                "INSERT INTO snapshots VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    summary.saved_id,
                    summary.project_name,
                    summary.saved_at.isoformat(),
                    encoded,
                    identity,
                    *payloads(session),
                ),
            )
            return summary

    def list(self, page: int) -> LibraryPage:
        if page < 1:
            raise LibraryError(LibraryCode.CORRUPT)
        if not self.path.exists():
            return LibraryPage(items=(), total=0, page=page)
        with database(self.path) as connection:
            count, _ = bounds(connection, self.limits)
            rows = TypeAdapter(tuple[tuple[str, str, datetime], ...]).validate_python(
                connection.execute(
                    """SELECT saved_id,project_name,saved_at FROM snapshots
                    ORDER BY saved_at DESC,saved_id DESC LIMIT 20 OFFSET ?""",
                    ((page - 1) * 20,),
                ).fetchall()
            )
            return LibraryPage(
                items=tuple(
                    SavedSummary(saved_id=identifier, project_name=project, saved_at=date)
                    for identifier, project, date in rows
                ),
                total=count,
                page=page,
            )

    def load(self, identifier: str) -> SavedPair:
        if not self.path.exists():
            raise LibraryError(LibraryCode.NOT_FOUND)
        with database(self.path) as connection:
            _ = bounds(connection, self.limits)
            rows = TypeAdapter(
                tuple[tuple[str, datetime, str, str, bytes, bytes, bytes, bytes], ...]
            ).validate_python(
                connection.execute(
                    """SELECT project_name,saved_at,manifest,digest,guide_original,
                    guide_pdf,report_original,report_pdf FROM snapshots WHERE saved_id=?""",
                    (identifier,),
                ).fetchall()
            )
        if not rows:
            raise LibraryError(LibraryCode.NOT_FOUND)
        project, date, encoded, identity, first, first_pdf, second, second_pdf = rows[0]
        try:
            manifest = SnapshotManifest.model_validate_json(encoded)
            check(digest(manifest) == identity and project == manifest.project_name)
            check(
                manifest.hashes
                == tuple(
                    sha256(value).hexdigest() for value in (first, first_pdf, second, second_pdf)
                )
            )
            guide = PreparedRole(manifest.guide, first, first_pdf or None)
            report = PreparedRole(manifest.report, second, second_pdf or None)
            validate_role(guide, DocumentRole.GUIDE)
            validate_role(report, DocumentRole.REPORT)
            check(guide.available or report.available)
            validate_archive(manifest.semantic_archive, guide, report)
        except (ValidationError, ReportCheckError, RequirementError):
            raise LibraryError(LibraryCode.CORRUPT) from None
        return SavedPair(
            SavedSummary(saved_id=identifier, project_name=project, saved_at=date),
            guide,
            report,
            manifest.environment,
            manifest.semantic_archive,
        )

    def delete(self, identifier: str) -> None:
        if not self.path.exists():
            raise LibraryError(LibraryCode.NOT_FOUND)
        with database(self.path) as connection:
            cursor = connection.execute("DELETE FROM snapshots WHERE saved_id=?", (identifier,))
            if not cursor.rowcount:
                raise LibraryError(LibraryCode.NOT_FOUND)
