import re
from hashlib import sha256
from pathlib import Path
from typing import TYPE_CHECKING, Final, cast

if TYPE_CHECKING:
    from collections.abc import Callable

from submission.expression_contracts import ExpressionFinding, ExpressionMetric, ExpressionResult
from submission.pair_contracts import EvidenceSelection, PairError, PairErrorCode, PreparedRole

VENDOR_FILE: Final = Path(__file__).resolve().parents[2] / "vendor/im-not-ai/local_metrics.py"
VENDOR_SHA: Final = "c3c8194df6ffdbf9a40d82cab85cc32b9354dcdda256d003e91620fdc1606b1c"
MAX_TEXT: Final = 20_000
MAX_FINDINGS: Final = 100
PIVOT_THRESHOLD: Final = 4
PIVOTS: Final = ("결론적으로", "따라서", "이를 통해", "그러므로", "요약하면", "정리하자면")
# Straight quotes double as apostrophes and inch marks, so only closed pairs are protected.
PROTECTED_PATTERNS: Final = (
    r'```[\s\S]*?(?:```|$)|`[^`]*(?:`|$)|"[^"\n]*"',
    r"'[^'\n]*'|“[^”]*(?:”|$)|\u2018[^\u2019]*(?:\u2019|$)",
    r"「[^」]*(?:」|$)|『[^』]*(?:』|$)",
)
PROTECTED: Final = re.compile("|".join(PROTECTED_PATTERNS))
WARNINGS: Final = (
    (
        "선택 구간의 일부 표현 규칙만 로컬에서 점검했습니다. "
        "AI 작성 여부나 문장의 정확성을 판정하지 않습니다."
    ),
    (
        "인용부호와 코드로 둘러싸인 구간은 제외했습니다. "
        "원문의 사실·수치·인용·요구사항은 변경하지 않았습니다."
    ),
    (
        "횟수는 원본 도구의 표면형 집계이며 겹치는 표현이 중복 집계될 수 있습니다. "
        "문맥을 보고 검토하세요."
    ),
)


def load_metrics() -> dict[str, object]:
    try:
        content = VENDOR_FILE.read_bytes()
        if sha256(content).hexdigest() != VENDOR_SHA:
            raise PairError(PairErrorCode.UNAVAILABLE)
        namespace: dict[str, object] = {}
        # Execute only the exact hash-verified bytes, avoiding a second file read.
        exec(compile(content, "im-not-ai-local", "exec"), namespace)  # noqa: S102
    except (OSError, SyntaxError, ImportError, ValueError):
        raise PairError(PairErrorCode.UNAVAILABLE) from None
    else:
        return namespace


def masked_selection(text: str, selection: EvidenceSelection) -> str:
    return PROTECTED.sub(lambda match: "\0" * len(match.group()), text)[
        selection.start : selection.end
    ]


def literal_pattern(tokens: tuple[str, ...]) -> re.Pattern[str]:
    return re.compile("|".join(re.escape(token) for token in sorted(tokens, key=len, reverse=True)))


def find_expressions(
    module: dict[str, object], text: str, offset: int
) -> tuple[ExpressionFinding, ...]:
    double = cast("tuple[str, ...]", module["_DOUBLE_PASSIVE_TOKENS"])
    have = cast("tuple[str, ...]", module["_HAVE_MAKE_LITERAL_TOKENS"])
    rules = (
        (
            "A-8",
            "이중 피동 표현",
            literal_pattern(double),
            "피동 표현이 겹치는지 확인하세요.",
            "문맥과 주장의 강도를 유지하면서 한 번의 피동으로 표현할 수 있는지 검토하세요.",
        ),
        (
            "A-19",
            "조사가 겹친 표현",
            cast("re.Pattern[str]", module["_DOUBLE_PARTICLE_RE"]),
            "조사가 이어진 위치입니다. 보고서에서는 필요한 표현일 수 있습니다.",
            "의미를 유지하는 더 짧은 조사나 절로 풀 수 있는지 검토하세요.",
        ),
        (
            "A-7",
            "가지다·만들다 표현",
            literal_pattern(have),
            "직역처럼 길어진 표현인지, 실제 소유·행위를 뜻하는지 문맥을 확인하세요.",
            None,
        ),
        (
            "A-9",
            "행위자와 피동 표현",
            cast("re.Pattern[str]", module["_BY_PASSIVE_RE"]),
            "행위자와 피동이 함께 나온 구간입니다. 보고서에서 적절한 경우에는 유지하세요.",
            None,
        ),
    )
    findings = tuple(
        ExpressionFinding(
            pattern_id=key,
            label=label,
            start=offset + m.start(),
            end=offset + m.end(),
            original=m.group(),
            explanation=explanation,
            suggestion=suggestion,
        )
        for key, label, pattern, explanation, suggestion in rules
        for m in pattern.finditer(text)
        if "\0" not in m.group()
    )
    pivots = tuple(re.finditer(r"(?<!\w)(?:" + "|".join(PIVOTS) + r")(?!\w)", text))
    conclusions = tuple(
        ExpressionFinding(
            pattern_id="D-1",
            label="결론 연결 표현 반복",
            start=offset + m.start(),
            end=offset + m.end(),
            original=m.group(),
            explanation="선택 구간에서 결론 연결 표현이 4회 이상 나옵니다.",
            suggestion="논리 연결에 필요한 표현은 유지하고 반복만 줄일지 검토하세요.",
        )
        for m in pivots
        if len(pivots) >= PIVOT_THRESHOLD
    )
    return tuple(
        sorted((*findings, *conclusions), key=lambda finding: (finding.start, finding.end))
    )


def compute_metrics(module: dict[str, object], text: str) -> tuple[ExpressionMetric, ...]:
    counters = (
        ("double_passive_count", "이중 피동 표면형"),
        ("double_particle_count", "겹친 조사 표면형"),
        ("by_passive_count", "행위자·피동 결합"),
        ("have_make_literal_count", "가지다·만들다 표면형"),
        ("conclusion_pivot_count", "결론 연결어 원본 사전"),
        ("safe_balance_count", "균형 표현 원본 사전"),
    )
    segments = tuple(segment for segment in text.split("\0") if segment)
    return tuple(
        ExpressionMetric(
            id=key,
            label=label,
            count=sum(cast("Callable[[str], int]", module[key])(segment) for segment in segments),
        )
        for key, label in counters
    )


def check_expression(role: PreparedRole, selection: EvidenceSelection) -> ExpressionResult:
    document = role.view.document
    if document is None or sha256(role.original).hexdigest() != document.source.content_sha256:
        raise PairError(PairErrorCode.UNAVAILABLE)
    block = next((item for item in document.blocks if item.block_id == selection.block_id), None)
    if (
        block is None
        or not 0 <= selection.start < selection.end <= len(block.raw_text)
        or selection.end - selection.start > MAX_TEXT
    ):
        raise PairError(PairErrorCode.INVALID)
    if block.source_locator.source_sha256 != document.source.content_sha256:
        raise PairError(PairErrorCode.UNAVAILABLE)
    text = masked_selection(block.raw_text, selection)
    module = load_metrics()
    findings = find_expressions(module, text, selection.start)
    return ExpressionResult(
        source_sha256=document.source.content_sha256,
        block_id=selection.block_id,
        start=selection.start,
        end=selection.end,
        findings=findings[:MAX_FINDINGS],
        metrics=compute_metrics(module, text),
        warnings=(*WARNINGS, "결과는 처음 100개까지 표시합니다.")
        if len(findings) > MAX_FINDINGS
        else WARNINGS,
    )
