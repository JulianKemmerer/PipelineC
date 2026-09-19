#!/usr/bin/env python3
# C frontend `#pragma AUTOPIPELINE N` = fixed latency N, honored by a --comb
# build: the tagged call's entity must be written with exactly N clocks of
# latency, and the fixed-latency region report must say so.
import argparse
import glob
import os
import re
import subprocess
import sys

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
PYPELINEC = os.path.join(THIS_DIR, "../../../pypelinec")
DESIGN = os.path.join(THIS_DIR, "auto_pipeline_c_pragma_design.c")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out_dir", default=None)
    args = parser.parse_args()
    cmd = [sys.executable, PYPELINEC, DESIGN, "--comb", "--syn_tool", "device_models"]
    if args.out_dir:
        cmd += ["--out_dir", args.out_dir]
    print("Running:", " ".join(cmd), flush=True)
    result = subprocess.run(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
    )
    out = result.stdout
    print(out)
    if result.returncode != 0:
        print("FAIL: pypelinec exited nonzero", result.returncode)
        sys.exit(1)
    if not re.search(
        r"^AUTO_PIPELINE c_pragma_core \(latency=2\): 2 clk\(s\) built", out, re.M
    ):
        print("FAIL: fixed #pragma AUTOPIPELINE 2 region not built with 2 clks")
        sys.exit(1)
    if args.out_dir:
        entities = glob.glob(
            os.path.join(args.out_dir, "**", "c_pragma_core_2CLK_*.vhd"), recursive=True
        )
        if not entities:
            print("FAIL: no c_pragma_core_2CLK_*.vhd entity written")
            sys.exit(1)
    print("All C #pragma AUTOPIPELINE N tests passed.")


if __name__ == "__main__":
    main()
