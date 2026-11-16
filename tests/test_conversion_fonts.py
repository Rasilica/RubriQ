import time
from hashlib import sha256
from pathlib import Path

import pytest

from submission import conversion_fonts
from submission.conversion_contracts import FontManifest
from submission.conversion_fonts import collect_fonts, discover_fonts, measure_font


def test_font_inventory_is_ordered_and_measured(tmp_path: Path) -> None:
    first = tmp_path / "a"
    second = tmp_path / "b"
    first.mkdir()
    second.mkdir()
    (second / "z.ttf").write_bytes(b"font z")
    (first / "a.otf").write_bytes(b"font a")
    (first / "other.txt").write_bytes(b"ignored")

    manifest = collect_fonts(("/Helvetica",), time.monotonic() + 5, (second, first))

    assert tuple(entry.sha256 for entry in manifest.inventory) == (
        sha256(b"font a").hexdigest(),
        sha256(b"font z").hexdigest(),
    )
    assert manifest == collect_fonts(("/Helvetica",), time.monotonic() + 5, (first, second))
    assert FontManifest.model_validate_json(manifest.model_dump_json()) == manifest


def test_content_change_changes_manifest_digest(tmp_path: Path) -> None:
    font = tmp_path / "a.ttf"
    font.write_bytes(b"first")
    before = collect_fonts((), time.monotonic() + 5, (tmp_path,))
    font.write_bytes(b"changed")

    after = collect_fonts((), time.monotonic() + 5, (tmp_path,))

    assert (
        sha256(before.model_dump_json().encode()).digest()
        != sha256(after.model_dump_json().encode()).digest()
    )


def test_missing_symlink_and_size_limits_remain_partial(tmp_path: Path) -> None:
    font = tmp_path / "a.ttf"
    font.write_bytes(b"font")
    link = tmp_path / "link.ttf"
    link.symlink_to(font)
    missing = tmp_path / "missing"

    manifest = collect_fonts((), time.monotonic() + 5, (tmp_path, missing))

    assert manifest.inventory_complete is False
    assert str(link) in manifest.unavailable_or_skipped
    assert str(missing) in manifest.unavailable_or_skipped
    assert measure_font(font, 2) is None
    assert measure_font(missing, 100) is None


def test_expired_inventory_records_skipped_root(tmp_path: Path) -> None:
    font = tmp_path / "a.ttf"
    font.write_bytes(b"font")

    manifest = collect_fonts((), time.monotonic() - 1, (tmp_path,))

    assert not manifest.inventory
    assert manifest.unavailable_or_skipped == (str(tmp_path),)


def test_directory_enumeration_stops_at_budget(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for number in range(10):
        (tmp_path / f"font{number}.ttf").write_bytes(b"font")
    monkeypatch.setattr(conversion_fonts, "MAX_DIRECTORY_ENTRIES", 2)

    paths, complete = discover_fonts(tmp_path, time.monotonic() + 5)

    assert len(paths) == 2
    assert complete is False


def test_inventory_count_stops_with_bounded_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for number in range(10):
        (tmp_path / f"font{number}.ttf").write_bytes(b"font")
    monkeypatch.setattr(conversion_fonts, "MAX_FILES", 1)

    manifest = collect_fonts((), time.monotonic() + 5, (tmp_path,))

    assert len(manifest.inventory) == 1
    assert manifest.unavailable_or_skipped == (str(tmp_path),)
