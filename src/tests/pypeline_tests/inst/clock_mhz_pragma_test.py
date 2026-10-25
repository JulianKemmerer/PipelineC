# pyright: reportInvalidTypeForm=none
"""In-process regression test for clocks bound to pins (pll_clk:
Input[uint1_t] = make_clock(85.0), pypeline's CLK_MHZ equivalent).

Exit-code-only elaboration (as in NO_SYNTH_TEST_FILES's user_clock_test.py)
can't distinguish "clk_mhz populated correctly" from "the binding silently a
no-op" -- both elaborate successfully. So this asserts directly against
parser_state.clk_mhz / clk_group / SYN.GET_ALL_USER_CLOCKS for the success
paths (an unnamed clock, two named clocks of one rate), and that each invalid
binding raises an ElaborationError naming the problem: a non-uint1_t wire, an
Output, two pins bound to one clock, a clock no @MAIN runs on.
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

TWO_NAMED_SRC = """
from pypeline import MAIN, Input, uint1_t, make_clock

rx_clk = make_clock(25.0, name="eth_rx")
tx_clk = make_clock(25.0, name="eth_tx")
RX_CLK: Input[uint1_t] = rx_clk
TX_CLK: Input[uint1_t] = tx_clk

@MAIN(rx_clk)
def rx(x: uint1_t) -> uint1_t:
    return ~x

@MAIN(tx_clk)
def tx(x: uint1_t) -> uint1_t:
    return x
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


def test_two_named_clocks_of_one_rate():
    parser_state = _parse_source(TWO_NAMED_SRC)
    assert parser_state.clk_mhz == {"RX_CLK": 25.0, "TX_CLK": 25.0}, parser_state.clk_mhz
    assert parser_state.clk_group == {"RX_CLK": "eth_rx", "TX_CLK": "eth_tx"}
    assert SYN.GET_ALL_USER_CLOCKS(parser_state) == {"clk_25p0_eth_rx", "clk_25p0_eth_tx"}
    print("test_two_named_clocks_of_one_rate PASS")


def _expect_error(src, *tokens):
    try:
        _parse_source(src)
    except ElaborationError as e:
        for token in tokens:
            assert token in str(e), (token, str(e))
        return str(e)
    raise AssertionError(f"expected an ElaborationError mentioning {tokens}")


def test_non_uint1_t_rejected():
    _expect_error(BAD_TYPE_SRC, "'pll_clk'", "must be uint1_t")
    print("test_non_uint1_t_rejected PASS")


def test_output_rejected():
    _expect_error(BAD_OUTPUT_SRC, "Output 'clk_out'", "exactly one driver")
    print("test_output_rejected PASS")


def test_two_pins_for_one_clock_rejected():
    _expect_error(BAD_DUP_RATE_SRC, "clk_b", "clk_85p0", "a clock has one pin", "name=")
    print("test_two_pins_for_one_clock_rejected PASS")


def test_clock_of_no_main_rejected():
    _expect_error(BAD_RATE_MISMATCH_SRC, "'pll_clk'", "clk_85p0", "not the clock of any @MAIN")
    print("test_clock_of_no_main_rejected PASS")


if __name__ == "__main__":
    test_clk_mhz_populated_on_success()
    test_two_named_clocks_of_one_rate()
    test_non_uint1_t_rejected()
    test_output_rejected()
    test_two_pins_for_one_clock_rejected()
    test_clock_of_no_main_rejected()
    print("All clock_mhz_pragma tests passed.")
