from xml.etree.ElementTree import Element

from submission.format_containers import PackageMember, member_bytes, parse_xml, relationship_target
from submission.input_contracts import (
    FormatDetails,
    InputErrorCode,
    InputLimits,
    InputValidationError,
)

REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
OFFICE_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument"
STRICT_REL = "http://purl.oclc.org/ooxml/officeDocument/relationships/officeDocument"
WORD_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
STRICT_WORD_NS = "http://purl.oclc.org/ooxml/wordprocessingml/main"
CONTENT_NS = "http://schemas.openxmlformats.org/package/2006/content-types"
DOCX_CONTENT = "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"


def relationships(content: bytes, limits: InputLimits) -> Element:
    root = parse_xml(content, limits)
    if root.tag != f"{{{REL_NS}}}Relationships":
        raise InputValidationError(InputErrorCode.UNSUPPORTED_VERSION, detected_format="docx")
    ids = tuple(child.get("Id") for child in root)
    if None in ids or len(set(ids)) != len(ids):
        raise InputValidationError(InputErrorCode.CORRUPT_DOCUMENT, detected_format="docx")
    return root


def validate_relationship_parts(members: tuple[PackageMember, ...], limits: InputLimits) -> None:
    for member in members:
        if not member.name.endswith(".rels"):
            continue
        root = relationships(member.data, limits)
        if member.name == "_rels/.rels":
            owner = ""
        else:
            parent, separator, basename = member.name.rpartition("/_rels/")
            if not separator:
                raise InputValidationError(InputErrorCode.CORRUPT_DOCUMENT)
            owner = f"{parent}/{basename.removesuffix('.rels')}"
            _ = member_bytes(members, owner)
        for child in root:
            if child.tag != f"{{{REL_NS}}}Relationship":
                raise InputValidationError(InputErrorCode.UNSUPPORTED_FEATURE)
            mode = child.get("TargetMode", "Internal")
            if mode == "External":
                continue
            if mode != "Internal":
                raise InputValidationError(InputErrorCode.CORRUPT_DOCUMENT)
            target = relationship_target(owner, child.get("Target", ""))
            _ = member_bytes(members, target)


def document_protection(members: tuple[PackageMember, ...], limits: InputLimits) -> None:
    for member in members:
        if not member.name.endswith(".xml"):
            continue
        root = parse_xml(member.data, limits)
        for element in root.iter(f"{{{WORD_NS}}}documentProtection"):
            enforcement = element.get(f"{{{WORD_NS}}}enforcement", "false")
            if enforcement in {"1", "true", "on"}:
                raise InputValidationError(
                    InputErrorCode.PROTECTED_DOCUMENT, detected_format="docx"
                )


def inspect_docx(members: tuple[PackageMember, ...], limits: InputLimits) -> FormatDetails:
    root_rels = relationships(member_bytes(members, "_rels/.rels"), limits)
    office_parts = tuple(
        child for child in root_rels if child.get("Type") in {OFFICE_REL, STRICT_REL}
    )
    if len(office_parts) != 1:
        raise InputValidationError(InputErrorCode.CORRUPT_DOCUMENT, detected_format="docx")
    relation = office_parts[0]
    if relation.get("Type") == STRICT_REL:
        raise InputValidationError(InputErrorCode.UNSUPPORTED_VERSION, detected_format="docx")
    if relation.get("TargetMode", "Internal") != "Internal":
        raise InputValidationError(InputErrorCode.CORRUPT_DOCUMENT, detected_format="docx")
    main_part = relationship_target("", relation.get("Target", ""))
    content_types = parse_xml(member_bytes(members, "[Content_Types].xml"), limits)
    if content_types.tag != f"{{{CONTENT_NS}}}Types":
        raise InputValidationError(InputErrorCode.UNSUPPORTED_VERSION, detected_format="docx")
    declarations = tuple(
        child.get("ContentType")
        for child in content_types
        if child.tag == f"{{{CONTENT_NS}}}Override" and child.get("PartName") == f"/{main_part}"
    )
    if len(declarations) != 1:
        raise InputValidationError(InputErrorCode.CORRUPT_DOCUMENT, detected_format="docx")
    if declarations[0] != DOCX_CONTENT:
        raise InputValidationError(InputErrorCode.UNSUPPORTED_FEATURE, detected_format="docx")
    document = parse_xml(member_bytes(members, main_part), limits)
    if document.tag == f"{{{STRICT_WORD_NS}}}document":
        raise InputValidationError(InputErrorCode.UNSUPPORTED_VERSION, detected_format="docx")
    if document.tag != f"{{{WORD_NS}}}document" or document.find(f"{{{WORD_NS}}}body") is None:
        raise InputValidationError(InputErrorCode.CORRUPT_DOCUMENT, detected_format="docx")
    validate_relationship_parts(members, limits)
    document_protection(members, limits)
    return FormatDetails(
        detected_format="docx",
        version="OOXML-Transitional",
        members=tuple(member.name for member in members),
        content_members=(main_part,),
    )
