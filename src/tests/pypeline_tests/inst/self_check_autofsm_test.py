# pyright: reportInvalidTypeForm=none
"""Self-checking AUTOFSM design: drives a resource-shared FSM with a sequence of
inputs and checks every result in hardware with sim_assert, calling sim_finish()
when all cases have passed. Pass/fail is decided entirely by whether the
simulation halts cleanly.

Registered in native_sim_tests.py, and TWICE in native_vs_vhdl_sim_tests.py:
once with --comb (the call site is still the combinational passthrough) and
once without (a full build whose native sim then runs against the REAL
scheduled FSM latency). Both diff native against cocotb+GHDL cycle by cycle;
the non---comb one is what proves the generated FSM hardware computes the
same thing as the pure function it replaced.

The testbench deliberately reacts to `o.valid` instead of counting cycles, so
the identical source is correct at any latency: 0 in a --comb build (where the
call site is still the combinational passthrough) and .latency in a scheduled
build. That property is worth preserving in any AUTOFSM testbench.
"""

import os
import sys

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..")
)

from pypeline import (
    AUTOFSM,
    MAIN,
    NamedTuple,
    Reg,
    hw_func,
    int16_t,
    sim_assert,
    sim_finish,
    sim_print,
    struct,
    uint1_t,
    uint4_t,
)

NUM_CASES = 6


@struct
class case_t(NamedTuple):
    a: int16_t
    b: int16_t
    c: int16_t
    d: int16_t


@hw_func
def mixed_ops(x: case_t) -> int16_t:
    """Repeated adds/subtracts (the shareable part) plus a shift, a compare and
    a conditional (variety for the code generator)."""
    t0: int16_t = x.a + x.b
    t1: int16_t = t0 + x.c
    t2: int16_t = t1 - x.d
    t3: int16_t = t2 + t0
    half: int16_t = t3 >> 1
    rv: int16_t = half
    if t3 > 100:
        rv = half + x.a
    return rv


OPS_FSM = AUTOFSM(mixed_ops)


@MAIN(25.0)
def self_check_autofsm() -> int16_t:
    # Returning the last result gives the design a real output port. Without
    # one, synthesis optimizes the whole self-contained state machine away and
    # the timing report has no path to measure -- so this design could only be
    # run in --comb mode, where the AUTOFSM call site is still a passthrough
    # and the generated FSM would never be exercised in hardware at all.
    last: Reg[int16_t]
    case_idx: Reg[uint4_t]
    busy: Reg[uint1_t]

    # Inputs derived arithmetically from the case index, so no lookup table (and
    # therefore no dynamic array indexing) is needed in the testbench.
    x: case_t
    x.a = case_idx + 1
    x.b = case_idx + 2
    x.c = case_idx + 3
    x.d = case_idx + 4

    s: OPS_FSM.in_stream_t
    s.data = x
    s.valid = 0
    if busy == 0:
        s.valid = 1
        busy = 1

    o = OPS_FSM(s)

    if o.valid:
        # Reference computed the same way as mixed_ops, in the testbench:
        #   t0 = (i+1)+(i+2), t1 = t0+(i+3), t2 = t1-(i+4), t3 = t2+t0
        t0: int16_t = (case_idx + 1) + (case_idx + 2)
        t1: int16_t = t0 + (case_idx + 3)
        t2: int16_t = t1 - (case_idx + 4)
        t3: int16_t = t2 + t0
        half: int16_t = t3 >> 1
        want: int16_t = half
        if t3 > 100:
            want = half + (case_idx + 1)
        sim_assert(o.data == want, "AUTOFSM result did not match the pure function")
        last = o.data
        busy = 0
        # No debug print on the sim_finish() cycle -- see self_check_counter_test.py.
        if case_idx < NUM_CASES - 1:
            sim_print(f"self_check_autofsm case_idx={case_idx} data={o.data}", debug=True)
        if case_idx == NUM_CASES - 1:
            sim_finish()
        case_idx += 1

    return last
