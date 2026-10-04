#!/usr/bin/env python3
# start_latency= is only a starting guess: a constrained AUTO_PIPELINE region
# must reach the same pipeline the untagged call site does. Builds
# auto_pipeline_region_minisweep_design.py (sky130, 120 MHz) twice -- untagged,
# then start_latency=1 -- and asserts both:
#  - take the measured mini-sweep of the repeated `step` helper and lock it,
#  - meet timing with the same total depth, in at most 3 full syntheses.
# Before the fix a start_latency region never mini-swept (locks were refused
# inside every constrained region): the same design grew the region uniformly
# over the delay model's serial quarter-round layout to 31 cuts, then trimmed
# to 22 -- twice the untagged depth, in 5 syntheses. On WireGuard this was
# ChaCha at 44-56 clks instead of the 20 its block_step lock gives.
import argparse
import json
import os
import re
import subprocess
import sys

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
PYPELINEC = os.path.join(THIS_DIR, "../../../pypelinec")
DESIGN = os.path.join(THIS_DIR, "auto_pipeline_region_minisweep_design.py")
ENV = "AUTO_PIPELINE_REGION_MINISWEEP_START_LATENCY"
MAX_FULL_SYN_RUNS = 3


def fail(msg):
    print("FAIL:", msg)
    sys.exit(1)


def build(out_dir, start_latency):
    env = dict(os.environ)
    env.pop(ENV, None)
    if start_latency is not None:
        env[ENV] = str(start_latency)
    cmd = [sys.executable, PYPELINEC, DESIGN, "--syn_tool", "device_models"]
    if out_dir:
        cmd += ["--out_dir", out_dir]
    print(f"Running ({ENV}={start_latency}):", " ".join(cmd), flush=True)
    result = subprocess.run(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=env
    )
    out = result.stdout
    print(out)
    label = "untagged" if start_latency is None else f"start_latency={start_latency}"
    if result.returncode != 0:
        fail(f"{label} build exited {result.returncode}")
    if "Isolated coarse sweep of hotspot: step" not in out:
        fail(f"{label}: the repeated step helper was never mini-swept")
    if not re.search(r"^\[sweep\] Locked step .* on 6 instance\(s\)", out, re.M):
        fail(f"{label}: step was not locked on its 6 instances")
    syns = len(re.findall(r"^Running syn w timing params", out, re.M))
    if syns > MAX_FULL_SYN_RUNS:
        fail(f"{label}: {syns} full-design syntheses (expected <= {MAX_FULL_SYN_RUNS})")
    m = re.search(r"^\[sweep\]   region_minisweep_main: (\d+) slice\(s\) total", out, re.M)
    if not m:
        fail(f"{label}: no pipeline depth summary line")
    depth = int(m.group(1))
    if out_dir:
        with open(os.path.join(out_dir, "top", "sweep_history.json")) as f:
            final = json.load(f)["mains"]["region_minisweep_main"]["final"]
        if final["met"] is not True or final["slices_built"] != depth:
            fail(f"{label}: history final {final} disagrees with depth {depth}")
    return depth


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out_dir", default=None)
    args = parser.parse_args()
    sub = lambda name: os.path.join(args.out_dir, name) if args.out_dir else None
    untagged = build(sub("untagged"), None)
    seeded = build(sub("start_latency_1"), 1)
    if seeded != untagged:
        fail(f"start_latency=1 built {seeded} slices, the untagged call site {untagged}")
    print(f"PASS: both builds mini-swept step and built {untagged} slices")


if __name__ == "__main__":
    main()
