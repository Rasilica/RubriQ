import json
from datetime import datetime
from hashlib import sha256
from typing import Final, assert_never

from pydantic import BaseModel, InstanceOf, JsonValue, TypeAdapter

from submission.models import PdfInput
from submission.persistence_contracts import PersistenceError, PersistenceErrorCode

type Node = (
    InstanceOf[BaseModel]
    | InstanceOf[PdfInput]
    | datetime
    | bytes
    | str
    | int
    | float
    | bool
    | list[Node]
    | tuple[Node, ...]
    | dict[str, Node]
    | None
)

NODE: Final = TypeAdapter[Node](Node)


def encode(value: Node, blobs: dict[str, bytes]) -> JsonValue:
    match value:
        case BaseModel() | PdfInput():
            return encode(model_fields(value), blobs)
        case bytes():
            digest = sha256(value).hexdigest()
            blobs[digest] = value
            return {"blob_sha256": digest, "byte_size": len(value)}
        case datetime():
            return value.isoformat()
        case dict():
            return {key: encode(child, blobs) for key, child in value.items()}
        case tuple() | list():
            return [encode(child, blobs) for child in value]
        case str() | int() | float() | None:
            return value
        case _:
            assert_never(value)


def model_fields(value: BaseModel | PdfInput) -> Node:
    match value:
        case BaseModel():
            if value.model_fields_set - type(value).model_fields.keys() or value.model_extra:
                raise PersistenceError(PersistenceErrorCode.INVALID_INPUT)
            return NODE.validate_python(value.__dict__)
        case PdfInput():
            return {"filename": value.filename, "content": value.content, "role": value.role}
        case _:
            assert_never(value)


def decode(value: JsonValue, blobs: dict[str, bytes]) -> Node:
    match value:
        case dict():
            if "blob_sha256" in value:
                digest = value["blob_sha256"]
                if not isinstance(digest, str) or set(value) != {"blob_sha256", "byte_size"}:
                    raise PersistenceError(PersistenceErrorCode.CORRUPT_STORE)
                payload = blobs.get(digest)
                if (
                    payload is None
                    or sha256(payload).hexdigest() != digest
                    or len(payload) != value["byte_size"]
                ):
                    raise PersistenceError(PersistenceErrorCode.CORRUPT_STORE)
                return payload
            return {key: decode(child, blobs) for key, child in value.items()}
        case list():
            return [decode(child, blobs) for child in value]
        case str() | int() | float() | None:
            return value
        case _:
            assert_never(value)


def canonical(value: JsonValue) -> str:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    )


def admitted[T: BaseModel](value: T) -> T:
    blobs: dict[str, bytes] = {}
    encoded = encode(value, blobs)
    rebuilt = type(value).model_validate(decode(encoded, blobs), strict=False)
    if canonical(encode(rebuilt, {})) != canonical(encoded):
        raise PersistenceError(PersistenceErrorCode.INVALID_INPUT)
    return rebuilt
