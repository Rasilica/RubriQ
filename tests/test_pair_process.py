import os
import selectors
import signal
import subprocess
import sys
from contextlib import suppress
from pathlib import Path
from time import monotonic

import pytest
from conversion_helpers import fake_renderer

from submission import conversion_process
from submission.conversion_contracts import ConversionConfig
from submission.conversion_process import run_process
from submission.input_contracts import DocumentInput
from submission.models import DocumentRole
from submission.pair_contracts import PairError, PairRuntime
from submission.pair_process import PairJob, bounded_file, run_preparation
from submission.pair_worker import WorkerCancelled, execute, main, terminate


def test_hard_timeout_cleans_job_and_allows_retry(
    text_pdf: bytes,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    guide = DocumentInput("guide.pdf", text_pdf, DocumentRole.GUIDE)
    report = DocumentInput("report.pdf", text_pdf, DocumentRole.REPORT)
    paths: list[Path] = []

    def stalled(
        arguments: tuple[str, ...], directory: Path, deadline: float, grace: float
    ) -> bytes:
        paths.append(Path(arguments[-1]))
        return run_process(
            (arguments[0], "-c", "import time; time.sleep(30)"), directory, deadline, grace
        )

    with monkeypatch.context() as patch:
        patch.setattr("submission.pair_process.run_process", stalled)
        with pytest.raises(PairError, match="preparation_timeout"):
            _ = run_preparation(guide, report, PairRuntime(), timeout_seconds=0.1)
    assert paths
    assert all(not path.exists() for path in paths)
    first, second = run_preparation(guide, report, PairRuntime())
    assert first.pdf == second.pdf == text_pdf


def test_worker_output_and_signal(
    tmp_path: Path, text_pdf: bytes, monkeypatch: pytest.MonkeyPatch
) -> None:
    _ = (tmp_path / "guide.input").write_bytes(text_pdf)
    _ = (tmp_path / "report.input").write_bytes(text_pdf)
    job = PairJob(
        guide_filename="g.pdf",
        report_filename="r.pdf",
        runtime=PairRuntime(),
        deadline=monotonic() + 30,
    )
    _ = (tmp_path / "job.json").write_text(job.model_dump_json())
    execute(tmp_path)
    assert (tmp_path / "guide.pdf").read_bytes() == text_pdf
    assert (tmp_path / "result.json").stat().st_size > 0
    with pytest.raises(WorkerCancelled):
        terminate(15, None)
    with pytest.raises(PairError):
        _ = bounded_file(tmp_path / "guide.pdf", 1)
    monkeypatch.setattr(sys, "argv", ["worker", str(tmp_path)])
    previous = signal.getsignal(signal.SIGTERM)
    try:
        main()
    finally:
        _ = signal.signal(signal.SIGTERM, previous)


def test_worker_rejects_large_result_and_missing_file(
    tmp_path: Path,
    text_pdf: bytes,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _ = (tmp_path / "guide.input").write_bytes(text_pdf)
    _ = (tmp_path / "report.input").write_bytes(b"invalid")
    job = PairJob(
        guide_filename="g.pdf",
        report_filename="r.pdf",
        runtime=PairRuntime(),
        deadline=monotonic() + 30,
    )
    _ = (tmp_path / "job.json").write_text(job.model_dump_json())
    execute(tmp_path)
    assert not (tmp_path / "report.pdf").exists()
    monkeypatch.setattr("submission.pair_worker.MAX_RESULT_BYTES", 1)
    with pytest.raises(WorkerCancelled):
        execute(tmp_path)


def test_parent_rejects_missing_result_and_worker_exit(
    text_pdf: bytes,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = DocumentInput("g.pdf", text_pdf, DocumentRole.GUIDE)

    def no_output(
        _arguments: tuple[str, ...], _directory: Path, _deadline: float, _grace: float
    ) -> bytes:
        return b""

    monkeypatch.setattr("submission.pair_process.run_process", no_output)
    with pytest.raises(PairError, match="pair_failed"):
        _ = run_preparation(source, source, PairRuntime())


@pytest.mark.parametrize("grace", [0.2, 10.0])
def test_hard_deadline_terminates_native_converter_and_retry(
    tmp_path: Path,
    text_pdf: bytes,
    monkeypatch: pytest.MonkeyPatch,
    grace: float,
) -> None:
    binary = tmp_path / "renderer"
    pid_file = tmp_path / "native.pid"
    ready_pipe = tmp_path / "native.ready"
    os.mkfifo(ready_pipe)
    _ = binary.write_text(
        "\n".join(
            (
                f"#!{sys.executable}",
                "import os,pathlib,signal,sys,time",
                "if '--version' in sys.argv:",
                "    print('LibreOffice 26.2.1.2 8399f6259d8c87f40e7255cdb3c9b958f5e08948')",
                "    sys.exit(0)",
                "signal.signal(signal.SIGTERM, signal.SIG_IGN)",
                f"pathlib.Path({str(pid_file)!r}).write_text(str(os.getpid()))",
                f"pathlib.Path({str(ready_pipe)!r}).write_bytes(b'ready')",
                "time.sleep(30)",
                "",
            )
        )
    )
    binary.chmod(0o700)
    runtime = PairRuntime(
        docx=ConversionConfig(
            soffice=binary, work_root=tmp_path / "jobs", terminate_grace_seconds=grace
        )
    )
    guide = DocumentInput("guide.pdf", text_pdf, DocumentRole.GUIDE)
    report = DocumentInput(
        "report.docx", Path("samples/formats/boundary.docx").read_bytes(), DocumentRole.REPORT
    )
    original_capture = conversion_process.capture_process
    with (
        os.fdopen(os.open(ready_pipe, os.O_RDONLY | os.O_NONBLOCK), "rb", buffering=0) as ready,
        selectors.DefaultSelector() as selector,
    ):
        selector.register(ready, selectors.EVENT_READ)

        def expire_after_ready(process: subprocess.Popen[bytes], _deadline: float) -> bytes:
            assert selector.select(10), "native converter did not signal readiness"
            assert ready.read() == b"ready"
            return original_capture(process, monotonic() - 1)

        try:
            with monkeypatch.context() as patch:
                patch.setattr(conversion_process, "capture_process", expire_after_ready)
                first, second = run_preparation(guide, report, runtime, timeout_seconds=30)
            assert pid_file.exists()
            with pytest.raises(ProcessLookupError):
                os.kill(int(pid_file.read_text()), 0)
        finally:
            if pid_file.exists():
                with suppress(ProcessLookupError):
                    os.kill(int(pid_file.read_text()), signal.SIGKILL)
    assert first.pdf == text_pdf
    assert second.view.document is not None
    assert second.view.document.blocks
    assert second.view.error_code in ("preparation_timeout", "conversion_timeout")
    assert second.pdf is None
    assert pid_file.exists()
    with pytest.raises(ProcessLookupError):
        os.kill(int(pid_file.read_text()), 0)
    assert not tuple((tmp_path / "jobs").iterdir())
    _ = fake_renderer(tmp_path, text_pdf)
    first, second = run_preparation(guide, report, runtime)
    assert first.pdf == second.pdf == text_pdf
