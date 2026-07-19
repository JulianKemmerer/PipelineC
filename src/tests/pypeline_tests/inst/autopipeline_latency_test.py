#!/usr/bin/env python3
# AUTOPIPELINE .latency pin-and-confirm end-to-end test.
# Runs pipelinec (full sweep, no --comb) on stream_pipeline_test.py -- whose
# make_stream_pipeline reads AUTOPIPELINE(...).latency to size its FIFO --
# and asserts the driver's pin-and-confirm loop:
#  - pass 1 discovers a real (>0) latency for the AUTOPIPELINE'd core
#  - pass 2 re-elaborates with it, seeds the previous pipelining, and runs a
#    seeded confirmation synthesis (not a second full sweep)
#  - additional passes are allowed (and typical): realizing the seeded
#    fractional slices hierarchically (e.g. into pipelined built-in div
#    entities with their own stage granularity) can change the total latency
#    on a passing confirmation, and the loop must keep re-elaborating until
#    the .latency the design's Python consumed equals the stage counts
#    actually built -- exiting early on "met" alone would bake contradictory
#    .latency-derived constants into the final VHDL
#  - the loop settles within the pass cap and the build exits successfully
import argparse
import os
import re
import subprocess
import sys

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
PIPELINEC = os.path.join(THIS_DIR, "../../../pipelinec")
DESIGN = os.path.join(THIS_DIR, "stream_pipeline_test.py")


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

    if "AUTOPIPELINE Pass 2" not in out:
        print(
            "FAIL: pin-and-confirm pass 2 never ran (.latency is consumed "
            "by make_stream_pipeline, so it must)"
        )
        sys.exit(1)
    if ".latency did not settle" in out:
        print("FAIL: pin-and-confirm loop hit the pass cap without settling")
        sys.exit(1)

    latency_lines = re.findall(r"^AUTOPIPELINE (\S+): (\d+) clks$", out, re.M)
    if not latency_lines:
        print("FAIL: no harvested AUTOPIPELINE latency printed")
        sys.exit(1)
    latencies = {key: int(clks) for key, clks in latency_lines}
    if not any(clks > 0 for clks in latencies.values()):
        print(f"FAIL: harvested latencies not > 0: {latencies}")
        sys.exit(1)

    if "confirmation synthesis with pipelining pinned" not in out:
        print("FAIL: pass 2 did not run the seeded confirmation synthesis")
        sys.exit(1)
    if not re.search(r"^PASS .* \(confirmation run\)$", out, re.M):
        print("FAIL: confirmation synthesis did not pass timing")
        sys.exit(1)
    if "falling back to a full throughput sweep" in out:
        print(
            "FAIL: confirmation fell back to a full sweep -- seeding "
            "did not carry the pass-1 pipelining over"
        )
        sys.exit(1)

    # The confirmation must be a REAL synthesis of the pass-2 design, not a
    # replay of an existing log (all tools print "Reading log" on replay): a
    # slices-only top hash used to collide with pass 1's accepted iteration,
    # silently replaying its timing report despite the resized FIFO.
    confirm_start = out.index("confirmation synthesis with pipelining pinned")
    verdict_match = re.search(
        r"^(PASS|FAIL) .* \(confirmation run\)$", out[confirm_start:], re.M
    )
    confirm_window = out[confirm_start : confirm_start + verdict_match.start()]
    if "Reading log" in confirm_window:
        print(
            "FAIL: confirmation replayed an existing synthesis log instead "
            "of synthesizing the re-elaborated design"
        )
        sys.exit(1)
    if "Running:" not in confirm_window:
        print("FAIL: no fresh synthesis run observed in the confirmation window")
        sys.exit(1)

    # Stale zero-clock pipeline-map cache noise must be gone (the mismatch
    # branch used to print this once per stale func during pass 2, its
    # sys.exit defused by a bare except)
    if "Zero clock cache no mactho" in out:
        print(
            "FAIL: stale zero-clock pipeline-map cache consulted "
            "('Zero clock cache no mactho' printed)"
        )
        sys.exit(1)

    # (No sweep_history cross-check: the final consumed latency is the
    # hierarchically-REALIZED total -- e.g. built-in div entities' own stage
    # counts -- which legitimately differs from the planner's per-iteration
    # cut counts recorded in sweep_history.json. Consumed == built is instead
    # guaranteed by the loop's convergence condition (exit 0 implies it) and
    # cycle-verified end-to-end by the native_vs_vhdl_* diff tests.)

    print(f"All AUTOPIPELINE .latency end-to-end tests passed ({latencies}).")


if __name__ == "__main__":
    main()
