#!/usr/bin/env python3
"""The sweep reports a failing reset-distribution path instead of pipelining
it (in-process, no tool).

- SWEEP.RESET_DISTRIBUTION_PATH on a parsed design and timing-report names
  built from its entity names: a path from the MAIN driving a reset Wire, or
  from a reset pin (also as the start_port_name of a path with no start
  register), to a MAIN that resets with it is the reset's; a path
  inside one MAIN, into a MAIN without that reset, or from a source MAIN that
  also drives data the reset MAIN reads, directly or through another MAIN's
  wires, is not.
- A scripted sweep (sweep_cross_main_test's harness) whose failing path is a
  reset's stops the reset MAIN's plan at once, never pipelines it, and names
  the reset in the timing failures; the same path not classified as a
  reset's is pipelined (control). A reset path in an iteration worse than an
  earlier one of the plan (SWEEP.RESET_PATH_STOPS_PLAN) does not stop it.
"""

import contextlib
import io
import os
import sys
import tempfile
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "../../.."))
import AUTO_PIPELINE
import PY_TO_LOGIC
import SWEEP
import VHDL
from sweep_cross_main_test import _locked, _scripted_run, _scripted_state

REPO_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..")

DESIGN = """
import sys
sys.path.insert(0, {repo_root!r})
from pypeline import *

gen_rst: Wire[uint1_t] = make_reset()
pin_rst: Input[uint1_t] = make_reset()
t_out: Wire[uint8_t]
fwd_out: Wire[uint8_t]
clk = make_clock(100.0)

@MAIN(clk)
def rst_gen():
    t: Reg[uint8_t]
    gen_rst = t == 3
    t_out = t
    t += 1

@MAIN(clk, reset=gen_rst, reset_registers="all")
def dut() -> uint8_t:
    n: Reg[uint8_t]
    n += {dut_step}
    return n

@MAIN(clk, reset=pin_rst, reset_registers="all")
def pinned() -> uint8_t:
    n: Reg[uint8_t]
    n += 1
    return n

@MAIN(clk)
def checker() -> uint8_t:
    return t_out

@MAIN(clk)
def forwarder():
    fwd_out = t_out + 1
"""


def _parse(dut_step):
    with tempfile.TemporaryDirectory(prefix="reset_sweep_path_test_") as tmpdir:
        path = os.path.join(tmpdir, "design.py")
        with open(path, "w") as f:
            f.write(DESIGN.format(repo_root=os.path.abspath(REPO_ROOT), dut_step=dut_step))
        with contextlib.redirect_stdout(io.StringIO()):
            state = PY_TO_LOGIC.PARSE_FILE(path)
    timing = AUTO_PIPELINE.GET_ZERO_ADDED_CLKS_TIMING_PARAMS_LOOKUP(state)
    params = SimpleNamespace(TimingParamsLookupTable=timing)
    entity = {
        m: VHDL.GET_ENTITY_NAME(m, state.LogicInstLookupTable[m], timing, state)
        for m in state.main_mhz
    }
    return state, params, entity


def _report(start, end, start_port=None):
    report = SimpleNamespace(start_reg_name=start, end_reg_name=end, netlist_resources=set())
    if start_port is not None:
        report.start_port_name = start_port
    return report


def test_reset_paths_are_classified():
    state, params, e = _parse("1")

    def classify(start, end):
        return SWEEP.RESET_DISTRIBUTION_PATH(_report(start, end), state, params)

    # The reset Wire's fanout, in a tool's case and hierarchy separators
    assert classify(f"{e['rst_gen']}/t_reg[0]", f"{e['dut']}/n_reg[3]") == (
        "gen_rst", "rst_gen", "dut")
    assert classify(f"{e['rst_gen']}.t_reg_0".lower(), f"{e['dut']}.n_reg_3".lower()) == (
        "gen_rst", "rst_gen", "dut")
    # The reset pin, as the port or its input buffer
    assert classify("pin_rst", f"{e['pinned']}/n_reg[0]") == ("pin_rst", None, "pinned")
    assert classify("pin_rst_IBUF_inst/O", f"{e['pinned']}/n_reg[0]") == (
        "pin_rst", None, "pinned")
    # The reset pin as the input port sky130 STA names for a path with no
    # start register
    report = _report(None, f"{e['pinned']}/n_reg[0]", start_port="pin_rst")
    assert SWEEP.RESET_DISTRIBUTION_PATH(report, state, params) == ("pin_rst", None, "pinned")
    report = _report(None, f"{e['pinned']}/n_reg[0]", start_port="x[0]")
    assert SWEEP.RESET_DISTRIBUTION_PATH(report, state, params) is None
    # Not a reset's path
    assert classify(f"{e['dut']}/n_reg[0]", f"{e['dut']}/n_reg[3]") is None
    assert classify(f"{e['rst_gen']}/t_reg[0]", f"{e['checker']}/out_reg[0]") is None
    assert classify("pin_rst_count_reg/Q", f"{e['pinned']}/n_reg[0]") is None
    assert classify("pin_rst", f"{e['dut']}/n_reg[0]") is None  # dut resets with gen_rst
    assert classify(f"{e['rst_gen']}/t_reg[0]", None) is None


def test_source_driving_data_is_not_classified():
    # dut also reads t_out from rst_gen: the path could be that data's
    state, params, e = _parse("t_out")
    report = _report(f"{e['rst_gen']}/t_reg[0]", f"{e['dut']}/n_reg[3]")
    assert SWEEP.RESET_DISTRIBUTION_PATH(report, state, params) is None


def test_source_data_through_another_main_is_not_classified():
    # dut reads fwd_out, which forwarder makes from rst_gen's t_out in the
    # same cycle: the path could be that data's
    state, params, e = _parse("fwd_out")
    report = _report(f"{e['rst_gen']}/t_reg[0]", f"{e['dut']}/n_reg[3]")
    assert SWEEP.RESET_DISTRIBUTION_PATH(report, state, params) is None


def _reset_path(delay):
    """A path from the planless 'fixture' (the reset's source) into 'core'."""
    return SimpleNamespace(
        start_reg_name="fixture/src/launch[0]",
        end_reg_name="core/logic/capture[0]",
        path_group="clk_shared",
        path_delay_ns=delay,
        slack_ns=10.0 - delay,
        requirement_ns=10.0,
        source_ns_per_clock=10.0,
        netlist_resources=set(),
        logic_levels=1,
    )


def _sweep(classified):
    ps = _scripted_state(["core"])

    def rule(ps_, params):
        # Meets once core's helper is pipelined: only the control gets there
        return [_reset_path(5.0 if _locked(params, "core") else 12.0)]

    def classify(path_report, ps_, params):
        if classified and path_report.start_reg_name.startswith("fixture/"):
            return ("rst", "fixture", "core")
        return None

    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        result = _scripted_run(
            ps, rule, ["core"],
            [
                (SWEEP, "RESET_DISTRIBUTION_PATH", classify),
                (SWEEP, "RESOLVE_PIPELINABLE_HOTSPOT", lambda p, plan, ps_: ("h_core", None, "")),
            ],
        )
    return result, out.getvalue()


def test_sweep_stops_on_a_reset_path():
    (result, history, minis, locked, backend), printed = _sweep(classified=True)
    assert minis == [] and locked == {"core": 0}, (minis, locked)
    assert len(backend.calls) == 1, backend.calls
    actions = [r["action"] for r in history["core"]["iterations"]]
    assert actions == ["stop(reset distribution)"], actions
    failures = {f[0]: f[3] for f in result.sweep_timing_failures}
    reason = "reset_distribution: reset rst from fixture, which drives it, to the registers it resets in core"
    assert failures == {"core": reason, "fixture": reason}, failures
    assert printed.count("is the distribution of reset rst") == 1, printed


def test_unclassified_path_is_pipelined():
    (result, history, minis, locked, backend), _ = _sweep(classified=False)
    assert minis == ["h_core"] and locked == {"core": 1}, (minis, locked)
    assert "core" not in {f[0] for f in result.sweep_timing_failures}, result.sweep_timing_failures


def test_reset_path_stops_a_plan_only_at_its_best():
    def plan(*achieved):
        return SimpleNamespace(history=[{"achieved_mhz": a} for a in achieved])

    assert SWEEP.RESET_PATH_STOPS_PLAN(plan(), 38.9)
    assert SWEEP.RESET_PATH_STOPS_PLAN(plan(30.0, 38.9), 38.9)
    # An earlier, better iteration had fewer registers on the reset
    assert not SWEEP.RESET_PATH_STOPS_PLAN(plan(73.0, 50.0), 38.9)


def test_reset_path_after_a_better_iteration_keeps_the_feedback():
    """core first fails on a data path; the registers its feedback adds give
    the reset a longer fanout, a worse result: no stop, that iteration gets
    the normal feedback (the helper's mini-sweep)."""
    ps = _scripted_state(["core"])
    calls = []

    def rule(ps_, params):
        calls.append(1)
        if len(calls) == 1:
            data = _reset_path(12.0)
            data.start_reg_name = "core/src/launch[0]"
            return [data]
        return [_reset_path(15.0)]

    def classify(path_report, ps_, params):
        if path_report.start_reg_name.startswith("fixture/"):
            return ("rst", "fixture", "core")
        return None

    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        result, history, minis, locked, backend = _scripted_run(
            ps, rule, ["core"],
            [
                (SWEEP, "RESET_DISTRIBUTION_PATH", classify),
                (SWEEP, "RESOLVE_PIPELINABLE_HOTSPOT", lambda p, plan, ps_: ("h_core", None, "")),
            ],
        )
    actions = [r["action"] for r in history["core"]["iterations"]]
    assert len(calls) == 2 and actions[1] == "minisweep(h_core)", (calls, actions)
    assert "stop(reset distribution)" not in actions, actions


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"{name} PASS")
    print("reset_sweep_path_test: all PASS")
