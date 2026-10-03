#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Complexity and failure-mode regression for GET_PIPELINE_MAP scheduling.

The scheduler used to rescan every remaining submodule (readiness) and sort
every wire (newly driven outputs) on every logic level: O(levels * N) each.
Both are now worklists: RECORD_DRIVEN_BY wakes waiting submodules, and
submodule outputs are bucketed by the stage their latency elapses. Work is
measured deterministically, not by wall clock:
- input driver lookups (GET_SUBMODULE_INPUT_PORT_DRIVING_WIRE calls) guard
  the readiness worklist,
- total elements handed to sorted() inside AUTO_PIPELINE guard both halves
  (a module global `sorted` shadows the builtin for that module only).
"""

import builtins
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "../../../"))

import AUTO_PIPELINE
import C_TO_LOGIC
import PY_TO_LOGIC

COUNT = 64
DELAY_EVERY = 8  # every 8th chain element is a @pipeline_latency(1) delay


def _parse_chain(directory: str, name: str, count: int, delay_every=None):
    path = Path(directory) / f"{name}.py"
    lines = [
        "from pypeline import *",
        "",
        "@hw_func",
        "def step(x: uint16_t) -> uint16_t:",
        "    return x + 1",
        "",
        "@pipeline_latency(1)",
        "def delay(x: uint16_t) -> uint16_t:",
        "    saved: Reg[uint16_t]",
        "    result: uint16_t = saved",
        "    saved = x",
        "    return result",
        "",
        "@MAIN",
        "def chain(x: uint16_t) -> uint16_t:",
        "    y: uint16_t = x",
    ]
    for i in range(count):
        if delay_every is not None and i % delay_every == delay_every - 1:
            lines.append("    y = delay(y)")
        else:
            lines.append("    y = step(y)")
    lines.append("    return y")
    path.write_text("\n".join(lines) + "\n")
    state = PY_TO_LOGIC.PARSE_FILE(str(path))
    root = next(
        inst
        for inst in state.main_mhz
        if state.LogicInstLookupTable[inst].func_name == "chain"
    )
    logic = state.LogicInstLookupTable[root]
    timing = AUTO_PIPELINE.GET_ZERO_ADDED_CLKS_TIMING_PARAMS_LOOKUP(state)
    assert len(logic.submodule_instances) == count
    return state, root, logic, timing


def _counted_pipeline_map(root, logic, state, timing):
    """GET_PIPELINE_MAP plus (input driver lookups, elements sorted)."""
    counts = {"lookups": 0, "sorted": 0}
    original_lookup = C_TO_LOGIC.GET_SUBMODULE_INPUT_PORT_DRIVING_WIRE

    def counted_lookup(*args, **kwargs):
        counts["lookups"] += 1
        return original_lookup(*args, **kwargs)

    def counted_sorted(iterable, *args, **kwargs):
        rv = builtins.sorted(iterable, *args, **kwargs)
        counts["sorted"] += len(rv)
        return rv

    C_TO_LOGIC.GET_SUBMODULE_INPUT_PORT_DRIVING_WIRE = counted_lookup
    AUTO_PIPELINE.sorted = counted_sorted
    try:
        pipeline_map = AUTO_PIPELINE.GET_PIPELINE_MAP(root, logic, state, timing)
    finally:
        C_TO_LOGIC.GET_SUBMODULE_INPUT_PORT_DRIVING_WIRE = original_lookup
        del AUTO_PIPELINE.sorted
    return pipeline_map, counts["lookups"], counts["sorted"]


def _scheduled_count(pipeline_map):
    return sum(
        len(level.submodule_insts)
        for stage in pipeline_map.stage_infos
        for level in stage.submodule_level_infos
    )


def test_zero_latency_chain_scheduling_work_is_linear():
    with tempfile.TemporaryDirectory() as directory:
        state, root, logic, timing = _parse_chain(directory, "zero_latency_chain", COUNT)
        pipeline_map, lookups, sorted_elements = _counted_pipeline_map(
            root, logic, state, timing
        )
    # Prerequisites are looked up once to build the worklist and once to
    # verify each ready submodule (2N). Rescanning took 2080 at N=64.
    assert lookups <= 3 * COUNT, lookups
    # ~9 per element now. Rescanning sorted 174 per element at N=64 (654 at
    # N=256); reverting only the output-wire buckets still sorts ~143.
    assert sorted_elements <= 16 * COUNT, sorted_elements
    assert pipeline_map.num_stages == 1
    assert _scheduled_count(pipeline_map) == COUNT


def test_latency_chain_scheduling_work_is_linear():
    # Nonzero latency submodules used to force the rescanning scheduler for
    # the whole container (pipelined builds, every sweep iteration).
    with tempfile.TemporaryDirectory() as directory:
        state, root, logic, timing = _parse_chain(
            directory, "latency_chain", COUNT, delay_every=DELAY_EVERY
        )
        pipeline_map, lookups, sorted_elements = _counted_pipeline_map(
            root, logic, state, timing
        )
    assert lookups <= 3 * COUNT, lookups
    # ~10 per element now. Rescanning sorted 204 per element at N=64.
    assert sorted_elements <= 16 * COUNT, sorted_elements
    # One extra stage per delay element
    assert pipeline_map.num_stages == 1 + COUNT // DELAY_EVERY, pipeline_map.num_stages
    assert _scheduled_count(pipeline_map) == COUNT


def test_stuck_graph_reports_waiting_submodule():
    # A submodule input whose driver is never driven can never be scheduled.
    # That must fail right away naming the submodule and wire, not spin to
    # the 5000 stage limit and sys.exit.
    with tempfile.TemporaryDirectory() as directory:
        state, root, logic, timing = _parse_chain(directory, "stuck_chain", 8)
        stuck_submodule = sorted(logic.submodule_instances)[3]
        stuck_input = stuck_submodule + C_TO_LOGIC.SUBMODULE_MARKER + "x"
        assert stuck_input in logic.wire_driven_by, stuck_input
        logic.wire_driven_by[stuck_input] = "never_driven_wire"
        try:
            AUTO_PIPELINE.GET_PIPELINE_MAP(root, logic, state, timing)
        except BaseException as e:  # SystemExit would mean the old spin
            assert type(e) is Exception, repr(e)
            message = str(e)
        else:
            raise AssertionError("stuck pipeline map did not raise")
    assert "no progress possible" in message, message
    assert f"submodule {stuck_submodule} waits on: never_driven_wire" in message, message


if __name__ == "__main__":
    from _test_main import run_module_tests

    run_module_tests()
