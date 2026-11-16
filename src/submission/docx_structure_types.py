from collections.abc import Iterator
from dataclasses import dataclass
from typing import Final, Literal
from xml.etree.ElementTree import Element

from submission.document_contracts import (
    BlockId,
    DocumentBlock,
    DocumentDiagnostic,
    SourceLocator,
    SourceTextSpan,
)
from submission.docx_validation import WORD_NS

REL: Final = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PROPERTIES: Final = frozenset({"pPr", "rPr", "tblPr", "tblGrid", "trPr", "tcPr", "sectPr"})
MARKERS: Final = frozenset(
    {
        "bookmarkStart",
        "bookmarkEnd",
        "proofErr",
        "commentRangeStart",
        "commentRangeEnd",
        "footnoteRef",
        "lastRenderedPageBreak",
    }
)
UNSUPPORTED: Final = frozenset(
    {
        "ins",
        "del",
        "moveFrom",
        "moveTo",
        "drawing",
        "pict",
        "object",
        "txbxContent",
        "fldSimple",
        "instrText",
        "fldChar",
        "commentReference",
    }
)
CONTROLS: Final = {
    "tab": "\t",
    "br": "\n",
    "cr": "\n",
    "noBreakHyphen": "\u2011",
    "softHyphen": "\u00ad",
}


@dataclass(frozen=True, slots=True)
class PendingReference:
    kind: Literal["footnote", "header", "footer"]
    key: str
    source_locator: SourceLocator
    source_block_id: BlockId | None
    source_char_offset: int | None


@dataclass(frozen=True, slots=True)
class StructureResult:
    blocks: tuple[DocumentBlock, ...] = ()
    warnings: tuple[DocumentDiagnostic, ...] = ()
    references: tuple[PendingReference, ...] = ()


@dataclass(frozen=True, slots=True)
class ParagraphText:
    text: str = ""
    spans: tuple[SourceTextSpan, ...] = ()
    warnings: tuple[DocumentDiagnostic, ...] = ()
    references: tuple[PendingReference, ...] = ()


EMPTY_TEXT: Final = ParagraphText()


def node_name(node: Element) -> str:
    return (
        node.tag.removeprefix(f"{{{WORD_NS}}}")
        if node.tag.startswith(f"{{{WORD_NS}}}")
        else f"unknown:{node.tag}"
    )


def node_segment(node: Element) -> str:
    return node.tag.replace(f"{{{WORD_NS}}}", "w:")


def child_paths(node: Element, path: str) -> Iterator[tuple[Element, str]]:
    counts: dict[str, int] = {}
    for child in node:
        index = counts.get(child.tag, 0) + 1
        counts = {**counts, child.tag: index}
        yield child, f"{path}/{node_segment(child)}[{index}]"


@dataclass(frozen=True, slots=True)
class RegionPosition:
    root_path: str | None = None
    start_order: int = 0


EMPTY_POSITION: Final = RegionPosition()
FORMATTING: Final = frozenset(
    [
        "pStyle",
        "rStyle",
        "b",
        "bCs",
        "i",
        "iCs",
        "caps",
        "smallCaps",
        "strike",
        "dstrike",
        "outline",
        "shadow",
        "emboss",
        "imprint",
        "vanish",
        "webHidden",
        "color",
        "spacing",
        "sz",
        "szCs",
        "highlight",
        "u",
        "effect",
        "bdr",
        "shd",
        "fitText",
        "vertAlign",
        "rtl",
        "cs",
        "em",
        "lang",
        "eastAsianLayout",
        "specVanish",
        "oMath",
        "rFonts",
        "kern",
        "position",
        "textScale",
        "keepNext",
        "keepLines",
        "pageBreakBefore",
        "framePr",
        "widowControl",
        "numPr",
        "suppressLineNumbers",
        "pBdr",
        "tabs",
        "tab",
        "suppressAutoHyphens",
        "kinsoku",
        "wordWrap",
        "overflowPunct",
        "topLinePunct",
        "autoSpaceDE",
        "autoSpaceDN",
        "bidi",
        "adjustRightInd",
        "snapToGrid",
        "ind",
        "contextualSpacing",
        "mirrorIndents",
        "suppressOverlap",
        "jc",
        "textDirection",
        "textAlignment",
        "textboxTightWrap",
        "outlineLvl",
        "divId",
        "cnfStyle",
        "gridCol",
        "tblStyle",
        "tblpPr",
        "tblOverlap",
        "tblW",
        "tblInd",
        "tblBorders",
        "tblLayout",
        "tblCellMar",
        "tblLook",
        "tblCaption",
        "tblDescription",
        "tblStyleRowBandSize",
        "tblStyleColBandSize",
        "trHeight",
        "cantSplit",
        "tblHeader",
        "tblCellSpacing",
        "gridBefore",
        "gridAfter",
        "wBefore",
        "wAfter",
        "hidden",
        "tcW",
        "gridSpan",
        "hMerge",
        "vMerge",
        "tcBorders",
        "noWrap",
        "tcMar",
        "tcFitText",
        "vAlign",
        "hideMark",
        "top",
        "bottom",
        "left",
        "right",
        "start",
        "end",
        "insideH",
        "insideV",
        "pgSz",
        "pgMar",
        "paperSrc",
        "pgBorders",
        "lnNumType",
        "pgNumType",
        "cols",
        "col",
        "formProt",
        "type",
        "vAlign",
        "titlePg",
        "textDirection",
        "bidi",
        "rtlGutter",
        "docGrid",
        "printerSettings",
        "footnotePr",
        "endnotePr",
        "numFmt",
        "numStart",
        "numRestart",
        "pos",
        "numId",
        "ilvl",
    ]
)
STRUCTURAL_CHILDREN: Final = {
    "body": frozenset({"p", "tbl", "sectPr"}),
    "hdr": frozenset({"p", "tbl"}),
    "ftr": frozenset({"p", "tbl"}),
    "footnote": frozenset({"p", "tbl"}),
    "tbl": frozenset({"tblPr", "tblGrid", "tr"}),
    "tr": frozenset({"trPr", "tc"}),
    "tc": frozenset({"tcPr", "p", "tbl"}),
}
