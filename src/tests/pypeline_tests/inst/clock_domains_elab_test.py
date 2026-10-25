"""In-process checks of clock assignment and the clock-crossing check: each
design below is written to a temp .py file and parsed with
PY_TO_LOGIC.PARSE_FILE, then checked against the parser state, the raised
ElaborationError, or the printed notes and warnings.

- Clocks: named clocks of one rate are two clocks (main_clk_group), a clock's
  syn_mhz reaches every MAIN on it (main_syn_mhz), including a rate-only
  @MAIN of the same clock.
- Inference: a bare MAIN takes its clock through a plain wire, through a
  helper that uses the wire, from a pin with a stated clock, and through a
  global instance; a bare MAIN reached only through an async wire runs on the
  default clock, with a warning; a bare MAIN that plain wires connect to two
  clocks is an error naming both paths; an instance used on two clocks is
  reported as the instance; each bare MAIN's note is printed once per session.
- The crossing check: a plain wire read on another clock is an error naming
  both ends and the two fixes; a compound wire split per leaf across clocks
  is legal; ASYNC leaves read on other clocks become crossing rows, and an
  ASYNC wire never read on another clock warns; stated clocks are enforced on
  writers and on pin readers; a plain pin read on two clocks is an error,
  an ASYNC pin is not.
- A board clock module (board.arty.clocks) binds its pin to its clock.
"""

import contextlib
import io
import os
import sys
import tempfile

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..")
)

import PY_TO_LOGIC
import SYN

REPO_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..")

_HEADER = """
import sys, os
sys.path.insert(0, {repo_root!r})
from pypeline import *

"""


def _parse(src, name):
    """Parse a design; returns (parser_state, printed output)."""
    out = io.StringIO()
    with tempfile.TemporaryDirectory(prefix="clock_domains_elab_test_") as tmpdir:
        path = os.path.join(tmpdir, name)
        with open(path, "w") as f:
            f.write(_HEADER.format(repo_root=os.path.abspath(REPO_ROOT)))
            f.write(src)
        with contextlib.redirect_stdout(out):
            state = PY_TO_LOGIC.PARSE_FILE(path)
    return state, out.getvalue()


def _expect_error(src, name, must_contain):
    try:
        _parse(src, name)
    except PY_TO_LOGIC.ElaborationError as e:
        msg = str(e)
        for token in must_contain:
            assert token in msg, f"{name}: expected {token!r} in the error, got: {msg}"
        print(f"{name} PASS  ({msg.splitlines()[0]})")
        return
    raise AssertionError(f"{name}: expected an ElaborationError, PARSE_FILE succeeded")


def _clock(state, main):
    return state.main_mhz[main], state.main_clk_group[main], state.main_syn_mhz[main]


def test_named_clocks_and_syn_mhz():
    state, _out = _parse(
        """
rx_clk = make_clock(25.0, name="eth_rx")
tx_clk = make_clock(25.0, name="eth_tx")
dsp_clk = make_clock(125.0, syn_mhz=147.0)

@MAIN(rx_clk)
def eth_rx():
    n: Reg[uint8_t]
    n += 1

@MAIN(clock=tx_clk)
def eth_tx():
    n: Reg[uint8_t]
    n += 1

@MAIN(dsp_clk)
def dsp():
    n: Reg[uint8_t]
    n += 1

@MAIN(125.0)
def filt():
    n: Reg[uint8_t]
    n += 1
""",
        "named_clocks_test.py",
    )
    assert _clock(state, "eth_rx") == (25.0, "eth_rx", 25.0), _clock(state, "eth_rx")
    assert _clock(state, "eth_tx") == (25.0, "eth_tx", 25.0), _clock(state, "eth_tx")
    assert _clock(state, "dsp") == (125.0, None, 147.0), _clock(state, "dsp")
    assert _clock(state, "filt") == (125.0, None, 147.0), _clock(state, "filt")
    assert state.pypeline_clock_names[(25.0, "eth_rx")] == "rx_clk"
    print("test_named_clocks_and_syn_mhz PASS")


def test_inference():
    state, out = _parse(
        """
eth_clk = make_clock(125.0, name="eth_rx")
rmii_clk = make_clock(50.0, name="rmii")
shared: Wire[uint8_t]
RMII_RXD: Input[uint2_t, rmii_clk]

@hw_func
def write_via_helper(x: uint8_t) -> uint8_t:
    shared = x
    return x

@MAIN(eth_clk)
def driver(x: uint8_t) -> uint8_t:
    return write_via_helper(x)

@MAIN
def reader() -> uint8_t:
    return shared

@MAIN
def rmii_reader() -> uint2_t:
    return RMII_RXD

@MAIN(clock=rmii_clk)
def rmii_owner():
    n: Reg[uint8_t]
    n += 1

@hw_func
def add(a: uint8_t, b: uint8_t) -> uint8_t:
    return a + b

adder: Inst[add]

@MAIN(eth_clk)
def drive_a():
    adder.a = 1

@MAIN
def drive_b():
    adder.b = 2
""",
        "inference_test.py",
    )
    assert _clock(state, "reader")[:2] == (125.0, "eth_rx"), _clock(state, "reader")
    assert _clock(state, "rmii_reader")[:2] == (50.0, "rmii"), _clock(state, "rmii_reader")
    assert _clock(state, "adder_INST")[:2] == (125.0, "eth_rx"), _clock(state, "adder_INST")
    assert _clock(state, "drive_b")[:2] == (125.0, "eth_rx"), _clock(state, "drive_b")
    note = "Clock of bare @MAIN 'reader': eth_clk (clk_125p0_eth_rx), from @MAIN 'driver'"
    assert note in out, out
    assert "Clock of bare @MAIN 'adder_INST'" not in out, out
    print("test_inference PASS")


def test_notes_printed_once():
    src = """
fast_wire: Wire[uint8_t]

@MAIN(100.0)
def writer():
    fast_wire = 3

@MAIN
def follower() -> uint8_t:
    return fast_wire
"""
    _state, out1 = _parse(src, "notes_once_test.py")
    _state, out2 = _parse(src, "notes_once_test.py")
    note = "Clock of bare @MAIN 'follower': clk_100p0"
    assert note in out1, out1
    assert note not in out2, out2
    print("test_notes_printed_once PASS")


def test_default_clock_warning():
    state, out = _parse(
        """
flag: Wire[uint1_t, ASYNC]

@MAIN(100.0)
def writer():
    flag = 1

@MAIN
def lonely() -> uint1_t:
    return flag
""",
        "default_clock_test.py",
    )
    assert _clock(state, "lonely")[:2] == (None, None), _clock(state, "lonely")
    assert "WARNING: bare @MAIN 'lonely' runs on the default clock clk_None" in out, out
    assert "clk_100p0" in out
    print("test_default_clock_warning PASS")


def test_bare_main_two_clocks():
    _expect_error(
        """
eth_clk = make_clock(125.0, name="eth_rx")
a: Wire[uint8_t]
b: Wire[uint8_t]

@MAIN(100.0)
def fast():
    a = 1

@MAIN(eth_clk)
def eth():
    b = 2

@MAIN
def bridge() -> uint8_t:
    return a + b
""",
        "bridge_two_clocks_test.py",
        [
            "@MAIN 'bridge' names no clock",
            "clk_100p0: @MAIN 'fast' -> wire 'a'",
            "eth_clk (clk_125p0_eth_rx): @MAIN 'eth' -> wire 'b'",
            "Wire[T, ASYNC]",
        ],
    )


def test_crossing_error():
    _expect_error(
        """
eth_clk = make_clock(125.0, name="eth_rx")

@struct
class status_t(NamedTuple):
    eth_up: uint1_t
    pcie_up: uint1_t

status: Wire[status_t]

@MAIN(eth_clk)
def eth():
    status.eth_up = 1

@MAIN(100.0)
def csr() -> uint1_t:
    return status.eth_up
""",
        "crossing_error_test.py",
        [
            "wire 'status.eth_up' crosses clocks without a crossing.",
            "driven on clock eth_clk (clk_125p0_eth_rx) by eth() at crossing_error_test.py:18",
            "read on clock clk_100p0 by csr() at crossing_error_test.py:22",
            "status: Wire[status_t, ASYNC]",
            "status_q: Fifo[status_t] = global_fifo(4)",
        ],
    )


def test_per_leaf_split_is_legal():
    state, _out = _parse(
        """
eth_clk = make_clock(125.0, name="eth_rx")
pcie_clk = make_clock(125.0, name="pcie")

@struct
class status_t(NamedTuple):
    eth_up: uint1_t
    pcie_up: uint1_t

status: Wire[status_t]

@MAIN(eth_clk)
def eth() -> uint1_t:
    status.eth_up = 1
    return status.eth_up

@MAIN(pcie_clk)
def pcie() -> uint1_t:
    status.pcie_up = 1
    return status.pcie_up
""",
        "per_leaf_test.py",
    )
    assert "status" in state.wire_clocks_checked
    assert state.pypeline_clock_crossings == [], state.pypeline_clock_crossings
    print("test_per_leaf_split_is_legal PASS")


def test_async_rows_and_warning():
    state, out = _parse(
        """
eth_clk = make_clock(125.0, name="eth_rx")
link_up: Wire[uint1_t, ASYNC]
same_clock: Wire[uint1_t, ASYNC]

@MAIN(eth_clk)
def eth():
    link_up = 1
    same_clock = 1

@MAIN(eth_clk)
def eth_reader() -> uint1_t:
    return same_clock

@MAIN(100.0)
def app() -> uint1_t:
    sync: Reg[uint1_t[2]]
    up = sync[1]
    sync[1] = sync[0]
    sync[0] = link_up
    return up
""",
        "async_rows_test.py",
    )
    rows = [(r.name, r.kind, r.write_clock, r.read_clock) for r in state.pypeline_clock_crossings]
    assert rows == [("link_up", "ASYNC wire", (125.0, "eth_rx"), (100.0, None))], rows
    assert "link_up" in state.async_wires and "same_clock" in state.async_wires
    assert state.global_vars["link_up"].pipeline_timing == "volatile"
    assert "WARNING: async wire 'same_clock'" in out, out
    assert "WARNING: async wire 'link_up'" not in out, out
    print("test_async_rows_and_warning PASS")


def test_stated_clocks():
    _expect_error(
        """
eth_clk = make_clock(125.0, name="eth_rx")
status: Wire[uint8_t, eth_clk]

@MAIN(100.0)
def wrong():
    status = 1

@MAIN(eth_clk)
def user() -> uint8_t:
    return status
""",
        "stated_wire_test.py",
        ["Wire 'status'", "declared on eth_clk (clk_125p0_eth_rx)", "wrong() writes it on clk_100p0"],
    )
    _expect_error(
        """
rmii_clk = make_clock(50.0, name="rmii")
RMII_RXD: Input[uint2_t, rmii_clk]

@MAIN(rmii_clk)
def owner() -> uint2_t:
    return RMII_RXD

@MAIN(100.0)
def stray() -> uint2_t:
    return RMII_RXD
""",
        "stated_pin_test.py",
        ["Pin 'RMII_RXD'", "declared on rmii_clk (clk_50p0_rmii)", "stray() reads it on clk_100p0"],
    )


def test_pins_on_two_clocks():
    _expect_error(
        """
BTN: Input[uint4_t]

@MAIN(100.0)
def a() -> uint4_t:
    return BTN

@MAIN(50.0)
def b() -> uint4_t:
    return BTN
""",
        "pin_two_clocks_test.py",
        ["Pin 'BTN'", "read on two clocks", "Input[T, ASYNC]"],
    )
    state, _out = _parse(
        """
BTN: Input[uint4_t, ASYNC]

@MAIN(100.0)
def a() -> uint4_t:
    return BTN

@MAIN(50.0)
def b() -> uint4_t:
    return BTN
""",
        "async_pin_test.py",
    )
    rows = sorted((r.name, r.kind, r.write_clock, r.read_clock) for r in state.pypeline_clock_crossings)
    assert rows == [
        ("BTN", "ASYNC pin", None, (50.0, None)),
        ("BTN", "ASYNC pin", None, (100.0, None)),
    ], rows
    print("test_pins_on_two_clocks PASS")


def test_board_clock_binding():
    state, _out = _parse(
        """
import board.arty.clocks as arty_clocks

@MAIN(arty_clocks.clk100)
def top() -> uint1_t:
    return 1
""",
        "board_clock_test.py",
    )
    assert state.clk_mhz == {"CLK100MHZ": 100.0}, state.clk_mhz
    assert SYN.GET_ALL_USER_CLOCKS(state) == {"clk_100p0"}
    assert state.pypeline_clock_names[(100.0, None)] == "clk100"
    print("test_board_clock_binding PASS")


if __name__ == "__main__":
    from _test_main import run_module_tests

    run_module_tests()
