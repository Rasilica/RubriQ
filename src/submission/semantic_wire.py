import json
from dataclasses import dataclass
from typing import Final, Literal

from pydantic import JsonValue, TypeAdapter

MAX_OUTPUT_BYTES: Final = 262144


@dataclass(frozen=True, slots=True)
class WireDocument:
    blocks: tuple[tuple[str, str], ...]

    def prepare(self, payload: str) -> str:
        value = TypeAdapter[JsonValue](JsonValue).validate_json(payload)
        return json.dumps(self.walk(value, "prepare"), ensure_ascii=False)

    def restore(self, payload: str) -> str:
        value = TypeAdapter[JsonValue](JsonValue).validate_json(payload)
        return json.dumps(self.walk(value, "restore"), ensure_ascii=False)

    def translate(self, identifier: str, mode: Literal["prepare", "restore"]) -> str:
        for index, (original, _) in enumerate(self.blocks):
            alias = f"b{index}"
            if identifier == (original if mode == "prepare" else alias):
                return alias if mode == "prepare" else original
        return identifier

    def walk(self, value: JsonValue, mode: Literal["prepare", "restore"]) -> JsonValue:
        if isinstance(value, list):
            return [self.walk(item, mode) for item in value]
        if not isinstance(value, dict):
            return value
        result = {key: self.walk(item, mode) for key, item in value.items()}
        identifier = value.get("block_id")
        if isinstance(identifier, str):
            result["block_id"] = self.translate(identifier, mode)
        reviewed = value.get("reviewed_block_ids")
        if isinstance(reviewed, list):
            result["reviewed_block_ids"] = [
                self.translate(item, mode) if isinstance(item, str) else item for item in reviewed
            ]
        raw = value.get("raw_text")
        if mode == "prepare" and isinstance(raw, str) and isinstance(identifier, str):
            result["unicode_length"] = len(raw)
        if mode == "restore" and set(value) == {"block_id", "quote", "char_range"}:
            return self.anchor(result)
        return result

    def anchor(self, citation: dict[str, JsonValue]) -> dict[str, JsonValue]:
        quote, span = citation.get("quote"), citation.get("char_range")
        if not isinstance(quote, str) or not quote or not isinstance(span, dict):
            return citation
        start, end = span.get("start"), span.get("end")
        if set(span) != {"start", "end"} or type(start) is not int or type(end) is not int:
            return citation
        raw = next(
            (text for identifier, text in self.blocks if identifier == citation["block_id"]), None
        )
        if raw is None or (0 <= start < end <= len(raw) and raw[start:end] == quote):
            return citation
        offset = raw.find(quote)
        if offset < 0 or raw.find(quote, offset + 1) >= 0:
            return citation
        return {**citation, "char_range": {"start": offset, "end": offset + len(quote)}}


def wire_document(payload: str) -> WireDocument:
    value = TypeAdapter[JsonValue](JsonValue).validate_json(payload)
    if not isinstance(value, dict) or not isinstance(value.get("blocks"), list):
        return WireDocument(())
    blocks = value["blocks"]
    if not isinstance(blocks, list):
        return WireDocument(())
    return WireDocument(tuple(pair for block in blocks if (pair := block_pair(block)) is not None))


def block_pair(block: JsonValue) -> tuple[str, str] | None:
    if not isinstance(block, dict):
        return None
    identifier, text = block.get("block_id"), block.get("raw_text")
    if isinstance(identifier, str) and isinstance(text, str):
        return identifier, text
    return None
