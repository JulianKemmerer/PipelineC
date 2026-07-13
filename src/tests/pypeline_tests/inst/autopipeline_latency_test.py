#!/usr/bin/env python3
# AUTOPIPELINE .latency pin-and-confirm end-to-end test.
# Runs pipelinec (full sweep, no --comb) on stream_pipeline_test.py -- whose
# make_stream_pipeline reads AUTOPIPELINE(...).latency to size its FIFO --
# and asserts the driver's pin-and-confirm loop:
#  - pass 1 discovers a real (>0) latency for the AUTOPIPELINE'd core
#  - pass 2 re-elaborates with it, seeds the previous pipelining, and needs
#    only ONE confirmation synthesis (not a second full sweep)
#  - the confirmation run passes timing and the build exits successfully
#  - the discovered latency matches what sweep_history.json recorded
import argparse
import json
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
    if "AUTOPIPELINE Pass 3" in out:
        print(
            "FAIL: needed a 3rd pass -- pinned confirmation should settle "
            "this design in 2"
        )
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

    # Cross-check against sweep_history.json: the harvested latency must be
    # one of the deepest-pipeline depths the sweep actually built (the
    # accepted iteration's depth -- not necessarily the max, since post-met
    # trim probes may appear in the history too).
    if args.out_dir:
        history_path = os.path.join(args.out_dir, "top", "sweep_history.json")
        with open(history_path) as f:
            history = json.load(f)
        depths_seen = {
            iteration.get("deepest_pipeline", 0)
            for iterations in history.values()
            for iteration in iterations
        }
        harvested = max(latencies.values())
        if harvested not in depths_seen:
            print(
                f"FAIL: harvested latency {harvested} not among "
                f"sweep_history deepest_pipeline depths {sorted(depths_seen)}"
            )
            sys.exit(1)

    print(f"All AUTOPIPELINE .latency end-to-end tests passed ({latencies}).")


if __name__ == "__main__":
    main()
