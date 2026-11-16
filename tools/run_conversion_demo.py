# /// script
# requires-python = ">=3.13"
# dependencies = []
# ///
# ─── How to run ───
# From API: PYTHONPATH=src .venv/bin/python -m tools.run_conversion_demo INPUT OUTPUT_DIR
# Optional arguments: SOFFICE --timeout SECONDS. OUTPUT_DIR must be new.
import os
import shutil
import sys
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Final, Literal, override

from pydantic import ValidationError

from submission.conversion_contracts import ConversionConfig, ConversionError
from submission.document_contracts import DocumentArtifact, DocumentSource
from submission.docx_conversion import convert_docx
from submission.evidence_contracts import EvidenceModel
from submission.input_contracts import DocumentInput, InputValidationError
from submission.models import DocumentRole

USAGE: Final = (
    "PYTHONPATH=src .venv/bin/python -m tools.run_conversion_demo "
    "INPUT OUTPUT_DIR [SOFFICE] [--timeout SECONDS]"
)
MIN_TIMEOUT_ARGUMENTS: Final = 4
EXECUTABLE_ARGUMENTS: Final = 3


class CliErrorCode(StrEnum):
    USAGE = "usage"
    INVALID_CONFIG = "invalid_config"
    INPUT_IO = "input_io_error"
    OUTPUT_IO = "output_io_error"
    OUTPUT_EXISTS = "output_exists"


@dataclass(frozen=True, slots=True)
class Arguments:
    source: Path
    output: Path
    soffice: Path
    timeout: float


class ConversionReceipt(EvidenceModel):
    source: DocumentSource
    artifact: DocumentArtifact
    preview_page_count: int
    pdf_byte_size: int
    warnings: tuple[str, ...]
    original_layout_verified: Literal[False] = False


class FailureReceipt(EvidenceModel):
    error: str


@dataclass(frozen=True, slots=True)
class CliError(Exception):
    code: CliErrorCode

    @override
    def __str__(self) -> str:
        return self.code.value


def parse_arguments(arguments: tuple[str, ...]) -> Arguments:
    timeout = 60.0
    positional = arguments
    if "--timeout" in arguments:
        if len(arguments) < MIN_TIMEOUT_ARGUMENTS or arguments[-2] != "--timeout":
            raise CliError(CliErrorCode.USAGE)
        positional = arguments[:-2]
        try:
            timeout = float(arguments[-1])
        except ValueError:
            raise CliError(CliErrorCode.INVALID_CONFIG) from None
    if len(positional) not in {2, 3}:
        raise CliError(CliErrorCode.USAGE)
    executable = (
        positional[2] if len(positional) == EXECUTABLE_ARGUMENTS else shutil.which("soffice")
    )
    return Arguments(
        source=Path(positional[0]),
        output=Path(positional[1]),
        soffice=Path(executable or "soffice"),
        timeout=timeout,
    )


def write_private(path: Path, content: bytes) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        _ = stream.write(content)


def execute(arguments: Arguments) -> ConversionReceipt:
    if arguments.output.exists() or arguments.output.is_symlink():
        raise CliError(CliErrorCode.OUTPUT_EXISTS)
    try:
        with arguments.source.open("rb") as stream:
            content = stream.read(10 * 1024 * 1024 + 1)
    except OSError:
        raise CliError(CliErrorCode.INPUT_IO) from None
    source = DocumentInput(arguments.source.name, content, DocumentRole.REPORT)
    with TemporaryDirectory(prefix="submission-conversion-cli-") as work_root:
        config = ConversionConfig(
            soffice=arguments.soffice,
            work_root=Path(work_root),
            timeout_seconds=arguments.timeout,
        )
        result = convert_docx(source, config)
    receipt = ConversionReceipt(
        source=result.source,
        artifact=result.artifact,
        preview_page_count=result.preview_page_count,
        pdf_byte_size=len(result.pdf_bytes),
        warnings=result.warnings,
    )
    try:
        arguments.output.mkdir(mode=0o700)
    except FileExistsError:
        raise CliError(CliErrorCode.OUTPUT_EXISTS) from None
    except OSError:
        raise CliError(CliErrorCode.OUTPUT_IO) from None
    published = False
    try:
        write_private(arguments.output / "preview.pdf", result.pdf_bytes)
        write_private(arguments.output / "receipt.json", receipt.model_dump_json().encode())
        write_private(
            arguments.output / "font-manifest.json", result.font_manifest.model_dump_json().encode()
        )
    except OSError:
        raise CliError(CliErrorCode.OUTPUT_IO) from None
    else:
        published = True
    finally:
        if not published:
            shutil.rmtree(arguments.output)
    return receipt


def main() -> int:
    exit_code = 1
    try:
        receipt = execute(parse_arguments(tuple(sys.argv[1:])))
    except CliError as error:
        if error.code is CliErrorCode.USAGE:
            _ = sys.stderr.write(USAGE + "\n")
            exit_code = 2
        else:
            _ = sys.stderr.write(FailureReceipt(error=error.code.value).model_dump_json() + "\n")
    except ValidationError:
        _ = sys.stderr.write(FailureReceipt(error="invalid_config").model_dump_json() + "\n")
    except ConversionError as error:
        _ = sys.stderr.write(FailureReceipt(error=error.code.value).model_dump_json() + "\n")
    except InputValidationError as error:
        _ = sys.stderr.write(FailureReceipt(error=error.code.value).model_dump_json() + "\n")
    except OSError:
        _ = sys.stderr.write(FailureReceipt(error="conversion_io_error").model_dump_json() + "\n")
    except KeyboardInterrupt:
        _ = sys.stderr.write(
            FailureReceipt(error="conversion_interrupted").model_dump_json() + "\n"
        )
        exit_code = 130
    else:
        _ = sys.stdout.write(receipt.model_dump_json() + "\n")
        exit_code = 0
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
