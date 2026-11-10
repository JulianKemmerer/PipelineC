#!/usr/bin/env python3
"""AUTO_PIPELINE(imported_f) keeps the sweep's path attribution (#387).

The call's instance is labeled with the bare Python name (`square`), while the
callee's func_name is module-prefixed (`imported_math_square`). Attribution
(SWEEP.RANK_PATH_FUNC_CANDIDATES) looks for func names inside register names,
which matches nothing here; a region root is also found by its instance's
exact label path (SYN.INSTANCE_LABEL_POSITION). Before that, the sweep fell
back to blind global replans: WireGuard tagging poly1305_body directly built
bodies 6/12 deep, over DSP capacity, instead of 8/8 through a wrapper.
region_root_minisweep_test.py checks the sweep then mini-sweeps the root.

In process, no synthesis tool: elaborate a two-module design, build a register
path from the real emitted VHDL label path (SYN._VHDL_INSTANCE_TRIE) and ask
SWEEP.RESOLVE_PIPELINABLE_HOTSPOT for the region's function. The same path in
sky130 STA's flattened form ($flatten\\main.\\label.) must attribute the same.

Exits 0 when the region root is attributed, 1 otherwise.
"""
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", ".."))

import AUTO_PIPELINE  # noqa: E402
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
    with tempfile.TemporaryDirectory(prefix="imported_ap_") as tmp:
        path = Path(tmp)
        (path / "imported_math.py").write_text(
            "from pypeline import hw_func, uint8_t\n"
            "@hw_func\ndef square(x: uint8_t) -> uint8_t:\n    return x * x\n"
        )
        design = path / "top.py"
        design.write_text(
            "from pypeline import AUTO_PIPELINE, MAIN, uint8_t\n"
            "from imported_math import square\n"
            "TAG = AUTO_PIPELINE(square, start_latency=1)\n"
            "@MAIN(50.0)\ndef top(x: uint8_t) -> uint8_t:\n    return TAG(x)\n"
        )
        SYN.SYN_OUTPUT_DIRECTORY = str(path / "out")
        os.makedirs(SYN.SYN_OUTPUT_DIRECTORY)
        sys.path.insert(0, tmp)
        pypeline.SET_AUTO_PIPELINE_BUILD_MODE("sweep")
        try:
            ps = PY_TO_LOGIC.PARSE_FILE(str(design))
            (region,) = AUTO_PIPELINE.COLLECT_AUTO_PIPELINE_REGIONS(ps)
            plan = SWEEP.MainSweepPlan("top", 50.0)
            plan.subtrees = ["top"]
            plan.regions = [region]
            labels = label_path(SYN._VHDL_INSTANCE_TRIE(ps)["top"], region.inst)
            assert labels, f"no emitted instance path for {region.inst}"
            prefix = "top_0CLK_12345678/" + "/".join(labels)
            report = SimpleNamespace(
                start_reg_name=prefix + "/REG_STAGE0_reg",
                end_reg_name=prefix + "/REG_STAGE1_reg",
                netlist_resources=set(),
            )
            hotspot, reason, _stage = SWEEP.RESOLVE_PIPELINABLE_HOTSPOT(report, plan, ps)
            print(
                f"Real VHDL path: {prefix}; region={region.func_name}; "
                f"hotspot={hotspot}; reason={reason}"
            )
            if hotspot != region.func_name:
                print(f"FAIL: the path was attributed to {hotspot}, not {region.func_name}")
                return 1
            basis = SWEEP.ATTRIBUTION_BASIS(report, hotspot, plan, ps)
            if basis != "inside":
                print(f"FAIL: the attribution basis is {basis}, not inside")
                return 1
            # sky130 STA flattens the hierarchy into escaped identifiers
            flat = "$flatten\\top_0clk_12345678." + "".join(
                "\\" + label + "." for label in labels
            )
            flat_report = SimpleNamespace(
                start_reg_name=flat + "$auto$ff.cc:266:slice$1",
                end_reg_name=flat + "$auto$ff.cc:266:slice$2",
                netlist_resources=set(),
            )
            flat_hotspot, _reason, _stage = SWEEP.RESOLVE_PIPELINABLE_HOTSPOT(
                flat_report, plan, ps
            )
            print(f"Flattened path: {flat_report.start_reg_name}; hotspot={flat_hotspot}")
            if flat_hotspot != region.func_name:
                print(f"FAIL: the flattened path was attributed to {flat_hotspot}")
                return 1
        finally:
            pypeline.SET_AUTO_PIPELINE_BUILD_MODE(None)
            sys.path.remove(tmp)
    print("PASS: the imported region root is attributed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
