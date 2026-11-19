# This is a standalone maintenance script, not an importable application package.
# ruff: noqa: INP001
from pathlib import Path, PurePosixPath
from shutil import copy2, move
from tempfile import TemporaryDirectory
from typing import Final
from zipfile import ZIP_DEFLATED, ZipFile

PRIVATE_PARTS: Final = frozenset(
    {
        ".git",
        ".omo",
        ".runtime",
        ".venv",
        "__pycache__",
        "contest",
        "java",
        "private",  # samples/private: redacted real documents, internal tests only
        "_workspace",
    }
)
PRIVATE_SUFFIXES: Final = (".pyc", ".sqlite", ".sqlite3", ".db", ".key", ".pem", ".oxt")
ROOT_FILES: Final = frozenset(
    {
        "README.md",
        "LICENSE",
        "NOTICE",
        "THIRD_PARTY_NOTICES.md",
        "pyproject.toml",
        "uv.lock",
        ".gitignore",
        ".gitattributes",
    }
)


class UnsafePublicPathError(ValueError):
    path: str

    def __init__(self, path: str) -> None:
        self.path = path
        super().__init__(f"Unsafe public path: {path}")


def public_files(root: Path) -> tuple[Path, ...]:
    entries = (root / "tools/public-files.txt").read_text().splitlines()
    files: list[Path] = []
    for entry in entries:
        if not entry or entry.startswith("#"):
            continue
        relative = PurePosixPath(entry)
        if (
            relative.is_absolute()
            or relative.as_posix() != entry
            or ".." in relative.parts
            or (len(relative.parts) == 1 and entry not in ROOT_FILES)
            or "\\" in entry
            or PRIVATE_PARTS.intersection(relative.parts)
            or any(part.startswith(".env") for part in relative.parts)
            or entry.endswith(PRIVATE_SUFFIXES)
            or any(
                root.joinpath(*relative.parts[:i]).is_symlink()
                for i in range(1, len(relative.parts) + 1)
            )
        ):
            raise UnsafePublicPathError(entry)
        source = root / relative
        if not source.is_file():
            raise FileNotFoundError(source)
        files.append(source)
    if not files or len(files) != len(set(files)):
        message = "empty or duplicate manifest"
        raise UnsafePublicPathError(message)
    return tuple(files)


def export_public_source(root: Path) -> tuple[Path, Path]:
    files = public_files(root)
    output = root / "_release"
    folder, archive = output / "RubriQ", output / "RubriQ-source.zip"
    if any(path.is_symlink() for path in (output, folder, archive)):
        raise UnsafePublicPathError(output.name)
    if folder.exists() or archive.exists():
        message = "Existing public export must be reviewed before replacement"
        raise FileExistsError(message)
    output.mkdir(exist_ok=True)
    with TemporaryDirectory(prefix="public-", dir=output) as temporary:
        stage = Path(temporary) / "RubriQ"
        bundle = Path(temporary) / archive.name
        with ZipFile(bundle, "w", compression=ZIP_DEFLATED) as zipped:
            for source in files:
                relative = source.relative_to(root)
                destination = stage / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                _ = copy2(source, destination)
                zipped.write(destination, arcname=f"RubriQ/{relative.as_posix()}")
        _ = move(stage, folder)
        _ = move(bundle, archive)
    return folder, archive


if __name__ == "__main__":
    for path in export_public_source(Path(__file__).resolve().parents[1]):
        print(path)  # noqa: T201
