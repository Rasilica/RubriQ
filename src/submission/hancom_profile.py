import os
import stat
import time
from collections.abc import Generator, Iterator
from contextlib import ExitStack, closing
from hashlib import sha256
from pathlib import Path
from typing import Final
from xml.etree.ElementTree import ParseError

from defusedxml.common import DefusedXmlException
from defusedxml.ElementTree import fromstring
from pydantic import TypeAdapter

from submission.conversion_contracts import ConversionError, ConversionErrorCode
from submission.conversion_profile import PROFILE_SETTINGS
from submission.hancom_contracts import HancomProvision, ProfileFile, RuntimeFile

MAX_ENTRIES: Final = 4096
MAX_PROFILE_BYTES: Final = 128 * 1024 * 1024
MAX_FILE_BYTES: Final = 64 * 1024 * 1024
MAX_RUNTIME_BYTES: Final = 256 * 1024 * 1024
MAX_DIRECTORY_DEPTH: Final = 64
CHUNK_BYTES: Final = 1024 * 1024
DESCRIPTION_NS: Final = "{http://openoffice.org/extensions/description/2006}"
JAVA_FILES: Final = ("bin/java", "lib/server/libjvm.dylib", "release")


def check_deadline(deadline: float) -> None:
    if time.monotonic() >= deadline:
        raise ConversionError(ConversionErrorCode.TIMEOUT)


def bounded_read(path: Path, deadline: float, limit: int, *, parent_fd: int | None = None) -> bytes:
    check_deadline(deadline)
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent_fd)
    with os.fdopen(descriptor, "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size > limit:
            raise ConversionError(ConversionErrorCode.INVALID_CONFIG)
        content = bytearray()
        while chunk := stream.read(min(CHUNK_BYTES, limit + 1 - len(content))):
            check_deadline(deadline)
            content.extend(chunk)
            if len(content) > limit:
                raise ConversionError(ConversionErrorCode.INVALID_CONFIG)
    return bytes(content)


def walk_directory(descriptor: int, relative: Path, depth: int) -> Generator[tuple[Path, int, int]]:
    if depth > MAX_DIRECTORY_DEPTH:
        raise ConversionError(ConversionErrorCode.INVALID_CONFIG)
    with os.scandir(descriptor) as children:
        for child in children:
            mode = child.stat(follow_symlinks=False).st_mode
            path = relative / child.name
            yield path, descriptor, mode
            if stat.S_ISDIR(mode):
                with ExitStack() as stack:
                    directory = os.open(
                        child.name,
                        os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                        dir_fd=descriptor,
                    )
                    _ = stack.callback(os.close, directory)
                    yield from walk_directory(directory, path, depth + 1)


def walk_profile(root: Path) -> Generator[tuple[Path, int, int]]:
    with ExitStack() as stack:
        directory = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        _ = stack.callback(os.close, directory)
        yield from walk_directory(directory, Path(), 0)


def profile_files(root: Path, deadline: float) -> Iterator[tuple[ProfileFile, bytes]]:
    if root.is_symlink() or not root.is_dir():
        raise ConversionError(ConversionErrorCode.INVALID_CONFIG)
    entries = 0
    total = 0
    with closing(walk_profile(root)) as tree:
        for relative, descriptor, mode in tree:
            check_deadline(deadline)
            entries += 1
            if entries > MAX_ENTRIES or stat.S_ISLNK(mode) or relative.name == ".lock":
                raise ConversionError(ConversionErrorCode.INVALID_CONFIG)
            if stat.S_ISDIR(mode):
                continue
            content = bounded_read(
                Path(relative.name),
                deadline,
                min(MAX_FILE_BYTES, MAX_PROFILE_BYTES - total),
                parent_fd=descriptor,
            )
            total += len(content)
            yield (
                ProfileFile(
                    relative_path=relative.as_posix(),
                    byte_size=len(content),
                    sha256=sha256(content).hexdigest(),
                ),
                content,
            )


def profile_digest(files: tuple[ProfileFile, ...]) -> str:
    return sha256(TypeAdapter(tuple[ProfileFile, ...]).dump_json(files)).hexdigest()


def runtime_file(path: Path, deadline: float) -> RuntimeFile:
    return RuntimeFile(
        path=path.absolute(),
        sha256=sha256(bounded_read(path, deadline, MAX_RUNTIME_BYTES)).hexdigest(),
    )


def extension_identity(files: tuple[ProfileFile, ...], template: Path, deadline: float) -> str:
    jars = tuple(
        file for file in files if file.relative_path.endswith("/H2Orestart.oxt/H2Orestart.jar")
    )
    if len(jars) != 1:
        raise ConversionError(ConversionErrorCode.INVALID_CONFIG)
    description = template / Path(jars[0].relative_path).parent / "description.xml"
    root = fromstring(bounded_read(description, deadline, MAX_FILE_BYTES))
    version = root.find(f"{DESCRIPTION_NS}version")
    identifier = root.find(f"{DESCRIPTION_NS}identifier")
    if (
        version is None
        or version.get("value") != "0.7.14"
        or identifier is None
        or identifier.get("value") != "ebandal.libreoffice.H2Orestart"
    ):
        raise ConversionError(ConversionErrorCode.INVALID_CONFIG)
    return jars[0].sha256


def seal_profile(template: Path, soffice: Path, java_home: Path) -> HancomProvision:
    """Pin an administrator-provisioned idle profile; this is not extension installation."""
    deadline = time.monotonic() + 30
    try:
        files = tuple(
            sorted(
                (item for item, _ in profile_files(template, deadline)),
                key=lambda item: item.relative_path,
            )
        )
        extension_hash = extension_identity(files, template, deadline)
        return HancomProvision(
            template=template.absolute(),
            files=files,
            template_sha256=profile_digest(files),
            soffice=runtime_file(soffice, deadline),
            java_home=java_home.absolute(),
            java_files=tuple(runtime_file(java_home / name, deadline) for name in JAVA_FILES),
            extension_version="0.7.14",
            extension_sha256=extension_hash,
        )
    except (OSError, ParseError, DefusedXmlException) as error:
        raise ConversionError(ConversionErrorCode.INVALID_CONFIG) from error


def validate_runtime(provision: HancomProvision, soffice: Path, deadline: float) -> None:
    if soffice.absolute() != provision.soffice.path:
        raise ConversionError(ConversionErrorCode.INVALID_CONFIG)
    expected = (provision.soffice, *provision.java_files)
    if tuple(item.path for item in provision.java_files) != tuple(
        provision.java_home / name for name in JAVA_FILES
    ):
        raise ConversionError(ConversionErrorCode.INVALID_CONFIG)
    if any(runtime_file(item.path, deadline) != item for item in expected):
        raise ConversionError(ConversionErrorCode.INVALID_CONFIG)


def copy_profile(provision: HancomProvision, directory: Path, deadline: float) -> Path:
    """Verify every copied byte against the seal before a renderer can consume it."""
    profile = directory / "profile"
    profile.mkdir(parents=True, mode=0o700)
    files: list[ProfileFile] = []
    for item, content in profile_files(provision.template, deadline):
        target = profile / item.relative_path
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with target.open("xb") as stream:
            target.chmod(0o600)
            _ = stream.write(content)
        files.append(item)
    copied = tuple(sorted(files, key=lambda item: item.relative_path))
    if copied != provision.files or profile_digest(copied) != provision.template_sha256:
        raise ConversionError(ConversionErrorCode.INVALID_CONFIG)
    if extension_identity(copied, profile, deadline) != provision.extension_sha256:
        raise ConversionError(ConversionErrorCode.INVALID_CONFIG)
    _ = (profile / "user/registrymodifications.xcu").write_bytes(PROFILE_SETTINGS)
    return profile
