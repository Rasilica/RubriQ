import os
import time
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Final

from pydantic import ValidationError

from submission.conversion_contracts import ConversionError, ConversionErrorCode
from submission.conversion_process import run_process
from submission.formats import inspect_document
from submission.hancom_profile import JAVA_FILES, runtime_file
from submission.hwp_reading_contracts import (
    HwpReadConfig,
    HwpReaderProvision,
    HwpReadResult,
    HwpStructure,
)
from submission.input_contracts import DocumentInput

HWPLIB_SHA256: Final = "fd464ff56eec7f58d463f7533da7501d4bb8261a225c20b7b19bed9e137f7e04"


def provision_hwp_reader(java_home: Path, jar: Path, worker: Path) -> HwpReaderProvision:
    deadline = time.monotonic() + 30
    try:
        library = runtime_file(jar, deadline)
        if library.sha256 != HWPLIB_SHA256:
            raise ConversionError(ConversionErrorCode.INVALID_CONFIG)
        return HwpReaderProvision(
            java_home=java_home.absolute(),
            java_files=tuple(runtime_file(java_home / name, deadline) for name in JAVA_FILES),
            jar=library,
            worker=runtime_file(worker, deadline),
        )
    except OSError as error:
        raise ConversionError(ConversionErrorCode.INVALID_CONFIG) from error


def decode_structure(raw: bytes) -> HwpStructure:
    try:
        result = HwpStructure.model_validate_json(raw)
    except ValidationError as error:
        raise ConversionError(ConversionErrorCode.RENDERER_FAILED) from error
    for section_index, section in enumerate(result.sections):
        section_path = f"BodyText/Section{section_index}"
        if section.path != section_path:
            raise ConversionError(ConversionErrorCode.RENDERER_FAILED)
        for paragraph_index, paragraph in enumerate(section.paragraphs):
            paragraph_path = f"{section_path}/paragraph[{paragraph_index}]"
            if paragraph.path != paragraph_path or any(
                control.path != f"{paragraph_path}/control[{index}]"
                for index, control in enumerate(paragraph.controls)
            ):
                raise ConversionError(ConversionErrorCode.RENDERER_FAILED)
    return result


def read_hwp_structure(source: DocumentInput, config: HwpReadConfig) -> HwpReadResult:
    """Inspect top-level hwplib objects in an isolated, bounded Java process."""
    deadline = time.monotonic() + config.timeout_seconds
    identity = inspect_document(source, config.input_limits).source
    if identity.detected_format != "hwp":
        raise ConversionError(ConversionErrorCode.UNSUPPORTED_FORMAT)
    if os.name != "posix":
        raise ConversionError(ConversionErrorCode.UNSUPPORTED_PLATFORM)
    provision = config.provision
    try:
        if provision.jar.sha256 != HWPLIB_SHA256 or tuple(
            item.path for item in provision.java_files
        ) != tuple(provision.java_home / name for name in JAVA_FILES):
            raise ConversionError(ConversionErrorCode.INVALID_CONFIG)
        if any(
            runtime_file(item.path, deadline) != item
            for item in (*provision.java_files, provision.jar, provision.worker)
        ):
            raise ConversionError(ConversionErrorCode.INVALID_CONFIG)
        config.work_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        with TemporaryDirectory(prefix="hwp-read-", dir=config.work_root) as job:
            directory = Path(job).resolve()
            input_path = directory / "source.hwp"
            _ = input_path.write_bytes(source.content)
            raw = run_process(
                (
                    "/usr/bin/env",
                    "-i",
                    "PATH=/usr/bin:/bin",
                    "LANG=en_US.UTF-8",
                    str(provision.java_home / "bin/java"),
                    "-Xmx128m",
                    f"-Duser.home={directory}",
                    f"-Djava.io.tmpdir={directory}",
                    "--class-path",
                    str(provision.jar.path),
                    str(provision.worker.path),
                    str(input_path),
                ),
                directory,
                deadline,
                2.0,
            )
            return HwpReadResult(
                source=identity, structure=decode_structure(raw), provision=provision
            )
    except OSError as error:
        raise ConversionError(ConversionErrorCode.IO_ERROR) from error
