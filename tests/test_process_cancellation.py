import signal
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from contextvars import Context, copy_context
from pathlib import Path

import pytest
from conversion_helpers import fake_renderer

from submission import conversion_process, pair_prepare
from submission.conversion_contracts import ConversionConfig, ConversionError, ConversionErrorCode
from submission.conversion_process import check_cancellation, owned_process, request_cancellation
from submission.models import DocumentRole
from submission.pair_contracts import PairRuntime
from submission.pair_process import PairJob
from submission.pair_worker import WorkerCancelled, execute


def cancel_capture(_process: subprocess.Popen[bytes], _deadline: float) -> bytes:
    request_cancellation(WorkerCancelled())
    check_cancellation()
    raise AssertionError


def test_cancellation_survives_cleanup_failure_and_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original_stop = conversion_process.stop_group
    processes: list[subprocess.Popen[bytes]] = []

    def failed_stop(process: subprocess.Popen[bytes], grace: float) -> None:
        original_stop(process, grace)
        processes.append(process)
        raise ConversionError(ConversionErrorCode.CLEANUP_FAILED)

    with monkeypatch.context() as patch:
        patch.setattr(conversion_process, "capture_process", cancel_capture)
        patch.setattr(conversion_process, "stop_group", failed_stop)
        with pytest.raises(WorkerCancelled) as caught:
            conversion_process.run_process(
                (sys.executable, "-c", "import time; time.sleep(30)"),
                tmp_path,
                time.monotonic() + 5,
                0.2,
            )
    assert isinstance(caught.value.__context__, ConversionError)
    assert caught.value.__context__.code == ConversionErrorCode.CLEANUP_FAILED
    assert processes[0].returncode is not None
    assert (
        conversion_process.run_process(
            (sys.executable, "-c", "print('retry')"), tmp_path, time.monotonic() + 5, 0.2
        )
        == b"retry\n"
    )


def test_cancelled_preparation_does_not_start_next_role(
    tmp_path: Path, text_pdf: bytes, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = Path("samples/formats/boundary.docx").read_bytes()
    (tmp_path / "guide.input").write_bytes(source)
    (tmp_path / "report.input").write_bytes(text_pdf)
    runtime = PairRuntime(
        docx=ConversionConfig(
            soffice=fake_renderer(tmp_path, text_pdf), work_root=tmp_path / "jobs"
        )
    )
    (tmp_path / "job.json").write_text(
        PairJob(
            guide_filename="guide.docx",
            report_filename="report.pdf",
            runtime=runtime,
            deadline=time.monotonic() + 30,
        ).model_dump_json()
    )
    original_stop = conversion_process.stop_group
    original_read = pair_prepare.read_source
    roles: list[DocumentRole] = []

    def failed_stop(process: subprocess.Popen[bytes], grace: float) -> None:
        original_stop(process, grace)
        raise ConversionError(ConversionErrorCode.CLEANUP_FAILED)

    def read_source(source, runtime, deadline):
        roles.append(source.role)
        return original_read(source, runtime, deadline)

    monkeypatch.setattr(conversion_process, "capture_process", cancel_capture)
    monkeypatch.setattr(conversion_process, "stop_group", failed_stop)
    monkeypatch.setattr(pair_prepare, "read_source", read_source)
    with pytest.raises(WorkerCancelled):
        execute(tmp_path)
    assert roles == [DocumentRole.GUIDE]
    assert not (tmp_path / "report.json").exists()
    assert not (tmp_path / "result.json").exists()
    assert not tuple((tmp_path / "jobs").iterdir())


def test_nested_scope_cannot_consume_outer_cancellation() -> None:
    cancellation = WorkerCancelled()

    def nested_cancellation() -> None:
        with owned_process():
            request_cancellation(cancellation)
            with pytest.raises(WorkerCancelled), owned_process():
                check_cancellation()
            request_cancellation(WorkerCancelled())

    with pytest.raises(WorkerCancelled) as caught:
        nested_cancellation()
    assert caught.value is cancellation
    check_cancellation()


def test_cancellation_isolated_from_fresh_context_and_thread() -> None:
    def isolated_cancellation() -> None:
        with owned_process():
            request_cancellation(WorkerCancelled())
            Context().run(check_cancellation)
            with ThreadPoolExecutor(max_workers=1) as pool:
                pool.submit(check_cancellation).result(timeout=5)

    with pytest.raises(WorkerCancelled):
        isolated_cancellation()
    with owned_process():
        check_cancellation()


class TeardownSignal:
    """Track teardown events to inject a real signal at each reachable boundary."""

    def __init__(self, *, nested: bool, cleanup_fails: bool) -> None:
        self.nested = nested
        self.cleanup_fails = cleanup_fails
        self.leaving = False
        self.target_event: int | None = None
        self.event_count = 0
        self.delivered = False
        self.cancellation = WorkerCancelled()

    def handler(self, _signum, _frame):
        request_cancellation(self.cancellation)

    def trace(self, frame, event, _arg):
        if frame.f_code is owned_process.__wrapped__.__code__ and event == "line" and self.leaving:
            self.event_count += 1
            if self.event_count == self.target_event:
                self.delivered = True
                signal.raise_signal(signal.SIGUSR1)
        return self.trace

    def leave_scope(self) -> None:
        with owned_process():
            if self.nested:
                with owned_process():
                    self.leaving = True
            else:
                self.leaving = True
            if self.cleanup_fails:
                raise ConversionError(ConversionErrorCode.CLEANUP_FAILED)

    def scenario(self) -> None:
        self.leaving = False
        self.event_count = 0
        self.delivered = False
        previous_trace = sys.gettrace()
        sys.settrace(self.trace)
        try:
            if self.target_event is not None:
                with pytest.raises(WorkerCancelled) as caught:
                    self.leave_scope()
                assert caught.value is self.cancellation
            elif self.cleanup_fails:
                with pytest.raises(ConversionError):
                    self.leave_scope()
            else:
                self.leave_scope()
        finally:
            sys.settrace(previous_trace)
        check_cancellation()
        with owned_process():
            check_cancellation()


@pytest.mark.parametrize("nested", [False, True])
@pytest.mark.parametrize("cleanup_fails", [False, True])
def test_signal_at_every_teardown_boundary_is_delivered(
    *, nested: bool, cleanup_fails: bool
) -> None:
    injection = TeardownSignal(nested=nested, cleanup_fails=cleanup_fails)
    previous_handler = signal.signal(signal.SIGUSR1, injection.handler)
    try:
        Context().run(injection.scenario)
        assert injection.event_count > 0
        for event in range(1, injection.event_count + 1):
            injection.target_event = event
            Context().run(injection.scenario)
            assert injection.delivered
    finally:
        signal.signal(signal.SIGUSR1, previous_handler)


def test_copied_context_cancellation_does_not_change_parent_scope() -> None:
    cancellation = WorkerCancelled()
    with owned_process():
        child_context = copy_context()
        child_context.run(request_cancellation, cancellation)
        check_cancellation()
        with pytest.raises(WorkerCancelled) as caught:
            child_context.run(check_cancellation)
        assert caught.value is cancellation
    check_cancellation()
