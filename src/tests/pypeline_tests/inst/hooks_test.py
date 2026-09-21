# pyright: reportInvalidTypeForm=none
"""@initial/@final hooks under the native sim (pypeline_sim.run_sim, in-process).

Runs hooks_design.py once per HOOKS_TEST_MODE and checks its EVENTS log:
- sim @initial hooks all run before the first @sim_input
- sim @final hooks all run after the last @sim_output, after sim_finish(), a
  --run N cutoff, or an error, and the error that ended the run is still the
  one raised
- syn-only hooks never run in a simulation
- sim_finish() inside a hook, a hook with parameters, and sim=False/syn=False
  are errors

hooks_order_test.py covers the pypelinec driver flows (syn hooks, cocotb+GHDL).
"""

import sys, os

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..")
)

import pypeline
import pypeline_sim
from pypeline import final, initial

DESIGN = os.path.join(os.path.dirname(os.path.abspath(__file__)), "hooks_design.py")
SIM_INITIALS = {"both_initial", "sim_initial_a", "sim_initial_b"}
SIM_FINALS = {"both_final", "sim_final"}


def _run(mode, num_cycles):
    """Returns (EVENTS, exception raised by run_sim or None)."""
    os.environ["HOOKS_TEST_MODE"] = mode
    err = None
    try:
        pypeline_sim.run_sim(DESIGN, num_cycles)
    except BaseException as e:
        err = e
    # The design module is not in sys.modules; reach its globals via a hook
    events = pypeline._hook_registry[0][0].__globals__["EVENTS"]
    return list(events), err


def _check_order(events, n_outputs):
    n = len(SIM_INITIALS)
    assert set(events[:n]) == SIM_INITIALS, events
    assert set(events[-len(SIM_FINALS) :]) == SIM_FINALS, events
    middle = events[n : -len(SIM_FINALS)]
    assert set(middle) <= {"sim_input", "sim_output"}, events
    assert middle.count("sim_output") == n_outputs, events
    assert not any(e.startswith("syn_") for e in events), events


def test_sim_finish():
    events, err = _run("finish", pypeline_sim.RUN_ALL)
    assert err is None, err
    _check_order(events, n_outputs=5)


def test_run_n_cutoff():
    events, err = _run("cutoff", 3)
    assert err is None, err
    _check_order(events, n_outputs=3)


def test_error_still_runs_finals():
    events, err = _run("assert", 10)
    assert isinstance(err, AssertionError), err
    assert "deliberate sim assert" in str(err), err
    _check_order(events, n_outputs=3)


def test_final_hook_error_raised_after_all_finals():
    events, err = _run("final_raises", pypeline_sim.RUN_ALL)
    assert isinstance(err, AssertionError), err
    assert "deliberate hook failure" in str(err), err
    _check_order(events, n_outputs=5)


def test_sim_finish_in_hook():
    events, err = _run("hook_finish", 10)
    assert isinstance(err, RuntimeError) and "sim_finish()" in str(err), err
    # No cycle ran; the finals still did
    assert "sim_input" not in events, events
    assert SIM_FINALS <= set(events), events


def test_decorator_errors():
    try:

        @initial
        def takes_arg(x):
            pass

    except TypeError as e:
        assert "no arguments" in str(e), e
    else:
        raise AssertionError("hook with a parameter was accepted")
    try:

        @final(sim=False, syn=False)
        def never():
            pass

    except ValueError as e:
        assert "never runs" in str(e), e
    else:
        raise AssertionError("sim=False, syn=False was accepted")


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            print(f"=== {name}", flush=True)
            fn()
    print("hooks_test: all passed")
