import os
import stat
import time
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Final

from pydantic import ValidationError

from submission.conversion_contracts import ConversionError, ConversionErrorCode
from submission.conversion_process import run_process
from submission.document_contracts import CommonDocument
from submission.formats import inspect_document
from submission.hancom_profile import JAVA_FILES, runtime_file
from submission.hwp_reader_contracts import HwpTree
from submission.hwp_reader_projection import project_tree
from submission.hwp_reader_validation import validate_tree
from submission.hwp_reading import HWPLIB_SHA256
from submission.hwp_reading_contracts import HwpReadConfig
from submission.input_contracts import DocumentInput

MAX_RESULT_BYTES: Final = 4 * 1024 * 1024


def read_result(path: Path) -> HwpTree:
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError as error:
        raise ConversionError(ConversionErrorCode.OUTPUT_MISSING) from error
    except OSError as error:
        raise ConversionError(ConversionErrorCode.OUTPUT_INVALID) from error
    with os.fdopen(descriptor, "rb") as stream:
        metadata = os.fstat(stream.fileno())
        if not stat.S_ISREG(metadata.st_mode):
            raise ConversionError(ConversionErrorCode.OUTPUT_INVALID)
        raw = stream.read(MAX_RESULT_BYTES + 1)
    if len(raw) > MAX_RESULT_BYTES:
        raise ConversionError(ConversionErrorCode.OUTPUT_LIMIT)
    try:
        return HwpTree.model_validate_json(raw)
    except ValidationError as error:
        raise ConversionError(ConversionErrorCode.OUTPUT_INVALID) from error


def verify_provision(config: HwpReadConfig, deadline: float) -> None:
    provision = config.provision
    if provision.jar.sha256 != HWPLIB_SHA256 or tuple(
        item.path for item in provision.java_files
    ) != tuple(provision.java_home / name for name in JAVA_FILES):
        raise ConversionError(ConversionErrorCode.INVALID_CONFIG)
    if any(
        runtime_file(item.path, deadline) != item
        for item in (*provision.java_files, provision.jar, provision.worker)
    ):
        raise ConversionError(ConversionErrorCode.INVALID_CONFIG)


def read_hwp(source: DocumentInput, config: HwpReadConfig) -> CommonDocument:
    deadline = time.monotonic() + config.timeout_seconds
    identity = inspect_document(source, config.input_limits).source
    if identity.detected_format != "hwp":
        raise ConversionError(ConversionErrorCode.UNSUPPORTED_FORMAT)
    if os.name != "posix":
        raise ConversionError(ConversionErrorCode.UNSUPPORTED_PLATFORM)
    try:
        verify_provision(config, deadline)
        config.work_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        with TemporaryDirectory(prefix="hwp-nested-", dir=config.work_root) as job:
            directory = Path(job).resolve()
            input_path = directory / "source.hwp"
            output_path = directory / "result.json"
            _ = input_path.write_bytes(source.content)
            provision = config.provision
            status = run_process(
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
                    str(output_path),
                ),
                directory,
                deadline,
                2.0,
            )
            if status.strip() == b"output_limit":
                raise ConversionError(ConversionErrorCode.OUTPUT_LIMIT)
            if status.strip() != b"ok":
                raise ConversionError(ConversionErrorCode.OUTPUT_INVALID)
            tree = read_result(output_path)
            document = validate_tree(tree, project_tree(tree, identity))
            if time.monotonic() >= deadline:
                raise ConversionError(ConversionErrorCode.TIMEOUT)
            return document
    except OSError as error:
        raise ConversionError(ConversionErrorCode.IO_ERROR) from error
