#!/usr/bin/env python3
# Planned throughput sweep test (f): unpipelinable design messaging.
# Runs pypelinec on sweep_unpipelinable_design.py (a stateful MAIN with no
# AUTO_PIPELINE regions and an unreachable 100 MHz goal) and asserts the tool
# tells the user PLAINLY that auto-pipelining cannot help:
#  - at planning time (main has a goal but nothing cuttable)
#  - via the standalone as-written synthesis check (FAIL vs the goal)
#  - when the timing report fails (named main + guidance)
#  - without burning full-design synthesis runs on a hopeless sweep
#  - and FAILS with a non zero exit + TIMING NOT MET error block
#    (results still written for debugging first)
#  - with sweep_history.json's final record agreeing: not met, same MHz
import argparse
import json
import os
import re
import subprocess
import sys

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
PYPELINEC = os.path.join(THIS_DIR, "../../../pypelinec")
DESIGN = os.path.join(THIS_DIR, "sweep_unpipelinable_design.py")

MAX_FULL_SYN_RUNS = 1


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
    if "contains nothing auto-pipelining can help" not in out:
        print("FAIL: no planning-time warning that auto-pipelining cannot help")
        sys.exit(1)
    if not re.search(
        r"\[sweep\] sweep_unpipelinable_main synthesized as written "
        r"\(standalone check\): \S+ MHz vs 100\.00 MHz goal - FAIL",
        out,
    ):
        print("FAIL: no as-written standalone check FAIL line for the main")
        sys.exit(1)
    if "auto-pipelining cannot help it" not in out:
        print("FAIL: no failing-timing warning naming the main + guidance")
        sys.exit(1)
    full_syn_runs = len(re.findall(r"Running syn w timing params", out))
    if full_syn_runs > MAX_FULL_SYN_RUNS:
        print(
            f"FAIL: {full_syn_runs} full design synthesis runs (max {MAX_FULL_SYN_RUNS}) - nothing to sweep, should characterize once and stop"
        )
        sys.exit(1)
    # sweep_history.json's final verdict must agree with the exit gate
    error_mhz = re.search(
        r"ERROR: TIMING NOT MET: sweep_unpipelinable_main achieved ([\d.]+) MHz",
        out,
    )
    history_paths = re.findall(r"^\[sweep\] History: (.+)$", out, re.M)
    if not error_mhz or not history_paths:
        print("FAIL: no TIMING NOT MET MHz or no sweep_history.json written")
        sys.exit(1)
    with open(history_paths[-1]) as f:
        history = json.load(f)
    final = history["mains"].get("sweep_unpipelinable_main", {}).get("final") or {}
    if not (
        history.get("build_complete") is True
        and final.get("met") is False
        and final.get("achieved_mhz") is not None
        and abs(final["achieved_mhz"] - float(error_mhz.group(1))) < 0.01
        and final.get("mhz_is_lower_bound") is False
        and final.get("failure_reason")
    ):
        print(f"FAIL: wrong sweep_history.json final record for the main: {final}")
        sys.exit(1)
    print(f"All sweep unpipelinable tests passed ({full_syn_runs} full syn runs).")


if __name__ == "__main__":
    main()
