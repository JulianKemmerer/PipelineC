# pyright: reportInvalidTypeForm=none
"""Native testbench of built_hardware_core_design.py, simulated on the
hardware built from built_hardware_top_design.py (see
built_hardware_sim_test.py). It prints the cycles each result took to arrive
and checks every value against the pure functions.

-D EXTRA_TAG=1 adds an AUTO_PIPELINE the build never decided, and
-D CALL_SPARE=1 calls the one the build only read."""

from pypeline import (
    AUTO_PIPELINE,
    MAIN,
    Reg,
    hw_func,
    param,
    sim_assert,
    sim_finish,
    sim_print,
    uint1_t,
    uint16_t,
)

import built_hardware_core_design as core

EXTRA_TAG = param("EXTRA_TAG", 0, help="1: read the latency of a tag the build never decided")
CALL_SPARE = param("CALL_SPARE", 0, help="1: call the tag the build read but never built")
RUN_CYCLES = 40  # long enough for both results at any depth this build picks


@hw_func
def extra_body(x: uint16_t) -> uint16_t:
    return x + 1


if EXTRA_TAG:
    EXTRA_LATENCY = AUTO_PIPELINE(extra_body, name="built_hardware_extra").latency

print(f"built_hardware_tb: BODY.latency {core.BODY.latency}")
print(f"built_hardware_tb: OPS_FSM.latency {core.OPS_FSM.latency}")
print(f"built_hardware_tb: SPARE.latency {core.SPARE_LATENCY}")


@MAIN(core.GOAL_MHZ)
def built_hardware_tb():
    n: Reg[uint16_t]  # cycle count
    first: Reg[uint16_t]  # cycle the first region result arrived
    seen: Reg[uint1_t]
    launched: Reg[uint16_t]  # cycle the FSM case launched
    fsm_busy: Reg[uint1_t]
    fsm_done: Reg[uint1_t]

    # Region: input n + 1 at cycle n, never zero, so the first nonzero output
    # marks the arrival of the first input
    core.body_in = n + 1
    out: uint16_t = core.body_out
    if seen == 1:
        sim_assert(out == core.divide_body(n - first + 1), "region result mismatch")
    elif out != 0:
        sim_print(f"built_hardware_tb: region result after {n} cycles")
        sim_assert(out == core.divide_body(1), "first region result mismatch")
        first = n
        seen = 1

    # FSM: one case, launched on the first cycle
    case: core.case_t
    case.a = 3
    case.b = 5
    case.c = 7
    case.d = 2
    s: core.OPS_FSM.in_stream_t
    s.data = case
    s.valid = 0
    if fsm_busy == 0 and fsm_done == 0:
        s.valid = 1
        fsm_busy = 1
        launched = n
    core.fsm_in = s
    o = core.fsm_out
    if CALL_SPARE:
        spare: uint16_t = core.SPARE(n)
    if o.valid and fsm_done == 0:
        sim_print(f"built_hardware_tb: FSM result after {n - launched} cycles")
        sim_assert(o.data == core.mixed_ops(case), "FSM result mismatch")
        fsm_done = 1
        fsm_busy = 0

    if n == RUN_CYCLES:
        sim_assert(seen == 1 and fsm_done == 1, "a result never arrived")
        sim_finish()
    n += 1
