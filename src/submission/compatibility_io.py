import os
import stat
from contextlib import ExitStack
from hashlib import sha256
from html import escape
from pathlib import Path
from typing import Final

from submission.compatibility_contracts import (
    CompatibilityError,
    CompatibilityErrorCode,
    CompatibilityReport,
    MaterialFile,
)

FILE_LIMIT: Final = 10 * 1024 * 1024


def read_bounded(path: Path, maximum: int = FILE_LIMIT) -> bytes:
    try:
        with ExitStack() as stack:
            absolute = path.absolute()
            parent = os.open(absolute.anchor, os.O_RDONLY | os.O_DIRECTORY)
            _ = stack.callback(os.close, parent)
            for component in absolute.parts[1:-1]:
                parent = os.open(
                    component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent
                )
                _ = stack.callback(os.close, parent)
            descriptor = os.open(
                absolute.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent
            )
            stream = stack.enter_context(os.fdopen(descriptor, "rb"))
            details = os.fstat(stream.fileno())
            if not stat.S_ISREG(details.st_mode) or details.st_size > maximum:
                raise CompatibilityError(CompatibilityErrorCode.LIMIT)
            content = stream.read(maximum + 1)
    except OSError:
        raise CompatibilityError(CompatibilityErrorCode.IO) from None
    if len(content) > maximum:
        raise CompatibilityError(CompatibilityErrorCode.LIMIT)
    return content


def read_material(material: MaterialFile) -> bytes:
    content = read_bounded(material.path)
    if sha256(content).hexdigest() != material.sha256:
        raise CompatibilityError(CompatibilityErrorCode.HASH)
    return content


def write_private(path: Path, content: bytes) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        _ = stream.write(content)


def write_report(directory: Path, report: CompatibilityReport) -> None:
    status_labels = {
        "material_missing": "자료 미확보",
        "review_pending": "검수 대기",
        "review_recorded": "검수 기록됨",
        "invalid": "자료 오류",
    }
    sections: list[str] = []
    for case in report.cases:
        provenance = "합성 회귀 자료" if case.provenance == "synthetic" else "작성 앱 자료"
        links: list[str] = []
        for name, label in (("reference", "작성 앱 기준 PDF"), ("preview", "서비스 PDF")):
            relative = f"{case.case_id}/{name}.pdf"
            if (directory / relative).is_file():
                links.append(
                    "".join(
                        (
                            f'<section><h3>{label}</h3><a href="{relative}">PDF 열기</a>',
                            f'<object data="{relative}" type="application/pdf" ',
                            'width="100%" height="700"><p>PDF 링크로 확인하세요.</p>',
                            "</object></section>",
                        )
                    )
                )
        sections.append(
            "".join(
                (
                    f"<article><h2>{escape(case.case_id)}</h2>",
                    f"<p>{status_labels[case.status]} / {provenance}</p>",
                    f'<div class="comparison">{"".join(links)}</div>',
                    "<details><summary>검증 기록</summary><pre>",
                    f"{escape(case.model_dump_json(indent=2))}</pre></details></article>",
                )
            )
        )
    html = "".join(
        (
            '<!doctype html><html lang="ko"><meta charset="utf-8">',
            '<meta name="viewport" content="width=device-width,initial-scale=1">',
            "<title>문서 호환성 검토</title><style>body{font:16px sans-serif;margin:2rem}",
            ".comparison{display:grid;grid-template-columns:1fr 1fr;gap:1rem}",
            "pre{white-space:pre-wrap;overflow-wrap:anywhere}",
            "@media(max-width:700px){.comparison{grid-template-columns:1fr}}</style>",
            "<h1>문서 호환성 검토</h1><p>자료 출처는 등록자의 선언입니다. ",
            "자동 문구 대응은 레이아웃 검수 또는 지원 등급 인증이 아닙니다. ",
            "합성 자료는 도구 회귀 시험에만 사용합니다.</p>",
            "".join(sections),
            "</html>",
        )
    )
    write_private(directory / "index.html", html.encode())
    write_private(directory / "report.json", report.model_dump_json(indent=2).encode())
