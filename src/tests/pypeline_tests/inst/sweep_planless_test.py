#!/usr/bin/env python3
# Planned throughput sweep test (g): planless mains get an "as written" check.
# Runs pypelinec on sweep_planless_design.py (a stateful MAIN with no
# AUTO_PIPELINE regions and an easily met 1 MHz goal) and asserts:
#  - the planning-time warning still tells the user nothing is cuttable
#  - the main gets ONE standalone whole-module synthesis and the new
#    "synthesized as written (standalone check) ... PASS" line
#  - the reported critical path is NOT stored as the func's delay
#    (no measured-delay print for the main func)
#  - timing is met in context: exit 0, one full-design characterization syn
#  - sweep_history.json carries the main's final as-written verdict
import argparse
import json
import os
import re
import subprocess
import sys

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
PYPELINEC = os.path.join(THIS_DIR, "../../../pypelinec")
DESIGN = os.path.join(THIS_DIR, "sweep_planless_design.py")

MAX_FULL_SYN_RUNS = 1


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out_dir", default=None)
    args = parser.parse_args()

    cmd = [sys.executable, PYPELINEC, DESIGN, "--syn_tool", "device_models"]
    if args.out_dir:
        cmd += ["--out_dir", args.out_dir]
    print("Running:", " ".join(cmd), flush=True)
    result = subprocess.run(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
    )
    out = result.stdout
    print(out)

    if result.returncode != 0:
        print("FAIL: pypelinec exited non zero despite met timing goal")
        sys.exit(1)
    if "contains nothing auto-pipelining can help" not in out:
        print("FAIL: no planning-time warning that auto-pipelining cannot help")
        sys.exit(1)
    as_written_syns = len(
        re.findall(r"Synthesizing function: \S+ \(as-written timing check\)", out)
    )
    if as_written_syns != 1:
        print(f"FAIL: expected 1 as-written check synthesis, saw {as_written_syns}")
        sys.exit(1)
    m = re.search(
        r"\[sweep\] sweep_planless_main synthesized as written "
        r"\(standalone check\): \S+ MHz vs 1\.00 MHz goal - PASS",
        out,
    )
    if not m:
        print("FAIL: no as-written standalone check PASS line for the main")
        sys.exit(1)
    if "Function: sweep_planless_main measured path delay" in out:
        print(
            "FAIL: standalone check stored its critical path as the main "
            "func's measured delay (must stay estimated)"
        )
        sys.exit(1)
    if "ERROR: TIMING NOT MET" in out:
        print("FAIL: unexpected TIMING NOT MET error block")
        sys.exit(1)
    full_syn_runs = len(re.findall(r"Running syn w timing params", out))
    if full_syn_runs > MAX_FULL_SYN_RUNS:
        print(
            f"FAIL: {full_syn_runs} full design synthesis runs (max {MAX_FULL_SYN_RUNS}) - nothing to sweep, should characterize once and stop"
        )
        sys.exit(1)
    # sweep_history.json must carry the planless main's final verdict (it
    # used to be keyed by sweep plans only, so planless mains were absent)
    history_paths = re.findall(r"^\[sweep\] History: (.+)$", out, re.M)
    if not history_paths:
        print("FAIL: no sweep_history.json written")
        sys.exit(1)
    with open(history_paths[-1]) as f:
        history = json.load(f)
    if history.get("schema_version") != 2 or history.get("build_complete") is not True:
        print(f"FAIL: sweep_history.json not a complete schema 2 file: {history}")
        sys.exit(1)
    final = history["mains"].get("sweep_planless_main", {}).get("final") or {}
    if not (
        final.get("met") is True
        and final.get("source") == "as_written"
        and final.get("standalone_mhz")
        and final.get("auto_pipelined") is False
    ):
        print(f"FAIL: wrong sweep_history.json final record for the main: {final}")
        sys.exit(1)
    print(f"All sweep planless tests passed ({full_syn_runs} full syn runs).")


if __name__ == "__main__":
    main()
