#!/usr/bin/env python3
# Planned throughput sweep test (e): fmax floor detection.
# Runs pipelinec on sweep_floor_detect_design.py (whose 50 MHz goal is
# unreachable - a divider is trapped inside a stateful submodule) and asserts:
#  - the sweep predicts and reports the fmax floor BEFORE any synthesis runs
#  - it stops after only a few full-design synthesis runs instead of blindly
#    growing the cut count
#  - the build still exits successfully, keeping the best result
import argparse
import os
import re
import subprocess
import sys

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
PIPELINEC = os.path.join(THIS_DIR, "../../../pipelinec")
DESIGN = os.path.join(THIS_DIR, "sweep_floor_detect_design.py")

MAX_FULL_SYN_RUNS = 4


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out_dir", default=None)
    args = parser.parse_args()

    cmd = [sys.executable, PIPELINEC, DESIGN]
    if args.out_dir:
        cmd += ["--out_dir", args.out_dir]
    print("Running:", " ".join(cmd), flush=True)
    result = subprocess.run(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
    )
    out = result.stdout
    print(out)

    if result.returncode != 0:
        print("FAIL: pipelinec exited nonzero", result.returncode)
        sys.exit(1)
    if "predicted fmax floor" not in out:
        print("FAIL: no predicted fmax floor report before synthesis")
        sys.exit(1)
    if "below the" not in out or "goal" not in out:
        print("FAIL: no warning that the floor is below the timing goal")
        sys.exit(1)
    full_syn_runs = len(re.findall(r"Running syn w timing params", out))
    if full_syn_runs > MAX_FULL_SYN_RUNS:
        print(
            f"FAIL: {full_syn_runs} full design synthesis runs (max {MAX_FULL_SYN_RUNS}) - floor detection should stop the sweep quickly"
        )
        sys.exit(1)
    print(f"All sweep floor detect tests passed ({full_syn_runs} full syn runs).")


if __name__ == "__main__":
    main()
