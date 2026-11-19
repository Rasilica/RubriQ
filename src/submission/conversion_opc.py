"""Resolve the conversion policy from OPC declarations, independently of filenames."""

from collections.abc import Mapping
from typing import Final
from xml.etree.ElementTree import Element
from zipfile import ZipFile

from defusedxml.ElementTree import fromstring

from submission.conversion_contracts import ConversionError, ConversionErrorCode
from submission.conversion_images import IMAGE_TYPES, SIGNATURE_BYTES, inspect_raster_signature
from submission.format_containers import relationship_target
from submission.input_contracts import InputValidationError

CONTENT_NS: Final = "{http://schemas.openxmlformats.org/package/2006/content-types}"
OFFICE_REL: Final = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/"
XML_TYPES: Final = frozenset(
    {
        "application/xml",
        "text/xml",
        "application/vnd.openxmlformats-package.relationships+xml",
        "application/vnd.openxmlformats-package.core-properties+xml",
        "application/vnd.openxmlformats-officedocument.extended-properties+xml",
        "application/vnd.openxmlformats-officedocument.custom-properties+xml",
        "application/vnd.openxmlformats-officedocument.customXmlProperties+xml",
        "application/vnd.openxmlformats-officedocument.theme+xml",
        "application/vnd.ms-word.stylesWithEffects+xml",
        "application/vnd.openxmlformats-officedocument.drawing+xml",
        "application/vnd.openxmlformats-officedocument.drawingml.chart+xml",
        "application/vnd.openxmlformats-officedocument.drawingml.chartshapes+xml",
        "application/vnd.openxmlformats-officedocument.drawingml.diagramData+xml",
        "application/vnd.openxmlformats-officedocument.drawingml.diagramLayout+xml",
        "application/vnd.openxmlformats-officedocument.drawingml.diagramStyle+xml",
        "application/vnd.openxmlformats-officedocument.drawingml.diagramColors+xml",
    }
) | frozenset(
    f"application/vnd.openxmlformats-officedocument.wordprocessingml.{part}+xml"
    for part in (
        "document.main",
        "styles",
        "settings",
        "webSettings",
        "fontTable",
        "numbering",
        "header",
        "footer",
        "footnotes",
        "endnotes",
        "comments",
        "document.glossary",
    )
)
RELATIONSHIPS: Final = frozenset(
    f"{OFFICE_REL}{part}"
    for part in (
        "officeDocument",
        "styles",
        "settings",
        "webSettings",
        "fontTable",
        "numbering",
        "header",
        "footer",
        "footnotes",
        "endnotes",
        "comments",
        "glossaryDocument",
        "theme",
        "customXml",
        "customXmlProps",
        "extended-properties",
        "custom-properties",
        "image",
        "drawing",
        "chart",
        "chartUserShapes",
        "diagramData",
        "diagramLayout",
        "diagramQuickStyle",
        "diagramColors",
    )
) | frozenset(
    {
        "http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties",
        "http://schemas.openxmlformats.org/package/2006/relationships/metadata/thumbnail",
        "http://schemas.microsoft.com/office/2007/relationships/stylesWithEffects",
    }
)


def inspect_relationship(node: Element) -> None:
    """Only inert, known internal relationships may reach the renderer."""
    if node.get("Type") not in RELATIONSHIPS or node.get("TargetMode", "Internal") != "Internal":
        raise ConversionError(ConversionErrorCode.UNSUPPORTED_ACTIVE_CONTENT)


def xml_parts(package: ZipFile) -> tuple[str, ...]:
    """Select every declared XML part and reject unknown or ambiguous declarations."""
    root = fromstring(package.read("[Content_Types].xml"))
    if root.tag != f"{CONTENT_NS}Types":
        raise ConversionError(ConversionErrorCode.UNSUPPORTED_ACTIVE_CONTENT)
    defaults: dict[str, str] = {}
    overrides: dict[str, str] = {}
    for node in root:
        content_type = node.get("ContentType", "")
        if content_type not in XML_TYPES | IMAGE_TYPES:
            raise ConversionError(ConversionErrorCode.UNSUPPORTED_ACTIVE_CONTENT)
        if node.tag == f"{CONTENT_NS}Default":
            extension = node.get("Extension", "").lower()
            if not extension or extension in defaults:
                raise ConversionError(ConversionErrorCode.UNSUPPORTED_ACTIVE_CONTENT)
            defaults[extension] = content_type
        elif node.tag == f"{CONTENT_NS}Override":
            name = node.get("PartName", "")
            if not name.startswith("/") or name in overrides:
                raise ConversionError(ConversionErrorCode.UNSUPPORTED_ACTIVE_CONTENT)
            overrides[name] = content_type
        else:
            raise ConversionError(ConversionErrorCode.UNSUPPORTED_ACTIVE_CONTENT)
    selected = _xml_members(package, defaults, overrides)
    _validate_relationship_targets(package, selected, defaults, overrides)
    return selected


def _xml_members(
    package: ZipFile, defaults: Mapping[str, str], overrides: Mapping[str, str]
) -> tuple[str, ...]:
    selected: list[str] = []
    for member in package.infolist():
        name = member.filename
        if any(part in name.lower() for part in ("vbaproject", "activex/", "embeddings/")):
            raise ConversionError(ConversionErrorCode.UNSUPPORTED_ACTIVE_CONTENT)
        if member.is_dir():
            continue
        content_type = overrides.get(f"/{name}", defaults.get(name.rsplit(".", 1)[-1].lower()))
        if name == "[Content_Types].xml" or content_type in XML_TYPES:
            selected.append(name)
        elif content_type not in IMAGE_TYPES:
            raise ConversionError(ConversionErrorCode.UNSUPPORTED_ACTIVE_CONTENT)
        else:
            with package.open(member) as image:
                inspect_raster_signature(image.read(SIGNATURE_BYTES), content_type)
    return tuple(selected)


def _validate_relationship_targets(
    package: ZipFile,
    selected: tuple[str, ...],
    defaults: Mapping[str, str],
    overrides: Mapping[str, str],
) -> None:
    for name in selected:
        root = fromstring(package.read(name))
        if root.tag.rsplit("}", 1)[-1] != "Relationships":
            continue
        owner = _relationship_owner(name)
        for node in root:
            inspect_relationship(node)
            try:
                target = relationship_target(owner, node.get("Target", ""))
            except InputValidationError as error:
                raise ConversionError(ConversionErrorCode.UNSUPPORTED_ACTIVE_CONTENT) from error
            is_image = node.get("Type", "").rsplit("/", 1)[-1] in {"image", "thumbnail"}
            target_type = overrides.get(
                f"/{target}", defaults.get(target.rsplit(".", 1)[-1].lower())
            )
            if is_image and target_type not in IMAGE_TYPES:
                raise ConversionError(ConversionErrorCode.UNSUPPORTED_ACTIVE_CONTENT)
            if target not in package.namelist() or (not is_image and target not in selected):
                raise ConversionError(ConversionErrorCode.UNSUPPORTED_ACTIVE_CONTENT)


def _relationship_owner(name: str) -> str:
    if name == "_rels/.rels":
        return ""
    parent, separator, basename = name.rpartition("/_rels/")
    if not separator or not basename.lower().endswith(".rels"):
        raise ConversionError(ConversionErrorCode.UNSUPPORTED_ACTIVE_CONTENT)
    return f"{parent}/{basename[:-5]}"
