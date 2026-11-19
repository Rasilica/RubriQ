from pathlib import Path
from zipfile import ZipFile

import pytest
from export_public_source import export_public_source, public_files


def project(tmp_path: Path, entries: str = "README.md\nsrc/app.py\n") -> Path:
    (tmp_path / "tools").mkdir()
    (tmp_path / "tools/public-files.txt").write_text(entries)
    (tmp_path / "README.md").write_text("Public documentation")
    (tmp_path / "src").mkdir()
    (tmp_path / "src/app.py").write_text("print('RubriQ')")
    (tmp_path / ".env").write_text("PRIVATE=must-not-copy")
    (tmp_path / "src/new-private.txt").write_text("not reviewed")
    return tmp_path


def test_only_reviewed_files_are_exported_and_originals_are_preserved(tmp_path: Path) -> None:
    root = project(tmp_path)
    folder, archive = export_public_source(root)
    assert (root / ".env").read_text() == "PRIVATE=must-not-copy"
    assert sorted(p.relative_to(folder).as_posix() for p in folder.rglob("*") if p.is_file()) == [
        "README.md",
        "src/app.py",
    ]
    with ZipFile(archive) as zipped:
        assert sorted(zipped.namelist()) == ["RubriQ/README.md", "RubriQ/src/app.py"]
        assert zipped.read("RubriQ/src/app.py") == (root / "src/app.py").read_bytes()


@pytest.mark.parametrize(
    "entry",
    [
        "../secret",
        "/etc/passwd",
        "src/../README.md",
        ".env",
        "samples/private/os/report.docx",
        "_workspace/test-corpus/rules.tsv",
    ],
)
def test_unsafe_manifest_entries_are_rejected(tmp_path: Path, entry: str) -> None:
    with pytest.raises(ValueError, match="Unsafe public path"):
        public_files(project(tmp_path, entry))


def test_symlinked_files_and_directories_are_rejected(tmp_path: Path) -> None:
    root = project(tmp_path, "src/linked.txt")
    (root / "src/linked.txt").symlink_to(root / ".env")
    with pytest.raises(ValueError, match="Unsafe public path"):
        public_files(root)


def test_existing_export_is_never_overwritten(tmp_path: Path) -> None:
    root = project(tmp_path)
    folder, _ = export_public_source(root)
    (folder / "user-note.txt").write_text("preserve me")
    with pytest.raises(FileExistsError):
        export_public_source(root)
    assert (folder / "user-note.txt").read_text() == "preserve me"


def test_missing_reviewed_file_fails_before_creating_export(tmp_path: Path) -> None:
    root = project(tmp_path, "src/missing.txt")
    with pytest.raises(FileNotFoundError):
        export_public_source(root)
    assert not (root / "_release").exists()


@pytest.mark.parametrize("entries", ["", "README.md\nREADME.md"])
def test_empty_and_duplicate_manifests_are_rejected(tmp_path: Path, entries: str) -> None:
    with pytest.raises(ValueError, match="empty or duplicate"):
        public_files(project(tmp_path, entries))


def test_symlinked_parent_directory_is_rejected(tmp_path: Path) -> None:
    root = project(tmp_path, "linked/README.md")
    (root / "linked").symlink_to(root, target_is_directory=True)
    with pytest.raises(ValueError, match="Unsafe public path"):
        public_files(root)


@pytest.mark.parametrize(
    "destination", ["_release", "_release/RubriQ", "_release/RubriQ-source.zip"]
)
def test_symlinked_output_is_rejected(tmp_path: Path, destination: str) -> None:
    root = project(tmp_path)
    target = root / destination
    target.parent.mkdir(exist_ok=True)
    target.symlink_to(root / "missing-outside-target")
    with pytest.raises(ValueError, match="Unsafe public path"):
        export_public_source(root)
    assert not (root / "missing-outside-target").exists()
