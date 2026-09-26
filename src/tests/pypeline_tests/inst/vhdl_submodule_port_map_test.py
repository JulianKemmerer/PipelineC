#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Every submodule instance gets its own port map, with every port, in order.

VHDL.WRITE_LOGIC_ENTITY builds each port map as a list of items joined with
",\n". It used to append each item with a trailing ",\n" and slice the last
one back off the whole entity text. The chain alternates a two-input stateless
call with a stateful one (leading clk + CLOCK_ENABLE items), and each port map
is checked item by item: a stray or missing separator changes the item list.

This checks the text, not the speed.
"""

import os
import re
import sys
import tempfile
from pathlib import Path

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "../../../")
)

import AUTO_PIPELINE
import PY_TO_LOGIC
import VHDL

PORT_MAP_RE = re.compile(
    r"^(\w+) : entity work\.\w+ port map \(\n(.*?)\);\n\n", re.MULTILINE | re.DOTALL
)


def _write_chain(directory: str, count: int) -> str:
    path = Path(directory) / "port_map_chain.py"
    lines = [
        "from pypeline import *",
        "",
        "@hw_func",
        "def step(x: uint16_t, y: uint16_t) -> uint16_t:",
        "    return x + y",
        "",
        "@hw_func",
        "def acc(x: uint16_t) -> uint16_t:",
        "    total: Reg[uint16_t]",
        "    total = total + x",
        "    return total",
        "",
        "@MAIN",
        "def chain(x: uint16_t) -> uint16_t:",
        "    y: uint16_t = x",
    ]
    for _ in range(count // 2):
        lines.append("    y = step(y, x)")
        lines.append("    y = acc(y)")
    lines.append("    return y")
    path.write_text("\n".join(lines) + "\n")
    return str(path)


def _expected_port_map(inst: str) -> list:
    if inst.startswith("step_"):
        return [f"{inst}_x", f"{inst}_y", f"{inst}_return_output"]
    assert inst.startswith("acc_"), inst
    return ["clk", f"{inst}_CLOCK_ENABLE", f"{inst}_x", f"{inst}_return_output"]


def test_every_submodule_port_map_is_exact():
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
    port_maps = PORT_MAP_RE.findall(text)
    assert len(port_maps) == count, len(port_maps)
    for inst, items in port_maps:
        assert items.split(",\n") == _expected_port_map(inst), (inst, items)


if __name__ == "__main__":
    from _test_main import run_module_tests

    run_module_tests()
