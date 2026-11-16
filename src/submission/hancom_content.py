import re
from io import BytesIO
from urllib.parse import unquote
from xml.etree.ElementTree import Element
from zipfile import ZipFile

from defusedxml.ElementTree import fromstring

from submission.conversion_contracts import ConversionError, ConversionErrorCode

# Hancom Office saves these do-nothing script stubs into every HWPX it writes.
HANCOM_HEADER_SCRIPT = (
    "var Documents = XHwpDocuments; var Document = Documents.Active_XHwpDocument;"
)
EMPTY_HANDLERS = re.compile(r"(?:function \w+\(\) ?\{ ?\} ?)*")


def is_hancom_default_script(name: str, data: bytes) -> bool:
    """True only for Hancom's default template: the fixed header and empty handlers."""
    try:
        text = data.decode("utf-16")
    except UnicodeDecodeError:
        return False
    # JavaScript also ends a line comment at U+2028/U+2029; stop there so no code hides.
    code = " ".join(re.sub(r"//[^\r\n\u2028\u2029]*", "", text).split())
    match name:
        case "Scripts/headerScripts":
            return code == HANCOM_HEADER_SCRIPT
        case "Scripts/sourceScripts":
            return EMPTY_HANDLERS.fullmatch(code) is not None
        case _:
            return False


# Fields that only draw text: form placeholders (누름틀), links and table formulas.
INERT_FIELD_TYPES = frozenset({"CLICK_HERE", "HYPERLINK", "FORMULA"})
LINK_SCHEMES = frozenset({"http", "https", "mailto"})


def is_safe_link(target: str) -> bool:
    """Web/mail links or in-document bookmarks only; never local files or other schemes."""
    previous = None
    while target != previous:  # undo layered %-encoding
        previous, target = target, unquote(target)
    target = target.strip().replace("\\:", ":")  # Hancom escapes the scheme colon
    if "\\" in target or target.startswith(("/", "~")) or ".." in target:
        return False
    scheme, separator, _ = target.partition(":")
    if separator:
        return scheme.lower() in LINK_SCHEMES
    # No scheme: a bookmark, or a bare host such as "www.daum.net" that Hancom stores as-is.
    # shortcut: a dotted first segment ("a.b/c") is trusted as a host; parse URLs if abused.
    head, slash, _ = target.partition("/")
    return not slash or "." in head


def is_inert_field(node: Element) -> bool:
    kind = node.get("type", "")
    if kind not in INERT_FIELD_TYPES:
        return False
    # A formula's Command is "=SUM(A1:A3)", so only links have their Command checked.
    names = {"Command", "Path"} if kind == "HYPERLINK" else {"Path"}
    targets = (
        (child.text or "").split(";", 1)[0]
        for child in node.iter()
        if child.tag.rsplit("}", 1)[-1] == "stringParam" and child.get("name") in names
    )
    return all(is_safe_link(target) for target in targets)


def reject_hwpx_active_content(content: bytes) -> None:
    with ZipFile(BytesIO(content)) as package:
        for name in package.namelist():
            lowered = name.lower()
            if lowered.startswith("scripts/") and is_hancom_default_script(
                name, package.read(name)
            ):
                continue
            if lowered.startswith(("scripts/", "embeddings/")):
                raise ConversionError(ConversionErrorCode.UNSUPPORTED_ACTIVE_CONTENT)
            if not lowered.endswith((".xml", ".hpf", ".rels")):
                continue
            root = fromstring(package.read(name))
            for node in root.iter():
                local = node.tag.rsplit("}", 1)[-1].lower()
                if local == "fieldbegin" and not is_inert_field(node):
                    raise ConversionError(ConversionErrorCode.UNSUPPORTED_ACTIVE_CONTENT)
                if local in {"script", "ole", "oleobject"}:
                    raise ConversionError(ConversionErrorCode.UNSUPPORTED_ACTIVE_CONTENT)
                for key, value in node.attrib.items():
                    attribute = key.rsplit("}", 1)[-1].lower()
                    target = unquote(value).strip()
                    if (
                        (attribute == "targetmode" and value.lower() == "external")
                        or (
                            local != "font"
                            and attribute in {"isembeded", "isembedded"}
                            and value.lower() not in {"1", "true"}
                        )
                        or (
                            attribute in {"href", "src", "target", "url", "path"}
                            and (
                                ":" in target
                                or target.startswith("/")
                                or "\\" in target
                                or ".." in target.split("/")
                            )
                        )
                    ):
                        raise ConversionError(ConversionErrorCode.UNSUPPORTED_ACTIVE_CONTENT)
