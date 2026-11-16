from typing import Annotated, Literal

from pydantic import Field

from submission.models import FrozenModel

type HwpPath = Annotated[
    str,
    Field(pattern=r"^BodyText/Section[0-9]+(?:/(?:paragraph|control|row|cell|char)\[[0-9]+\])*$"),
]


class HwpNode(FrozenModel):
    path: HwpPath
    kind: Literal["paragraph", "table_cell", "footnote", "header", "footer"]
    text: str
    parent: HwpPath | None
    fragment: Annotated[int, Field(gt=0)] | None
    start: Annotated[int, Field(ge=0)]


class HwpLink(FrozenModel):
    kind: Literal["footnote", "header", "footer"]
    path: HwpPath
    owner: HwpPath
    fragment: Annotated[int, Field(gt=0)]
    offset: Annotated[int, Field(ge=0)]
    resolved: bool


class HwpTree(FrozenModel):
    parts: Annotated[tuple[HwpPath, ...], Field(min_length=1, max_length=1000)]
    nodes: Annotated[tuple[HwpNode, ...], Field(max_length=10000)]
    omitted: Annotated[tuple[HwpPath, ...], Field(max_length=20000)]
    references: Annotated[tuple[HwpLink, ...], Field(max_length=10000)]
