from pathlib import Path
from typing import Annotated, ClassVar, Literal

from pydantic import ConfigDict, Field

from submission.conversion_contracts import ConversionConfig
from submission.document_contracts import Sha256
from submission.models import FrozenModel


class ProfileFile(FrozenModel):
    relative_path: str
    byte_size: Annotated[int, Field(ge=0)]
    sha256: Sha256


class RuntimeFile(FrozenModel):
    path: Path
    sha256: Sha256


class HancomProvision(FrozenModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="forbid", strict=True)

    template: Path
    files: tuple[ProfileFile, ...]
    template_sha256: Sha256
    soffice: RuntimeFile
    java_home: Path
    java_files: tuple[RuntimeFile, ...]
    extension_version: Literal["0.7.14"]
    extension_sha256: Sha256


class HancomConversionConfig(ConversionConfig):
    provision: HancomProvision
