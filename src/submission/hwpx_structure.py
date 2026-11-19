from dataclasses import dataclass, replace
from typing import assert_never
from xml.etree.ElementTree import Element

from submission.document_contracts import (
    BlockId,
    DocumentDiagnostic,
    DocumentSource,
    SourceReference,
)
from submission.hwpx_projection import (
    FIGURES,
    FORMATTING,
    SHAPES,
    STORIES,
    ParagraphProjection,
    figure_parts,
)
from submission.hwpx_structure_types import (
    BlockPosition,
    HwpxReadResult,
    LocatedNode,
    ParagraphFragment,
    SourceContext,
    StoryKind,
    TextPiece,
    node_segment,
)


@dataclass(frozen=True, slots=True)
class _Reader:
    context: SourceContext

    @property
    def projection(self) -> ParagraphProjection:
        return ParagraphProjection(self.context)

    def paragraph(self, located: LocatedNode, position: BlockPosition) -> HwpxReadResult:
        result = HwpxReadResult()
        fragment = ParagraphFragment()
        has_boundary = False
        for event in self.projection.inline(located):
            match event:
                case TextPiece():
                    fragment = event.append_to(fragment, self.context)
                    continue
                case DocumentDiagnostic():
                    result = replace(result, warnings=(*result.warnings, event))
                    continue
                case LocatedNode():
                    has_boundary = True
                    scanned, fragment = self.boundary(
                        event,
                        replace(position, order=position.order + len(result.blocks)),
                        fragment,
                    )
                    result = result.joined(scanned)
                    continue
                case _:
                    assert_never(event)
        if fragment.text or not has_boundary:
            block = self.context.block(
                replace(position, order=position.order + len(result.blocks)), "paragraph", fragment
            )
            result = replace(result, blocks=(*result.blocks, block))
        return result

    def boundary(
        self, located: LocatedNode, position: BlockPosition, fragment: ParagraphFragment
    ) -> tuple[HwpxReadResult, ParagraphFragment]:
        kind = STORIES.get(located.name)
        result = HwpxReadResult()
        if fragment.text or kind is not None:
            owner = self.context.block(position, "paragraph", fragment)
            result = HwpxReadResult((owner,))
            fragment = ParagraphFragment(
                offset=fragment.offset + len(fragment.text), index=fragment.index + 1
            )
            if kind is not None:
                scanned = self.story(
                    located, replace(position, path=located.path, order=position.order + 1), kind
                )
                target = scanned.blocks[0].source_locator if scanned.blocks else None
                reference = SourceReference(
                    kind=kind,
                    source_locator=self.context.locator(located.path),
                    source_block_id=owner.block_id,
                    source_char_offset=len(owner.raw_text),
                    target_locator=target,
                    status="resolved" if target is not None else "unresolved",
                )
                scanned = replace(scanned, references=(reference, *scanned.references))
                return result.joined(scanned), fragment
        scanned = self.structure(
            located, replace(position, path=located.path, order=position.order + len(result.blocks))
        )
        return result.joined(scanned), fragment

    def story(
        self, located: LocatedNode, position: BlockPosition, kind: StoryKind
    ) -> HwpxReadResult:
        children = tuple(located.children())
        valid = (
            len(children) == 1
            and children[0].name == "hp:subList"
            and not (located.node.text or "").strip()
            and not (children[0].node.tail or "").strip()
        )
        if not valid:
            return HwpxReadResult(warnings=(self.context.warning(located.path, invalid=True),))
        container = self.context.block(position, kind)
        child = children[0]
        return HwpxReadResult((container,)).joined(
            self.structure(child, BlockPosition(child.path, container.block_id, position.order + 1))
        )

    def figure(self, located: LocatedNode, position: BlockPosition) -> HwpxReadResult:
        figure = self.context.block(position, "figure")
        captions, lists, has_picture = figure_parts(located)
        result = HwpxReadResult((figure,))
        # Unread unless nothing but text boxes was found (nothing at all is also unread).
        if has_picture or not (captions or lists):
            result = result.joined(
                HwpxReadResult(
                    warnings=(self.context.warning(located.path, code="figure_content_unread"),)
                )
            )
        for child in (*captions, *lists):
            at = BlockPosition(child.path, figure.block_id, position.order + len(result.blocks))
            result = result.joined(self.structure(child, at))
        return result

    def structure(self, located: LocatedNode, position: BlockPosition) -> HwpxReadResult:
        if located.name == "hp:p":
            return self.paragraph(located, position)
        if located.name in FIGURES | SHAPES:
            return self.figure(located, position)
        if located.name in FORMATTING:
            return HwpxReadResult(warnings=tuple(self.projection.formatting(located)))
        allowed = {
            "hs:sec": frozenset({"hp:p"}),
            "hp:tbl": frozenset(
                {"hp:tr", "hp:sz", "hp:pos", "hp:outMargin", "hp:inMargin", "hp:caption"}
            ),
            "hp:caption": frozenset({"hp:subList"}),
            "hp:tr": frozenset({"hp:tc"}),
            "hp:tc": frozenset(
                {"hp:subList", "hp:cellAddr", "hp:cellSpan", "hp:cellSz", "hp:cellMargin"}
            ),
            "hp:subList": frozenset({"hp:p"}),
        }
        if located.name not in allowed:
            return HwpxReadResult(warnings=(self.context.warning(located.path),))
        result = HwpxReadResult(warnings=tuple(self.projection.outside_text(located)))
        parent: BlockId | None = position.parent
        if located.name == "hp:tc":
            sublists = tuple(child for child in located.children() if child.name == "hp:subList")
            if len(sublists) != 1:
                return result.joined(
                    HwpxReadResult(warnings=(self.context.warning(located.path, invalid=True),))
                )
            container = self.context.block(position, "table_cell")
            result = replace(result, blocks=(container,))
            parent = container.block_id
        for child in located.children():
            scanned = (
                self.structure(
                    child, BlockPosition(child.path, parent, position.order + len(result.blocks))
                )
                if child.name in allowed[located.name]
                else HwpxReadResult(warnings=(self.context.warning(child.path),))
            )
            result = result.joined(scanned).joined(
                HwpxReadResult(warnings=tuple(self.projection.tail_warning(child)))
            )
        return result


def read_section(
    root: Element, part: str, source: DocumentSource, *, start_order: int = 0
) -> HwpxReadResult:
    """Read XML source order and paragraph Unicode coordinates without layout inference."""
    path = f"/{node_segment(root)}[1]"
    reader = _Reader(SourceContext(source, part))
    return reader.structure(LocatedNode(root, path), BlockPosition(path, None, start_order))
