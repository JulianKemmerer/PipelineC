#!/usr/bin/env python3
"""Known issue: a path inside an imported helper is attributed to its caller.

A call is labeled with the name it is called by: an imported function's bare
name (`square`), while its func_name is module-prefixed
(`imported_math_square`). Attribution (SWEEP.RANK_PATH_FUNC_CANDIDATES)
looks for func names inside register names, so it never finds the helper.
Only an AUTO_PIPELINE region root is also found by its instance's label path
(#387), so a path inside the helper goes to the region root around it: the
sweep mini-sweeps the whole region instead of the repeated helper. Seen on
WireGuard's Poly1305 body, whose feedback_mul_add_mod (an imported alias of
poly1305_math_residue_mul_add_mod_inferred) is never attributed.

In process, no synthesis tool: elaborate a two-module design whose region
root calls the imported helper twice, build a register path inside the first
call from the real emitted VHDL label path (SYN._VHDL_INSTANCE_TRIE) and ask
SWEEP.RESOLVE_PIPELINABLE_HOTSPOT for the function.

Exits 1 while the bug is present (registered expect_fail in
known_issues_tests.py), 0 once the helper is attributed.
"""
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", ".."))

import AUTO_PIPELINE  # noqa: E402
import LOGIC  # noqa: E402
import PY_TO_LOGIC  # noqa: E402
import SWEEP  # noqa: E402
import SYN  # noqa: E402
import pypeline  # noqa: E402


def label_path(node, inst, labels=()):
    """The VHDL instance labels from a MAIN down to inst, or None."""
    if node.get(SYN._PATH_TRIE_INST) == inst:
        return list(labels)
    for label, child in node.items():
        if label != SYN._PATH_TRIE_INST:
            found = label_path(child, inst, labels + (label,))
            if found is not None:
                return found
    return None


def main():
    with tempfile.TemporaryDirectory(prefix="imported_helper_") as tmp:
        path = Path(tmp)
        (path / "imported_math.py").write_text(
            "from pypeline import hw_func, uint8_t\n"
            "@hw_func\ndef square(x: uint8_t) -> uint8_t:\n    return x * x\n"
        )
        design = path / "top.py"
        design.write_text(
            "from pypeline import AUTO_PIPELINE, MAIN, hw_func, uint8_t\n"
            "from imported_math import square\n"
            "@hw_func\ndef outer(x: uint8_t) -> uint8_t:\n"
            "    return square(square(x) + 1)\n"
            "TAG = AUTO_PIPELINE(outer, start_latency=1)\n"
            "@MAIN(50.0)\ndef top(x: uint8_t) -> uint8_t:\n    return TAG(x)\n"
        )
        SYN.SYN_OUTPUT_DIRECTORY = str(path / "out")
        os.makedirs(SYN.SYN_OUTPUT_DIRECTORY)
        sys.path.insert(0, tmp)
        pypeline.SET_AUTO_PIPELINE_BUILD_MODE("sweep")
        try:
            ps = PY_TO_LOGIC.PARSE_FILE(str(design))
            (region,) = AUTO_PIPELINE.COLLECT_AUTO_PIPELINE_REGIONS(ps)
            helper = "imported_math_square"
            helper_inst = sorted(
                inst
                for inst in ps.FuncToInstances[helper]
                if inst.startswith(region.inst + LOGIC.SUBMODULE_MARKER)
            )[0]
            plan = SWEEP.MainSweepPlan("top", 50.0)
            plan.subtrees = ["top"]
            plan.regions = [region]
            plan.landscapes = {}
            region.landscape = SWEEP.BUILD_SLICE_LANDSCAPE(region.inst, ps, {
                inst: AUTO_PIPELINE.TimingParams(inst, logic)
                for inst, logic in ps.LogicInstLookupTable.items()
            }, {})
            labels = label_path(SYN._VHDL_INSTANCE_TRIE(ps)["top"], helper_inst)
            assert labels, f"no emitted instance path for {helper_inst}"
            prefix = "top_0CLK_12345678/" + "/".join(labels)
            report = SimpleNamespace(
                start_reg_name=prefix + "/REG_STAGE0_reg",
                end_reg_name=prefix + "/REG_STAGE1_reg",
                netlist_resources=set(),
            )
            hotspot, reason, _stage = SWEEP.RESOLVE_PIPELINABLE_HOTSPOT(report, plan, ps)
            print(
                f"Path inside {helper_inst}: {prefix}; hotspot={hotspot}; reason={reason}"
            )
            if hotspot != helper:
                print(f"FAIL: the path was attributed to {hotspot}, not {helper}")
                return 1
        finally:
            pypeline.SET_AUTO_PIPELINE_BUILD_MODE(None)
            sys.path.remove(tmp)
    print("PASS: the imported helper is attributed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
