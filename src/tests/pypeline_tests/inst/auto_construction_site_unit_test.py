"""AUTO objects and clock goals, on the runtime side (pypeline.py, no
elaboration): each AUTO_PIPELINE / AUTO_FSM object's construction site tells
objects built on one source line apart; an object finds its results through
the binding installed for its site; and a native simulation replaying
per-goal results takes those of its own clock's goal."""

import importlib.util
import os
import sys
import tempfile
from pathlib import Path

# Standalone compiler imports; tests write only under the runner's TMPDIR.
sys.path[:0] = [
    str(Path(__file__).resolve().parents[3]),
    str(Path(__file__).resolve().parents[4] / "include" / "pypeline"),
]
sys.dont_write_bytecode = True

import pypeline
import pypeline_sim

# Objects from separate calls, a comprehension, a for loop, a helper called
# from two lines, and a library factory called twice.
SITES_SOURCE = """
from pypeline import AUTO_PIPELINE, hw_func, uint8_t
from stream.stream_auto_pipeline import make_stream_auto_pipeline
@hw_func
def work(x: uint8_t) -> uint8_t:
    return x + 1
def make(f):
    return AUTO_PIPELINE(f)
A = make(work)
B = make(work)
LISTED = [make(work) for _ in range(2)]
LOOPED = []
for _ in range(2):
    LOOPED.append(make(work))
def helper():
    return make(work)
H1 = helper()
H2 = helper()
S1 = make_stream_auto_pipeline(work)
S2 = make_stream_auto_pipeline(work)
"""


def import_source(tmp, name, source):
    path = Path(tmp, name + ".py")
    path.write_text(source)
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    pypeline.RESET_AUTO_MULTI_CYCLE_TRACKING()
    spec.loader.exec_module(module)
    return module


def test_sites_tell_apart_objects_from_one_line():
    with tempfile.TemporaryDirectory() as tmp:
        mod = import_source(tmp, "sites_design", SITES_SOURCE)
        objects = [mod.A, mod.B, *mod.LISTED, *mod.LOOPED, mod.H1, mod.H2]
        objects += [mod.S1.auto_pipeline, mod.S2.auto_pipeline]
        sites = [tag.site for tag in objects]
        assert len(set(sites)) == len(sites), sites
        # Separate calls differ in the calling line; a loop's objects only in
        # their ordinal
        assert mod.A.site.split("|")[0] == mod.B.site.split("|")[0]
        assert mod.LISTED[0].site.endswith("#0") and mod.LISTED[1].site.endswith("#1")
        assert mod.LISTED[0].site[:-2] == mod.LISTED[1].site[:-2]
        assert mod.LOOPED[0].site[:-2] == mod.LOOPED[1].site[:-2]
        # A library factory's own frames are part of the chain
        assert "stream_auto_pipeline" in mod.S1.auto_pipeline.site
        constructed = pypeline.AUTO_CONSTRUCTED()
        assert [row[2] for row in constructed] == [
            tag.site for _kind, tag in pypeline._auto_constructed
        ]
        assert all(row[0] == "AUTO_PIPELINE" and row[3] for row in constructed)


def test_sites_restart_with_each_design_execution():
    with tempfile.TemporaryDirectory() as tmp:
        first = import_source(tmp, "sites_design", SITES_SOURCE)
        again = import_source(tmp, "sites_design", SITES_SOURCE)
        assert [t.site for t in first.LISTED] == [t.site for t in again.LISTED]


def test_object_built_while_elaborating_a_body_has_its_body_line():
    from pypeline import AUTO_PIPELINE, hw_func, uint8_t

    @hw_func
    def work(x: uint8_t) -> uint8_t:
        return x + 1

    saved = pypeline._const_folding
    pypeline._const_folding = True
    try:
        first, second = AUTO_PIPELINE(work), AUTO_PIPELINE(work)
    finally:
        pypeline._const_folding = saved
    assert first.site.startswith("body:") and first.site == second.site, first.site


def installed(site_bindings=None, split=None, latencies=None, schedules=None):
    """Context: these tables and caches installed, then cleared."""
    import contextlib

    @contextlib.contextmanager
    def ctx():
        pypeline.SET_AUTO_GOAL_TABLES(site_bindings or {}, split or {})
        pypeline.SET_AUTO_PIPELINE_LATENCY_CACHE(latencies or {})
        pypeline.SET_AUTO_FSM_SCHEDULE_CACHE(schedules or {})
        try:
            yield
        finally:
            pypeline.SET_AUTO_GOAL_TABLES({}, {})
            pypeline.SET_AUTO_PIPELINE_LATENCY_CACHE({})
            pypeline.SET_AUTO_FSM_SCHEDULE_CACHE({})

    return ctx()


def test_object_resolves_through_its_sites_binding():
    """Two objects of one key, each used at its own goal, get that goal's
    depth; an object no table names (one used at both goals, say) keeps its
    key, which has no value at one goal: the build's default."""
    from pypeline import AUTO_PIPELINE, hw_func, uint8_t

    @hw_func
    def work(x: uint8_t) -> uint8_t:
        return x + 1

    def build_four():
        return [AUTO_PIPELINE(work, name="core") for _ in range(4)]

    # Built twice from one line, so the second objects have the first's sites:
    # once to learn the sites, once with tables naming them installed
    latencies = {"core@50p0mhz": 1, "core@100p0mhz": 3}
    tables = {}
    for _attempt in range(2):
        pypeline.RESET_AUTO_MULTI_CYCLE_TRACKING()
        with installed(site_bindings=tables, latencies=latencies if tables else {}):
            tags = build_four()
        sites = [tag.site for tag in tags]
        tables = {
            ("AUTO_PIPELINE", sites[0]): pypeline.GOAL_BINDING("core", 50.0),
            ("AUTO_PIPELINE", sites[1]): pypeline.GOAL_BINDING("core", 100.0),
        }
    slow, fast, both, unnamed = tags
    assert (slow.binding_key, slow.latency) == ("core@50p0mhz", 1)
    assert (fast.binding_key, fast.latency) == ("core@100p0mhz", 3)
    assert both.binding_key == unnamed.binding_key == "core"
    assert both.latency == unnamed.latency == 0


def test_goal_text_is_clock_port_style():
    assert pypeline.GOAL_TEXT(50.0) == "50p0mhz"
    assert pypeline.GOAL_TEXT(62.5) == "62p5mhz"
    assert pypeline.GOAL_TEXT(None) == "nogoal"
    assert pypeline.GOAL_BINDING("k", 100) == "k@100p0mhz"


# A testbench on one clock whose AUTO_PIPELINE reads .latency at import
TB_SOURCE = """
from pypeline import AUTO_PIPELINE, MAIN, Reg, hw_func, uint8_t
@hw_func
def work(x: uint8_t) -> uint8_t:
    return x + 1
AP = AUTO_PIPELINE(work, name="core")
DEPTH = AP.latency
@MAIN({goal})
def tb():
    r: Reg[uint8_t]
    r = AP(r)
"""


def replay(tmp, goal, latencies):
    """Simulate the testbench at `goal` on a build that recorded these
    AUTO_PIPELINE latencies; return its AUTO_PIPELINE object."""
    path = Path(tmp, "tb_design.py")
    path.write_text(TB_SOURCE.format(goal=goal))
    try:
        pypeline_sim.run_sim(
            str(path),
            2,
            main_latencies={},
            auto_pipeline_latencies=latencies,
            built_hardware_from=os.path.join(tmp, "build"),
            goal_mode="pnr",
        )
    finally:
        pypeline.SET_BUILT_HARDWARE_SOURCE(None)
        pypeline.SET_AUTO_RUN_GOAL(None)
        pypeline.SET_AUTO_PIPELINE_LATENCY_CACHE({})
    ((_kind, tag),) = pypeline._auto_constructed
    return tag


def test_replay_takes_the_run_goals_results():
    """A record with depths at 50 and 100 MHz: a 50 MHz testbench's object
    reads, and delays by, the 50 MHz depth, also at import."""
    with tempfile.TemporaryDirectory() as tmp:
        tag = replay(tmp, 50.0, {"core@50p0mhz": 1, "core@100p0mhz": 3})
        assert (tag.binding_key, tag.latency) == ("core@50p0mhz", 1)
        tag = replay(tmp, 100.0, {"core@50p0mhz": 1, "core@100p0mhz": 3})
        assert (tag.binding_key, tag.latency) == ("core@100p0mhz", 3)


def test_replay_of_one_goal_record_is_unchanged():
    with tempfile.TemporaryDirectory() as tmp:
        tag = replay(tmp, 75.0, {"core": 2})
        assert (tag.binding_key, tag.latency) == ("core", 2)


def test_replay_at_a_goal_the_build_lacks_raises():
    with tempfile.TemporaryDirectory() as tmp:
        try:
            replay(tmp, 75.0, {"core@50p0mhz": 1, "core@100p0mhz": 3})
        except pypeline.BuiltHardwareError as e:
            assert "core" in str(e), e
        else:
            raise AssertionError("a 75 MHz testbench used a 50/100 MHz build's object")


if __name__ == "__main__":
    from _test_main import run_module_tests

    run_module_tests()
