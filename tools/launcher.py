"""Interactive start used by the Windows batch file: choose a mode, serve, open the browser."""

# This is a standalone start script that talks to the user on the console.
# ruff: noqa: T201, INP001

import os
import socket
import sys
import threading
import time
import webbrowser
from collections.abc import Callable
from pathlib import Path
from typing import Final

HOST: Final = "127.0.0.1"
PORT: Final = 8293
URL: Final = f"http://{HOST}:{PORT}/prepare"
MODES: Final = {"1": "demo", "2": "real"}
SOURCE: Final = Path(__file__).resolve().parents[1] / "src"
MENU: Final = """
==============================================
 RubriQ 실행 모드를 고르세요
----------------------------------------------
 1. 체험 모드  샘플 문서만, 저장된 예시 결과
              (API 키와 비용 없음, 실제 AI 아님)
 2. 실전 모드  내 문서, 실제 AI
              (API 키 필요, 비용 발생 가능)
==============================================
"""


def choose_mode(ask: Callable[[str], str]) -> str:
    print(MENU)
    while True:
        mode = MODES.get(ask("번호(1 또는 2)를 입력하고 Enter: ").strip())
        if mode is not None:
            return mode
        print("1 또는 2를 입력해 주세요.")


def port_is_free(port: int) -> bool:
    with socket.socket() as probe:
        probe.settimeout(1)
        return probe.connect_ex((HOST, port)) != 0


def announce(is_started: Callable[[], bool]) -> None:
    while not is_started():
        time.sleep(0.2)
    print(f"\n접속 주소: {URL}")
    print("브라우저가 자동으로 열리지 않으면 위 주소를 주소창에 입력하세요.")
    print("사용하는 동안 이 창을 닫지 마세요. 종료하려면 이 창을 닫으면 됩니다.\n")
    _ = webbrowser.open(URL)


def main() -> int:
    if not port_is_free(PORT):
        print(f"이미 실행 중이거나 {PORT}번 포트를 다른 프로그램이 사용 중입니다.")
        print("열려 있는 RubriQ 실행 창을 닫은 뒤 다시 실행해 주세요.")
        return 1
    os.environ["RUBRIQ_MODE"] = choose_mode(input)
    sys.path.insert(0, str(SOURCE))
    import uvicorn  # noqa: PLC0415 -- the menu should appear before the slow imports.

    from submission.main import create_app  # noqa: PLC0415

    server = uvicorn.Server(uvicorn.Config(create_app(), host=HOST, port=PORT))
    threading.Thread(target=announce, args=(lambda: server.started,), daemon=True).start()
    server.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
