import shutil
import subprocess
from pathlib import Path

import pytest

MODULES = sorted(Path("src/submission/static").rglob("*.mjs"))
NODE = shutil.which("node")


@pytest.mark.skipif(NODE is None, reason="node is not installed")
@pytest.mark.parametrize("module", MODULES, ids=str)
def test_frontend_module_parses(module: Path) -> None:
    # A page whose module fails to parse falls back to a plain GET form submission.
    assert NODE is not None
    result = subprocess.run(  # noqa: S603 -- fixed node binary on repository files only.
        [NODE, "--check", str(module)], capture_output=True, text=True, check=False
    )

    assert result.returncode == 0, result.stderr
