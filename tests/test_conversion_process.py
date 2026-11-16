import os
import signal
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from submission import conversion_process
from submission.conversion_contracts import ConversionError, ConversionErrorCode
from submission.conversion_process import run_process
from submission.pair_worker import WorkerCancelled, terminate


@pytest.mark.parametrize(
    ("program", "expected"),
    [
        ("import time; time.sleep(10)", ConversionErrorCode.TIMEOUT),
        ("import sys; sys.stdout.write('x' * 200000)", ConversionErrorCode.PROCESS_OUTPUT_LIMIT),
        ("import sys; sys.stderr.write('x' * 200000)", ConversionErrorCode.PROCESS_OUTPUT_LIMIT),
        ("raise SystemExit(7)", ConversionErrorCode.RENDERER_FAILED),
    ],
)
def test_process_failures_are_bounded(tmp_path: Path, program: str, expected) -> None:
    with pytest.raises(ConversionError) as caught:
        run_process((sys.executable, "-c", program), tmp_path, time.monotonic() + 0.3, 0.05)

    assert caught.value.code == expected


@pytest.mark.parametrize("parent_exits", [True, False])
def test_descendant_is_terminated_on_every_exit(tmp_path: Path, *, parent_exits: bool) -> None:
    marker = tmp_path / "child.pid"
    program = (
        "import os,signal,time,pathlib; "
        "pid=os.fork(); "
        f"pathlib.Path({str(marker)!r}).write_text(str(pid or os.getpid())); "
        "signal.signal(signal.SIGTERM, signal.SIG_IGN); "
        + ("os._exit(0) if pid else time.sleep(10)" if parent_exits else "time.sleep(10)")
    )

    if parent_exits:
        _ = run_process((sys.executable, "-c", program), tmp_path, time.monotonic() + 1, 0.05)
    else:
        with pytest.raises(ConversionError):
            run_process((sys.executable, "-c", program), tmp_path, time.monotonic() + 0.3, 0.05)

    child = int(marker.read_text())
    with pytest.raises(ProcessLookupError):
        os.kill(child, 0)


def test_interrupt_reaps_owned_process(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    process_ids: list[int] = []

    def interrupt(process: subprocess.Popen[bytes], deadline: float) -> bytes:
        assert deadline > time.monotonic()
        assert process.stdout is not None
        assert process.stdout.readline() == b"ready\n"
        process_ids.append(process.pid)
        raise KeyboardInterrupt

    monkeypatch.setattr(conversion_process, "capture_process", interrupt)
    program = "import signal; print('ready', flush=True); signal.pause()"

    with pytest.raises(KeyboardInterrupt):
        run_process((sys.executable, "-c", program), tmp_path, time.monotonic() + 5, 0.2)

    with pytest.raises(ProcessLookupError):
        os.kill(process_ids[0], 0)


def test_owned_timeout_preserves_unrelated_process(tmp_path: Path) -> None:
    control = subprocess.Popen(
        (sys.executable, "-c", "import signal; signal.pause()"),
        start_new_session=True,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        with pytest.raises(ConversionError) as caught:
            run_process(
                (sys.executable, "-c", "import time; time.sleep(10)"),
                tmp_path,
                time.monotonic() + 0.3,
                0.2,
            )

        assert caught.value.code == ConversionErrorCode.TIMEOUT
        assert control.poll() is None
    finally:
        control.terminate()
        _ = control.wait(timeout=5)


@pytest.mark.parametrize("phase", ["spawn", "cleanup", "escalation", "wait"])
def test_worker_cancellation_cannot_interrupt_process_ownership(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, phase: str
) -> None:
    processes: list[subprocess.Popen[bytes]] = []
    original_spawn = subprocess.Popen
    original_stop = conversion_process.stop_group
    original_group_stopped = conversion_process.group_stopped
    original_wait = subprocess.Popen.wait
    cancelled_wait = False

    def spawn(*args, **kwargs):
        process = original_spawn(*args, **kwargs)
        processes.append(process)
        assert process.stdout is not None
        assert process.stdout.readline() == b"ready\n"
        if phase == "spawn":
            os.kill(os.getpid(), signal.SIGTERM)
        return process

    def stop(process: subprocess.Popen[bytes], grace: float) -> None:
        if phase == "cleanup":
            os.kill(os.getpid(), signal.SIGTERM)
        original_stop(process, grace)

    def group_stopped(process: subprocess.Popen[bytes], grace: float) -> bool:
        if phase == "escalation":
            os.kill(os.getpid(), signal.SIGTERM)
        return original_group_stopped(process, grace)

    def wait(process: subprocess.Popen[bytes], timeout: float | None = None) -> int:
        nonlocal cancelled_wait
        if phase == "wait" and not cancelled_wait:
            cancelled_wait = True
            os.kill(os.getpid(), signal.SIGTERM)
        return original_wait(process, timeout)

    program = (
        "import os,signal,time; "
        "signal.signal(signal.SIGTERM, signal.SIG_IGN); "
        "print('ready', flush=True); "
        + ("os.close(1); os.close(2); " if phase == "wait" else "")
        + "time.sleep(30)"
    )
    previous = signal.signal(signal.SIGTERM, terminate)
    try:
        with monkeypatch.context() as patch:
            patch.setattr(conversion_process.subprocess, "Popen", spawn)
            patch.setattr(conversion_process, "stop_group", stop)
            patch.setattr(conversion_process, "group_stopped", group_stopped)
            patch.setattr(original_spawn, "wait", wait)
            started = time.monotonic()
            with pytest.raises(WorkerCancelled):
                run_process(
                    (sys.executable, "-c", program),
                    tmp_path,
                    started + (30 if phase in ("spawn", "wait") else 0.3),
                    0.2,
                )
        assert time.monotonic() - started < 3
        with pytest.raises(ProcessLookupError):
            os.kill(processes[0].pid, 0)
        assert processes[0].returncode is not None
        assert (
            run_process(
                (sys.executable, "-c", "print('retry')"), tmp_path, time.monotonic() + 5, 0.2
            )
            == b"retry\n"
        )
    finally:
        _ = signal.signal(signal.SIGTERM, previous)
        for process in processes:
            original_stop(process, 0.2)


def test_threaded_process_does_not_inherit_blocked_termination(tmp_path: Path) -> None:
    program = (
        "import signal; "
        "assert signal.SIGTERM not in signal.pthread_sigmask(signal.SIG_BLOCK, []); "
        "print('unblocked')"
    )
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = [
            pool.submit(
                run_process, (sys.executable, "-c", program), tmp_path, time.monotonic() + 5, 0.2
            )
            for _ in range(2)
        ]
        assert [future.result(timeout=5) for future in results] == [b"unblocked\n"] * 2


def test_output_written_before_exit_is_fully_captured(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    size = 50_000
    program = f"import sys; sys.stdout.write('x' * {size})"
    original = conversion_process.check_cancellation
    delayed = iter((True,))

    def exit_before_first_read() -> None:
        if next(delayed, False):
            time.sleep(0.5)  # The child exits with buffered output before any read.
        original()

    monkeypatch.setattr(conversion_process, "check_cancellation", exit_before_first_read)

    output = run_process((sys.executable, "-c", program), tmp_path, time.monotonic() + 5, 0.05)

    assert output == b"x" * size
