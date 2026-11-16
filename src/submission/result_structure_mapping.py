from hashlib import sha256
from typing import Literal

from submission.document_contracts import (
    ArtifactId,
    ArtifactTextRange,
    CharacterRange,
    CommonDocument,
    DocumentArtifact,
)
from submission.evidence_artifacts import make_synthetic_artifact
from submission.evidence_contracts import (
    ArtifactBinding,
    ArtifactPage,
    EvidenceMapContext,
    EvidenceMapRequest,
    SyntheticArtifactInput,
)
from submission.evidence_mapping import map_evidence
from submission.requirement_contracts import CitationInput
from submission.requirement_validation import verify_citation
from submission.result_structure_contracts import StructureScenario


def synthetic_target(document: CommonDocument, name: str, text: str) -> SyntheticArtifactInput:
    return make_synthetic_artifact(
        ArtifactBinding(
            source=document.source,
            artifact=DocumentArtifact(
                artifact_id=ArtifactId(f"synthetic:{name}"),
                artifact_sha256=sha256(text.encode()).hexdigest(),
                kind="preview_pdf",
                parent_source_id=document.source.source_id,
            ),
        ),
        (ArtifactPage(number=1, text=text),),
    )


def structure_scenarios(document: CommonDocument) -> tuple[StructureScenario, ...]:
    block = next(block for block in document.blocks if block.raw_text.strip())
    span = CharacterRange(start=0, end=len(block.raw_text))
    citation = verify_citation(
        CitationInput(block_id=block.block_id, char_range=span, quote=block.raw_text),
        document.blocks,
    )
    names: tuple[Literal["ambiguous", "unmapped", "mismatch"], ...] = (
        "ambiguous",
        "unmapped",
        "mismatch",
    )
    labels = ("합성 예시 · 여러 대응 후보", "합성 예시 · 대응 없음", "합성 예시 · 지정 위치 불일치")
    texts = (block.raw_text + "\n" + block.raw_text, "별도 합성 문장", "변" + block.raw_text[1:])
    return tuple(
        StructureScenario(
            case_name=name,
            label=label,
            citation=citation,
            result=map_evidence(
                EvidenceMapContext(
                    document=document,
                    target=synthetic_target(document, name, text),
                ),
                EvidenceMapRequest(
                    citation=CitationInput(
                        block_id=block.block_id,
                        char_range=span,
                        quote=block.raw_text,
                    ),
                    expected_target_ranges=(ArtifactTextRange(page_number=1, char_range=span),)
                    if name == "mismatch"
                    else None,
                ),
            ),
        )
        for name, label, text in zip(names, labels, texts, strict=True)
    )
