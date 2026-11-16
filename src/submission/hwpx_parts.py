from typing import Final
from xml.etree.ElementTree import Element

from submission.document_contracts import DocumentDiagnostic, DocumentSource, SourceLocator
from submission.format_containers import PackageMember, member_bytes, parse_xml
from submission.hwpx_validation import HEAD_NS, OPF_NS, SECTION_NS, VERSION_NS
from submission.input_contracts import InputErrorCode, InputLimits, InputValidationError

PARA_NS: Final = "http://www.hancom.co.kr/hwpml/2011/paragraph"
CONTAINER_NS: Final = "urn:oasis:names:tc:opendocument:xmlns:container"
CORE_NS: Final = "http://www.hancom.co.kr/hwpml/2011/core"
DC_NS: Final = "http://purl.org/dc/elements/1.1/"
ROOT_PREFIXES: Final = ((SECTION_NS, "hs"), (HEAD_NS, "hh"), (PARA_NS, "hp"))
AUXILIARY_PREVIEWS: Final = frozenset({"Preview/PrvText.txt", "Preview/PrvImage.png"})


def part_locator(source: DocumentSource, member: str, path: str) -> SourceLocator:
    return SourceLocator(
        source_sha256=source.content_sha256, path=f"{member}::{path}", original_page_number=None
    )


def root_path(root: Element) -> str:
    name = root.tag
    for uri, prefix in ROOT_PREFIXES:
        if name.startswith(f"{{{uri}}}"):
            name = f"{prefix}:{name.removeprefix(f'{{{uri}}}')}"
            break
    return f"/{name}[1]"


def validate_package_order(members: tuple[PackageMember, ...], limits: InputLimits) -> None:
    package = parse_xml(member_bytes(members, "Contents/content.hpf"), limits)
    for name, child_name in (("manifest", "item"), ("spine", "itemref")):
        branches = tuple(package.findall(f"{{{OPF_NS}}}{name}"))
        if len(branches) != 1 or any(
            child.tag != f"{{{OPF_NS}}}{child_name}" for child in branches[0]
        ):
            raise InputValidationError(InputErrorCode.CORRUPT_DOCUMENT, detected_format="hwpx")


def metadata_root(member: str, root: Element) -> bool:
    expected = {
        "version.xml": f"{{{VERSION_NS}}}HCFVersion",
        "Contents/content.hpf": f"{{{OPF_NS}}}package",
        "META-INF/container.xml": f"{{{CONTAINER_NS}}}container",
    }
    if root.tag == f"{{{HEAD_NS}}}head":
        namespaces = (HEAD_NS, CORE_NS)
    elif expected.get(member) == root.tag:
        namespaces = (root.tag[1:].split("}", 1)[0],)
        if member == "Contents/content.hpf":
            namespaces += (DC_NS,)
    else:
        return False
    prefixes = tuple(f"{{{uri}}}" for uri in namespaces)
    for node in root.iter():
        if not node.tag.startswith(prefixes) or (node.tail or "").strip():
            return False
        scalar = not len(node) and (
            node.tag.startswith(f"{{{DC_NS}}}") or node.tag == f"{{{OPF_NS}}}meta"
        )
        if (node.text or "").strip() and not scalar:
            return False
    return True


def inventory_warnings(
    members: tuple[PackageMember, ...],
    processed: tuple[str, ...],
    source: DocumentSource,
    limits: InputLimits,
) -> tuple[DocumentDiagnostic, ...]:
    warnings: tuple[DocumentDiagnostic, ...] = ()
    for member in members:
        if (
            member.name in processed
            or member.name == "mimetype"
            or member.name in AUXILIARY_PREVIEWS
        ):
            continue
        path = "/"
        if member.name.endswith((".xml", ".hpf")):
            root = parse_xml(member.data, limits)
            if metadata_root(member.name, root):
                continue
            path = root_path(root)
        warnings += (
            DocumentDiagnostic(
                code="unsupported_part",
                page_number=None,
                source_locator=part_locator(source, member.name, path),
            ),
        )
    return warnings
