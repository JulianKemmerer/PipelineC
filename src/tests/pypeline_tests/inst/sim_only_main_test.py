# pyright: reportInvalidTypeForm=none
"""Simulation-only @MAINs in native simulation: a @MAIN over @sim_input (a
stimulus process) and two over @sim_output (a checker, and a finisher made
with MAIN(fn, name=)) around one hardware @MAIN. Run only via the multi-MAIN
runner (pypeline_sim.py sim_only_main_test.py --run N).

Checks, every cycle:
- the stimulus runs once, before its cycle converges, and the hardware
  @MAIN's output the checker reads is computed from that cycle's stimulus;
- the checker runs once, in the final pass only, never in a convergence pass;
- the finisher runs after the checker (registration order), so the last
  cycle's checks run before sim_finish() ends the run.
An @final(sim) hook checks both ran every cycle, so a run in which the sim-only
@MAINs never ran does not pass.
"""

import sys, os

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..")
)

from pypeline import (
    MAIN,
    Input,
    Output,
    final,
    sim_finish,
    sim_input,
    sim_output,
    uint8_t,
)

CYCLES = 8

in0: Input[uint8_t]
out0: Output[uint8_t]

# Runs of each sim-only body. A mutable container, not rebound module names:
# sim-only bodies run against a detached snapshot of this module's globals.
_runs = {"drive": 0, "check": 0}


@MAIN
def add_one():
    # Hardware: the only MAIN a build would see
    out0 = in0 + 1


@MAIN
@sim_input
def drive():
    in0 = 3 * _runs["drive"]
    _runs["drive"] += 1


@MAIN
@sim_output
def check():
    cycle = _runs["check"]
    assert _runs["drive"] == cycle + 1, (
        f"cycle {cycle}: the stimulus ran {_runs['drive']} time(s) by now, "
        f"expected {cycle + 1} (once per cycle, before the final pass)"
    )
    assert int(in0) == 3 * cycle, f"cycle {cycle}: in0 is {int(in0)}"
    assert int(out0) == 3 * cycle + 1, f"cycle {cycle}: out0 is {int(out0)}"
    _runs["check"] += 1


@sim_output
def finish_when_checked():
    if _runs["check"] == CYCLES:
        sim_finish()


MAIN(finish_when_checked, name="finisher")


@final(sim=True)
def all_cycles_ran():
    assert _runs == {"drive": CYCLES, "check": CYCLES}, _runs
    print(f"sim_only_main_test: {CYCLES} cycles, every sim-only @MAIN ran once each")
