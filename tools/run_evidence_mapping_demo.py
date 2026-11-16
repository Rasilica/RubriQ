# /// script
# requires-python = ">=3.13"
# dependencies = []
# ///
# Run from API: PYTHONPATH=src .venv/bin/python tools/run_evidence_mapping_demo.py
import json
import sys
from hashlib import sha256
from pathlib import Path
from typing import Literal

from submission.document_contracts import (
    ArtifactId,
    ArtifactTextRange,
    CharacterRange,
    CommonDocument,
    DocumentArtifact,
    ToolDescriptor,
)
from submission.docx_reader import read_docx
from submission.evidence_artifacts import inspect_artifact, make_synthetic_artifact
from submission.evidence_contracts import (
    ArtifactBinding,
    ArtifactPage,
    BoundEvidenceMapping,
    BoundPageCountAssessment,
    EvidenceMapContext,
    EvidenceMapRequest,
    PageSelection,
    PdfArtifactInput,
    SyntheticArtifactInput,
)
from submission.evidence_mapping import map_evidence
from submission.evidence_page_count import assess_page_count
from submission.extraction import extract_pdf
from submission.input_contracts import DocumentInput
from submission.models import DocumentRole, FrozenModel, PdfInput
from submission.pdf_adapter import adapt_pdf
from submission.requirement_contracts import CitationInput


class DemoMapping(FrozenModel):
    case_name: str
    result: BoundEvidenceMapping


class DemoCount(FrozenModel):
    case_name: str
    result: BoundPageCountAssessment


class DemoResult(FrozenModel):
    pdf_source_sha256: str
    docx_source_sha256: str
    pdf_mappings: tuple[BoundEvidenceMapping, ...]
    synthetic_mappings: tuple[DemoMapping, ...]
    counts: tuple[DemoCount, ...]
    conversion_performed: Literal[False] = False


class SyntheticCase(FrozenModel):
    name: str
    texts: tuple[str, ...]
    span: CharacterRange
    expected_ranges: tuple[ArtifactTextRange, ...] | None = None
    block_index: int = 0


def preview_binding(document: CommonDocument, content_hash: str) -> ArtifactBinding:
    return ArtifactBinding(
        source=document.source,
        artifact=DocumentArtifact(
            artifact_id=ArtifactId("demo:preview"),
            artifact_sha256=content_hash,
            kind="preview_pdf",
            parent_source_id=document.source.source_id,
            conversion_chain=(ToolDescriptor(name="authored-test-pair", version="1"),),
        ),
    )


def synthetic_target(document: CommonDocument, texts: tuple[str, ...]) -> SyntheticArtifactInput:
    """Construct authored page fixtures, without claiming a conversion took place."""
    pages = tuple(ArtifactPage(number=index, text=text) for index, text in enumerate(texts, 1))
    fixture_hash = sha256(
        json.dumps(texts, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return make_synthetic_artifact(preview_binding(document, fixture_hash), pages)


def run_synthetic_case(document: CommonDocument, case: SyntheticCase) -> DemoMapping:
    block = document.blocks[case.block_index]
    return DemoMapping(
        case_name=case.name,
        result=map_evidence(
            EvidenceMapContext(document=document, target=synthetic_target(document, case.texts)),
            EvidenceMapRequest(
                citation=CitationInput(
                    block_id=block.block_id,
                    char_range=case.span,
                    quote=block.raw_text[case.span.start : case.span.end],
                ),
                expected_target_ranges=case.expected_ranges,
            ),
        ),
    )


def selection(target: PdfArtifactInput | SyntheticArtifactInput) -> PageSelection:
    snapshot = inspect_artifact(target)
    return PageSelection(
        binding_sha256=snapshot.binding_sha256,
        basis="original_pdf",
        included_pages=tuple(page.number for page in snapshot.pages),
        excluded_pages=(),
        scope_confirmed=True,
    )


def synthetic_cases(document: CommonDocument) -> tuple[SyntheticCase, ...]:
    text = document.blocks[0].raw_text
    midpoint = len(text) // 2
    full = CharacterRange(start=0, end=len(text))
    split_texts = (text[:midpoint], text[midpoint:])
    return (
        SyntheticCase(name="unique", texts=(text,), span=full),
        SyntheticCase(name="split", texts=split_texts, span=full),
        SyntheticCase(name="repeated", texts=(text, text), span=full),
        SyntheticCase(name="missing", texts=("별도 합성 문장",), span=full),
        SyntheticCase(
            name="mismatch",
            texts=("변" + text[1:],),
            span=full,
            expected_ranges=(ArtifactTextRange(page_number=1, char_range=full),),
        ),
        SyntheticCase(
            name="many_to_one_first",
            texts=("합성",),
            span=CharacterRange(start=0, end=2),
        ),
        SyntheticCase(
            name="many_to_one_second",
            texts=("합성",),
            span=CharacterRange(start=0, end=2),
            block_index=next(
                index
                for index, block in enumerate(document.blocks[1:], 1)
                if block.raw_text.startswith("합성")
            ),
        ),
    )


def demo_counts(docx: CommonDocument, original: PdfArtifactInput) -> tuple[DemoCount, ...]:
    actual_preview = PdfArtifactInput(
        binding=preview_binding(docx, original.binding.artifact.artifact_sha256),
        pdf=original.pdf,
    )
    synthetic = synthetic_target(docx, (docx.blocks[0].raw_text,))
    all_pages = selection(original)
    declared = selection(actual_preview).model_copy(
        update={
            "basis": "declared_submission_pdf",
            "declared_submission_sha256": original.binding.artifact.artifact_sha256,
        }
    )
    count_inputs = (
        ("original_all", original, all_pages),
        (
            "original_body_only",
            original,
            all_pages.model_copy(update={"included_pages": (2,), "excluded_pages": (1,)}),
        ),
        ("scope_unconfirmed", original, all_pages.model_copy(update={"scope_confirmed": False})),
        ("declared_pdf", actual_preview, declared),
        (
            "original_editable_layout",
            actual_preview,
            declared.model_copy(update={"basis": "verified_original_layout"}),
        ),
        ("synthetic", synthetic, selection(synthetic)),
    )
    return tuple(
        DemoCount(case_name=name, result=assess_page_count(target, scope))
        for name, target, scope in count_inputs
    )


def run_demo() -> DemoResult:
    samples = Path(__file__).resolve().parents[1] / "samples"
    pdf_path = samples / "pdf/normal.pdf"
    pdf_input = PdfInput(pdf_path.name, pdf_path.read_bytes(), DocumentRole.REPORT)
    pdf_document = adapt_pdf(pdf_input, extract_pdf(pdf_input))
    original = PdfArtifactInput(
        binding=ArtifactBinding(source=pdf_document.source, artifact=pdf_document.artifacts[0]),
        pdf=pdf_input,
    )
    docx_path = samples / "formats/boundary.docx"
    docx = read_docx(DocumentInput(docx_path.name, docx_path.read_bytes(), DocumentRole.REPORT))
    return DemoResult(
        pdf_source_sha256=pdf_document.source.content_sha256,
        docx_source_sha256=docx.source.content_sha256,
        pdf_mappings=tuple(
            map_evidence(
                EvidenceMapContext(document=pdf_document, target=original),
                EvidenceMapRequest(
                    citation=CitationInput(
                        block_id=block.block_id,
                        char_range=CharacterRange(start=0, end=len(block.raw_text)),
                        quote=block.raw_text,
                    )
                ),
            )
            for block in pdf_document.blocks
        ),
        synthetic_mappings=tuple(run_synthetic_case(docx, case) for case in synthetic_cases(docx)),
        counts=demo_counts(docx, original),
    )


if __name__ == "__main__":
    _ = sys.stdout.write(run_demo().model_dump_json(indent=2) + "\n")
