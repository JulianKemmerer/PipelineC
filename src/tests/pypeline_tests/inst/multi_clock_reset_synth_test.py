"""Synthesize multi_clock_reset_design.py (two clocks, each with its own
reset, per-policy entities of one function, a reset global FIFO and global
instance) with --comb on one tool, and check that both clocks meet timing
and that the entities with a RESET port were synthesized.

Run: python3 multi_clock_reset_synth_test.py --syn_tool TOOL --out_dir DIR
"""

import argparse
import os
import re
import subprocess
import sys

INST_DIR = os.path.dirname(os.path.abspath(__file__))
PYPELINEC = os.path.join(INST_DIR, "..", "..", "..", "pypelinec")
DESIGN = os.path.join(INST_DIR, "multi_clock_reset_design.py")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--syn_tool", required=True)
    parser.add_argument("--out_dir", required=True)
    args = parser.parse_args()
    build_dir = os.path.join(args.out_dir, "build")
    proc = subprocess.run(
        [sys.executable, PYPELINEC, DESIGN, "--comb", "--syn_tool", args.syn_tool,
         "--out_dir", build_dir],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    print(proc.stdout)
    assert proc.returncode == 0, f"build failed ({proc.returncode})"
    assert "TIMING NOT MET" not in proc.stdout, "a clock missed timing"
    # Both bump() variants and the reset FIFO were in the synthesized design
    names = os.listdir(os.path.join(build_dir, "src", "tests", "pypeline_tests", "inst",
                                    "multi_clock_reset_design.py", "bump"))
    assert len([n for n in names if n.endswith(".vhd") and "_top" not in n]) == 2, names
    fifo = open(os.path.join(build_dir, "built_in", "pipelinec_fifo_fwft.vhd")).read()
    assert re.search(r"rst\s*:\s*in std_logic", fifo), "FIFO primitive without its reset"
    print("multi_clock_reset_synth_test: all PASS")


if __name__ == "__main__":
    main()
