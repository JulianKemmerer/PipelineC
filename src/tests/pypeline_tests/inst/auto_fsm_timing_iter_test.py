#!/usr/bin/env python3
"""AUTO_FSM synthesis-iteration test: does the build FIND a critical path inside
an AUTO_FSM and FIX it by rescheduling?

This is the AUTO_FSM analogue of "the sweep adds pipeline stages until timing is
met", and it is the property that makes the feature usable in practice: a user
who sees a timing report blaming an AUTO_FSM must be able to get more states out
of the tool without hand-editing anything.

Method: build auto_fsm_tighten_test.py with a deliberately LOOSE per-state
budget (--auto_fsm_budget_scale 1.5, i.e. the scheduler is told a state's
operation chain may fill 1.5x the clock period). The first schedule therefore
over-packs its states and the synthesized FSM misses the clock. The driver must:
  1. detect the timing failure and attribute it to the AUTO_FSM region,
  2. shrink that region's per-state budget and reschedule with less work per
     state (more states, or the same number balanced better -- either is a
     valid way to shorten the worst state, and which one the scheduler picks
     depends on the operation mix),
  3. rebuild, and converge on a schedule that meets timing,
  4. exit 0.

Asserted below: at least two schedule passes ran, a tightening was applied,
the worst state got shorter, the first build missed the clock while the last
one met it, and the exit code is 0.
"""
import argparse
import os
import re
import subprocess
import sys

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
PYPELINEC = os.path.join(THIS_DIR, "../../../pypelinec")
DESIGN = os.path.join(THIS_DIR, "..", "auto_fsm_tighten_test.py")
START_BUDGET_SCALE = "1.5"


def fail(msg):
    print("FAIL:", msg)
    sys.exit(1)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out_dir", default=None)
    args = parser.parse_args()

    out_dir = args.out_dir or os.path.join(THIS_DIR, "auto_fsm_timing_iter_test_out")
    cmd = [
        sys.executable,
        PYPELINEC,
        DESIGN,
        # PyRTL on purpose (run_all category build_report_pyrtl): under sky130
        # the design's critical path (~9.8 ns, ~102 MHz) is the FSM's
        # input-capture enable fanning out to all 142 input-register bits, not
        # any state's operations, so no reschedule changes it -- a goal below
        # it is met by the first schedule, and one above it can never be met
        # (auto_fsm_tighten_stall_test.py covers that case under sky130).
        "--syn_tool",
        "pyrtl",
        "--out_dir",
        out_dir,
        "--auto_fsm_budget_scale",
        START_BUDGET_SCALE,
    ]
    print("Running:", " ".join(cmd), flush=True)
    result = subprocess.run(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
    )
    out = result.stdout
    print(out)

    if result.returncode != 0:
        fail(f"pypelinec exited nonzero ({result.returncode})")

    passes = re.findall(r"^=+ AUTO_FSM Pass (\d+): ", out, re.M)
    if len(passes) < 2:
        fail(
            "only one AUTO_FSM schedule pass ran -- the loose starting budget "
            "was supposed to miss timing and force a reschedule. If the delay "
            "model changed, retune START_BUDGET_SCALE / the design's clock goal."
        )

    if "timing missed; tightened per-state budget" not in out:
        fail("the driver never tightened an AUTO_FSM budget in response to timing")

    schedules = re.findall(
        r"^AUTO_FSM (\S+): (\d+) ops -> (\d+) shared unit\(s\), (\d+) states, "
        r"latency (\d+) clks, budget \S+ ns/state \(scale \S+\), "
        r"worst state ([\d.]+) ns",
        out,
        re.M,
    )
    if len(schedules) < 2:
        fail("expected a schedule summary per pass, got: %r" % (schedules,))
    first_states, first_worst = int(schedules[0][3]), float(schedules[0][5])
    last_states, last_worst = int(schedules[-1][3]), float(schedules[-1][5])
    if last_worst >= first_worst:
        fail(
            f"rescheduling did not shorten the worst state: {first_worst} ns -> "
            f"{last_worst} ns (tightening the budget must move work out of the "
            f"critical state, whether by adding states or rebalancing them)"
        )

    # The point of the whole exercise: the first attempt missed the clock and a
    # later one made it, without the user changing anything.
    checks = re.findall(
        r"^\[sweep\] \S+ synthesized as written \(standalone check\): "
        r"([\d.]+) MHz vs ([\d.]+) MHz goal - (PASS|FAIL)",
        out,
        re.M,
    )
    if len(checks) < 2:
        fail(f"expected a timing check per pass, got {checks!r}")
    if checks[0][2] != "FAIL":
        fail(
            f"the first (deliberately over-packed) schedule was supposed to miss "
            f"timing but passed at {checks[0][0]} MHz -- retune "
            f"START_BUDGET_SCALE or the design's clock goal"
        )
    if checks[-1][2] != "PASS":
        fail(f"the final schedule still misses timing: {checks[-1]}")
    if "ERROR: TIMING NOT MET" in out:
        fail("final build still does not meet timing")

    print(
        f"AUTO_FSM timing-iteration test passed: the first schedule missed the "
        f"clock at {checks[0][0]} MHz (worst state {first_worst} ns, "
        f"{first_states} states); after tightening, the FSM met it at "
        f"{checks[-1][0]} MHz (worst state {last_worst} ns, {last_states} states)."
    )


if __name__ == "__main__":
    main()
