from hashlib import sha256
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile, ZipInfo

from submission.document_contracts import CommonDocument, StructuralCoverage
from submission.docx_reader import read_docx
from submission.hwpx_reader import read_hwpx
from submission.input_contracts import DocumentInput
from submission.models import DocumentRole
from submission.result_assets import SAMPLES, bounded_read
from submission.result_contracts import ResultCase, ResultError, ResultErrorCode
from submission.result_structure_contracts import StructuralViewerDocument


def verified_sample(path: Path, expected: str) -> bytes:
    content = bounded_read(path)
    if sha256(content).hexdigest() != expected:
        raise ResultError(ResultErrorCode.UNAVAILABLE)
    return content


def replace_member(content: bytes, member: str, replacement: bytes) -> bytes:
    output = BytesIO()
    with ZipFile(BytesIO(content)) as source, ZipFile(output, "w") as target:
        for name in source.namelist():
            target.writestr(
                ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0)),
                replacement if name == member else source.read(name),
            )
    return output.getvalue()


def structure_document(case: ResultCase, *, samples: Path = SAMPLES) -> CommonDocument:
    if case == ResultCase.DOCX_STRUCTURE:
        content = verified_sample(
            samples / "formats/boundary.docx",
            "0ae5c18880f328e11af79b6df953a03dccf1226ea557859c65be4c3fe108a09c",
        )
        with ZipFile(BytesIO(content)) as package:
            body = package.read("word/document.xml")
        body = body.replace(
            b"</w:body>",
            b"<w:p><w:r><w:drawing/></w:r></w:p></w:body>",
        )
        return read_docx(
            DocumentInput(
                "synthetic-structure-loss.docx",
                replace_member(content, "word/document.xml", body),
                DocumentRole.REPORT,
            )
        )
    if case == ResultCase.HWPX_STRUCTURE:
        content = verified_sample(
            samples / "formats/spine-order.hwpx",
            "72372e048f95b841953084893d9a7d172d90761361fa41d6f08a5b36604a275b",
        )
        section = verified_sample(
            samples / "formats/cases/hwpx-structure.xml",
            "2205f6e9740e244516122046adb679848b6f9b2d507880bff6f1d2a7660571e9",
        ).replace(
            b"</hs:sec>",
            b"<hp:p><hp:run><hp:rect/></hp:run></hp:p></hs:sec>",
        )
        return read_hwpx(
            DocumentInput(
                "synthetic-structure-loss.hwpx",
                replace_member(content, "Contents/section1.xml", section),
                DocumentRole.REPORT,
            )
        )
    raise ResultError(ResultErrorCode.NOT_FOUND)


def structure_viewer(document: CommonDocument) -> StructuralViewerDocument:
    if not isinstance(document.coverage, StructuralCoverage):
        raise ResultError(ResultErrorCode.UNAVAILABLE)
    return StructuralViewerDocument(
        source=document.source,
        blocks=document.blocks,
        coverage=document.coverage,
        warnings=document.warnings,
        typed_errors=document.typed_errors,
        extraction_status=document.extraction_status,
        rendering_status=document.rendering_status,
        page_count_assessment=document.page_count,
        references=document.references,
    )
