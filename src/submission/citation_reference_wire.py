"""Request-local selectors bind report evidence to authoritative source intervals."""

import json
from dataclasses import dataclass
from typing import Final

from pydantic import JsonValue, TypeAdapter, ValidationError

from submission import semantic_diagnostics as diagnostics
from submission.cloud_contracts import CloudCode, CloudError
from submission.report_check_contracts import ReportCheckModelResponse
from submission.semantic_wire import MAX_OUTPUT_BYTES, WireDocument, wire_document

MAX_WHOLE_BLOCK: Final = 10_000
CHUNK_CHARACTERS: Final = 4_000


@dataclass(frozen=True, slots=True)
class CitationReference:
    reference: str
    block_id: str
    quote: str
    start: int
    end: int

    def metadata(self) -> JsonValue:
        return {
            "citation_ref": self.reference,
            "char_range": {"start": self.start, "end": self.end},
        }

    def citation(self) -> JsonValue:
        return {
            "block_id": self.block_id,
            "quote": self.quote,
            "char_range": {"start": self.start, "end": self.end},
        }


@dataclass(frozen=True, slots=True)
class ReferenceWire:
    document: WireDocument
    references: tuple[CitationReference, ...]

    def prepare(self, payload: str) -> str:
        value = TypeAdapter(dict[str, JsonValue]).validate_json(self.document.prepare(payload))
        schema = TypeAdapter(dict[str, JsonValue]).validate_python(
            ReportCheckModelResponse.model_json_schema()
        )
        definitions = schema.get("$defs")
        match definitions:
            case dict():
                schema = {
                    **schema,
                    "$defs": {
                        **definitions,
                        "CitationInput": {
                            "type": "object",
                            "additionalProperties": False,
                            "required": ["citation_ref"],
                            "properties": {
                                "citation_ref": {
                                    "type": "string",
                                    "enum": [ref.reference for ref in self.references],
                                }
                            },
                        },
                    },
                }
            case _:
                return self.document.prepare(payload)
        blocks = value.get("blocks")
        match blocks:
            case list():
                value = {**value, "blocks": [self.prepare_block(block) for block in blocks]}
            case _:
                return self.document.prepare(payload)
        return json.dumps({**value, "response_schema_json": json.dumps(schema)}, ensure_ascii=False)

    def prepare_block(self, block: JsonValue) -> JsonValue:
        match block:
            case {"block_id": str(identifier)}:
                return {
                    **block,
                    "citation_refs": [
                        ref.metadata()
                        for ref in self.references
                        if self.document.translate(ref.block_id, "prepare") == identifier
                    ],
                }
            case _:
                return block

    def restore(self, payload: str) -> str:
        value = TypeAdapter[JsonValue](JsonValue).validate_json(payload)
        restored = self.restore_references(value)
        restored = self.document.walk(restored, "restore")
        # Bound serialization while expanding repeated references to long source intervals.
        chunks: list[str] = []
        total = 0
        for chunk in json.JSONEncoder(ensure_ascii=False).iterencode(restored):
            total += len(chunk.encode("utf-8"))
            if total > MAX_OUTPUT_BYTES:
                diagnostics.mark("output_validation", "response_too_large")
                raise CloudError(CloudCode.INVALID_RESPONSE, 502)
            chunks.append(chunk)
        return "".join(chunks)

    def restore_references(self, value: JsonValue, path: tuple[str, ...] = ()) -> JsonValue:
        """Only evidence citations, not arbitrary similarly named data, carry selectors."""
        citation_paths = (
            ("items", "*", "evidence", "*", "citation"),
            ("items", "*", "subconditions", "*", "evidence", "*", "citation"),
        )
        match value:
            case dict():
                if path in citation_paths and set(value) == {"citation_ref"}:
                    found = next(
                        (ref for ref in self.references if ref.reference == value["citation_ref"]),
                        None,
                    )
                    if found is not None:
                        return found.citation()
                return {
                    key: self.restore_references(item, (*path, key)) for key, item in value.items()
                }
            case list():
                return [self.restore_references(item, (*path, "*")) for item in value]
            case _:
                return value


def reference_wire(payload: str) -> ReferenceWire | WireDocument:
    """Enable selectors only for the server's exact report response contract."""
    document = wire_document(payload)
    value = TypeAdapter[JsonValue](JsonValue).validate_json(payload)
    match value:
        case {"expected_items": list(), "response_schema_json": str(schema)}:
            try:
                parsed = TypeAdapter[JsonValue](JsonValue).validate_json(schema)
            except ValidationError:
                return document
            if parsed != ReportCheckModelResponse.model_json_schema():
                return document
        case _:
            return document
    intervals = tuple(
        (identifier, text[start : start + chunk_size], start)
        for identifier, text in document.blocks
        for chunk_size in (len(text) if len(text) <= MAX_WHOLE_BLOCK else CHUNK_CHARACTERS,)
        for start in range(0, len(text), max(chunk_size, 1))
        if text[start : start + chunk_size].strip()
    )
    return ReferenceWire(
        document,
        tuple(
            CitationReference(f"q{index}", identifier, quote, start, start + len(quote))
            for index, (identifier, quote, start) in enumerate(intervals)
        ),
    )
