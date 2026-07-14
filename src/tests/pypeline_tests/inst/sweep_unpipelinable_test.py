#!/usr/bin/env python3
# Planned throughput sweep test (f): unpipelinable design messaging.
# Runs pipelinec on sweep_unpipelinable_design.py (a stateful MAIN with no
# AUTOPIPELINE regions and an unreachable 100 MHz goal) and asserts the tool
# tells the user PLAINLY that autopipelining cannot help:
#  - at planning time (main has a goal but nothing cuttable)
#  - when the timing report fails (named main + guidance)
#  - without burning full-design synthesis runs on a hopeless sweep
#  - and FAILS with a non zero exit + TIMING NOT MET error block
#    (results still written for debugging first)
import argparse
import os
import re
import subprocess
import sys

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
PIPELINEC = os.path.join(THIS_DIR, "../../../pipelinec")
DESIGN = os.path.join(THIS_DIR, "sweep_unpipelinable_design.py")

MAX_FULL_SYN_RUNS = 1


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

    # Timing is NOT met by design here: the build must FAIL (non zero exit)
    # so users cannot miss it - but only after writing results for debugging
    if result.returncode == 0:
        print("FAIL: pipelinec exited zero despite unmet timing goal")
        sys.exit(1)
    if "ERROR: TIMING NOT MET" not in out:
        print("FAIL: no TIMING NOT MET error block")
        sys.exit(1)
    if "Writing Results of Throughput Sweep" not in out:
        print("FAIL: results were not written before failing")
        sys.exit(1)
    if "contains nothing autopipelining can help" not in out:
        print("FAIL: no planning-time warning that autopipelining cannot help")
        sys.exit(1)
    if "autopipelining cannot help it" not in out:
        print("FAIL: no failing-timing warning naming the main + guidance")
        sys.exit(1)
    full_syn_runs = len(re.findall(r"Running syn w timing params", out))
    if full_syn_runs > MAX_FULL_SYN_RUNS:
        print(
            f"FAIL: {full_syn_runs} full design synthesis runs (max {MAX_FULL_SYN_RUNS}) - nothing to sweep, should characterize once and stop"
        )
        sys.exit(1)
    print(f"All sweep unpipelinable tests passed ({full_syn_runs} full syn runs).")


if __name__ == "__main__":
    main()
