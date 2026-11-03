"""One AUTO object per clock domain, through elaboration (PY_TO_LOGIC.PARSE_FILE
in-process, results installed by hand instead of a build).

Two factory calls on one function build two AUTO_PIPELINE / AUTO_FSM objects
with one key. Their factory products used to elaborate as one function, so
both domains got one object's hardware. Now a key used at several clock goals
and built at several sites is split: PARSE_FILE elaborates every object on its
own once, learns the goals each is used at, then names objects by those goals,
so objects at one goal still share hardware. Each object then finds its
results under its key at its goal. Covers separate calls, a comprehension,
objects held in a dict, a bundle and a factory argument, a body loop over a
list, MAINs made in a loop, a bare MAIN inferred onto a clock, AUTO_FSM call
sites, the read error for one object used at two goals, and name stability
(construction order, hash seed). No synthesis."""

import contextlib
import io
import os
import subprocess
import sys
import tempfile
from pathlib import Path

# Standalone compiler imports; tests write only under the runner's TMPDIR.
SRC = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(SRC), str(SRC.parent / "include" / "pypeline")]
sys.dont_write_bytecode = True

import AUTO_FSM
import PY_TO_LOGIC
import pypeline

REPARSE_NOTE = "elaborating again so each gets its own goal's hardware"

HEADER = """
from types import SimpleNamespace
from pypeline import *

@hw_func
def work(x: uint32_t) -> uint32_t:
    return (x * x) + x

def make_lane():
    AP = AUTO_PIPELINE(work)
    depth = AP.latency

    @hw_func
    def lane(x: uint32_t) -> uint32_t:
        return AP(x) + depth

    lane.ap = AP
    return lane
"""

TWO_CALLS = HEADER + """
SLOW = make_lane()
FAST = make_lane()

@MAIN(50.0)
def slow(x: uint32_t) -> uint32_t:
    return SLOW(x)

@MAIN(100.0)
def fast(x: uint32_t) -> uint32_t:
    return FAST(x)
"""


def reset():
    pypeline.SET_AUTO_GOAL_TABLES({}, {})
    pypeline.SET_AUTO_PIPELINE_LATENCY_CACHE({})
    pypeline.SET_AUTO_FSM_SCHEDULE_CACHE({})


def parse(tmp, source, latencies=None):
    """(parser state, output) of PARSE_FILE on `source` as tmp/top.py, with
    these AUTO_PIPELINE results installed; tables from an earlier parse in
    this test stay installed, as between a build's passes."""
    path = Path(tmp, "top.py")
    path.write_text(source)
    pypeline.SET_AUTO_PIPELINE_LATENCY_CACHE(latencies or {})
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        state = PY_TO_LOGIC.PARSE_FILE(str(path))
    return state, out.getvalue()


def callee(state, inst):
    return state.LogicInstLookupTable[inst].func_name


def child(state, main, prefix):
    """The function of MAIN `main`'s submodule whose instance name starts with
    `prefix`."""
    logic = state.LogicInstLookupTable[main]
    (local,) = [n for n in logic.submodule_instances if n.startswith(prefix)]
    return logic.submodule_instances[local]


def test_two_calls_at_two_goals_build_their_own_hardware():
    reset()
    with tempfile.TemporaryDirectory() as tmp:
        state, out = parse(tmp, TWO_CALLS)
        assert out.count(REPARSE_NOTE) == 2, out
        assert child(state, "slow", "SLOW") != child(state, "fast", "FAST")
        key = state.top_level_module_globals["SLOW"].ap.canonical_key
        # A build installs what it harvested per goal; each object reads its own
        state, out = parse(
            tmp, TWO_CALLS, {f"{key}@50p0mhz": 1, f"{key}@100p0mhz": 3}
        )
        assert REPARSE_NOTE not in out, out
        mod = state.top_level_module_globals
        assert (mod["SLOW"].ap.latency, mod["FAST"].ap.latency) == (1, 3)
        assert child(state, "slow", "SLOW") != child(state, "fast", "FAST")
    reset()


def test_objects_at_one_goal_still_share_hardware():
    reset()
    source = TWO_CALLS.replace("@MAIN(100.0)", "@MAIN(50.0)")
    with tempfile.TemporaryDirectory() as tmp:
        state, out = parse(tmp, source)
        assert REPARSE_NOTE not in out, out
        assert pypeline.AUTO_GOAL_TABLES() == ({}, {})
        assert child(state, "slow", "SLOW") == child(state, "fast", "FAST")
    reset()


COMPREHENSION = HEADER + """
LANES = [make_lane() for _ in range(4)]

@MAIN(50.0)
def slow_a(x: uint32_t) -> uint32_t:
    return LANES[{a}](x)

@MAIN(50.0)
def slow_b(x: uint32_t) -> uint32_t:
    return LANES[{b}](x)

@MAIN(100.0)
def fast_a(x: uint32_t) -> uint32_t:
    return LANES[{c}](x)

@MAIN(100.0)
def fast_b(x: uint32_t) -> uint32_t:
    return LANES[{d}](x)
"""


def lane_functions(state):
    return {
        main: child(state, main, "lane")
        for main in ("slow_a", "slow_b", "fast_a", "fast_b")
    }


def test_comprehension_objects_are_named_by_goal_not_position():
    """Four objects from one line, two per goal: two functions, named by goal,
    so reordering which object each MAIN uses renames nothing."""
    reset()
    with tempfile.TemporaryDirectory() as tmp:
        state, _out = parse(tmp, COMPREHENSION.format(a=0, b=1, c=2, d=3))
        names = lane_functions(state)
        assert names["slow_a"] == names["slow_b"] != names["fast_a"] == names["fast_b"]
        reset()
        state, _out = parse(tmp, COMPREHENSION.format(a=3, b=1, c=0, d=2))
        assert lane_functions(state) == names
    reset()


HOLDERS = HEADER + """
def make_wrapper(inner):
    @hw_func
    def wrapped(x: uint32_t) -> uint32_t:
        return inner(x) + 1
    return wrapped

BY_NAME = {"slow": make_lane(), "fast": make_lane()}
BUNDLES = [SimpleNamespace(lane=make_lane()) for _ in range(2)]
WRAPPED = [make_wrapper(make_lane()) for _ in range(2)]
LOOPED = [make_lane() for _ in range(3)]

@MAIN(50.0)
def slow(x: uint32_t) -> uint32_t:
    acc: uint32_t = BY_NAME["slow"](x) + BUNDLES[0].lane(x) + WRAPPED[0](x)
    for i in range(2):
        acc = acc + LOOPED[i](x)
    return acc

@MAIN(100.0)
def fast(x: uint32_t) -> uint32_t:
    return BY_NAME["fast"](x) + BUNDLES[1].lane(x) + WRAPPED[1](x) + LOOPED[2](x)
"""


def submodule_functions(state, main):
    return set(state.LogicInstLookupTable[main].submodule_instances.values())


def test_objects_held_in_containers_and_arguments_are_told_apart():
    """A dict, a bundle's attribute, a factory argument and a body loop over a
    list each reach the object they hold: the 50 MHz MAIN's AUTO hardware is
    disjoint from the 100 MHz MAIN's, and its four lane objects (the dict's,
    the bundle's and the loop's two) share one function, so their identical
    calls collapse into one."""
    reset()
    with tempfile.TemporaryDirectory() as tmp:
        state, _out = parse(tmp, HOLDERS)
        slow, fast = submodule_functions(state, "slow"), submodule_functions(state, "fast")
        lanes_and_wrappers = {
            f for f in slow | fast if f.startswith(("lane", "wrapped"))
        }
        assert lanes_and_wrappers and not (slow & fast & lanes_and_wrappers), (slow, fast)
        slow_lanes = {f for f in slow if f.startswith("lane")}
        assert len(slow_lanes) == 1, slow
        tables = pypeline.AUTO_GOAL_TABLES()[0]
        goals = sorted(set(tables.values()))
        assert len(goals) == 2 and all(b.endswith(("@50p0mhz", "@100p0mhz")) for b in goals)
    reset()


MADE_MAINS = HEADER + """
def make_lane_main():
    LANE = make_lane()

    @hw_func
    def lane_main(x: uint32_t) -> uint32_t:
        return LANE(x)

    return lane_main

LANE_MAINS = [MAIN(make_lane_main(), mhz=mhz, name=f"lane{i}") for i, mhz in enumerate((50.0, 100.0))]
"""


def test_mains_made_in_a_loop_get_their_own_goals_hardware():
    reset()
    with tempfile.TemporaryDirectory() as tmp:
        state, _out = parse(tmp, MADE_MAINS)
        assert callee(state, "lane0") != callee(state, "lane1")
        lane0 = child(state, "lane0", "LANE")
        lane1 = child(state, "lane1", "LANE")
        assert lane0 != lane1
    reset()


INFERRED = HEADER + """
shared: Wire[uint32_t]
SLOW = make_lane()
FAST = make_lane()

@MAIN(50.0)
def driver(x: uint32_t) -> uint32_t:
    shared = x
    return x

@MAIN
def inferred() -> uint32_t:
    return SLOW(shared)

@MAIN(100.0)
def fast(x: uint32_t) -> uint32_t:
    return FAST(x)
"""


def test_bare_main_counts_at_its_inferred_goal():
    reset()
    with tempfile.TemporaryDirectory() as tmp:
        state, _out = parse(tmp, INFERRED)
        bindings = set(pypeline.AUTO_GOAL_TABLES()[0].values())
        assert any(b.endswith("@50p0mhz") for b in bindings), bindings
        assert any(b.endswith("@100p0mhz") for b in bindings), bindings
    reset()


SHARED = HEADER + """
LANE = make_lane()

@MAIN(50.0)
def slow(x: uint32_t) -> uint32_t:
    return LANE(x)

@MAIN(100.0)
def fast(x: uint32_t) -> uint32_t:
    return LANE(x)
"""


def test_one_object_at_two_goals_whose_latency_is_read_is_an_error():
    reset()
    with tempfile.TemporaryDirectory() as tmp:
        try:
            parse(tmp, SHARED)
        except PY_TO_LOGIC.ElaborationError as e:
            message = str(e)
            assert "50 MHz, 100 MHz" in message, message
            assert "make_lane" in message and "one object per clock domain" in message
        else:
            raise AssertionError("a .latency read of an object at two goals parsed")
    reset()


def test_one_object_at_two_goals_without_a_read_parses():
    """Each instance gets its own goal's depth; nothing to tell apart, so one
    parse."""
    reset()
    source = SHARED.replace("    depth = AP.latency\n", "    depth = 0\n")
    with tempfile.TemporaryDirectory() as tmp:
        _state, out = parse(tmp, source)
        assert REPARSE_NOTE not in out, out
    reset()


FSMS = """
from pypeline import *

@struct
class in_t(NamedTuple):
    x: uint16_t
    y: uint16_t

@hw_func
def fsm_func(v: in_t) -> uint16_t:
    return v.x + v.y

def make_fsm_lane():
    FSM = AUTO_FSM(fsm_func)

    @hw_func
    def fsm_lane(a: in_t, valid: uint1_t) -> uint16_t:
        s: FSM.in_stream_t
        s.data = a
        s.valid = valid
        o = FSM(s)
        return o.data

    return fsm_lane

SLOW = make_fsm_lane()
FAST = make_fsm_lane()

@MAIN(50.0)
def slow(a: in_t, valid: uint1_t) -> uint16_t:
    return SLOW(a, valid)

@MAIN(100.0)
def fast(a: in_t, valid: uint1_t) -> uint16_t:
    return FAST(a, valid)
"""


def test_auto_fsm_objects_at_two_goals_get_a_call_site_each():
    reset()
    with tempfile.TemporaryDirectory() as tmp:
        state, _out = parse(tmp, FSMS)
        keys = sorted(AUTO_FSM.GET_TAGS(state))
        assert len(keys) == 2, keys
        assert keys[0].endswith("@100p0mhz") and keys[1].endswith("@50p0mhz"), keys
        assert AUTO_FSM._period_du(state, keys[1]) == 200.0, keys
    reset()


def test_names_do_not_depend_on_the_hash_seed():
    names = []
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp, "top.py")
        path.write_text(COMPREHENSION.format(a=0, b=1, c=2, d=3))
        script = (
            "import sys; sys.path[:0] = [{src!r}, {inc!r}]\n"
            "import PY_TO_LOGIC\n"
            "s = PY_TO_LOGIC.PARSE_FILE({path!r})\n"
            "print('NAMES', sorted(s.FuncLogicLookupTable))\n"
        ).format(src=str(SRC), inc=str(SRC.parent / "include" / "pypeline"), path=str(path))
        for seed in ("1", "2"):
            env = dict(os.environ, PYTHONHASHSEED=seed)
            result = subprocess.run(
                [sys.executable, "-c", script], capture_output=True, text=True, env=env, cwd=tmp
            )
            assert result.returncode == 0, result.stderr[-2000:]
            names.append([l for l in result.stdout.splitlines() if l.startswith("NAMES")])
    assert names[0] == names[1] and names[0], names


if __name__ == "__main__":
    from _test_main import run_module_tests

    run_module_tests()
