from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

from submission.docx_validation import WORD_NS
from submission.input_contracts import DocumentInput
from submission.models import DocumentRole

FIXTURE = Path(__file__).parents[1] / "samples/formats/boundary.docx"
REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
OFFICE_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"


def make_docx(
    body: str,
    members: tuple[tuple[str, str], ...] = (),
    relations: str = "",
) -> bytes:
    result = BytesIO()
    with ZipFile(FIXTURE) as original, ZipFile(result, "w") as package:
        for path in ("[Content_Types].xml", "_rels/.rels"):
            package.writestr(path, original.read(path))
        package.writestr(
            "word/document.xml",
            f'<w:document xmlns:w="{WORD_NS}" xmlns:r="{OFFICE_NS}">'
            f"<w:body>{body}</w:body></w:document>",
        )
        if relations:
            package.writestr(
                "word/_rels/document.xml.rels",
                f'<Relationships xmlns="{REL_NS}">{relations}</Relationships>',
            )
        for path, content in members:
            package.writestr(path, content)
    return result.getvalue()


def source(content: bytes, role: DocumentRole = DocumentRole.REPORT) -> DocumentInput:
    return DocumentInput("../report.docx", content, role)
