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


@pytest.mark.parametrize(
    "version",
    [
        b"""<HCFVersion xmlns="http://www.hancom.co.kr/hwpml/2011/version"
major="5" minor="1" micro="0" buildNumber="1" xmlVersion="1.5"/>""",
        b"""<HCFVersion xmlns="http://www.hancom.co.kr/hwpml/2011/version"
major="5" minor="0" micro="5" buildNumber="0" xmlVersion="1.5"/>""",
        b"""<HCFVersion xmlns="http://www.hancom.co.kr/hwpml/2011/version"
major="5" minor="1" micro="1" buildNumber="0" xmlVersion="1.4"/>""",
    ],
)
def test_unknown_hwpx_version_pairs_remain_rejected(version: bytes) -> None:
    with pytest.raises(InputValidationError):
        _ = inspect_document(versioned_hwpx(version))
