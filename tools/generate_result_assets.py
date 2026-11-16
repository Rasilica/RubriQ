# /// script
# requires-python = ">=3.13"
# dependencies = []
# ///
# Run prepare, render with pdftoppm, then manifest <renderer-version> from API.
import sys
from enum import StrEnum
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from typing import Final, Literal, assert_never

from pypdf import PdfReader, PdfWriter

from submission.models import FrozenModel

type DocumentName = Literal["guide", "normal", "missing", "over_limit"]
MANIFEST_ARGUMENT_COUNT: Final = 2


class AssetMode(StrEnum):
    PREPARE = "prepare"
    MANIFEST = "manifest"


class Renderer(FrozenModel):
    name: Literal["pdftoppm"] = "pdftoppm"
    version: str
    dpi: Literal[110] = 110


class RenderedPage(FrozenModel):
    page_number: int
    image_path: str
    image_sha256: str
    width: int
    height: int


class RenderedDocument(FrozenModel):
    document_id: DocumentName
    pdf_path: str
    pdf_sha256: str
    pages: tuple[RenderedPage, ...]


class AssetManifest(FrozenModel):
    schema_version: Literal["1"] = "1"
    renderer: Renderer
    documents: tuple[RenderedDocument, ...]


def create_over_limit(samples: Path) -> Path:
    reader = PdfReader(BytesIO((samples / "pdf/normal.pdf").read_bytes()))
    writer = PdfWriter()
    for page in reader.pages:
        _ = writer.add_page(page)
    _ = writer.add_page(reader.pages[-1])
    output = BytesIO()
    _ = writer.write(output)
    destination = samples / "result-demos/over-limit.pdf"
    destination.parent.mkdir(parents=True, exist_ok=True)
    _ = destination.write_bytes(output.getvalue())
    return destination


def render_document(samples: Path, name: DocumentName, pdf_path: Path) -> RenderedDocument:
    content = pdf_path.read_bytes()
    page_count = len(PdfReader(BytesIO(content)).pages)
    pages = tuple(store_page(samples, name, number) for number in range(1, page_count + 1))
    return RenderedDocument(
        document_id=name,
        pdf_path=pdf_path.relative_to(samples).as_posix(),
        pdf_sha256=sha256(content).hexdigest(),
        pages=pages,
    )


def store_page(samples: Path, name: DocumentName, number: int) -> RenderedPage:
    destination = samples / "result-demos/pages" / f"{name}-{number}.png"
    content = destination.read_bytes()
    return RenderedPage(
        page_number=number,
        image_path=destination.relative_to(samples).as_posix(),
        image_sha256=sha256(content).hexdigest(),
        width=int.from_bytes(content[16:20], "big"),
        height=int.from_bytes(content[20:24], "big"),
    )


def write_manifest(version: str) -> None:
    samples = Path(__file__).resolve().parents[1] / "samples"
    sources: tuple[tuple[DocumentName, Path], ...] = (
        ("guide", samples / "pdf/guide.pdf"),
        ("normal", samples / "pdf/normal.pdf"),
        ("missing", samples / "pdf/missing.pdf"),
        ("over_limit", samples / "result-demos/over-limit.pdf"),
    )
    manifest = AssetManifest(
        renderer=Renderer(version=version),
        documents=tuple(render_document(samples, name, source) for name, source in sources),
    )
    _ = (samples / "result-demos/manifest.json").write_text(
        manifest.model_dump_json(indent=2) + "\n",
        encoding="utf-8",
    )
    count = sum(len(document.pages) for document in manifest.documents)
    _ = sys.stdout.write(f"Recorded {count} original PDF pages.\n")


def command(arguments: tuple[str, ...]) -> tuple[AssetMode, str]:
    if arguments == ("prepare",):
        return AssetMode.PREPARE, ""
    if len(arguments) == MANIFEST_ARGUMENT_COUNT and arguments[0] == "manifest":
        return AssetMode.MANIFEST, arguments[1]
    _ = sys.stderr.write("Usage: generate_result_assets prepare | manifest <pdftoppm-version>\n")
    raise SystemExit(2)


def main() -> None:
    mode, version = command(tuple(sys.argv[1:]))
    match mode:
        case AssetMode.PREPARE:
            samples = Path(__file__).resolve().parents[1] / "samples"
            _ = create_over_limit(samples)
            (samples / "result-demos/pages").mkdir(parents=True, exist_ok=True)
        case AssetMode.MANIFEST:
            write_manifest(version)
        case _:
            assert_never(mode)


if __name__ == "__main__":
    main()
