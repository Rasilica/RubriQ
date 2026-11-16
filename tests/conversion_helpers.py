import base64
import sys
from io import BytesIO
from pathlib import Path

from pypdf import PdfWriter

from submission.input_contracts import DocumentInput
from submission.models import DocumentRole


def source_docx() -> DocumentInput:
    return DocumentInput(
        "boundary.docx", Path("samples/formats/boundary.docx").read_bytes(), DocumentRole.REPORT
    )


def pdf_bytes(pages: int = 1, *, encrypted: bool = False) -> bytes:
    writer = PdfWriter()
    for _ in range(pages):
        _ = writer.add_blank_page(width=100, height=100)
    if encrypted:
        writer.encrypt("fixture")
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


def fake_renderer(tmp_path: Path, content: bytes | None = None, mode: str = "success") -> Path:
    renderer = tmp_path / "renderer"
    payload = base64.b64encode(pdf_bytes() if content is None else content).decode()
    _ = renderer.write_text(
        f"#!{sys.executable}\n"
        "import base64, pathlib, sys, time\n"
        f"mode = {mode!r}\n"
        "if '--version' in sys.argv:\n"
        "    print('LibreOffice 26.2.1.2 8399f6259d8c87f40e7255cdb3c9b958f5e08948')\n"
        "    sys.exit(0)\n"
        "if mode == 'failure': sys.exit(4)\n"
        "if mode == 'missing': sys.exit(0)\n"
        "if mode == 'timeout': time.sleep(10)\n"
        "output = pathlib.Path(sys.argv[sys.argv.index('--outdir') + 1])\n"
        f"(output / 'source.pdf').write_bytes(base64.b64decode({payload!r}))\n"
    )
    renderer.chmod(0o700)
    return renderer
