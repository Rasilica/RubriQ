"""Reviewed upstream metric excerpts; see PROVENANCE.md."""
import re


def conclusion_pivot_count(text: str, lexicon: list[str] | None = None) -> int:
    """Count occurrences of conclusion-pivot lexicon items."""
    items = lexicon or ["결론적으로", "따라서", "이를 통해", "그러므로"]
    return sum(text.count(w) for w in items)

def safe_balance_count(text: str, lexicon: list[str] | None = None) -> int:
    """Count occurrences of safe-balance hedge lexicon."""
    items = lexicon or ["양쪽 모두", "두 가지 모두", "장점도 있지만", "신중하게", "균형"]
    return sum(text.count(w) for w in items)

_DOUBLE_PASSIVE_TOKENS = (
    "되어진다",
    "되어졌다",
    "되어진",
    "되어지는",
    "여지다",
    "여진다",
    "여졌다",
    "여진",
    "잊혀진",
    "잊혀졌",
    "잊혀진다",
    "보여진다",
    "보여졌다",
    "보여진",
    "쓰여진다",
    "쓰여졌다",
    "쓰여진",
    "닫혀진",
    "열려진",
    "불려진",
    "놓여진",
)

_PASSIVE_JI_SURFACES = tuple(
    f"{pre}{suf}"
    for pre in ("어", "아", "여", "혀", "려", "해", "워")
    for suf in ("지", "진", "질", "짐", "졌", "져")
)

_BOUND = r"(?=\s|[\"'”’()\[\]\.,!?…;:「」『』《》〈〉]|$)"

_BY_PASSIVE_RE = re.compile(
    r"에\s*의(?:해|하여)\s+(?:\S+\s+){0,2}?\S*?(?:"
    r"(?:되|받|당하)(?:다|었|았|어|는|은|을|고|며|면|지|기|까|던|자|어서)"
    r"|된다|됐|당한다|당했|됩니다|됩니까"
    r"|(?:됨|된|될|되어|당한|당할|" + "|".join(_PASSIVE_JI_SURFACES) + r")"
    r"(?:지|고|며|까|으로써|으로|지만|데)?" + _BOUND +
    r"|(?:" + "|".join(_PASSIVE_JI_SURFACES) + r")"
    r"(?:다|는|던|자|기|까|고|며|면|서|음|었|았|지|만)"
    r")"
)

_HAVE_MAKE_LITERAL_TOKENS = (
    "가지고 있다",
    "가지고있다",
    "가지고 있는",
    "가지고있는",
    "가지고 있었",
    "가지고있었",
    "가지고 있으",
    "가지고있으",
    "갖고 있다",
    "갖고있다",
    "갖고 있는",
    "갖고있는",
    "을 가지다",
    "를 가지다",
    "을 가졌",
    "를 가졌",
    "을 가진다",
    "를 가진다",
    "을 만들다",
    "를 만들다",
    "을 만들었",
    "를 만들었",
    "을 만들어 낸",
    "를 만들어 낸",
    "을 만들어낸",
    "를 만들어낸",
    "회의를 가지",
    "회의를 가졌",
    "한번 봄을 가지",
    "결정을 내리",
    "결정을 내렸",
)

_DOUBLE_PARTICLE_RE = re.compile(
    r"(?:에서의|에로의|으로의|에의|으로부터의|로부터의)"
)

def by_passive_count(text: str) -> int:
    """T2a: ~에 의해 + passive-verb co-occurrence count.

    Bare '에 의해' is excluded. Only the regex-anchored
    '에 의해 ... 되/받/당하/지' pattern is counted. Returns int >= 0.
    """
    if not text.strip():
        return 0
    return len(_BY_PASSIVE_RE.findall(text))

def double_passive_count(text: str) -> int:
    """T2b: double-passive (잊혀지다·보여지다·되어진다·여지다·쓰여지다 …) count.

    Surface-form lexicon. 단순 '되다' 는 제외 (자연 표현). Returns int >= 0.
    """
    if not text.strip():
        return 0
    n = 0
    for tok in _DOUBLE_PASSIVE_TOKENS:
        n += text.count(tok)
    return n

def have_make_literal_count(text: str) -> int:
    """T6: count of literal have/make light-verb constructions.

    가지고 있다·갖고 있다·~을 가지다·~을 만들다·회의를 가지다·결정을 내리다 …
    Returns int >= 0.
    """
    if not text.strip():
        return 0
    n = 0
    for tok in _HAVE_MAKE_LITERAL_TOKENS:
        n += text.count(tok)
    return n

def double_particle_count(text: str) -> int:
    """T7: double-particle (에서의·에로의·으로의·에의·으로부터의·로부터의) count.

    Caveat #5 (single ~의 excluded) is *enforced by construction* — the
    regex never matches a bare ~의. Returns int >= 0.
    """
    if not text.strip():
        return 0
    return len(_DOUBLE_PARTICLE_RE.findall(text))
