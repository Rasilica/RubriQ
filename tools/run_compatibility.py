# /// script
# requires-python = ">=3.13"
# dependencies = []
# ///
# From API: PYTHONPATH=src .venv/bin/python -m tools.run_compatibility MANIFEST OUTPUT [RUNTIME]
import os
import sys
from pathlib import Path
from typing import Final

from pydantic import ValidationError

from submission.compatibility_contracts import (
    CompatibilityError,
    CompatibilityErrorCode,
    CompatibilityManifest,
)
from submission.compatibility_io import read_bounded
from submission.compatibility_review import record_reviews
from submission.compatibility_runner import run_manifest
from submission.pair_contracts import PairRuntime

RUNTIME_ARGUMENTS: Final = 3
REVIEW_ARGUMENTS: Final = 4


def load_manifest(path: str) -> CompatibilityManifest:
    manifest_path = Path(path).absolute()
    manifest = CompatibilityManifest.model_validate_json(read_bounded(manifest_path, 1024 * 1024))
    cases = tuple(
        case.model_copy(
            update={
                "source": case.source.model_copy(
                    update={"path": manifest_path.parent / case.source.path}
                )
                if case.source is not None
                else None,
                "reference": case.reference.model_copy(
                    update={"path": manifest_path.parent / case.reference.path}
                )
                if case.reference is not None
                else None,
            }
        )
        for case in manifest.cases
    )
    return manifest.model_copy(update={"cases": cases})


def execute(arguments: tuple[str, ...]) -> int:
    if arguments and arguments[0] == "--record-review":
        if len(arguments) != REVIEW_ARGUMENTS:
            raise CompatibilityError(CompatibilityErrorCode.USAGE)
        report = record_reviews(load_manifest(arguments[1]), Path(arguments[2]), Path(arguments[3]))
        _ = sys.stdout.write(report.model_dump_json() + "\n")
        return 0
    if len(arguments) not in {2, 3}:
        raise CompatibilityError(CompatibilityErrorCode.USAGE)
    manifest = load_manifest(arguments[0])
    runtime_path = (
        arguments[2]
        if len(arguments) == RUNTIME_ARGUMENTS
        else os.environ.get("DOCUMENT_PAIR_RUNTIME_FILE")
    )
    runtime = (
        PairRuntime.model_validate_json(read_bounded(Path(runtime_path), 1024 * 1024))
        if runtime_path
        else PairRuntime()
    )
    report = run_manifest(manifest, runtime, Path(arguments[1]))
    _ = sys.stdout.write(report.model_dump_json() + "\n")
    return int(any(case.status == "invalid" for case in report.cases))


def main() -> int:
    try:
        return execute(tuple(sys.argv[1:]))
    except CompatibilityError as error:
        _ = sys.stderr.write(error.code + "\n")
    except ValidationError:
        _ = sys.stderr.write("invalid_manifest_or_runtime\n")
    except OSError:
        _ = sys.stderr.write("output_io\n")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
