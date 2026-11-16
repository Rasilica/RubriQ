from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field

from submission.document_contracts import DocumentSource
from submission.hancom_contracts import RuntimeFile
from submission.input_contracts import InputLimits
from submission.models import FrozenModel


class HwpControl(FrozenModel):
    path: str
    kind: Annotated[str, Field(min_length=1, max_length=128)]


class HwpParagraph(FrozenModel):
    path: str
    text: Annotated[str, Field(max_length=32768)]
    controls: Annotated[tuple[HwpControl, ...], Field(max_length=1000)]


class HwpSection(FrozenModel):
    path: str
    paragraphs: Annotated[tuple[HwpParagraph, ...], Field(max_length=1000)]


class HwpStructure(FrozenModel):
    sections: Annotated[tuple[HwpSection, ...], Field(min_length=1, max_length=1000)]


class HwpReaderProvision(FrozenModel):
    java_home: Path
    java_files: tuple[RuntimeFile, ...]
    jar: RuntimeFile
    worker: RuntimeFile
    library_version: Literal["1.1.11"] = "1.1.11"


class HwpReadConfig(FrozenModel):
    provision: HwpReaderProvision
    work_root: Path
    timeout_seconds: Annotated[float, Field(gt=0, le=120)] = 30.0
    input_limits: InputLimits = InputLimits()


class HwpReadResult(FrozenModel):
    source: DocumentSource
    structure: HwpStructure
    provision: HwpReaderProvision
    scope: Literal["top_level_structure_feasibility"] = "top_level_structure_feasibility"
    original_page_count: None = None
    original_layout_verified: Literal[False] = False
    nested_control_content_extracted: Literal[False] = False
