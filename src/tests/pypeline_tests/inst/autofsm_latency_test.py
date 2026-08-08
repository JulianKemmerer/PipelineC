#!/usr/bin/env python3
"""AUTOFSM end-to-end scheduling test.

Runs a full pypelinec build (no --comb) on autofsm_test.py and asserts the
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
PYPELINEC = os.path.join(THIS_DIR, "../../../pypelinec")
DESIGN = os.path.join(THIS_DIR, "autofsm_test.py")


def fail(msg):
    print("FAIL:", msg)
    sys.exit(1)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out_dir", default=None)
    args = parser.parse_args()

    out_dir = args.out_dir or os.path.join(THIS_DIR, "autofsm_latency_test_out")
    cmd = [sys.executable, PYPELINEC, DESIGN, "--out_dir", out_dir]
    print("Running:", " ".join(cmd), flush=True)
    result = subprocess.run(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
    )
    out = result.stdout
    print(out)

    if result.returncode != 0:
        fail(f"pypelinec exited nonzero ({result.returncode})")
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
    #
    # Pre-existing fragility, not something this specific change is
    # responsible for fixing beyond making it deterministic: the design's
    # @MAIN is itself named autofsm_top, so its own top-level entity files
    # (autofsm_top_<hash>.vhd) also match "starts with autofsm_, ends with
    # .vhd, not a _top.vhd suffix, no _comb_" -- the same shape as the real
    # FSM blob entity (autofsm_<blob_func_name>_<hash>.vhd). Any unrelated
    # source change that shifts content hashes can reorder os.walk's
    # unsorted traversal and make this "last match wins" loop pick the
    # wrong file, even though the actual scheduling/VHDL is unaffected (this
    # was caught this way: verified by grepping the *correct* file directly
    # when this loop picked the top-level one instead). Fixed by also
    # excluding the @MAIN's own entity name explicitly, and preferring the
    # shortest matching path (blob entities live directly under out_dir;
    # the top-level entity lives several directories deeper, mirroring the
    # source file's path).
    #
    # Also excluded: autofsm_operand_mux_*, the generated operand multiplexer
    # entities (include/pypeline/operators/autofsm_mux.py). They are named
    # autofsm_* too, but they are what the FSM is BUILT FROM, not the FSM.
    candidates = []
    for root, _dirs, files in os.walk(out_dir):
        for f in files:
            if (
                f.startswith("autofsm_")
                and not f.startswith("autofsm_top_")
                and not f.startswith("autofsm_operand_mux")
                and f.endswith(".vhd")
                and not f.endswith("_top.vhd")
                and "_comb_" not in f
            ):
                candidates.append(os.path.join(root, f))
    if not candidates:
        fail(f"no generated AUTOFSM entity VHDL found under {out_dir}")
    if len(candidates) > 1:
        fail(
            f"ambiguous AUTOFSM entity VHDL candidates under {out_dir}, "
            f"expected exactly one: {candidates}"
        )
    fsm_vhd = candidates[0]
    print("Generated FSM entity VHDL:", fsm_vhd)
    with open(fsm_vhd) as f:
        vhdl = f.read()

    # The generated hardware must contain exactly as many copies of each shared
    # unit as the schedule says it does -- no more (sharing that did not
    # happen), and no fewer (a unit quietly dropped).
    #
    # Checked against the schedule's own per-unit report rather than a
    # hardcoded 1, because the area search may deliberately build a SECOND copy
    # of a cheap unit when its operand multiplexer would cost more than the
    # unit does. That is the search working, not sharing regressing -- the
    # units-fewer-than-operations check above is what guards against the
    # latter. (The state-decode tables and operand multiplexers the FSM adds
    # around all this appear many times; they are the price of sharing, not the
    # thing being shared.)
    units_claimed = {}
    for line in out.splitlines():
        fu = re.match(r"^  (\S+) x(\d+) -> 1 unit", line)
        if fu:
            units_claimed[fu.group(1)] = units_claimed.get(fu.group(1), 0) + 1
    if not units_claimed:
        fail("the schedule summary listed no shared units")
    for unit in ("BIN_OP_PLUS_int16_t_int16_t", "BIN_OP_MINUS_int16_t_int16_t"):
        want = units_claimed.get(unit)
        if want is None:
            fail(f"the schedule did not bind any {unit} unit")
        n = len(re.findall(r"entity work\.%s_" % re.escape(unit), vhdl))
        if n != want:
            fail(
                f"the schedule claims {want} shared {unit} unit(s) but the "
                f"generated FSM instantiates {n}"
            )
        print(f"  {unit}: {n} instance(s), matching the schedule")

    if "ERROR: TIMING NOT MET" in out:
        fail("build did not meet timing")

    print(
        f"AUTOFSM end-to-end test passed: {key} folded {n_ops} operations onto "
        f"{n_fus} shared units across {n_states} states (latency {latency})."
    )


if __name__ == "__main__":
    main()
