from hashlib import sha256

from submission.document_contracts import ArtifactId, CharacterRange, DocumentArtifact
from submission.evidence_artifacts import make_synthetic_artifact
from submission.evidence_contracts import (
    ArtifactBinding,
    ArtifactPage,
    EvidenceMapContext,
    EvidenceMapRequest,
    PdfArtifactInput,
)
from submission.extraction import extract_pdf
from submission.models import DocumentRole, PdfInput
from submission.pdf_adapter import adapt_pdf
from submission.requirement_contracts import CitationInput


def document(content):
    source = PdfInput("sample.pdf", content, DocumentRole.REPORT)
    return adapt_pdf(source, extract_pdf(source))


def synthetic_context(content, texts):
    source = document(content)
    artifact = DocumentArtifact(
        artifact_id=ArtifactId("preview"),
        artifact_sha256=sha256(b"synthetic fixture").hexdigest(),
        kind="preview_pdf",
        parent_source_id=source.source.source_id,
    )
    binding = ArtifactBinding(source=source.source, artifact=artifact)
    pages = tuple(ArtifactPage(number=index, text=text) for index, text in enumerate(texts, 1))
    return EvidenceMapContext(document=source, target=make_synthetic_artifact(binding, pages))


def request_for(ctx):
    block = ctx.document.blocks[0]
    return EvidenceMapRequest(
        citation=CitationInput(
            block_id=block.block_id,
            char_range=CharacterRange(start=0, end=len(block.raw_text)),
            quote=block.raw_text,
        )
    )


def original_target(content):
    source = document(content)
    return PdfArtifactInput(
        binding=ArtifactBinding(source=source.source, artifact=source.artifacts[0]),
        pdf=PdfInput("source.pdf", content, DocumentRole.REPORT),
    )
