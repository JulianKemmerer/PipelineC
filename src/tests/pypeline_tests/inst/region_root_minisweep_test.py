#!/usr/bin/env python3
# A region root is attributed and mini-swept like a helper inside a region
# (#387). Builds region_root_minisweep_design.py (sky130, 120 MHz) twice:
#  - the imported `chain` tagged directly: the critical path is found only by
#    the root instance's label path, the root itself is mini-swept and locked,
#    and the build meets timing with the lock retained;
#  - the one-line wrapper of -D REGION_ROOT_WRAPPER=1, the old workaround,
#    which mini-sweeps `chain` inside it.
# Both must reach the same depth, in at most 5 full syntheses each. Before the
# fix the direct tag was never mini-swept and only grew its region.
import argparse
import json
import os
import re
import subprocess
import sys
import tempfile

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
PYPELINEC = os.path.join(THIS_DIR, "../../../pypelinec")
DESIGN = os.path.join(THIS_DIR, "region_root_minisweep_design.py")
ROOT = "region_root_minisweep_chain_chain"
MAX_FULL_SYN_RUNS = 5


def fail(msg):
    print("FAIL:", msg)
    sys.exit(1)


def build(out_dir, wrapper):
    cmd = [sys.executable, PYPELINEC, DESIGN, "--syn_tool", "device_models",
           "--out_dir", out_dir, "-D", f"REGION_ROOT_WRAPPER={wrapper}"]
    print("Running:", " ".join(cmd), flush=True)
    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    out = result.stdout
    print(out)
    label = "wrapper" if wrapper else "direct tag"
    if result.returncode != 0:
        fail(f"{label} build exited {result.returncode}")
    if f"Isolated coarse sweep of hotspot: {ROOT}" not in out:
        fail(f"{label}: {ROOT} was never mini-swept")
    if not re.search(rf"^\[sweep\] Locked {ROOT} .* on 1 instance\(s\)", out, re.M):
        fail(f"{label}: {ROOT} was not locked")
    syns = len(re.findall(r"^Running syn w timing params", out, re.M))
    if syns > MAX_FULL_SYN_RUNS:
        fail(f"{label}: {syns} full-design syntheses (expected <= {MAX_FULL_SYN_RUNS})")
    with open(os.path.join(out_dir, "top", "sweep_history.json")) as f:
        history = json.load(f)["mains"]["region_root_main"]
    final = history["final"]
    if final["met"] is not True or final["achieved_mhz"] < history["goal_mhz"]:
        fail(f"{label}: the retained implementation misses timing: {final}")
    if final["locked_instances"] != 1:
        fail(f"{label}: the mini-sweep lock was discarded: {final}")
    actions = [record["action"] for record in history["iterations"]]
    if f"minisweep({ROOT})" not in actions:
        fail(f"{label}: no minisweep({ROOT}) action in {actions}")
    blamed = {record.get("bottleneck") for record in history["iterations"]} - {None}
    if blamed != {ROOT}:
        fail(f"{label}: critical paths blamed on {sorted(blamed)}, not {ROOT}")
    return final["slices_built"]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out_dir", default=None)
    args = parser.parse_args()
    args.out_dir = args.out_dir or tempfile.mkdtemp(prefix="region_root_minisweep_")
    direct = build(os.path.join(args.out_dir, "direct"), 0)
    wrapped = build(os.path.join(args.out_dir, "wrapper"), 1)
    if direct != wrapped:
        fail(f"tagging {ROOT} directly built {direct} slices, its wrapper {wrapped}")
    print(f"PASS: the directly tagged root and its wrapper both reach {direct} slices")
    return 0


if __name__ == "__main__":
    sys.exit(main())
