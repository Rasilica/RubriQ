import re
from pathlib import Path

from submission.conversion_contracts import ConversionErrorCode
from submission.input_contracts import InputErrorCode
from submission.pair_contracts import PairErrorCode

STATE = Path("src/submission/static/prepare/state.mjs")


def test_every_preparation_error_code_has_screen_text() -> None:
    block = re.search(r"const ERRORS=\{(.*?)\};", STATE.read_text(), re.DOTALL)
    assert block is not None
    listed = set(re.findall(r"(\w+):'", block.group(1)))
    codes = {
        str(code) for enum in (InputErrorCode, ConversionErrorCode, PairErrorCode) for code in enum
    }

    assert codes - listed == set()
