#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.13"
# dependencies = []
# ///
# ─── How to run ───
# From API: uv run tools/generate_format_fixtures.py
# Or use the project environment: .venv/bin/python tools/generate_format_fixtures.py
"""Generate deterministic boundary fixtures, never reader/rendering evidence.

본 제품은 한컴의 HWP 문서 파일(.hwp) 공개 문서를 참고하여 개발하였습니다.
The deliberately fixed CFB writer is fixture infrastructure, not a document writer.
"""

from __future__ import annotations

import hashlib
import json
import logging
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Final
from zipfile import ZIP_DEFLATED, ZIP_STORED, ZipFile, ZipInfo

ROOT: Final = Path(__file__).resolve().parents[1] / "samples" / "formats"
FREE: Final = 0xFFFFFFFF
END: Final = 0xFFFFFFFE
FAT: Final = 0xFFFFFFFD
HWP_TEXT: Final = "합성 HWP5 구조 위치 확인 문장."
LOGGER: Final = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class Directory:
    """The exact directory entries required by the fixed five-sector fixture."""

    name: str
    kind: int
    left: int = FREE
    right: int = FREE
    child: int = FREE
    start: int = 0
    size: int = 0
    color: int = 1


def directory_entry(entry: Directory) -> bytes:
    """Encode one MS-CFB 128-byte directory entry without mutable buffers."""
    name = (entry.name + "\0").encode("utf-16le") if entry.name else b""
    return (
        name.ljust(64, b"\0")
        + struct.pack(
            "<HBBIII", len(name), entry.kind, entry.color, entry.left, entry.right, entry.child
        )
        + bytes(36)
        + struct.pack("<IQ", entry.start, entry.size)
    )


def record(tag: int, level: int, payload: bytes) -> bytes:
    """Encode a short HWP record with its size, nesting level, and tag ID."""
    return struct.pack("<I", tag | level << 10 | len(payload) << 20) + payload


def build_hwp() -> bytes:
    """Build only the documented boundary streams, not full document styling."""
    file_header = b"HWP Document File".ljust(32, b"\0")
    file_header += struct.pack("<II", 0x05010100, 0) + bytes(216)
    properties = struct.pack("<7H3I", 1, 1, 1, 1, 1, 1, 1, 0, 0, 0)
    doc_info = record(16, 0, properties)
    text = (HWP_TEXT + "\r").encode("utf-16le")
    paragraph = struct.pack("<IIHBBHHHIH", len(text) // 2, 0, 0, 0, 0, 1, 0, 0, 1, 0)
    section = record(66, 0, paragraph) + record(67, 1, text)
    section += record(68, 1, struct.pack("<II", 0, 0))
    mini_stream = file_header + doc_info.ljust(64, b"\0") + section.ljust(128, b"\0")
    entries = (
        Directory("Root Entry", 5, child=2, start=3, size=len(mini_stream)),
        Directory("DocInfo", 2, start=4, size=len(doc_info), color=0),
        Directory("BodyText", 1, left=1, right=3, child=4),
        Directory("FileHeader", 2, start=0, size=len(file_header), color=0),
        Directory("Section0", 2, start=5, size=len(section)),
        *(Directory("", 0, color=0) for _ in range(3)),
    )
    return fixed_compound(entries, (1, 2, 3, END, END, 6, END), mini_stream)


def fixed_compound(
    entries: tuple[Directory, ...], mini_chain: tuple[int, ...], mini_stream: bytes
) -> bytes:
    """Encode the shared five-sector CFB layout for these bounded fixtures only."""
    header = bytes.fromhex("d0cf11e0a1b11ae1") + bytes(16)
    header += struct.pack("<5H", 0x003E, 3, 0xFFFE, 9, 6) + bytes(6)
    header += struct.pack("<9I", 0, 1, 0, 0, 4096, 2, 1, END, 0)
    header += struct.pack("<109I", 4, *([FREE] * 108))
    mini_fat = struct.pack("<128I", *mini_chain, *([FREE] * (128 - len(mini_chain))))
    fat = struct.pack("<128I", 1, END, END, END, FAT, *([FREE] * 123))
    return (
        header
        + b"".join(directory_entry(entry) for entry in entries)
        + mini_fat
        + mini_stream.ljust(512, b"\0")
        + fat
    )


def build_encrypted_placeholder() -> bytes:
    """Name the encryption streams without constructing encrypted document content."""
    encryption_info = b"SYNTHETIC-NOT-ENCRYPTION"
    encrypted_package = b"UNDECRYPTABLE-PLACEHOLDER"
    mini_stream = encryption_info.ljust(64, b"\0") + encrypted_package.ljust(64, b"\0")
    entries = (
        Directory("Root Entry", 5, child=1, start=3, size=len(mini_stream)),
        Directory("EncryptionInfo", 2, right=2, start=0, size=len(encryption_info)),
        Directory("EncryptedPackage", 2, start=1, size=len(encrypted_package), color=0),
        *(Directory("", 0, color=0) for _ in range(5)),
    )
    return fixed_compound(entries, (END, END), mini_stream)


def write_package(source: str, output: str) -> None:
    """Package authored XML with fixed timestamps; keep HWPX mimetype first."""
    directory = ROOT / "sources" / source
    paths = sorted(directory.rglob("*"), key=lambda path: (path.name != "mimetype", path))
    with ZipFile(ROOT / output, "w") as archive:
        for path in paths:
            if path.is_file():
                member = path.relative_to(directory).as_posix()
                info = ZipInfo(member, date_time=(1980, 1, 1, 0, 0, 0))
                info.compress_type = ZIP_STORED if member == "mimetype" else ZIP_DEFLATED
                info.create_system = 3
                info.external_attr = 0o100644 << 16
                data = path.read_bytes()
                archive.writestr(info, data.rstrip(b"\r\n") if member == "mimetype" else data)


def main() -> None:
    """Write boundary fixtures and hashes; preserve the authored locator truth."""
    ROOT.mkdir(parents=True, exist_ok=True)
    write_package("docx", "boundary.docx")
    write_package("hwpx", "spine-order.hwpx")
    _ = (ROOT / "minimal-5.1.1.0.hwp").write_bytes(build_hwp())
    _ = (ROOT / "encrypted-ooxml.cfb").write_bytes(build_encrypted_placeholder())
    specs = (
        ("pdf-baseline", "../pdf/guide.pdf", "pdf", "PDF-1.3", "before-submit-development-001"),
        (
            "docx-boundary",
            "boundary.docx",
            "docx",
            "OOXML Transitional 2006",
            "format-boundary-001",
        ),
        ("hwpx-spine", "spine-order.hwpx", "hwpx", "5.1.1.0 / XML 1.5", "format-boundary-001"),
        ("hwp5-boundary", "minimal-5.1.1.0.hwp", "hwp", "5.1.1.0", "format-boundary-001"),
        ("encrypted-ooxml-boundary", "encrypted-ooxml.cfb", "unknown", None, "format-boundary-001"),
    )
    documents = [
        {
            "id": doc_id,
            "path": filename,
            "format": format_name,
            "version": version,
            "family_id": family,
            "sha256": hashlib.sha256((ROOT / filename).read_bytes()).hexdigest(),
            "size_bytes": (ROOT / filename).stat().st_size,
            "provenance": "synthetic_development_fixture",
            "authoring_application": None,
            "human_review_completed": False,
            "independent_evaluation": False,
            "authored_app_original": False,
            "rendering_verified": False,
            "full_document_reader_verified": False,
        }
        for doc_id, filename, format_name, version, family in specs
    ]
    manifest = {
        "schema_version": 1,
        "usage": "container_boundary_development_only",
        "generator": "tools/generate_format_fixtures.py",
        "documents": documents,
    }
    _ = (ROOT / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    for document in documents:
        LOGGER.info("Generated/reference %s sha256=%s", document["path"], document["sha256"])


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
