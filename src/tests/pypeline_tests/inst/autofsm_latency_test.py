#!/usr/bin/env python3
"""AUTOFSM end-to-end scheduling test.

Runs a full pipelinec build (no --comb) on autofsm_test.py and asserts the
whole chain the feature depends on:
  - the schedule pass ran and produced a real multi-state schedule
  - the pure function's several same-kind operations were FOLDED onto fewer
    shared functional units (the entire point -- if this regresses to one unit
    per operation, AUTOFSM has become an expensive way to add latency)
  - the design's .latency matches the schedule's state count
  - the generated FSM entity really reached the VHDL, and instantiates each
    shared unit EXACTLY ONCE (the sharing claim, checked in the output rather
    than trusted from the scheduler's own report)
  - the build meets timing and exits successfully
"""
import argparse
import os
import re
import subprocess
import sys

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
PIPELINEC = os.path.join(THIS_DIR, "../../../pipelinec")
DESIGN = os.path.join(THIS_DIR, "autofsm_test.py")


def fail(msg):
    print("FAIL:", msg)
    sys.exit(1)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out_dir", default=None)
    args = parser.parse_args()

    out_dir = args.out_dir or os.path.join(THIS_DIR, "autofsm_latency_test_out")
    cmd = [sys.executable, PIPELINEC, DESIGN, "--out_dir", out_dir]
    print("Running:", " ".join(cmd), flush=True)
    result = subprocess.run(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
    )
    out = result.stdout
    print(out)

    if result.returncode != 0:
        fail(f"pipelinec exited nonzero ({result.returncode})")
    if "AUTOFSM Pass 1: Scheduling Shared-Resource FSMs" not in out:
        fail("the AUTOFSM schedule pass never ran")

    m = re.search(
        r"^AUTOFSM (\S+): (\d+) ops -> (\d+) shared unit\(s\), (\d+) states, "
        r"latency (\d+) clks",
        out,
        re.M,
    )
    if not m:
        fail("no AUTOFSM schedule summary printed")
    key, n_ops, n_fus, n_states, latency = (
        m.group(1),
        int(m.group(2)),
        int(m.group(3)),
        int(m.group(4)),
        int(m.group(5)),
    )
    if n_ops < 2:
        fail(f"expected several scheduled operations, got {n_ops}")
    if n_fus >= n_ops:
        fail(
            f"no resource sharing happened: {n_ops} operations bound to "
            f"{n_fus} units (expected fewer units than operations)"
        )
    if n_states < 2:
        fail(f"expected a multi-state FSM, got {n_states} state(s)")
    if latency != n_states + 1:
        fail(f"latency {latency} does not match {n_states} states + 1 accept cycle")

    # The scheduler claims folding; verify it in the generated hardware.
    fsm_vhd = None
    for root, _dirs, files in os.walk(out_dir):
        for f in files:
            if (
                f.startswith("autofsm_")
                and f.endswith(".vhd")
                and not f.endswith("_top.vhd")
                and "_comb_" not in f
            ):
                fsm_vhd = os.path.join(root, f)
    if fsm_vhd is None:
        fail(f"no generated AUTOFSM entity VHDL found under {out_dir}")
    print("Generated FSM entity VHDL:", fsm_vhd)
    with open(fsm_vhd) as f:
        vhdl = f.read()

    # One instance per shared arithmetic unit. The state-decode comparators and
    # operand multiplexers the FSM itself adds are expected to appear many
    # times -- they are the cost of sharing, not the thing being shared.
    for unit in ("BIN_OP_PLUS_int16_t_int16_t", "BIN_OP_MINUS_int16_t_int16_t"):
        n = len(re.findall(r"entity work\.%s_" % re.escape(unit), vhdl))
        if n != 1:
            fail(f"expected exactly 1 shared {unit} instance in the FSM, found {n}")
        print(f"  {unit}: 1 instance (shared)")

    if "ERROR: TIMING NOT MET" in out:
        fail("build did not meet timing")

    print(
        f"AUTOFSM end-to-end test passed: {key} folded {n_ops} operations onto "
        f"{n_fus} shared units across {n_states} states (latency {latency})."
    )


if __name__ == "__main__":
    main()
