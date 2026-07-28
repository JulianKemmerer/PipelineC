#!/usr/bin/env python3
"""AUTOFSM resource test: is the FSM actually SMALLER than the combinational
logic it replaces?

Everything else in the AUTOFSM test suite checks that the feature is correct
and meets timing. This one checks the reason it exists. Without it, a
regression that quietly stopped sharing (one unit per operation plus a pile of
multiplexers and registers) would still pass every other test while making
designs strictly worse.

Method: build autofsm_resources_test.py twice.
  --comb   the AUTOFSM call site stays a combinational passthrough, so the
           design is the full parallel blob: six multipliers, five adders.
  (full)   the scheduled FSM: one multiplier and one adder, time-multiplexed.
Then compare yosys cell counts for the same top-level entity in each build.
The PYRTL timing flow runs yosys first, so those counts are already produced
by both builds -- no extra tool invocation is needed. (On a real FPGA part the
equivalent numbers are in Vivado's report_utilization output.)

Also asserted: the two builds are genuinely comparable, i.e. the combinational
build really is the big one, and both builds succeed.
"""
import argparse
import os
import re
import subprocess
import sys

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
PIPELINEC = os.path.join(THIS_DIR, "../../../pipelinec")
DESIGN = os.path.join(THIS_DIR, "autofsm_resources_test.py")

# The FSM shares 6 multiplies onto 1 multiplier and 5 adds onto 1 adder, at the
# cost of operand multiplexers, state and value registers. A multiplier is far
# more expensive than the multiplexers that share it, so the net must be a
# large win -- but the threshold is deliberately loose (any real shrink counts)
# so the test tracks the property, not one synthesis tool's exact numbers.
MIN_SHRINK_RATIO = 1.5


def fail(msg):
    print("FAIL:", msg)
    sys.exit(1)


def run_build(out_dir, extra):
    cmd = [sys.executable, PIPELINEC, DESIGN, "--out_dir", out_dir] + extra
    print("Running:", " ".join(cmd), flush=True)
    result = subprocess.run(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
    )
    if result.returncode != 0:
        print(result.stdout)
        fail(f"build {extra} exited nonzero ({result.returncode})")
    return result.stdout


def top_cell_count(out_dir):
    """Cell count of the whole-design top entity, from the yosys statistics
    the PYRTL timing flow already emitted into its log."""
    top_dir = os.path.join(out_dir, "top")
    logs = [
        os.path.join(top_dir, f)
        for f in os.listdir(top_dir)
        if f.startswith("pyrtl_") and f.endswith(".log")
    ]
    if not logs:
        fail(f"no PYRTL/yosys log found under {top_dir}")
    logs.sort(key=os.path.getmtime)
    with open(logs[-1]) as f:
        text = f.read()
    m = re.findall(r"^\s*Number of cells:\s+(\d+)", text, re.M)
    if not m:
        fail(f"no yosys cell count in {logs[-1]}")
    return int(m[-1]), logs[-1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out_dir", default=None)
    args = parser.parse_args()

    base = args.out_dir or os.path.join(THIS_DIR, "autofsm_resources_test_out")
    comb_dir = os.path.join(base, "comb")
    fsm_dir = os.path.join(base, "fsm")

    run_build(comb_dir, ["--comb"])
    fsm_out = run_build(fsm_dir, [])

    m = re.search(
        r"^AUTOFSM \S+: (\d+) ops -> (\d+) shared unit\(s\), (\d+) states",
        fsm_out,
        re.M,
    )
    if not m:
        fail("the full build did not schedule an AUTOFSM")
    n_ops, n_fus, n_states = int(m.group(1)), int(m.group(2)), int(m.group(3))
    if n_fus >= n_ops:
        fail(f"no sharing: {n_ops} operations bound to {n_fus} units")

    comb_cells, comb_log = top_cell_count(comb_dir)
    fsm_cells, fsm_log = top_cell_count(fsm_dir)
    ratio = comb_cells / float(fsm_cells) if fsm_cells else 0.0

    print()
    print("=== AUTOFSM area comparison (yosys cell counts, whole design top) ===")
    print(f"  combinational (--comb, no sharing): {comb_cells:>8} cells  [{comb_log}]")
    print(f"  resource-shared FSM              : {fsm_cells:>8} cells  [{fsm_log}]")
    print(f"  shrink                           : {ratio:.2f}x")
    print(
        f"  schedule: {n_ops} operations -> {n_fus} shared units over "
        f"{n_states} states"
    )
    print()

    if ratio < MIN_SHRINK_RATIO:
        fail(
            f"the FSM is not meaningfully smaller than the combinational "
            f"version ({comb_cells} -> {fsm_cells} cells, {ratio:.2f}x, "
            f"expected at least {MIN_SHRINK_RATIO}x). Resource sharing is the "
            f"entire purpose of AUTOFSM -- if this regressed, the feature is "
            f"buying latency for nothing."
        )

    print(f"AUTOFSM resource test passed ({ratio:.2f}x smaller).")


if __name__ == "__main__":
    main()
