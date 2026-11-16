import zlib
from dataclasses import dataclass
from io import BytesIO
from pathlib import PurePosixPath
from posixpath import dirname, join, normpath
from struct import unpack_from
from typing import override
from urllib.parse import unquote, urlsplit
from xml.etree.ElementTree import Element, TreeBuilder
from zipfile import ZIP_DEFLATED, ZIP_STORED, BadZipFile, ZipFile, ZipInfo

from defusedxml.common import DefusedXmlException
from defusedxml.ElementTree import ParseError, XMLParser

from submission.input_contracts import InputErrorCode, InputLimits, InputValidationError


class BoundedTreeBuilder(TreeBuilder):
    limits: InputLimits
    depth: int
    nodes: int

    def __init__(self, limits: InputLimits) -> None:
        super().__init__()
        self.limits = limits
        self.depth = 0
        self.nodes = 0

    @override
    def start(self, tag: str, attrs: dict[str, str]) -> Element:
        if self.depth >= self.limits.max_xml_depth or self.nodes >= self.limits.max_xml_nodes:
            raise InputValidationError(InputErrorCode.XML_LIMIT)
        self.depth += 1
        self.nodes += 1
        return super().start(tag, attrs)

    @override
    def end(self, tag: str) -> Element:
        self.depth -= 1
        return super().end(tag)


def parse_xml(content: bytes, limits: InputLimits) -> Element:
    if len(content) > limits.max_xml_bytes:
        raise InputValidationError(InputErrorCode.XML_LIMIT)
    parser = XMLParser(
        target=BoundedTreeBuilder(limits),
        forbid_dtd=True,
        forbid_entities=True,
        forbid_external=True,
    )
    try:
        parser.feed(content)
        return parser.close()
    except DefusedXmlException as error:
        raise InputValidationError(InputErrorCode.UNSAFE_XML) from error
    except ParseError as error:
        raise InputValidationError(InputErrorCode.CORRUPT_DOCUMENT) from error


@dataclass(frozen=True, slots=True)
class PackageMember:
    name: str
    data: bytes


def validate_name(name: str) -> None:
    parts = name.removesuffix("/").split("/")
    if (
        not name
        or "\x00" in name
        or "\\" in name
        or name.startswith("/")
        or any(part in {"", ".", ".."} or ":" in part for part in parts)
        or PurePosixPath(name).is_absolute()
    ):
        raise InputValidationError(InputErrorCode.UNSAFE_PACKAGE_PATH)


def relationship_target(owner: str, target: str) -> str:
    try:
        parsed = urlsplit(target)
    except ValueError as error:
        raise InputValidationError(InputErrorCode.UNSAFE_PACKAGE_PATH) from error
    if parsed.scheme or parsed.netloc or parsed.query or parsed.fragment or not parsed.path:
        raise InputValidationError(InputErrorCode.UNSAFE_PACKAGE_PATH)
    decoded = unquote(parsed.path)
    path = normpath(
        decoded.lstrip("/") if decoded.startswith("/") else join(dirname(owner), decoded)
    )
    validate_name(path)
    return path


def preflight(members: list[ZipInfo], limits: InputLimits) -> None:
    if len(members) > limits.max_members:
        raise InputValidationError(InputErrorCode.PACKAGE_LIMIT)
    names: frozenset[str] = frozenset()
    total = 0
    for member in members:
        validate_name(member.orig_filename)
        name = member.filename.removesuffix("/")
        if name.casefold() in names:
            raise InputValidationError(InputErrorCode.DUPLICATE_MEMBER)
        names = names | {name.casefold()}
        if member.flag_bits & 1:
            raise InputValidationError(InputErrorCode.ENCRYPTED_DOCUMENT)
        if member.compress_type not in {ZIP_STORED, ZIP_DEFLATED}:
            raise InputValidationError(InputErrorCode.UNSUPPORTED_FEATURE)
        total += member.file_size
        if member.file_size > limits.max_member_bytes or total > limits.max_expanded_bytes:
            raise InputValidationError(InputErrorCode.PACKAGE_LIMIT)


def read_member(archive: ZipFile, member: ZipInfo, budget: int) -> bytes:
    with archive.open(member) as stream:
        buffer = BytesIO()
        while chunk := stream.read(min(32 * 1024, budget - buffer.tell() + 1)):
            if buffer.tell() + len(chunk) > budget:
                raise InputValidationError(InputErrorCode.PACKAGE_LIMIT)
            _ = buffer.write(chunk)
        if buffer.tell() != member.file_size:
            raise InputValidationError(InputErrorCode.CORRUPT_DOCUMENT)
        return buffer.getvalue()


def read_package(content: bytes, limits: InputLimits) -> tuple[PackageMember, ...]:
    try:
        preflight_directory(content, limits)
        with ZipFile(BytesIO(content)) as archive:
            members = archive.infolist()
            preflight(members, limits)
            result: tuple[PackageMember, ...] = ()
            total = 0
            for member in members:
                budget = min(limits.max_member_bytes, limits.max_expanded_bytes - total)
                data = read_member(archive, member, budget)
                total += len(data)
                if not member.is_dir():
                    result += (PackageMember(member.filename, data),)
            return result
    except (BadZipFile, OSError, EOFError, ValueError, zlib.error) as error:
        raise InputValidationError(InputErrorCode.CORRUPT_DOCUMENT) from error


def member_bytes(members: tuple[PackageMember, ...], path: str) -> bytes:
    for member in members:
        if member.name == path:
            return member.data
    raise InputValidationError(InputErrorCode.CORRUPT_DOCUMENT)


def validate_package_xml(members: tuple[PackageMember, ...], limits: InputLimits) -> None:
    for member in members:
        if member.name.lower().endswith((".xml", ".rels", ".hpf")):
            _ = parse_xml(member.data, limits)


def directory_bounds(content: bytes) -> tuple[int, int, int]:
    minimum_record_size = 22
    maximum_comment_size = 65535
    index = content.rfind(
        b"PK\x05\x06", max(0, len(content) - maximum_comment_size - minimum_record_size)
    )
    if index < 0 or len(content) - index < minimum_record_size:
        raise InputValidationError(InputErrorCode.CORRUPT_DOCUMENT)
    disk, directory_disk, disk_count, count, size, offset, comment_size = unpack_from(
        "<4H2IH", content, index + 4
    )
    zip64_marker = 0xFFFFFFFF
    zip64_locator_size = 20
    has_zip64_locator = (
        index >= zip64_locator_size
        and content[index - zip64_locator_size : index - zip64_locator_size + 4] == b"PK\x06\x07"
    )
    if (
        count == maximum_comment_size
        or zip64_marker in {size, offset}
        or disk
        or directory_disk
        or has_zip64_locator
    ):
        raise InputValidationError(InputErrorCode.UNSUPPORTED_FEATURE)
    if (
        disk_count != count
        or index + minimum_record_size + comment_size != len(content)
        or offset + size != index
    ):
        raise InputValidationError(InputErrorCode.CORRUPT_DOCUMENT)
    return offset, offset + size, count


def preflight_directory(content: bytes, limits: InputLimits) -> None:
    cursor, end, declared_count = directory_bounds(content)
    count = 0
    total = 0
    fixed_header_size = 46
    while cursor < end:
        if cursor + fixed_header_size > end or content[cursor : cursor + 4] != b"PK\x01\x02":
            raise InputValidationError(InputErrorCode.CORRUPT_DOCUMENT)
        count += 1
        size = unpack_from("<I", content, cursor + 24)[0]
        total += size
        if (
            count > limits.max_members
            or size > limits.max_member_bytes
            or total > limits.max_expanded_bytes
        ):
            raise InputValidationError(InputErrorCode.PACKAGE_LIMIT)
        name_size, extra_size, comment_size = unpack_from("<3H", content, cursor + 28)
        cursor += fixed_header_size + name_size + extra_size + comment_size
    if cursor != end or count != declared_count:
        raise InputValidationError(InputErrorCode.CORRUPT_DOCUMENT)
