#!/usr/bin/env python3
# start_latency= is only a starting guess: a constrained AUTO_PIPELINE region
# must reach the same pipeline the untagged call site does. Builds
# auto_pipeline_region_minisweep_design.py (sky130, 120 MHz) twice -- untagged,
# then start_latency=1 -- and asserts both:
#  - take the measured mini-sweep of the repeated `step` helper and lock it,
#  - meet timing with the same total depth, in at most 3 full syntheses.
# Then four latency-memory builds sharing one --syn_cache store:
#  - a baseline that records the `step` lock;
#  - a same-goal rebuild in a fresh output directory: the MAIN replays in one
#    confirmation with no new synthesis, so the locked winner's VHDL is the
#    same bytes the mini-sweep wrote before the lock marked it fixed;
#  - an edit outside `step` (REGION_MINISWEEP_OUTSIDE=1): the MAIN no longer
#    replays, but the unchanged lock is reused, in fewer full syntheses;
#  - a raised goal (130 MHz): the 120 MHz lock becomes a mini-sweep hint that
#    skips the hotspot streak and starts the isolated sweep at its depth.
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
import tempfile

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
PYPELINEC = os.path.join(THIS_DIR, "../../../pypelinec")
DESIGN = os.path.join(THIS_DIR, "auto_pipeline_region_minisweep_design.py")
PARAM = "AUTO_PIPELINE_REGION_MINISWEEP_START_LATENCY"
MAX_FULL_SYN_RUNS = 3


def fail(msg):
    print("FAIL:", msg)
    sys.exit(1)


def build(out_dir, start_latency, extra=(), memory=False, reused=False, hint=False):
    cmd = [sys.executable, PYPELINEC, DESIGN, "--syn_tool", "device_models"]
    if out_dir:
        cmd += ["--out_dir", out_dir]
    if start_latency is not None:
        cmd += ["-D", f"{PARAM}={start_latency}"]
    cmd += list(extra)
    print("Running:", " ".join(cmd), flush=True)
    result = subprocess.run(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        env=dict(os.environ, PIPELINEC_INTERNAL_NO_LATENCY_MEMORY="0" if memory else "1")
    )
    out = result.stdout
    print(out)
    label = "untagged" if start_latency is None else f"start_latency={start_latency}"
    if result.returncode != 0:
        fail(f"{label} build exited {result.returncode}")
    if reused:
        if "Reusing concrete lock for step" not in out or "Replaying MAIN" in out:
            fail("the outside edit did not reject MAIN replay and reuse step's lock")
    elif "Isolated coarse sweep of hotspot: step" not in out:
        fail(f"{label}: the repeated step helper was never mini-swept")
    if not reused and not re.search(r"^\[sweep\] Locked step .* on 6 instance\(s\)", out, re.M):
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
    if hint:
        if "Applying mini-sweep hint for step" not in out:
            fail("a lower-goal lock did not become a mini-sweep hint")
        if "Starting mini-sweep of step at remembered depth 1" not in out:
            fail("the mini-sweep did not start from its remembered depth")
        with open(os.path.join(out_dir, "top", "sweep_history.json")) as f:
            iterations = json.load(f)["mains"]["region_minisweep_main"]["iterations"]
        minis = [i for i, record in enumerate(iterations) if "minisweep" in str(record.get("action"))]
        if not minis or minis[0] != 0:
            fail("a lock hint did not skip the hotspot streak wait")
    return depth, syns


def check_replay(out_dir, base_dir, store):
    """A same-goal rebuild in a fresh output directory replays the recorded
    MAIN, step lock included, in one confirmation the store answers. The
    mini-sweep wrote step's winner before its lock marked it fixed, while the
    replay renders it fixed: its VHDL must not depend on that flag."""
    cmd = [sys.executable, PYPELINEC, DESIGN, "--syn_tool", "device_models",
           "--out_dir", out_dir, "--syn_cache", store]
    print("Running:", " ".join(cmd), flush=True)
    result = subprocess.run(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        env=dict(os.environ, PIPELINEC_INTERNAL_NO_LATENCY_MEMORY="0"))
    out = result.stdout
    print(out)
    if result.returncode != 0:
        fail(f"replay build exited {result.returncode}")
    if "Replaying MAIN" not in out or "Isolated coarse sweep" in out:
        fail("the same-goal rebuild did not replay the recorded MAIN")
    if re.search(r"^Running syn w timing params", out, re.M):
        fail("the replay ran planned sweep iterations")
    if len(re.findall(r"^Running confirmation synthesis", out, re.M)) != 1:
        fail("the replay did not run exactly one confirmation")
    if "0 new run(s)" not in out:
        fail("the replay's synthesis inputs missed the store (did step's VHDL change?)")
    latencies = []
    for d in (base_dir, out_dir):
        with open(os.path.join(d, "latency_profile.json")) as f:
            latencies.append({e["key"]: e["latency"] for e in json.load(f)["entries"]})
    if latencies[0] != latencies[1]:
        fail(f"replay built {latencies[1]}, the recorded build {latencies[0]}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out_dir", default=None)
    args = parser.parse_args()
    args.out_dir = args.out_dir or tempfile.mkdtemp(prefix="region_minisweep_")
    sub = lambda name: os.path.join(args.out_dir, name)
    untagged, _ = build(sub("untagged"), None)
    seeded, _ = build(sub("start_latency_1"), 1)
    if seeded != untagged:
        fail(f"start_latency=1 built {seeded} slices, the untagged call site {untagged}")
    store = sub("store")
    baseline, cold_syns = build(sub("memory_base"), None, ("--syn_cache", store), memory=True)
    check_replay(sub("memory_replay"), sub("memory_base"), store)
    edited, warm_syns = build(sub("memory_edited"), None,
        ("--syn_cache", store, "-D", "REGION_MINISWEEP_OUTSIDE=1"), memory=True, reused=True)
    if warm_syns >= cold_syns:
        fail(f"lock reuse did not save synthesis: {warm_syns} vs {cold_syns}")
    build(sub("goal_raised"), None,
          ("--syn_cache", store, "-D", "REGION_MINISWEEP_GOAL=130"), memory=True, hint=True)
    print(f"PASS: both starts built {untagged} slices; a same-goal rebuild replayed from the store; "
          "outside edit reused step; goal raise used the lock hint")


if __name__ == "__main__":
    main()
