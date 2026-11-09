"""Native simulation timeline of resets: each design below is written to a
temp file and run with pypeline_sim.py, and its printed per-cycle values are
checked.

- The default pulse: a reset pin is 1 in cycle 0 and 0 after it, so a
  Reg[T, RESET] holds its initial value through cycle 1; --run N still runs N
  cycles. A MAIN named by rate takes the reset of a make_clock of that rate
  that no MAIN names.
- A design without resets has the timeline it always had.
- A reset pin that Python code drives (a @sim_input) gets no default pulse.
- A reset Wire comes from its logic, never from the pulse.
- sim_call runs with every reset inactive.
"""

import os
import subprocess
import sys
import tempfile

REPO_SRC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..")
sys.path.insert(0, REPO_SRC)

_HEADER = """
import sys
sys.path.insert(0, {src!r})
from pypeline import *

"""


def _run(src, cycles):
    """Run a design for `cycles`; returns [(cycle, pc)] from its 'pc=' prints."""
    with tempfile.TemporaryDirectory(prefix="reset_sim_timeline_test_") as tmpdir:
        path = os.path.join(tmpdir, "design.py")
        with open(path, "w") as f:
            f.write(_HEADER.format(src=os.path.abspath(REPO_SRC)) + src)
        proc = subprocess.run(
            [sys.executable, os.path.join(REPO_SRC, "pypeline_sim.py"), path, "--run", str(cycles)],
            capture_output=True,
            text=True,
        )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    rows = [line.split() for line in proc.stdout.splitlines() if line.startswith("t=")]
    assert f"{cycles} cycles in" in proc.stdout, proc.stdout
    return [(int(r[0][2:]), int(r[1][3:])) for r in rows]


_COUNTER = """
@MAIN(clk)
def m():
    t: Reg[uint8_t]
    pc: Reg[uint8_t, RESET] = 7
    sim_print(f"t={t} pc={pc}")
    pc = pc + 1
    t = t + 1
"""


def test_default_pulse():
    rows = _run(
        "rst: Input[uint1_t] = make_reset()\nclk = make_clock(100.0, reset=rst)\n"
        + _COUNTER,
        5,
    )
    assert rows == [(0, 7), (1, 7), (2, 8), (3, 9), (4, 10)], rows
    print("test_default_pulse PASS")


def test_rate_main_takes_an_unnamed_clocks_reset():
    # make_clock(100.0, reset=rst) that no MAIN names is still the clock
    # @MAIN(100.0) runs on, so its Reg[T, RESET] gets the pulse
    rows = _run(
        "rst: Input[uint1_t] = make_reset()\nclk = make_clock(100.0, reset=rst)\n"
        + _COUNTER.replace("@MAIN(clk)", "@MAIN(100.0)"),
        4,
    )
    assert rows == [(0, 7), (1, 7), (2, 8), (3, 9)], rows
    print("test_rate_main_takes_an_unnamed_clocks_reset PASS")


def test_reset_free_timeline_unchanged():
    rows = _run(
        """
@MAIN(100.0)
def m():
    t: Reg[uint8_t]
    pc: Reg[uint8_t] = 7
    sim_print(f"t={t} pc={pc}")
    pc = pc + 1
    t = t + 1
""",
        4,
    )
    assert rows == [(0, 7), (1, 8), (2, 9), (3, 10)], rows
    print("test_reset_free_timeline_unchanged PASS")


def test_python_driven_reset_has_no_pulse():
    rows = _run(
        """
rst: Input[uint1_t] = make_reset()
clk = make_clock(100.0, reset=rst)
_t = [0]

@sim_input
def drive_rst():
    global rst
    rst = 1 if _t[0] == 2 else 0
    _t[0] += 1
"""
        + _COUNTER.replace("def m():\n", "def m():\n    drive_rst()\n"),
        6,
    )
    # No reset in cycle 0; the one Python drives in cycle 2 resets pc at that edge
    assert rows == [(0, 7), (1, 8), (2, 9), (3, 7), (4, 8), (5, 9)], rows
    print("test_python_driven_reset_has_no_pulse PASS")


def test_wire_reset_from_logic():
    rows = _run(
        """
gen: Wire[uint1_t] = make_reset()
clk = make_clock(100.0, reset=gen)

@MAIN(clk, reset=None)
def maker():
    n: Reg[uint8_t]
    gen = n == 3
    n = n + 1
"""
        + _COUNTER,
        6,
    )
    assert rows == [(0, 7), (1, 8), (2, 9), (3, 10), (4, 7), (5, 8)], rows
    print("test_wire_reset_from_logic PASS")


def test_sim_call_resets_inactive():
    from pypeline import MAIN, RESET, Input, Reg, make_reset, sim_call, sim_reset, uint1_t, uint8_t

    rst = make_reset()

    @MAIN(100.0, reset=rst)
    def stepper() -> uint8_t:
        pc: Reg[uint8_t, RESET] = 7
        rv = pc
        pc = pc + 1
        return rv

    sim_reset()
    values = [int(sim_call(stepper)) for _ in range(3)]
    assert values == [7, 8, 9], values
    print("test_sim_call_resets_inactive PASS")


if __name__ == "__main__":
    from _test_main import run_module_tests

    run_module_tests()
