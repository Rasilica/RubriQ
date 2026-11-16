import os
import selectors
import signal
import subprocess
import time
from collections.abc import Generator
from contextlib import ExitStack, contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from submission.conversion_contracts import ConversionError, ConversionErrorCode

OUTPUT_LIMIT: Final = 65536


@dataclass(frozen=True, slots=True)
class ProcessOwnership:
    pending: ContextVar[BaseException | None]


_ownership: ContextVar[ProcessOwnership | None] = ContextVar("process_ownership", default=None)


def request_cancellation(error: BaseException) -> None:
    ownership = _ownership.get()
    if ownership is not None:
        if ownership.pending.get() is None:
            _ = ownership.pending.set(error)
    else:
        raise error


def check_cancellation() -> None:
    ownership = _ownership.get()
    if ownership is not None:
        error = ownership.pending.get()
        if error is not None:
            raise error


@contextmanager
def owned_process() -> Generator[None]:
    """Defer worker signals until polling or cleanup, without changing child masks."""
    ownership = _ownership.get() or ProcessOwnership(
        ContextVar("pending_cancellation", default=None)
    )
    token = _ownership.set(ownership)
    try:
        yield
    finally:
        _ownership.reset(token)
        error = ownership.pending.get()
        if error is not None:
            raise error


def stop_group(process: subprocess.Popen[bytes], grace: float) -> None:
    """Terminate descendants even when a shell wrapper has already exited."""
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        reap_process(process, grace)
        return
    except PermissionError as error:
        raise ConversionError(ConversionErrorCode.CLEANUP_FAILED) from error
    if group_stopped(process, grace):
        reap_process(process, grace)
        return
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        _ = process.poll()
    except PermissionError as error:
        raise ConversionError(ConversionErrorCode.CLEANUP_FAILED) from error
    reap_process(process, grace)
    if not group_stopped(process, grace):
        raise ConversionError(ConversionErrorCode.CLEANUP_FAILED)


def reap_process(process: subprocess.Popen[bytes], grace: float) -> None:
    try:
        _ = process.wait(timeout=grace)
    except subprocess.TimeoutExpired as error:
        raise ConversionError(ConversionErrorCode.CLEANUP_FAILED) from error


def group_stopped(process: subprocess.Popen[bytes], grace: float) -> bool:
    until = time.monotonic() + grace
    while time.monotonic() < until:
        _ = process.poll()
        try:
            os.killpg(process.pid, 0)
        except ProcessLookupError:
            return True
        except PermissionError:
            _ = process.poll()
        time.sleep(min(0.01, max(0, until - time.monotonic())))
    return False


def capture_process(process: subprocess.Popen[bytes], deadline: float) -> bytes:
    with selectors.DefaultSelector() as selector:
        if process.stdout is None or process.stderr is None:
            raise ConversionError(ConversionErrorCode.RENDERER_FAILED)
        _ = selector.register(process.stdout, selectors.EVENT_READ)
        _ = selector.register(process.stderr, selectors.EVENT_READ)
        output = bytearray()
        total = 0
        stdout = process.stdout.fileno()
        exited = False
        while selector.get_map():
            check_cancellation()
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ConversionError(ConversionErrorCode.TIMEOUT)
            # After exit, read only what is already buffered: descendants may keep pipes open.
            ready = selector.select(0 if exited else min(remaining, 0.05))
            if exited and not ready:
                break
            for key, _events in ready:
                chunk = os.read(key.fd, 4096)
                if not chunk:
                    _ = selector.unregister(key.fd)
                    continue
                total += len(chunk)
                if total > OUTPUT_LIMIT:
                    raise ConversionError(ConversionErrorCode.PROCESS_OUTPUT_LIMIT)
                if key.fd == stdout:
                    output.extend(chunk)
            exited = exited or process.poll() is not None
        wait_process(process, deadline)
        return bytes(output)


def wait_process(process: subprocess.Popen[bytes], deadline: float) -> None:
    while True:
        check_cancellation()
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise ConversionError(ConversionErrorCode.TIMEOUT)
        try:
            code = process.wait(timeout=min(remaining, 0.05))
        except subprocess.TimeoutExpired:
            continue
        if code != 0:
            raise ConversionError(ConversionErrorCode.RENDERER_FAILED)
        return


def run_process(
    arguments: tuple[str, ...], directory: Path, deadline: float, grace: float
) -> bytes:
    """Run one POSIX process group with bounded pipes and a shared job deadline."""
    if time.monotonic() >= deadline:
        raise ConversionError(ConversionErrorCode.TIMEOUT)
    with owned_process():
        try:
            process = subprocess.Popen(  # noqa: S603 -- argv is built internally, without a shell.
                arguments,
                cwd=directory,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                start_new_session=True,
            )
        except OSError as error:
            raise ConversionError(ConversionErrorCode.RENDERER_UNAVAILABLE) from error
        with ExitStack() as stack:
            if process.stdout is not None:
                _ = stack.enter_context(process.stdout)
            if process.stderr is not None:
                _ = stack.enter_context(process.stderr)
            _ = stack.callback(stop_group, process, grace)
            return capture_process(process, deadline)
