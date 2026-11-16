import os
import time
from hashlib import sha256
from pathlib import Path
from typing import Final

from submission.conversion_contracts import FontManifest, FontRecord

FONT_ROOTS: Final = (
    Path("/System/Library/Fonts"),
    Path("/Library/Fonts"),
    Path.home() / "Library/Fonts",
    Path("/Applications/LibreOffice.app/Contents/Resources/fonts/truetype"),
    Path("/usr/share/fonts"),
    Path("/usr/local/share/fonts"),
    Path.home() / ".local/share/fonts",
)
MAX_FILES: Final = 512
MAX_FONT_BYTES: Final = 32 * 1024 * 1024
MAX_TOTAL_BYTES: Final = 128 * 1024 * 1024
MAX_DIRECTORY_ENTRIES: Final = 4096
NO_DEADLINE: Final = float("inf")


def discover_fonts(root: Path, deadline: float) -> tuple[tuple[Path, ...], bool]:
    pending = [root]
    found: list[Path] = []
    visited = 0
    while pending:
        directory = pending.pop()
        try:
            with os.scandir(directory) as entries:
                for entry in entries:
                    visited += 1
                    if visited > MAX_DIRECTORY_ENTRIES or time.monotonic() >= deadline:
                        return tuple(sorted(found)), False
                    if entry.is_dir(follow_symlinks=False):
                        pending.append(Path(entry.path))
                    elif Path(entry.name).suffix.lower() in {".ttf", ".otf", ".ttc", ".dfont"}:
                        found.append(Path(entry.path))
        except OSError:
            return tuple(sorted(found)), False
    return tuple(sorted(found)), True


def measure_font(path: Path, remaining: int, deadline: float = NO_DEADLINE) -> FontRecord | None:
    try:
        size = path.stat().st_size
        if path.is_symlink() or not path.is_file() or size > min(MAX_FONT_BYTES, remaining):
            return None
        digest = sha256()
        total = 0
        with path.open("rb") as stream:
            while chunk := stream.read(65536):
                total += len(chunk)
                if total > min(MAX_FONT_BYTES, remaining) or time.monotonic() >= deadline:
                    return None
                digest.update(chunk)
        return FontRecord(location=str(path), byte_size=total, sha256=digest.hexdigest())
    except OSError:
        return None


def collect_fonts(
    names: tuple[str, ...], deadline: float, roots: tuple[Path, ...] = FONT_ROOTS
) -> FontManifest:
    records: list[FontRecord] = []
    skipped: list[str] = []
    total = 0
    for root in sorted(roots):
        if time.monotonic() >= deadline or len(records) >= MAX_FILES or total >= MAX_TOTAL_BYTES:
            skipped.append(str(root))
            break
        if not root.is_dir() or root.is_symlink():
            skipped.append(str(root))
            continue
        paths, complete = discover_fonts(root, deadline)
        if not complete:
            skipped.append(str(root))
        for path in paths:
            if (
                time.monotonic() >= deadline
                or len(records) >= MAX_FILES
                or total >= MAX_TOTAL_BYTES
            ):
                skipped.append(str(root))
                break
            record = measure_font(path, MAX_TOTAL_BYTES - total, deadline)
            if record is None:
                skipped.append(str(path))
                continue
            total += record.byte_size
            records.append(record)
    return FontManifest(
        declared_roots=tuple(str(root) for root in sorted(roots)),
        unavailable_or_skipped=tuple(skipped),
        inventory=tuple(records),
        rendered_pdf_font_names=names,
    )
