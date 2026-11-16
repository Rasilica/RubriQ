from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Literal
from xml.etree.ElementTree import Element

from submission.document_contracts import DocumentDiagnostic, DocumentSource, SourceLocator
from submission.docx_structure_types import FORMATTING, PROPERTIES, child_paths, node_segment
from submission.docx_validation import WORD_NS, relationships
from submission.format_containers import PackageMember, member_bytes, parse_xml, relationship_target
from submission.input_contracts import InputLimits

OFFICE_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
type RegionKind = Literal["footnote", "header", "footer"]


def locator(source: DocumentSource, part: str, path: str) -> SourceLocator:
    return SourceLocator(
        source_sha256=source.content_sha256, path=f"{part}::{path}", original_page_number=None
    )


def root_path(root: Element) -> str:
    return f"/{node_segment(root)}[1]"


def diagnostic(
    code: Literal["invalid_structure", "unsupported_part", "invalid_reference"],
    position: SourceLocator,
) -> DocumentDiagnostic:
    return DocumentDiagnostic(code=code, page_number=None, source_locator=position)


@dataclass(frozen=True, slots=True)
class PartRelationship:
    identifier: str
    relation_type: str
    target: str | None
    source_locator: SourceLocator


@dataclass(frozen=True, slots=True)
class ReaderPart:
    kind: RegionKind
    member: str
    node: Element
    path: str
    key: str


@dataclass(frozen=True, slots=True)
class DocxPackage:
    source: DocumentSource
    members: tuple[PackageMember, ...]
    main_part: str
    limits: InputLimits

    def root(self, part: str) -> Element:
        return parse_xml(member_bytes(self.members, part), self.limits)

    def main_relationships(self) -> tuple[PartRelationship, ...]:
        owner = PurePosixPath(self.main_part)
        path = str(owner.parent / "_rels" / f"{owner.name}.rels")
        if path not in {member.name for member in self.members}:
            return ()
        root = relationships(member_bytes(self.members, path), self.limits)
        return tuple(
            PartRelationship(
                identifier=child.get("Id", ""),
                relation_type=child.get("Type", ""),
                target=(
                    relationship_target(self.main_part, child.get("Target", ""))
                    if child.get("TargetMode", "Internal") == "Internal"
                    else None
                ),
                source_locator=locator(
                    self.source, path, f"/rel:Relationships[1]/rel:Relationship[{index}]"
                ),
            )
            for index, child in enumerate(root, start=1)
        )


def note_key(value: str | None, *, allow_negative: bool = False) -> str | None:
    if value is None:
        return None
    value = value.strip()
    negative = value.startswith("-")
    digits = value[1:] if value.startswith(("+", "-")) else value
    if not digits.isascii() or not digits.isdecimal() or (negative and not allow_negative):
        return None
    normalized = digits.lstrip("0") or "0"
    return f"-{normalized}" if negative and normalized != "0" else normalized


def reserved_note_supported(node: Element) -> bool:
    allowed = FORMATTING | PROPERTIES | {"footnote", "p", "r", "separator", "continuationSeparator"}
    tags = frozenset(f"{{{WORD_NS}}}{name}" for name in allowed)
    return all(
        item.tag in tags and not (item.text or "").strip() and not (item.tail or "").strip()
        for item in node.iter()
    )


def note_parts(
    package: DocxPackage, relations: tuple[PartRelationship, ...]
) -> tuple[tuple[ReaderPart, ...], tuple[DocumentDiagnostic, ...], tuple[str, ...]]:
    candidates = tuple(item for item in relations if item.relation_type == f"{OFFICE_NS}/footnotes")
    if not candidates:
        return (), (), ()
    if len(candidates) != 1 or candidates[0].target is None:
        return (
            (),
            tuple(diagnostic("invalid_structure", item.source_locator) for item in candidates),
            (),
        )
    member = candidates[0].target
    root = package.root(member)
    position = locator(package.source, member, root_path(root))
    if root.tag != f"{{{WORD_NS}}}footnotes":
        return (), (diagnostic("invalid_structure", position),), ()
    keys = tuple(
        note_key(
            node.get(f"{{{WORD_NS}}}id"),
            allow_negative=(node.get(f"{{{WORD_NS}}}type", "normal") != "normal"),
        )
        for node in root
    )
    if any(key is None for key in keys) or len(set(keys)) != len(keys):
        return (), (diagnostic("invalid_structure", position),), ()
    parts = tuple(
        ReaderPart("footnote", member, node, path, note_key(node.get(f"{{{WORD_NS}}}id")) or "")
        for node, path in child_paths(root, root_path(root))
        if node.tag == f"{{{WORD_NS}}}footnote"
        and node.get(f"{{{WORD_NS}}}type", "normal") == "normal"
    )
    warnings = tuple(
        diagnostic("invalid_structure", locator(package.source, member, path))
        for node, path in child_paths(root, root_path(root))
        if node.tag != f"{{{WORD_NS}}}footnote"
        or node.get(f"{{{WORD_NS}}}type", "normal")
        not in {"normal", "separator", "continuationSeparator", "continuationNotice"}
        or (
            node.get(f"{{{WORD_NS}}}type", "normal") != "normal"
            and not reserved_note_supported(node)
        )
    )
    if (root.text or "").strip() or any((node.tail or "").strip() for node in root):
        warnings += (diagnostic("invalid_structure", position),)
    return parts, warnings, (member,)


def header_part(
    package: DocxPackage, relation: PartRelationship, kind: Literal["header", "footer"]
) -> ReaderPart | None:
    if relation.relation_type != f"{OFFICE_NS}/{kind}" or relation.target is None:
        return None
    root = package.root(relation.target)
    expected = "hdr" if kind == "header" else "ftr"
    if root.tag != f"{{{WORD_NS}}}{expected}":
        return None
    return ReaderPart(kind, relation.target, root, root_path(root), relation.identifier)


def inventory_warnings(
    package: DocxPackage, processed: tuple[str, ...]
) -> tuple[DocumentDiagnostic, ...]:
    metadata_roots = frozenset(
        {
            *(
                f"{{{WORD_NS}}}{name}"
                for name in ("styles", "settings", "numbering", "fonts", "webSettings")
            ),
            "{http://schemas.openxmlformats.org/drawingml/2006/main}theme",
            "{http://schemas.openxmlformats.org/package/2006/metadata/core-properties}coreProperties",
            "{http://schemas.openxmlformats.org/officeDocument/2006/extended-properties}Properties",
            "{http://schemas.openxmlformats.org/officeDocument/2006/custom-properties}Properties",
        }
    )
    warnings: tuple[DocumentDiagnostic, ...] = ()
    for member in package.members:
        if (
            member.name in processed
            or member.name == "[Content_Types].xml"
            or member.name.endswith(".rels")
        ):
            continue
        if member.name.endswith(".xml"):
            root = package.root(member.name)
            if root.tag in metadata_roots and root.find(f".//{{{WORD_NS}}}t") is None:
                continue
            path = root_path(root)
        else:
            path = "/"
        warnings += (diagnostic("unsupported_part", locator(package.source, member.name, path)),)
    return warnings
