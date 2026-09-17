#!/usr/bin/env python3
"""A copy of a warm output directory re-synthesizes nothing.

pypeline_sim_debug.py builds once, then runs its native and VHDL sims each in
their own copy of that warm directory. This checks the property that relies
on: rebuilding in a copy reuses every cached DEVICE_MODELS leaf report.

The copied rebuild goes through every parse pass again (AUTO_FSM schedule
passes included), so it fails on any generated file that changes between
passes of one run, and on any cache identity that depends on the directory's
location. Each of these once made leaves re-synthesize, and each is caught
here when its fix is reverted:
- DEVICE_MODELS recorded absolute VHDL input paths;
- c_structs_pkg was rewritten with each pass's own type set;
- shared built-in operator entities named the call site their pass
  elaborated first in a "-- Source:" comment.
"""
import argparse
import os
import shutil
import subprocess
import sys

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
PYPELINEC = os.path.join(THIS_DIR, "../../../pypelinec")
# Checked against each reverted fix: this design's AUTO_FSM passes differ in
# c_structs_pkg types and in which call site first elaborates a shared
# BIN_OP_AND. (auto_fsm_test.py has neither flip and only caught the
# absolute-path regression.)
DESIGN = os.path.join(THIS_DIR, "self_check_auto_fsm_test.py")
MISMATCH = "Cached timing identity/input mismatch"


def fail(msg):
    print("FAIL:", msg)
    sys.exit(1)


def build(out_dir):
    cmd = [sys.executable, PYPELINEC, DESIGN, "--syn_tool", "sky130", "--out_dir", out_dir]
    print("Running:", " ".join(cmd), flush=True)
    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    print(result.stdout, flush=True)
    if result.returncode != 0:
        fail(f"pypelinec exited nonzero ({result.returncode}) for {out_dir}")
    return result.stdout


def synth_runs(log):
    # DEVICE_MODELS prints "Running: <leaf log>" before each synthesis and
    # "Reading log <leaf log>" when it reuses a cached report.
    return [
        l
        for l in log.splitlines()
        if l.startswith("Running: ")
        and os.path.basename(l.split()[-1]).startswith("device_models")
    ]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out_dir", default=None)
    args = parser.parse_args()
    root = args.out_dir or os.path.join(THIS_DIR, "warm_copy_no_resynth_test_out")
    build_dir = os.path.join(root, "build")
    copy_dir = os.path.join(root, "copy")
    for d in (build_dir, copy_dir):
        if os.path.lexists(d):
            shutil.rmtree(d)

    build_log = build(build_dir)
    if "AUTO_FSM Pass 1: Scheduling Shared-Resource FSMs" not in build_log:
        fail("the AUTO_FSM schedule pass never ran; the design no longer re-parses")
    if not synth_runs(build_log):
        fail("the first build synthesized no DEVICE_MODELS leaves; nothing to reuse")

    shutil.copytree(build_dir, copy_dir, symlinks=True)
    copy_log = build(copy_dir)

    mismatches = [l for l in copy_log.splitlines() if MISMATCH in l]
    resynth = synth_runs(copy_log)
    reused = [l for l in copy_log.splitlines() if l.startswith("Reading log ")]
    print(f"copied rebuild: {len(resynth)} synthesized, {len(reused)} reused", flush=True)
    if mismatches or resynth:
        for line in mismatches + resynth:
            print("  ", line)
        fail(
            f"the copied warm directory re-synthesized {len(resynth)} leaf report(s) "
            f"({len(mismatches)} cache mismatch line(s) above name the changed input)"
        )
    if not reused:
        fail("the copied rebuild reused no cached leaf reports")
    print("PASS: copied warm output directory reused every leaf report")


if __name__ == "__main__":
    main()
