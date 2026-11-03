"""An AUTO_FSM's per-state budget comes from the clock goals of the MAINs that
instantiate it, never from another MAIN.

The fixture has one AUTO_FSM call site (two chained adds) in a MAIN whose
goal is a template parameter, beside a second MAIN. Adders are given 3 ns. The
schedule's budget_du is the call site's period times the default budget scale
0.9: 180 du at 50 MHz, 90 du at 100 MHz. No synthesis runs."""

import contextlib
import io
import sys
import tempfile
from pathlib import Path

# Standalone compiler imports; tests write only under the runner's TMPDIR.
sys.path[:0] = [
    str(Path(__file__).resolve().parents[3]),
    str(Path(__file__).resolve().parents[4] / "include" / "pypeline"),
]
# Each test rewrites the fixture in place within one second; a cached bytecode
# file that matches the old size and time would run the old source.
sys.dont_write_bytecode = True

import AUTO_FSM
import PY_TO_LOGIC
import SYN
import pypeline

FSM_SOURCE = """
from pypeline import AUTO_FSM, INFERRED, NamedTuple, hw_func, register_operator, struct, uint16_t
@struct
class a_in_t(NamedTuple):
    x: uint16_t
    y: uint16_t
    z: uint16_t
@hw_func
def fsm_a_func(v: a_in_t) -> uint16_t:
    s: uint16_t = v.x + v.y
    return s + v.z
register_operator("PLUS", uint16_t, uint16_t, INFERRED, scope=fsm_a_func)
FSM_A = AUTO_FSM(fsm_a_func)
"""

# {fsm_main} decorates the MAIN that uses the FSM, {other_main} the second one,
# whose body is {other_body}.
TOP_SOURCE = """
from pypeline import MAIN, make_clock, hw_func, uint1_t, uint16_t
from fsm_a import FSM_A, a_in_t
clk = make_clock(50.0, syn_mhz=60.0)
@hw_func
def use_fsm(a: a_in_t, valid: uint1_t) -> uint16_t:
    ra: FSM_A.in_stream_t
    ra.data = a
    ra.valid = valid
    o = FSM_A(ra)
    return o.data
{fsm_main}
def fsm_main(a: a_in_t, valid: uint1_t) -> uint16_t:
    return use_fsm(a, valid)
{other_main}
def other(a: a_in_t, valid: uint1_t, x: uint16_t) -> uint16_t:
    {other_body}
"""


def schedule_for(fsm_main, other_main, other_uses_fsm=False, tool=None):
    """(schedule, search digest, printed output) of the call site, harvested
    with every adder at 3 ns under synthesis tool `tool` (default: what the
    design's part selects)."""
    with tempfile.TemporaryDirectory() as tmp:
        Path(tmp, "fsm_a.py").write_text(FSM_SOURCE)
        path = Path(tmp, "top.py")
        path.write_text(
            TOP_SOURCE.format(
                fsm_main=fsm_main,
                other_main=other_main,
                other_body="return use_fsm(a, valid)" if other_uses_fsm else "return x ^ 5",
            )
        )
        saved = (SYN.SYN_TOOL, SYN.NUM_PROCESSES, SYN.SYN_OUTPUT_DIRECTORY)
        out = io.StringIO()
        try:
            parser = PY_TO_LOGIC.PARSE_FILE(str(path))
            if tool is None:
                SYN.PART_SET_TOOL(parser.part)
            else:
                SYN.SYN_TOOL = tool
            SYN.NUM_PROCESSES = 1
            SYN.SYN_OUTPUT_DIRECTORY = None
            for name, logic in parser.FuncLogicLookupTable.items():
                if name.startswith("BIN_OP_PLUS_"):
                    logic.delay = 30
            ((key, tag),) = AUTO_FSM.GET_TAGS(parser).items()
            request = [AUTO_FSM.DEFAULT_BUDGET_SCALE, None, True, "v3", [], []]
            with contextlib.redirect_stdout(out):
                digest = AUTO_FSM._search_digest(parser, key, tag, request)
                schedule = AUTO_FSM.HARVEST_AUTO_FSM_SCHEDULES(
                    parser, ctl="v3", keys={key}
                )[key]
        finally:
            SYN.SYN_TOOL, SYN.NUM_PROCESSES, SYN.SYN_OUTPUT_DIRECTORY = saved
            pypeline.SET_AUTO_FSM_SCHEDULE_CACHE({})
            AUTO_FSM._MULTI_GOAL_NOTED.clear()
        return schedule, digest, out.getvalue()


def test_unrelated_faster_main_does_not_tighten_budget():
    """The FSM is used only under @MAIN(50.0); an unrelated @MAIN(200.0)
    must not make its budget 45 du."""
    schedule, digest, _out = schedule_for("@MAIN(50.0)", "@MAIN(200.0)")
    assert schedule["budget_du"] == 180, schedule["budget_du"]
    _schedule, faster_other, _out = schedule_for("@MAIN(50.0)", "@MAIN(300.0)")
    assert faster_other == digest, "another MAIN's goal changed the search digest"


def test_main_without_goal_leaves_fsm_unconstrained():
    """A bare MAIN with no clock goal beside an unrelated 200 MHz MAIN: nothing
    to schedule against, so the whole function stays in one state."""
    schedule, _digest, _out = schedule_for("@MAIN", "@MAIN(200.0)")
    assert schedule["budget_du"] == 1 << 30, schedule["budget_du"]


def test_fsm_under_two_goals_uses_tightest_with_one_note():
    """One call site under 50 and 100 MHz MAINs gets one schedule, built for
    100 MHz, and one NOTE saying so."""
    schedule, _digest, out = schedule_for(
        "@MAIN(50.0)", "@MAIN(100.0)", other_uses_fsm=True
    )
    assert schedule["budget_du"] == 90, schedule["budget_du"]
    assert out.count("NOTE: AUTO_FSM") == 1, out
    assert "built for 100 MHz" in out, out


def test_synthesis_only_tool_uses_clock_syn_mhz():
    """A synthesis-only tool times against a clock's syn_mhz, so the budget
    does too: 60 MHz gives int(1000 / 60 * 10 * 0.9) = 150 du."""
    import DEVICE_MODELS

    schedule, _digest, _out = schedule_for(
        "@MAIN(clk)", "@MAIN(200.0)", tool=DEVICE_MODELS
    )
    assert schedule["budget_du"] == 150, schedule["budget_du"]


if __name__ == "__main__":
    from _test_main import run_module_tests

    run_module_tests()
