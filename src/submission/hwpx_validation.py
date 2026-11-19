from xml.etree.ElementTree import Element

from submission.format_containers import PackageMember, member_bytes, parse_xml, relationship_target
from submission.input_contracts import (
    FormatDetails,
    InputErrorCode,
    InputLimits,
    InputValidationError,
)

VERSION_NS = "http://www.hancom.co.kr/hwpml/2011/version"
OPF_NS = "http://www.idpf.org/2007/opf/"
SECTION_NS = "http://www.hancom.co.kr/hwpml/2011/section"
HEAD_NS = "http://www.hancom.co.kr/hwpml/2011/head"
SUPPORTED_HCF_MAJOR = "5"
SUPPORTED_XML_VERSIONS = frozenset({"1.3", "1.4", "1.5"})


def check_hwpx_protection(members: tuple[PackageMember, ...], limits: InputLimits) -> None:
    manifest = next((member for member in members if member.name == "META-INF/manifest.xml"), None)
    if manifest is not None:
        root = parse_xml(manifest.data, limits)
        if any(element.tag.rsplit("}", 1)[-1] == "encryption-data" for element in root.iter()):
            raise InputValidationError(InputErrorCode.ENCRYPTED_DOCUMENT, detected_format="hwpx")


def validate_hwpx_version(members: tuple[PackageMember, ...], limits: InputLimits) -> str:
    version = parse_xml(member_bytes(members, "version.xml"), limits)
    if version.tag != f"{{{VERSION_NS}}}HCFVersion":
        raise InputValidationError(InputErrorCode.UNSUPPORTED_VERSION, detected_format="hwpx")
    components = tuple(version.get(name) for name in ("major", "minor", "micro", "buildNumber"))
    xml_version = version.get("xmlVersion")
    is_supported = (
        components[0] == SUPPORTED_HCF_MAJOR
        and all(part is not None and part.isascii() and part.isdecimal() for part in components)
        and xml_version in SUPPORTED_XML_VERSIONS
    )
    if not is_supported:
        raise InputValidationError(InputErrorCode.UNSUPPORTED_VERSION, detected_format="hwpx")
    return f"HCF-{'.'.join(part for part in components if part is not None)}/XML-{xml_version}"


def hwpx_manifest(
    package: Element,
    members: tuple[PackageMember, ...],
) -> tuple[Element, Element]:
    if package.tag != f"{{{OPF_NS}}}package":
        raise InputValidationError(InputErrorCode.UNSUPPORTED_VERSION, detected_format="hwpx")
    manifest = package.find(f"{{{OPF_NS}}}manifest")
    spine = package.find(f"{{{OPF_NS}}}spine")
    if manifest is None or spine is None:
        raise InputValidationError(InputErrorCode.CORRUPT_DOCUMENT, detected_format="hwpx")
    ids = tuple(item.get("id") for item in manifest)
    if None in ids or len(ids) != len(set(ids)):
        raise InputValidationError(InputErrorCode.CORRUPT_DOCUMENT, detected_format="hwpx")
    for item in manifest:
        target = relationship_target("", item.get("href", ""))
        _ = member_bytes(members, target)
    return manifest, spine


def hwpx_sections(
    package: Element,
    members: tuple[PackageMember, ...],
    limits: InputLimits,
) -> tuple[str, ...]:
    manifest, spine = hwpx_manifest(package, members)
    ordered: tuple[str, ...] = ()
    for reference in spine:
        item = next(
            (entry for entry in manifest if entry.get("id") == reference.get("idref")), None
        )
        if item is None:
            raise InputValidationError(InputErrorCode.CORRUPT_DOCUMENT, detected_format="hwpx")
        # Hancom puts its (never executed) script parts in the spine; they hold no body text.
        if item.get("media-type", "").startswith("application/x-javascript") and item.get(
            "href", ""
        ).startswith("Scripts/"):
            continue
        target = relationship_target("", item.get("href", ""))
        root = parse_xml(member_bytes(members, target), limits)
        match root.tag:
            case tag if tag == f"{{{SECTION_NS}}}sec":
                if target in ordered:
                    raise InputValidationError(
                        InputErrorCode.CORRUPT_DOCUMENT, detected_format="hwpx"
                    )
                ordered += (target,)
            case tag if tag == f"{{{HEAD_NS}}}head":
                continue
            case _:
                raise InputValidationError(
                    InputErrorCode.UNSUPPORTED_VERSION, detected_format="hwpx"
                )
    if not ordered:
        raise InputValidationError(InputErrorCode.EMPTY_DOCUMENT, detected_format="hwpx")
    return ordered


def inspect_hwpx(members: tuple[PackageMember, ...], limits: InputLimits) -> FormatDetails:
    if member_bytes(members, "mimetype") != b"application/hwp+zip":
        raise InputValidationError(InputErrorCode.CORRUPT_DOCUMENT, detected_format="hwpx")
    check_hwpx_protection(members, limits)
    version = validate_hwpx_version(members, limits)
    package = parse_xml(member_bytes(members, "Contents/content.hpf"), limits)
    ordered = hwpx_sections(package, members, limits)
    return FormatDetails(
        detected_format="hwpx",
        version=version,
        members=tuple(member.name for member in members),
        content_members=ordered,
    )
