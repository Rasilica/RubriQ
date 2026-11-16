from dataclasses import dataclass, replace
from typing import Literal, assert_never
from xml.etree.ElementTree import Element

from submission.document_contracts import (
    BlockId,
    CharacterRange,
    DocumentBlock,
    DocumentDiagnostic,
    DocumentSource,
    NormalizationSpan,
    SourceLocator,
    SourceTextSpan,
)
from submission.docx_structure_types import (
    CONTROLS,
    EMPTY_POSITION,
    EMPTY_TEXT,
    FORMATTING,
    MARKERS,
    PROPERTIES,
    REL,
    STRUCTURAL_CHILDREN,
    UNSUPPORTED,
    ParagraphText,
    PendingReference,
    RegionPosition,
    StructureResult,
    child_paths,
    node_name,
    node_segment,
)
from submission.docx_validation import WORD_NS


@dataclass(frozen=True, slots=True)
class _Reader:
    source: DocumentSource
    part: str

    def locator(self, path: str) -> SourceLocator:
        return SourceLocator(
            source_sha256=self.source.content_sha256,
            path=f"{self.part}::{path}",
            original_page_number=None,
        )

    def identity(self, path: str) -> BlockId:
        return BlockId(f"{self.source.source_id}:{self.locator(path).path}")

    def warning(self, path: str, *, invalid: bool = False) -> DocumentDiagnostic:
        return DocumentDiagnostic(
            code="invalid_structure" if invalid else "unsupported_element",
            page_number=None,
            source_locator=self.locator(path),
        )

    def block(
        self,
        path: str,
        kind: Literal["paragraph", "table_cell", "header", "footer", "footnote"],
        parent: BlockId | None,
        order: int,
        text: ParagraphText = EMPTY_TEXT,
    ) -> DocumentBlock:
        bounds = CharacterRange(start=0, end=len(text.text))
        return DocumentBlock(
            block_id=self.identity(path),
            kind=kind,
            raw_text=text.text,
            normalized_text=text.text,
            normalization_version="identity-v1",
            normalization_map=(
                (NormalizationSpan(raw_range=bounds, normalized_range=bounds),)
                if kind == "paragraph"
                else ()
            ),
            source_locator=self.locator(path),
            raw_char_range=bounds,
            raw_coordinate_basis="docx_paragraph_unicode",
            source_spans=text.spans,
            parent_block_id=parent,
            reading_order=order,
        )

    def inline(
        self,
        node: Element,
        path: str,
        paragraph: BlockId | None,
        offset: int = 0,
        *,
        properties: bool = False,
    ) -> ParagraphText:
        name = node_name(node)
        if name in {"footnoteReference", "headerReference", "footerReference"}:
            kind: Literal["footnote", "header", "footer"] = "footnote"
            if name == "headerReference":
                kind = "header"
            elif name == "footerReference":
                kind = "footer"
            namespace = WORD_NS if kind == "footnote" else REL
            return ParagraphText(
                warnings=(self.warning(path, invalid=True),)
                if len(node) or (node.text or "").strip()
                else (),
                references=(
                    PendingReference(
                        kind,
                        node.get(f"{{{namespace}}}id", ""),
                        self.locator(path),
                        paragraph,
                        offset if paragraph is not None else None,
                    ),
                ),
            )
        if name in MARKERS:
            return (
                ParagraphText()
                if not len(node) and not (node.text or "").strip()
                else ParagraphText(warnings=(self.warning(path),))
            )
        if name == "t" or (name in CONTROLS and not (properties and name in FORMATTING)):
            if properties or paragraph is None or len(node):
                return ParagraphText(warnings=(self.warning(path),))
            text = (node.text or "") if name == "t" else CONTROLS[name]
            span = SourceTextSpan(
                source_locator=self.locator(path),
                source_coordinate_basis=(
                    "source_node_unicode" if name == "t" else "synthetic_control_unicode"
                ),
                source_char_range=CharacterRange(start=0, end=len(text)),
                block_char_range=CharacterRange(start=offset, end=offset + len(text)),
            )
            warnings = (
                ()
                if name == "t" or not (node.text or "").strip()
                else (self.warning(path, invalid=True),)
            )
            return ParagraphText(text, (span,), warnings)
        formatting = properties or name in PROPERTIES
        if (
            name in UNSUPPORTED
            or name.endswith("Change")
            or (
                name not in {"p", "r", "hyperlink"}
                and not (formatting and name in PROPERTIES | FORMATTING)
            )
        ):
            return ParagraphText(warnings=(self.warning(path),))
        result = (
            ParagraphText(warnings=(self.warning(path, invalid=True),))
            if (node.text or "").strip()
            else ParagraphText()
        )
        for child, child_path in child_paths(node, path):
            scanned = self.inline(
                child, child_path, paragraph, offset + len(result.text), properties=formatting
            )
            tail = (self.warning(child_path, invalid=True),) if (child.tail or "").strip() else ()
            result = ParagraphText(
                result.text + scanned.text,
                result.spans + scanned.spans,
                result.warnings + scanned.warnings + tail,
                result.references + scanned.references,
            )
        return result

    def structure(
        self, node: Element, path: str, parent: BlockId | None, order: int
    ) -> StructureResult:
        name = node_name(node)
        if name == "p":
            text = self.inline(node, path, self.identity(path))
            return StructureResult(
                (self.block(path, "paragraph", parent, order, text),),
                text.warnings,
                text.references,
            )
        if name in PROPERTIES | MARKERS:
            text = self.inline(node, path, None, properties=True)
            return StructureResult(warnings=text.warnings, references=text.references)
        if name not in STRUCTURAL_CHILDREN:
            return StructureResult(warnings=(self.warning(path),))
        result = StructureResult()
        if name == "tc":
            result = StructureResult((self.block(path, "table_cell", parent, order),))
            parent = self.identity(path)
        if (node.text or "").strip():
            result = replace(result, warnings=(self.warning(path, invalid=True),))
        for child, child_path in child_paths(node, path):
            scanned = (
                self.structure(child, child_path, parent, order + len(result.blocks))
                if node_name(child) in STRUCTURAL_CHILDREN[name] | MARKERS
                else StructureResult(warnings=(self.warning(child_path),))
            )
            tail = (self.warning(child_path, invalid=True),) if (child.tail or "").strip() else ()
            result = StructureResult(
                result.blocks + scanned.blocks,
                result.warnings + scanned.warnings + tail,
                result.references + scanned.references,
            )
        return result


def read_region(
    root: Element,
    part: str,
    source: DocumentSource,
    kind: Literal["body", "header", "footer", "footnote"],
    *,
    position: RegionPosition = EMPTY_POSITION,
) -> StructureResult:
    """Read bounded, parsed OOXML using Unicode offsets and no layout/page inference."""
    reader = _Reader(source, part)
    path = position.root_path or f"/{node_segment(root)}[1]"
    match kind:
        case "body":
            return reader.structure(root, path, None, position.start_order)
        case "header" | "footer" | "footnote":
            container = reader.block(path, kind, None, position.start_order)
            result = reader.structure(root, path, container.block_id, position.start_order + 1)
            return replace(result, blocks=(container, *result.blocks))
    assert_never(kind)
