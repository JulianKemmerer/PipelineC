#!/usr/bin/env python3
# Planned throughput sweep test (e): fmax floor detection.
# Runs pypelinec on sweep_floor_detect_design.py (whose 50 MHz goal is
# unreachable - a divider is trapped inside a stateful submodule) and asserts:
#  - the sweep predicts and reports the fmax floor BEFORE any synthesis runs
#  - it stops after only a few full-design synthesis runs instead of blindly
#    growing the cut count
#  - the build FAILS with a non zero exit + TIMING NOT MET error block
#    (results still written for debugging first)
import argparse
import os
import re
import subprocess
import sys

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
PYPELINEC = os.path.join(THIS_DIR, "../../../pypelinec")
DESIGN = os.path.join(THIS_DIR, "sweep_floor_detect_design.py")

# Raised from 4 -- sweep_floor_detect_design.py's soft comparator (from the
# soft-operator-library default flip, see include/pypeline/operators/) has a
# hierarchical, multi-submodule delay whose bottom-up *estimate* is
# measurably less accurate than a flat built-in op's, costing one extra
# "estimate was wrong -> resynthesize for real -> replan" cycle (2 extra
# full-design runs) before the sweep locks onto the true floor. The floor
# is still detected and the sweep still stops promptly relative to that --
# this just accounts for the soft comparator's estimation-accuracy cost.
# Accepted as a documented tradeoff; revisit only if this (or the wireguard
# build) shows it actually matters.
MAX_FULL_SYN_RUNS = 6


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out_dir", default=None)
    args = parser.parse_args()

    cmd = [sys.executable, PYPELINEC, DESIGN]
    if args.out_dir:
        cmd += ["--out_dir", args.out_dir]
    print("Running:", " ".join(cmd), flush=True)
    result = subprocess.run(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
    )
    out = result.stdout
    print(out)

    # Timing is NOT met by design here: the build must FAIL (non zero exit)
    # so users cannot miss it - but only after writing results for debugging
    if result.returncode == 0:
        print("FAIL: pypelinec exited zero despite unmet timing goal")
        sys.exit(1)
    if "ERROR: TIMING NOT MET" not in out:
        print("FAIL: no TIMING NOT MET error block")
        sys.exit(1)
    if "Writing Results of Throughput Sweep" not in out:
        print("FAIL: results were not written before failing")
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
