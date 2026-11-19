from collections.abc import Iterator
from dataclasses import dataclass
from typing import Final, Literal
from xml.etree.ElementTree import Element

from submission.document_contracts import (
    BlockId,
    CharacterRange,
    DocumentBlock,
    DocumentDiagnostic,
    DocumentSource,
    NormalizationSpan,
    SourceLocator,
    SourceReference,
    SourceTextSpan,
)

PARA_NS: Final = "http://www.hancom.co.kr/hwpml/2011/paragraph"
SECTION_NS: Final = "http://www.hancom.co.kr/hwpml/2011/section"
HEAD_NS: Final = "http://www.hancom.co.kr/hwpml/2011/head"
type StoryKind = Literal["footnote", "header", "footer"]
type BlockKind = Literal["paragraph", "table_cell", "footnote", "header", "footer", "figure"]
type TextBasis = Literal[
    "source_node_unicode", "source_node_tail_unicode", "synthetic_control_unicode"
]


def node_segment(node: Element) -> str:
    return (
        node.tag.replace(f"{{{PARA_NS}}}", "hp:")
        .replace(f"{{{SECTION_NS}}}", "hs:")
        .replace(f"{{{HEAD_NS}}}", "hh:")
    )


def child_paths(node: Element, path: str) -> Iterator[tuple[Element, str]]:
    counts: dict[str, int] = {}
    for child in node:
        index = counts.get(child.tag, 0) + 1
        counts = {**counts, child.tag: index}
        yield child, f"{path}/{node_segment(child)}[{index}]"


@dataclass(frozen=True, slots=True)
class LocatedNode:
    node: Element
    path: str

    @property
    def name(self) -> str:
        return node_segment(self.node)

    def children(self) -> Iterator["LocatedNode"]:
        return (LocatedNode(node, path) for node, path in child_paths(self.node, self.path))


@dataclass(frozen=True, slots=True)
class HwpxReadResult:
    blocks: tuple[DocumentBlock, ...] = ()
    warnings: tuple[DocumentDiagnostic, ...] = ()
    references: tuple[SourceReference, ...] = ()

    def joined(self, other: "HwpxReadResult") -> "HwpxReadResult":
        return HwpxReadResult(
            self.blocks + other.blocks,
            self.warnings + other.warnings,
            self.references + other.references,
        )


@dataclass(frozen=True, slots=True)
class BlockPosition:
    path: str
    parent: BlockId | None
    order: int


@dataclass(frozen=True, slots=True)
class ParagraphFragment:
    text: str = ""
    spans: tuple[SourceTextSpan, ...] = ()
    offset: int = 0
    index: int = 1


@dataclass(frozen=True, slots=True)
class SourceContext:
    source: DocumentSource
    part: str

    def locator(self, path: str) -> SourceLocator:
        return SourceLocator(
            source_sha256=self.source.content_sha256,
            path=f"{self.part}::{path}",
            original_page_number=None,
        )

    def warning(
        self, path: str, *, invalid: bool = False, code: str | None = None
    ) -> DocumentDiagnostic:
        return DocumentDiagnostic(
            code=code or ("invalid_structure" if invalid else "unsupported_element"),
            page_number=None,
            source_locator=self.locator(path),
        )

    def block(
        self,
        position: BlockPosition,
        kind: BlockKind,
        fragment: ParagraphFragment | None = None,
    ) -> DocumentBlock:
        text = fragment.text if fragment is not None else ""
        offset = fragment.offset if fragment is not None else 0
        bounds = CharacterRange(start=0, end=len(text))
        locator = self.locator(position.path)
        identity = f"{self.source.source_id}:{locator.path}"
        return DocumentBlock(
            block_id=BlockId(
                f"{identity}:fragment:{fragment.index}" if fragment is not None else identity
            ),
            kind=kind,
            raw_text=text,
            normalized_text=text,
            normalization_version="identity-v1",
            normalization_map=(NormalizationSpan(raw_range=bounds, normalized_range=bounds),)
            if fragment is not None
            else (),
            source_locator=locator,
            raw_char_range=CharacterRange(start=offset, end=offset + len(text)),
            raw_coordinate_basis="hwpx_paragraph_unicode",
            source_spans=fragment.spans if fragment is not None else (),
            source_fragment_index=fragment.index if fragment is not None else None,
            parent_block_id=position.parent,
            reading_order=position.order,
        )


@dataclass(frozen=True, slots=True)
class TextPiece:
    text: str
    path: str
    basis: TextBasis

    def append_to(self, fragment: ParagraphFragment, context: SourceContext) -> ParagraphFragment:
        offset = len(fragment.text)
        return ParagraphFragment(
            fragment.text + self.text,
            (
                *fragment.spans,
                SourceTextSpan(
                    source_locator=context.locator(self.path),
                    source_char_range=CharacterRange(start=0, end=len(self.text)),
                    block_char_range=CharacterRange(start=offset, end=offset + len(self.text)),
                    source_coordinate_basis=self.basis,
                ),
            ),
            fragment.offset,
            fragment.index,
        )
