# /// script
# requires-python = ">=3.13"
# dependencies = []
# ///
# ─── How to run ───
# From API: .venv/bin/python tools/build_vision_ocr.py [OUTPUT_PATH]
# Default OUTPUT_PATH is .runtime/ocr/vision-ocr. Pin the printed SHA-256 in the OCR runtime config.
import hashlib
import subprocess
import sys
from pathlib import Path
from typing import Final

SOURCE: Final = Path(__file__).with_name("VisionOcr.swift")
DEFAULT_OUTPUT: Final = Path(".runtime/ocr/vision-ocr")
BUILD_TIMEOUT_SECONDS: Final = 300


def build(output: Path) -> str:
    """Compile the helper and return its SHA-256."""
    output.parent.mkdir(parents=True, exist_ok=True)
    _ = subprocess.run(  # noqa: S603 -- fixed argv, no shell.
        ["swiftc", "-O", str(SOURCE), "-o", str(output)],  # noqa: S607
        check=True,
        timeout=BUILD_TIMEOUT_SECONDS,
    )
    return hashlib.sha256(output.read_bytes()).hexdigest()


def main(arguments: list[str]) -> int:
    if len(arguments) > 1:
        _ = sys.stderr.write("usage: build_vision_ocr.py [OUTPUT_PATH]\n")
        return 2
    output = Path(arguments[0]) if arguments else DEFAULT_OUTPUT
    try:
        digest = build(output)
    except (OSError, subprocess.SubprocessError):
        _ = sys.stderr.write("build_failed\n")
        return 1
    _ = sys.stdout.write(f"{output}\nsha256={digest}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
