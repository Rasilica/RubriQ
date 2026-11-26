import socket
from pathlib import Path

import pytest

from tools import launcher

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(
    ("answers", "expected"),
    [(["1"], "demo"), (["2"], "real"), (["", "3", " 2 "], "real")],
)
def test_menu_repeats_until_a_listed_number(answers, expected):
    replies = iter(answers)

    assert launcher.choose_mode(lambda _prompt: next(replies)) == expected


def test_detects_a_port_that_is_already_taken():
    with socket.socket() as taken:
        taken.bind((launcher.HOST, 0))
        taken.listen()

        assert not launcher.port_is_free(taken.getsockname()[1])


def test_batch_file_is_ascii_with_windows_line_endings():
    content = (ROOT / "RubriQ실행.bat").read_bytes()

    assert content.isascii()
    assert content.count(b"\r\n") == content.count(b"\n")
    assert b"tools\\launcher.py" in content
    assert b"--frozen --no-dev" in content


def test_public_copy_includes_everything_the_professor_runs():
    listed = (ROOT / "tools/public-files.txt").read_text(encoding="utf-8").splitlines()

    for name in (
        "RubriQ실행.bat",
        "사용설명서.txt",
        "tools/launcher.py",
        "tools/run_submission_check_demo.py",
        "src/submission/demo_ai.py",
        "src/submission/file_flags.py",
        "src/submission/pdfium_page.py",
        "samples/requirements/guide-offline-response.json",
    ):
        assert name in listed
