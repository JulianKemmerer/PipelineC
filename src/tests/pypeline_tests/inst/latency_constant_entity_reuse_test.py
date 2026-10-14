#!/usr/bin/env python3
"""Known issue: a pipelined top-level function that folds a value derived from an
AUTO_PIPELINE's .latency keeps pass 1's entity file in pin-and-confirm pass 2.

Within one build, AUTO_PIPELINE.WRITE_ALL_NON_ZERO_CLK_VHDL_FILES renders each
entity file once (_NON_ZERO_CLK_FILES_WRITTEN), trusting that an entity name
fixes its content. A top-level function's key is its module and name, and its
timing hash covers its children's names and slices, so when pass 2 replays pass
1's slices and the folded constant keeps its bit width (.latency 2 -> 3 here),
the name is unchanged while the body is not: pass 2 keeps the file holding
pass 1's constant. The final VHDL and its synthesis then build the stale body.

This test elaborates latency_constant_entity_reuse_design.py twice in one
process, with the harvested latency 2 and then 3, gives folds_latency's
multiplier the same slice both times, and writes the pipelined entities.
Exits 1 while pass 2's file still holds the constant 2 (registered expect_fail
in known_issues_tests.py), 0 once it holds 3.
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", ".."))

import AUTO_PIPELINE  # noqa: E402
import LOGIC
import PY_TO_LOGIC  # noqa: E402
import SYN  # noqa: E402
import VHDL  # noqa: E402
import pypeline  # noqa: E402

DESIGN = os.path.join(HERE, "latency_constant_entity_reuse_design.py")


def main():
    out_dir = sys.argv[sys.argv.index("--out_dir") + 1]
    SYN.SYN_OUTPUT_DIRECTORY = os.path.abspath(out_dir)
    SYN.TOP_LEVEL_MODULE = "top"
    os.makedirs(SYN.SYN_OUTPUT_DIRECTORY, exist_ok=True)
    pypeline.SET_AUTO_PIPELINE_BUILD_MODE("sweep")
    marker = LOGIC.SUBMODULE_MARKER
    files = []
    for latency in (2, 3):
        pypeline.SET_AUTO_PIPELINE_LATENCY_CACHE({"core": latency})
        parser_state = PY_TO_LOGIC.PARSE_FILE(DESIGN)
        AUTO_PIPELINE.WRITE_0_ADDED_CLKS_INIT_FILES(parser_state)
        parser_state = SYN.ADD_PATH_DELAY_TO_LOOKUP(parser_state)
        tpl = AUTO_PIPELINE.GET_ZERO_ADDED_CLKS_TIMING_PARAMS_LOOKUP(parser_state)
        (inst,) = [
            i for i, l in parser_state.LogicInstLookupTable.items()
            if l.func_name == "folds_latency"
        ]
        (mult,) = [
            i for i, l in parser_state.LogicInstLookupTable.items()
            if i.startswith(inst + marker) and "MULT" in l.func_name
        ]
        tpl[mult].SET_SLICES([0.5])
        for params in tpl.values():
            params.INVALIDATE_CACHE()
        AUTO_PIPELINE.WRITE_ALL_NON_ZERO_CLK_VHDL_FILES(tpl, parser_state, extra_insts={inst})
        logic = parser_state.LogicInstLookupTable[inst]
        name = VHDL.GET_ENTITY_NAME(inst, logic, tpl, parser_state)
        path = os.path.join(SYN.GET_OUTPUT_DIRECTORY(logic), name + ".vhd")
        with open(path) as f:
            constants = re.findall(r"to_unsigned\((\d+), 2\)", f.read())
        print(f".latency {latency}: {name}.vhd holds constant(s) {constants}", flush=True)
        files.append((name, constants))
    (name2, _), (name3, constants3) = files
    if name2 == name3 and "3" not in constants3:
        print("FAIL: pass 2 kept pass 1's entity file (constant 2) for a body that folds 3")
        return 1
    print("PASS: pass 2's entity holds its own constant")
    return 0


if __name__ == "__main__":
    sys.exit(main())
