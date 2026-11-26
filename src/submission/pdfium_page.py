"""Render one PDF page to PNG in a child process, used where Poppler is not installed."""

# pypdfium2 ships without complete type information.
# pyright: reportMissingImports=false, reportUnknownMemberType=false
# pyright: reportUnknownVariableType=false, reportUnknownArgumentType=false
# pyright: reportMissingTypeStubs=false, reportAny=false

import sys
from pathlib import Path


def render(source: Path, page: int, max_edge: int, target: Path) -> None:
    import pypdfium2  # noqa: PLC0415 -- installed on Windows only.

    document = pypdfium2.PdfDocument(source.read_bytes())
    try:
        sheet = document[page - 1]
        scale = max_edge / max(sheet.get_size())
        image = sheet.render(scale=scale).to_pil()
        image.thumbnail((max_edge, max_edge))
        _ = image.save(target, "PNG")
    finally:
        _ = document.close()


if __name__ == "__main__":
    render(Path(sys.argv[1]), int(sys.argv[2]), int(sys.argv[3]), Path(sys.argv[4]))
