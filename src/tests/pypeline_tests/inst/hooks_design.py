# pyright: reportInvalidTypeForm=none
"""@initial/@final hooks design, shared by hooks_test.py (native sim, run
in-process) and hooks_order_test.py (pypelinec subprocesses: native, pipelined
native, cocotb+GHDL).

Every hook appends its name to EVENTS and prints a "HOOK: <name>" marker, so a
test can check both what ran and in what order. HOOKS_TEST_MODE (environment)
picks a variant:
  finish       -- the counter calls sim_finish() on cycle NUM_CYCLES-1
  cutoff       -- no sim_finish(); the run ends at --run N
  assert       -- @sim_output fails an assert on cycle 2
  final_raises -- like finish, and the @final(sim) hook raises
  hook_finish  -- an @initial(sim) hook calls sim_finish()
  call_from_hw -- a MAIN calls a hook (an elaboration error)
"""

import sys, os

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..")
)

from pypeline import (
    MAIN,
    Output,
    Reg,
    final,
    initial,
    sim_finish,
    sim_input,
    sim_output,
    uint8_t,
    wires,
)

MODE = os.environ.get("HOOKS_TEST_MODE", "finish")
NUM_CYCLES = 5
# The counter never reaches 255 within any test's cycle count
FINISH_AT = 255 if MODE == "cutoff" else NUM_CYCLES - 1

# Mutated in place only: @sim_input/@sim_output bodies run against a detached
# copy of this module's globals
EVENTS = []
SIM_INITIALS = {"both_initial", "sim_initial_a", "sim_initial_b"}


def _event(name):
    EVENTS.append(name)
    print(f"HOOK: {name}", flush=True)


@initial
def both_initial():
    _event("both_initial")


@initial(sim=True)
def sim_initial_a():
    _event("sim_initial_a")


@initial(sim=True)
def sim_initial_b():
    _event("sim_initial_b")
    if MODE == "hook_finish":
        sim_finish()


@initial(syn=True)
def syn_initial():
    _event("syn_initial")


@final
def both_final():
    _event("both_final")


@final(sim=True)
def sim_final():
    _event("sim_final")
    if MODE == "final_raises":
        raise AssertionError("sim_final: deliberate hook failure")


@final(syn=True)
def syn_final():
    _event("syn_final")


@sim_input
def drive():
    missing = SIM_INITIALS - set(EVENTS)
    assert not missing, f"first @sim_input ran before @initial hooks {missing}"
    EVENTS.append("sim_input")


@sim_output
def observe():
    EVENTS.append("sim_output")
    if MODE == "assert" and EVENTS.count("sim_output") == 3:
        assert False, "observe: deliberate sim assert"


# Registered before the counter so the sim_finish() cycle's @sim_output still runs.
# @wires: no hardware at all, so nothing for a synthesis run to time.
@MAIN
@wires
def hooks_tb():
    drive()
    observe()


CALL_FROM_HW = MODE == "call_from_hw"
count_out: Output[uint8_t]


@MAIN
def hooks_counter():
    n: Reg[uint8_t]
    if n == FINISH_AT:
        sim_finish()
    if CALL_FROM_HW:
        both_final()
    count_out = n
    n += 1
