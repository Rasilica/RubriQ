from dataclasses import dataclass

from submission.compatibility_contracts import AnchorReport, ExpectedAnchor
from submission.document_contracts import CharacterRange, CommonDocument
from submission.evidence_anchors import find_candidates
from submission.evidence_artifacts import inspect_artifact
from submission.evidence_contracts import (
    ArtifactBinding,
    ArtifactSnapshot,
    EvidenceLimits,
    EvidenceMapRequest,
    PdfArtifactInput,
)
from submission.evidence_mapping import choose_mapping
from submission.models import PdfInput
from submission.pair_contracts import PreparedRole
from submission.requirement_contracts import CitationInput


@dataclass(frozen=True, slots=True)
class Comparison:
    document: CommonDocument
    preview: ArtifactSnapshot | None
    reference: tuple[str, ...]


def preview_snapshot(role: PreparedRole) -> ArtifactSnapshot | None:
    document = role.view.document
    if role.pdf is None or document is None:
        return None
    return inspect_artifact(
        PdfArtifactInput(
            binding=ArtifactBinding(source=document.source, artifact=document.artifacts[0]),
            pdf=PdfInput("preview.pdf", role.pdf, document.source.role),
        )
    )


def compare_anchor(anchor: ExpectedAnchor, comparison: Comparison) -> AnchorReport:
    matches = tuple(
        block
        for block in comparison.document.blocks
        if anchor.quote in block.raw_text
        and (anchor.locator_path is None or anchor.locator_path == block.source_locator.path)
    )
    snapshot = comparison.preview
    candidates = find_candidates(snapshot.pages, anchor.quote, EvidenceLimits()) if snapshot else ()
    reasons: tuple[str, ...] = ()
    if len(matches) > 1:
        reasons = ("source_ambiguous",)
    if len(matches) == 1 and snapshot is not None:
        block = matches[0]
        start = block.raw_text.index(anchor.quote)
        request = EvidenceMapRequest(
            citation=CitationInput(
                block_id=block.block_id,
                quote=anchor.quote,
                char_range=CharacterRange(start=start, end=start + len(anchor.quote)),
            )
        )
        reasons = (choose_mapping(candidates, request, snapshot).reason,)
    return AnchorReport(
        quote=anchor.quote,
        locator_path=anchor.locator_path,
        source_matches=len(matches),
        reference_pages=tuple(
            index for index, text in enumerate(comparison.reference, 1) if anchor.quote in text
        ),
        preview_pages=tuple(
            sorted({span.page_number for candidate in candidates for span in candidate})
        ),
        mapping_reasons=reasons,
    )
