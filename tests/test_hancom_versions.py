from io import BytesIO
from zipfile import ZipFile

import pytest

from submission.formats import inspect_document
from submission.input_contracts import DocumentInput, InputValidationError
from submission.models import DocumentRole


def versioned_hwpx(version: bytes) -> DocumentInput:
    package = BytesIO()
    with ZipFile("samples/formats/spine-order.hwpx") as original, ZipFile(package, "w") as archive:
        for item in original.infolist():
            content = version if item.filename == "version.xml" else original.read(item)
            archive.writestr(item, content)
    return DocumentInput("sample.hwpx", package.getvalue(), DocumentRole.REPORT)


def test_hwpx_5050_keeps_actual_version() -> None:
    version = b"""<HCFVersion xmlns="http://www.hancom.co.kr/hwpml/2011/version"
major="5" minor="0" micro="5" buildNumber="0" xmlVersion="1.4"/>"""

    result = inspect_document(versioned_hwpx(version))

    assert result.source.format_version == "HCF-5.0.5.0/XML-1.4"


def test_hwpx_5101_xml13_from_older_hancom_is_accepted() -> None:
    version = b"""<HCFVersion xmlns="http://www.hancom.co.kr/hwpml/2011/version"
major="5" minor="1" micro="0" buildNumber="1" xmlVersion="1.3"/>"""

    result = inspect_document(versioned_hwpx(version))

    assert result.source.format_version == "HCF-5.1.0.1/XML-1.3"


def hcf(
    major: str = "5", minor: str = "1", micro: str = "0", build: str = "1", xml: str = "1.4"
) -> bytes:
    attrs = {
        "major": major,
        "minor": minor,
        "micro": micro,
        "buildNumber": build,
        "xmlVersion": xml,
    }
    body = " ".join(f'{k}="{v}"' for k, v in attrs.items() if v is not None)
    return f'<HCFVersion xmlns="http://www.hancom.co.kr/hwpml/2011/version" {body}/>'.encode()


def test_hwpx_5101_xml14_from_hangul_2018_is_accepted() -> None:
    result = inspect_document(versioned_hwpx(hcf()))

    assert result.source.format_version == "HCF-5.1.0.1/XML-1.4"


@pytest.mark.parametrize(
    ("components", "xml"),
    [(("5", "1", "1", "0"), "1.5"), (("5", "0", "5", "0"), "1.4"), (("5", "1", "0", "1"), "1.3")],
)
def test_previously_accepted_hwpx_versions_still_pass(
    components: tuple[str, ...], xml: str
) -> None:
    result = inspect_document(versioned_hwpx(hcf(*components, xml)))

    assert result.source.format_version == f"HCF-{'.'.join(components)}/XML-{xml}"


@pytest.mark.parametrize(
    "version",
    [
        hcf(major="4"),
        hcf(major="6"),
        hcf(minor="x"),
        hcf(micro="1a"),
        hcf(build=""),
        hcf(minor=None),
        hcf(build=None),
        hcf(xml="1.6"),
        hcf(xml="2.0"),
        hcf(xml=None),
    ],
)
def test_unsupported_hwpx_versions_are_rejected(version: bytes) -> None:
    with pytest.raises(InputValidationError):
        _ = inspect_document(versioned_hwpx(version))
