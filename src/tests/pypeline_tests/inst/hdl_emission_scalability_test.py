#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Regression coverage for large-design HDL metadata and VHDL emission."""

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "../../../"))

import AUTO_PIPELINE
import PY_TO_LOGIC
import VHDL


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


def test_large_zero_latency_vhdl_emits_every_submodule():
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

        out = Path(directory) / "vhdl"
        VHDL.WRITE_LOGIC_ENTITY(root, logic, str(out), state, timing)
        files = list(out.glob("*.vhd"))
        assert len(files) == 1, files
        text = files[0].read_text()

    assert text.count("clocks latency") == count
    assert text.count(" port map (\n") == count


if __name__ == "__main__":
    from _test_main import run_module_tests

    run_module_tests()
