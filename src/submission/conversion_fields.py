"""Neutralize Word INCLUDEPICTURE web-image fields in the conversion working copy.

Word pastes web images as `INCLUDEPICTURE "https://..."` fields that carry the picture as a cached
result. Removing only the field code keeps what Word showed and leaves nothing for the renderer to
fetch. Anything that does not fit this narrow shape is left untouched, so the active-content
check still rejects it. The uploaded bytes are never modified; only the copy sent to LibreOffice.
"""

import re
from html import unescape
from io import BytesIO
from typing import Final
from zipfile import BadZipFile, ZipFile

# shortcut: assumes the conventional `w:` prefix; other prefixes simply stay rejected.
_MARKER: Final = (
    r'<w:fldChar\s+w:fldCharType="(?P<kind>begin|separate|end)"\s*/>'
    r"|<w:instrText(?:\s[^>]*)?>(?P<text>[^<]*)</w:instrText>"
)
_MARKER_RUN: Final = re.compile(
    rf"<w:r(?:\s[^>]*)?>(?:<w:rPr>(?:(?!</w:rPr>).)*</w:rPr>)?(?:{_MARKER})</w:r>", re.DOTALL
)
_SIMPLE: Final = re.compile(
    r'<w:fldSimple\s+w:instr="(?P<code>[^"]*)"\s*>(?P<body>.*?)</w:fldSimple>', re.DOTALL
)
_MARKER_WORDS: Final = re.compile(r"<w:(?:fldChar|instrText)\b")
_CACHED_RESULT: Final = re.compile(r"<w:(?:drawing|pict|t)[\s>/]")
_WEB_PICTURE: Final = re.compile(
    r'INCLUDEPICTURE\s+"?https?://[^\s"\\]+"?(?:\s+\\\*\s+MERGEFORMAT(?:INET)?)?',
    re.IGNORECASE | re.ASCII,
)


def _is_web_picture(instruction: str) -> bool:
    return _WEB_PICTURE.fullmatch(unescape(instruction).strip()) is not None


def _has_cached_result(result: str) -> bool:
    return _CACHED_RESULT.search(result) is not None and _MARKER_WORDS.search(result) is None


def _complex_spans(xml: str) -> list[tuple[int, int]] | None:
    """Spans of begin/code/separate/end runs of each web picture field; None if not analyzable."""
    runs = list(_MARKER_RUN.finditer(xml))
    if len(runs) != len(_MARKER_WORDS.findall(xml)):
        return None
    spans: list[tuple[int, int]] = []
    pending: list[tuple[int, int]] = []
    code, separated, result_start, is_open = "", False, 0, False
    for run in runs:
        kind = run.group("kind")
        if kind == "begin" and not is_open:
            pending, code, separated, is_open = [run.span()], "", False, True
        elif not is_open or (kind == "begin") or (separated and kind != "end"):
            return None
        elif kind is None:
            pending, code = [*pending, run.span()], code + run.group("text")
        elif kind == "separate":
            pending, separated, result_start = [*pending, run.span()], True, run.end()
        else:
            if (
                separated
                and _is_web_picture(code)
                and _has_cached_result(xml[result_start : run.start()])
            ):
                spans = [*spans, *pending, run.span()]
            is_open = False
    return None if is_open else spans


def _neutralize_part(xml: str) -> str:
    spans = _complex_spans(xml)
    if spans is None:
        return xml
    for start, end in sorted(spans, reverse=True):
        xml = xml[:start] + xml[end:]

    def unwrap(match: re.Match[str]) -> str:
        body = match.group("body")
        if (
            _is_web_picture(match.group("code"))
            and _has_cached_result(body)
            and "<w:fldSimple" not in body
        ):
            return body
        return match.group(0)

    return _SIMPLE.sub(unwrap, xml)


def neutralize_picture_fields(content: bytes) -> bytes:
    """Return a package copy without web INCLUDEPICTURE field codes, or `content` itself if none."""
    try:
        with ZipFile(BytesIO(content)) as package:
            changed: dict[str, bytes] = {}
            for member in package.infolist():
                name = member.filename
                if not (name.startswith("word/") and name.endswith(".xml")):
                    continue
                raw = package.read(member)
                if b"INCLUDEPICTURE" not in raw.upper():
                    continue
                try:
                    updated = _neutralize_part(raw.decode("utf-8")).encode("utf-8")
                except UnicodeDecodeError:
                    continue
                if updated != raw:
                    changed[name] = updated
            if not changed:
                return content
            output = BytesIO()
            with ZipFile(output, "w") as rewritten:
                for member in package.infolist():
                    rewritten.writestr(member, changed.get(member.filename, package.read(member)))
            return output.getvalue()
    except BadZipFile:
        return content
