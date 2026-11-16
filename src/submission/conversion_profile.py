import re
from io import BytesIO
from pathlib import Path
from typing import Final
from xml.etree.ElementTree import Element, ParseError
from zipfile import ZipFile

from defusedxml.common import DefusedXmlException
from defusedxml.ElementTree import fromstring

from submission.conversion_contracts import ConversionError, ConversionErrorCode
from submission.conversion_opc import inspect_relationship, xml_parts

WORD_NAMESPACE: Final = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
FIELD_ELEMENTS: Final = frozenset({"fldSimple", "fldChar", "instrText"})
PAGINATION_INSTRUCTION: Final = re.compile(
    r"(?:PAGE|NUMPAGES)(?:\s+\\\*\s+(?:MERGEFORMAT|ARABIC|ROMAN|ALPHABETIC))*",
    re.IGNORECASE | re.ASCII,
)

PROFILE_SETTINGS: Final = b"""<?xml version="1.0" encoding="UTF-8"?>
<oor:items xmlns:oor="http://openoffice.org/2001/registry">
<item oor:path="/org.openoffice.Office.Common/Security/Scripting">
<prop oor:name="DisableMacrosExecution" oor:op="fuse"><value>true</value></prop>
<prop oor:name="MacroSecurityLevel" oor:op="fuse"><value>3</value></prop>
<prop oor:name="DisableActiveContent" oor:op="fuse"><value>true</value></prop>
<prop oor:name="BlockUntrustedRefererLinks" oor:op="fuse"><value>true</value></prop>
</item>
<item oor:path="/org.openoffice.Office.Writer/Content/Update">
<prop oor:name="Link" oor:op="fuse"><value>2</value></prop>
<prop oor:name="Field" oor:op="fuse"><value>false</value></prop>
<prop oor:name="Chart" oor:op="fuse"><value>false</value></prop>
</item>
</oor:items>"""


def prepare_profile(directory: Path) -> Path:
    profile = directory / "profile"
    user = profile / "user"
    user.mkdir(parents=True, mode=0o700)
    _ = (user / "registrymodifications.xcu").write_bytes(PROFILE_SETTINGS)
    return profile


def reject_active_content(content: bytes) -> None:
    """Reject active content, allowing only complete Word pagination fields."""
    try:
        with ZipFile(BytesIO(content)) as package:
            for name in xml_parts(package):
                root = fromstring(package.read(name))
                for node in root.iter():
                    local_name = node.tag.rsplit("}", 1)[-1]
                    if local_name == "AlternateContent" and any(
                        child.tag.rsplit("}", 1)[-1] in FIELD_ELEMENTS for child in node.iter()
                    ):
                        raise ConversionError(ConversionErrorCode.UNSUPPORTED_ACTIVE_CONTENT)
                    if node.get("TargetMode", "").lower() == "external" or local_name in {
                        "altChunk",
                        "object",
                        "control",
                        "delInstrText",
                    }:
                        raise ConversionError(ConversionErrorCode.UNSUPPORTED_ACTIVE_CONTENT)
                    if local_name == "Relationship":
                        inspect_relationship(node)
                _validate_fields(root)
    except (ParseError, DefusedXmlException) as error:
        raise ConversionError(ConversionErrorCode.UNSUPPORTED_ACTIVE_CONTENT) from error


def _validate_instruction(instruction: str) -> None:
    if PAGINATION_INSTRUCTION.fullmatch(instruction.strip()) is None:
        raise ConversionError(ConversionErrorCode.UNSUPPORTED_ACTIVE_CONTENT)


def _field_boundary(
    node: Element, instruction: str | None, *, in_result: bool
) -> tuple[str | None, bool]:
    marker = node.get(f"{WORD_NAMESPACE}fldCharType")
    if len(node):
        raise ConversionError(ConversionErrorCode.UNSUPPORTED_ACTIVE_CONTENT)
    if marker == "begin" and instruction is None:
        return "", False
    if instruction is not None:
        _validate_instruction(instruction)
        if marker == "separate" and not in_result:
            return instruction, True
        if marker == "end":
            return None, False
    raise ConversionError(ConversionErrorCode.UNSUPPORTED_ACTIVE_CONTENT)


def _validate_fields(root: Element) -> None:
    """Read each XML part in order; reject nested, orphaned or unfinished fields."""
    instruction: str | None = None
    in_result = False
    for node in root.iter():
        local_name = node.tag.rsplit("}", 1)[-1]
        if local_name not in FIELD_ELEMENTS:
            continue
        if node.tag != f"{WORD_NAMESPACE}{local_name}":
            raise ConversionError(ConversionErrorCode.UNSUPPORTED_ACTIVE_CONTENT)
        if local_name == "fldSimple":
            if instruction is not None or any(
                child is not node and child.tag.rsplit("}", 1)[-1] in FIELD_ELEMENTS
                for child in node.iter()
            ):
                raise ConversionError(ConversionErrorCode.UNSUPPORTED_ACTIVE_CONTENT)
            _validate_instruction(node.get(f"{WORD_NAMESPACE}instr", ""))
        if local_name == "instrText":
            if instruction is None or in_result or len(node):
                raise ConversionError(ConversionErrorCode.UNSUPPORTED_ACTIVE_CONTENT)
            instruction += node.text or ""
        if local_name == "fldChar":
            instruction, in_result = _field_boundary(node, instruction, in_result=in_result)
    if instruction is not None:
        raise ConversionError(ConversionErrorCode.UNSUPPORTED_ACTIVE_CONTENT)
