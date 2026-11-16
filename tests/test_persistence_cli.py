import os
import sys
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

import anyio

from tools.run_persistence_demo import DemoReceipt

PROJECT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True, slots=True)
class ProcessResult:
    returncode: int
    stdout: str
    stderr: str


async def process(database: Path, action: str) -> ProcessResult:
    with anyio.fail_after(30):
        result = await anyio.run_process(
            [sys.executable, "-m", "tools.run_persistence_demo", str(database), action],
            cwd=PROJECT,
            env=os.environ | {"PYTHONPATH": str(PROJECT / "src")},
            check=False,
        )
    return ProcessResult(result.returncode, result.stdout.decode(), result.stderr.decode())


def invoke(database: Path, action: str) -> ProcessResult:
    return anyio.run(process, database, action)


def test_cli_reopens_stored_bytes_and_settings_in_a_new_process(tmp_path: Path) -> None:
    database = tmp_path / "checks.sqlite3"
    saved = invoke(database, "normal")
    assert saved.returncode == 0, saved.stderr
    receipt = DemoReceipt.model_validate_json(saved.stdout)

    reopened = invoke(database, "inspect")

    assert reopened.returncode == 0, reopened.stderr
    restored = DemoReceipt.model_validate_json(reopened.stdout)
    assert restored.latest_success == receipt.latest_success
    assert restored.latest_success is not None
    originals = restored.latest_success.originals
    assert tuple(item.byte_sha256 for item in originals) == tuple(
        sha256((PROJECT / "samples/pdf" / name).read_bytes()).hexdigest()
        for name in ("guide.pdf", "normal.pdf")
    )
    assert restored.latest_success.criteria.version == 1
    assert restored.latest_success.settings.toolchain
    assert all(
        item.byte_sha256 == item.binding.artifact.artifact_sha256
        for item in restored.latest_success.artifacts
    )


def test_failed_retry_preserves_success_after_process_restart(tmp_path: Path) -> None:
    database = tmp_path / "checks.sqlite3"
    saved = invoke(database, "normal")
    receipt = DemoReceipt.model_validate_json(saved.stdout)
    failure = invoke(database, "retry-failure")
    assert failure.returncode == 1

    reopened = invoke(database, "inspect")

    assert reopened.returncode == 0, reopened.stderr
    restored = DemoReceipt.model_validate_json(reopened.stdout)
    assert restored.latest_success == receipt.latest_success
    assert tuple(run.status for run in restored.runs) == ("succeeded", "failed")
    assert restored.selected is not None
    assert restored.selected.failure_code is not None
    assert restored.selected.result is None
    assert restored.selected.predecessor_run_id == restored.runs[0].run_id
    assert "invalid-offline-response" not in reopened.stdout


def test_another_report_is_a_new_run_after_restart(tmp_path: Path) -> None:
    database = tmp_path / "checks.sqlite3"
    first = DemoReceipt.model_validate_json(invoke(database, "normal").stdout)
    _ = invoke(database, "missing")

    reopened = DemoReceipt.model_validate_json(invoke(database, "inspect").stdout)

    assert len(reopened.runs) == 2
    assert reopened.runs[0].run_id == first.runs[0].run_id
    assert reopened.latest_success is not None
    assert (
        reopened.latest_success.originals[1].byte_sha256
        == sha256((PROJECT / "samples/pdf/missing.pdf").read_bytes()).hexdigest()
    )
    assert reopened.latest_success.sequence == 2


def test_unknown_action_returns_usage_without_creating_a_store(tmp_path: Path) -> None:
    database = tmp_path / "checks.sqlite3"

    result = invoke(database, "unknown")

    assert result.returncode == 2
    assert not database.exists()


def test_storage_failure_reports_a_safe_code(tmp_path: Path) -> None:
    private_path = tmp_path / "private-path"
    private_path.mkdir()

    result = invoke(private_path, "normal")

    assert result.returncode == 1
    assert "storage_error" in result.stderr
    assert str(private_path) not in result.stdout + result.stderr
