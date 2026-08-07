# pyright: reportInvalidTypeForm=none
"""In-process regression test for make_clock() (pypeline's CLK_MHZ equivalent).

Exit-code-only elaboration (as in NO_SYNTH_TEST_FILES's user_clock_test.py)
can't distinguish "clk_mhz populated correctly" from "make_clock() silently a
no-op" -- both elaborate successfully. So this asserts directly against
parser_state.clk_mhz / SYN.GET_ALL_USER_CLOCKS for the success path, and that
each invalid use raises ElaborationError.
"""

import os
import sys
import tempfile
import textwrap

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..")
)

import PY_TO_LOGIC
import SYN
from PY_TO_LOGIC import ElaborationError


def _parse_source(src: str):
    """Write `src` to a temp .py file and run it through PY_TO_LOGIC.PARSE_FILE,
    same setup two_factory_wrappers_test.py uses for calling PARSE_FILE directly."""
    tmp_dir = tempfile.mkdtemp(prefix="clock_mhz_pragma_test_")
    SYN.SYN_OUTPUT_DIRECTORY = tempfile.mkdtemp(prefix="clock_mhz_pragma_test_syn_")
    tmp_path = os.path.join(tmp_dir, "design.py")
    with open(tmp_path, "w") as f:
        f.write(textwrap.dedent(src))
    return PY_TO_LOGIC.PARSE_FILE(tmp_path)


GOOD_SRC = """
from pypeline import MAIN, Input, uint1_t, make_clock

pll_clk: Input[uint1_t] = make_clock(85.0)

@MAIN(85.0)
def solution(x: uint1_t) -> uint1_t:
    return ~x
"""

BAD_TYPE_SRC = """
from pypeline import MAIN, Input, uint32_t, make_clock

pll_clk: Input[uint32_t] = make_clock(85.0)

@MAIN(85.0)
def solution(x: uint32_t) -> uint32_t:
    return x
"""

BAD_OUTPUT_SRC = """
from pypeline import MAIN, Output, uint1_t, make_clock

clk_out: Output[uint1_t] = make_clock(85.0)

@MAIN(85.0)
def solution() -> uint1_t:
    return 0
"""

BAD_DUP_RATE_SRC = """
from pypeline import MAIN, Input, uint1_t, make_clock

clk_a: Input[uint1_t] = make_clock(85.0)
clk_b: Input[uint1_t] = make_clock(85.0)

@MAIN(85.0)
def solution(x: uint1_t) -> uint1_t:
    return ~x
"""

BAD_RATE_MISMATCH_SRC = """
from pypeline import MAIN, Input, uint1_t, make_clock

pll_clk: Input[uint1_t] = make_clock(85.0)

@MAIN(50.0)
def solution(x: uint1_t) -> uint1_t:
    return ~x
"""


def test_clk_mhz_populated_on_success():
    parser_state = _parse_source(GOOD_SRC)
    assert parser_state.clk_mhz == {"pll_clk": 85.0}, parser_state.clk_mhz
    assert SYN.GET_ALL_USER_CLOCKS(parser_state) == {"clk_85p0"}
    print("test_clk_mhz_populated_on_success PASS")


def test_non_uint1_t_rejected():
    try:
        _parse_source(BAD_TYPE_SRC)
        assert False, "expected ElaborationError for non-uint1_t make_clock() wire"
    except ElaborationError:
        print("test_non_uint1_t_rejected PASS")


def test_output_rejected():
    try:
        _parse_source(BAD_OUTPUT_SRC)
        assert False, "expected ElaborationError for make_clock() on an Output"
    except ElaborationError:
        print("test_output_rejected PASS")


def test_duplicate_rate_rejected():
    try:
        _parse_source(BAD_DUP_RATE_SRC)
        assert False, "expected ElaborationError for two clocks at the same rate"
    except ElaborationError:
        print("test_duplicate_rate_rejected PASS")


def test_rate_mismatch_rejected():
    try:
        _parse_source(BAD_RATE_MISMATCH_SRC)
        assert False, "expected ElaborationError for a clock rate matching no @MAIN"
    except ElaborationError:
        print("test_rate_mismatch_rejected PASS")


if __name__ == "__main__":
    test_clk_mhz_populated_on_success()
    test_non_uint1_t_rejected()
    test_output_rejected()
    test_duplicate_rate_rejected()
    test_rate_mismatch_rejected()
    print("All clock_mhz_pragma tests passed.")
