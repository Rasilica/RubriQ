from collections.abc import Iterator
from dataclasses import dataclass
from typing import Final

from submission.document_contracts import DocumentDiagnostic
from submission.hwpx_structure_types import LocatedNode, SourceContext, StoryKind, TextPiece

CONTROLS: Final = {
    "hp:tab": "\t",
    "hp:lineBreak": "\n",
    "hp:nbSpace": "\u00a0",
    "hp:fwSpace": "\u3000",
}
FORMATTING: Final = frozenset(
    {
        "hp:linesegarray",
        "hp:lineseg",
        "hp:cellAddr",
        "hp:cellSpan",
        "hp:cellSz",
        "hp:cellMargin",
        "hp:sz",
        "hp:pos",
        "hp:outMargin",
        "hp:inMargin",
    }
)
STORIES: Final[dict[str, StoryKind]] = {
    "hp:footNote": "footnote",
    "hp:header": "header",
    "hp:footer": "footer",
}
# Pictures and picture groups; drawn shapes count as figures only when they hold a text box.
FIGURES: Final = frozenset({"hp:pic", "hp:container"})
SHAPES: Final = frozenset({"hp:rect", "hp:ellipse", "hp:arc", "hp:polygon", "hp:curve"})


def figure_parts(located: LocatedNode) -> tuple[list[LocatedNode], list[LocatedNode], bool]:
    """Captions and text box lists in the figure's own subtree, and whether it holds a picture.

    Nested pictures own their captions; captions and text boxes are not searched inside.
    """
    captions: list[LocatedNode] = []
    lists: list[LocatedNode] = []
    has_picture = located.name == "hp:pic"
    pending = list(located.children())[::-1]
    while pending:
        child = pending.pop()
        if child.name == "hp:caption":
            captions.append(child)
        elif child.name == "hp:drawText":
            lists.extend(item for item in child.children() if item.name == "hp:subList")
        elif child.name == "hp:pic":
            has_picture = True
        else:
            pending.extend(list(child.children())[::-1])
    return captions, lists, has_picture


type InlineEvent = TextPiece | LocatedNode | DocumentDiagnostic


@dataclass(frozen=True, slots=True)
class ParagraphProjection:
    context: SourceContext

    def outside_text(self, located: LocatedNode) -> Iterator[DocumentDiagnostic]:
        if (located.node.text or "").strip():
            yield self.context.warning(located.path, invalid=True)

    def tail_warning(self, located: LocatedNode) -> Iterator[DocumentDiagnostic]:
        if (located.node.tail or "").strip():
            yield self.context.warning(located.path, invalid=True)

    def formatting(self, located: LocatedNode) -> Iterator[DocumentDiagnostic]:
        if located.name not in FORMATTING:
            yield self.context.warning(located.path)
            return
        yield from self.outside_text(located)
        for child in located.children():
            yield from self.formatting(child)
            yield from self.tail_warning(child)

    def text(self, located: LocatedNode) -> Iterator[InlineEvent]:
        if located.node.text:
            yield TextPiece(located.node.text, located.path, "source_node_unicode")
        for child in located.children():
            control = CONTROLS.get(child.name)
            if control is None:
                yield self.context.warning(child.path)
            elif len(child.node) or (child.node.text or "").strip():
                yield self.context.warning(child.path, invalid=True)
            else:
                yield TextPiece(control, child.path, "synthetic_control_unicode")
            if child.node.tail:
                yield TextPiece(child.node.tail, child.path, "source_node_tail_unicode")

    def inline(self, located: LocatedNode) -> Iterator[InlineEvent]:
        yield from self.outside_text(located)
        allowed = {
            "hp:p": frozenset({"hp:run", "hp:linesegarray"}),
            "hp:run": frozenset({"hp:t", "hp:tbl", "hp:ctrl", "hp:secPr", *FIGURES, *SHAPES}),
            "hp:ctrl": frozenset(STORIES),
        }
        for child in located.children():
            if child.name not in allowed[located.name]:
                yield self.context.warning(child.path)
            elif child.name in {"hp:run", "hp:ctrl"}:
                yield from self.inline(child)
            elif child.name == "hp:t":
                yield from self.text(child)
            elif child.name in SHAPES and not figure_parts(child)[1]:
                yield self.context.warning(child.path)
            elif child.name in {"hp:tbl", *FIGURES, *SHAPES, *STORIES}:
                yield child
            else:
                yield from self.formatting(child)
            yield from self.tail_warning(child)
