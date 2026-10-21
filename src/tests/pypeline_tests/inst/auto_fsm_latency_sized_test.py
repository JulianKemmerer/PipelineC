#!/usr/bin/env python3
"""AUTO_FSM sized from an AUTO_PIPELINE depth: the call site the pin-and-confirm
re-elaboration creates is scheduled, and the build finishes.

Builds auto_fsm_latency_sized_design.py under --syn_tool device_models. AUTO_FSM
pass 1 schedules the lane-sum function for capacity 2 (the bootstrap parse
reads depth 0). The sweep then pipelines the divider core, so AUTO_PIPELINE
pass 2 re-elaborates a capacity L+2 function: a call site with no schedule.
The WireGuard shared Poly1305 build stopped there with an AutoFsmInternalError
("no schedule was installed for this call site").

Asserted below, only what proves that scenario ran and was handled: the
build exits 0, AUTO_PIPELINE pass 2 ran with a harvested depth L >= 1, the
capacity L+2 call site was reported new and was scheduled, and pass 2 still
ran its single seeded confirmation synthesis (no fresh sweep). Latency memory
is off: with a remembered depth the bootstrap parse would already build the
final capacity, and the call site would never change.
"""

import argparse
import os
import re
import subprocess
import sys

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
PYPELINEC = os.path.join(THIS_DIR, "../../../pypelinec")
DESIGN = os.path.join(THIS_DIR, "auto_fsm_latency_sized_design.py")


def fail(msg):
    print("FAIL:", msg)
    sys.exit(1)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out_dir", default=None)
    args = parser.parse_args()

    out_dir = args.out_dir or os.path.join(THIS_DIR, "auto_fsm_latency_sized_test_out")
    cmd = [
        sys.executable,
        PYPELINEC,
        DESIGN,
        "--syn_tool",
        "device_models",
        "--no_latency_memory",
        "--out_dir",
        out_dir,
    ]
    print("Running:", " ".join(cmd), flush=True)
    result = subprocess.run(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
    )
    out = result.stdout
    print(out)

    if result.returncode != 0:
        fail(f"pypelinec exited nonzero ({result.returncode})")

    pass2 = out.find("AUTO_PIPELINE Pass 2")
    if pass2 < 0:
        fail(
            "AUTO_PIPELINE pass 2 never ran: the sweep left the divider at its "
            "bootstrap depth, so the AUTO_FSM call site never changed. Raise "
            "the design's clock goal above the divider's unpipelined fmax."
        )
    after = out[pass2:]
    depths = [
        int(n) for n in re.findall(r"^AUTO_PIPELINE \S+: (\d+) clks$", after, re.M)
    ]
    if not depths or depths[0] < 1:
        fail(f"pass 2 did not install a harvested depth >= 1: {depths}")
    capacity = depths[0] + 2

    new_call_sites = re.search(
        r"^AUTO_FSM: re-elaboration created call site\(s\) with no schedule.*: (.+)$",
        after,
        re.M,
    )
    if new_call_sites is None:
        fail("pass 2 re-elaboration did not report a new AUTO_FSM call site")
    key_prefix = f"lane_sum_capacity_{capacity}_"
    if not new_call_sites.group(1).startswith(key_prefix):
        fail(f"new call site {new_call_sites.group(1)!r} is not {key_prefix}...")
    scheduled = after[new_call_sites.end() :]
    if not re.search(rf"^AUTO_FSM {key_prefix}\S*: \d+ ops -> ", scheduled, re.M):
        fail(f"no schedule summary for the new {key_prefix}... call site")

    if "confirmation synthesis with pipelining pinned" not in scheduled:
        fail("pass 2 did not run its seeded confirmation synthesis")
    if (
        "falling back to a full throughput sweep" in scheduled
        or "replanning implicated pipelined MAINs" in scheduled
    ):
        fail("pass 2's confirmation fell back to a fresh sweep")

    print(
        f"AUTO_FSM latency-sized test passed: depth {depths[0]} gave capacity "
        f"{capacity}, whose call site was scheduled during pass 2 re-elaboration."
    )


if __name__ == "__main__":
    main()
