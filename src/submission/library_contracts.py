from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import Field

from submission.models import FrozenModel
from submission.pair_contracts import PreparedRole, RoleView
from submission.semantic_contracts import SemanticArchive


class LibraryCode(StrEnum):
    NOT_FOUND = "library_not_found"
    CORRUPT = "library_corrupt"
    LIMIT = "library_limit"
    UNAVAILABLE = "library_unavailable"


class LibraryError(Exception):
    code: LibraryCode

    def __init__(self, code: LibraryCode) -> None:
        super().__init__(code.value)
        self.code = code


class LibraryLimits(FrozenModel):
    max_snapshot_bytes: Annotated[int, Field(gt=0)] = 256 * 1024 * 1024
    max_total_bytes: Annotated[int, Field(gt=0)] = 1024 * 1024 * 1024
    max_snapshots: Annotated[int, Field(gt=0)] = 100


class SavedSummary(FrozenModel):
    saved_id: Annotated[str, Field(min_length=1, max_length=128)]
    project_name: Annotated[str, Field(min_length=1, max_length=120)]
    saved_at: datetime


class SavedReceipt(SavedSummary):
    already_saved: bool
    has_semantic_archive: bool = False
    has_check: bool = False


class LibraryPage(FrozenModel):
    items: tuple[SavedSummary, ...]
    total: int
    page: int
    page_size: Literal[20] = 20


class SnapshotManifest(FrozenModel):
    semantic_archive: SemanticArchive | None = None
    version: Literal[1] = 1
    project_name: Annotated[str, Field(min_length=1, max_length=120)]
    guide: RoleView
    report: RoleView
    environment: Annotated[tuple[Annotated[str, Field(max_length=256)], ...], Field(max_length=64)]
    hashes: Annotated[tuple[str, ...], Field(min_length=4, max_length=4)]


@dataclass(frozen=True, slots=True)
class SavedPair:
    summary: SavedSummary
    guide: PreparedRole
    report: PreparedRole
    environment: tuple[str, ...]
    semantic_archive: SemanticArchive | None = None
