from io import BytesIO
from pathlib import Path
from typing import Final
from zipfile import ZipFile

from submission.hwpx_validation import SECTION_NS
from submission.input_contracts import DocumentInput
from submission.models import DocumentRole

FIXTURE: Final = Path(__file__).parents[1] / "samples/formats/spine-order.hwpx"
PARA_NS: Final = "http://www.hancom.co.kr/hwpml/2011/paragraph"


def section(body: str) -> str:
    return f'<hs:sec xmlns:hs="{SECTION_NS}" xmlns:hp="{PARA_NS}">{body}</hs:sec>'


def make_hwpx(body: str, extra: tuple[tuple[str, str], ...] = ()) -> bytes:
    replacements = {"Contents/section1.xml": section(body), **dict(extra)}
    paths = frozenset(replacements)
    result = BytesIO()
    with ZipFile(FIXTURE) as original, ZipFile(result, "w") as package:
        for path in original.namelist():
            if path not in paths:
                package.writestr(path, original.read(path))
        for path, content in replacements.items():
            package.writestr(path, content)
    return result.getvalue()


def source(content: bytes, role: DocumentRole = DocumentRole.REPORT) -> DocumentInput:
    return DocumentInput("../report.hwpx", content, role)
