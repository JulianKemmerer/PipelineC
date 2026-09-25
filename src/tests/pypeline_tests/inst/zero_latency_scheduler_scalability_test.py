#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Complexity regression for zero-latency pipeline scheduling."""

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "../../../"))

import AUTO_PIPELINE
import C_TO_LOGIC
import PY_TO_LOGIC


def _write_chain(directory: str, count: int) -> str:
    path = Path(directory) / "large_zero_latency_chain.py"
    lines = [
        "from pypeline import *",
        "",
        "@hw_func",
        "def step(x: uint16_t) -> uint16_t:",
        "    return x + 1",
        "",
        "@MAIN",
        "def chain(x: uint16_t) -> uint16_t:",
        "    y: uint16_t = x",
    ]
    lines.extend("    y = step(y)" for _ in range(count))
    lines.append("    return y")
    path.write_text("\n".join(lines) + "\n")
    return str(path)


def test_zero_latency_scheduler_readiness_work_is_linear():
    count = 64
    with tempfile.TemporaryDirectory() as directory:
        state = PY_TO_LOGIC.PARSE_FILE(_write_chain(directory, count))
        root = next(
            name
            for name in state.main_mhz
            if state.LogicInstLookupTable[name].func_name == "chain"
        )
        logic = state.LogicInstLookupTable[root]
        timing = AUTO_PIPELINE.GET_ZERO_ADDED_CLKS_TIMING_PARAMS_LOOKUP(state)
        assert len(logic.submodule_instances) == count

        input_driver_lookups = 0
        original = C_TO_LOGIC.GET_SUBMODULE_INPUT_PORT_DRIVING_WIRE

        def counted(*args, **kwargs):
            nonlocal input_driver_lookups
            input_driver_lookups += 1
            return original(*args, **kwargs)

        C_TO_LOGIC.GET_SUBMODULE_INPUT_PORT_DRIVING_WIRE = counted
        try:
            pipeline_map = AUTO_PIPELINE.GET_PIPELINE_MAP(root, logic, state, timing)
        finally:
            C_TO_LOGIC.GET_SUBMODULE_INPUT_PORT_DRIVING_WIRE = original

    # The worklist discovers prerequisites once and verifies a ready submodule
    # once. The previous repeated-rescan path performs 2080 lookups here.
    assert input_driver_lookups <= 3 * count, input_driver_lookups
    assert pipeline_map.num_stages == 1
    scheduled = sum(
        len(level.submodule_insts)
        for stage in pipeline_map.stage_infos
        for level in stage.submodule_level_infos
    )
    assert scheduled == count, scheduled


if __name__ == "__main__":
    from _test_main import run_module_tests

    run_module_tests()
