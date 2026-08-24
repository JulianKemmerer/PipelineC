# pyright: reportInvalidTypeForm=none
"""Self-checking make_stream_autofsm design: drives the AUTOFSM valid/ready
stream wrapper (include/pypeline/stream/stream_autofsm.py) with a sequence of
inputs, toggles the DOWNSTREAM ready bit every cycle so real backpressure is
exercised (not just the raw FSM's pulse-and-ignore boundary), and checks
every result in hardware with sim_assert, calling sim_finish() when all cases
have passed. Pass/fail is decided entirely by whether the simulation halts
cleanly.

Registered in native_sim_tests.py, synth_tests.py (a real non---comb build,
proving the wrapper elaborates and synthesises with a real AUTOFSM schedule
installed underneath it), and TWICE in native_vs_vhdl_sim_tests.py: once with
--comb (the AUTOFSM call site inside the wrapper is still the combinational
passthrough) and once without (a full build whose native sim then runs
against the REAL scheduled FSM latency). Both diff native against cocotb+GHDL
cycle by cycle; the non---comb one is what proves the wrapper's generated
hardware -- FSM plus handshake registers -- computes and sequences the same
thing as the pure function it replaced.

The testbench reacts to `o.stream_out_if.stream.valid & ready_now` (a real
"consumed this cycle" condition) instead of counting cycles, mirroring
self_check_autofsm_test.py's `o.valid` reaction -- the identical source is
correct at any latency: 1 in a --comb build (wrapper latency floors at
fsm.latency + 1 == 0 + 1) and fsm.latency + 1 in a scheduled build.
"""

import os
import sys

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..")
)
sys.path.insert(
    0,
    os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "..",
        "..",
        "..",
        "..",
        "include",
        "pypeline",
    ),
)

from pypeline import (
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

from stream.stream_autofsm import make_stream_autofsm

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
    a conditional (variety for the code generator) -- same body as
    self_check_autofsm_test.py's mixed_ops, reused here for the same reason:
    well-understood int16 arithmetic that stays inside safe bounds."""
    t0: int16_t = x.a + x.b
    t1: int16_t = t0 + x.c
    t2: int16_t = t1 - x.d
    t3: int16_t = t2 + t0
    half: int16_t = t3 >> 1
    rv: int16_t = half
    if t3 > 100:
        rv = half + x.a
    return rv


OPS_FSM, OPS_FSM_T = make_stream_autofsm(mixed_ops)


@MAIN(25.0)
def self_check_stream_autofsm() -> int16_t:
    # Returning the last result gives the design a real output port -- see
    # self_check_autofsm_test.py's comment on why this matters for synthesis.
    last: Reg[int16_t]
    case_idx: Reg[uint4_t]
    sent: Reg[uint1_t]  # current case already accepted, awaiting its result
    ready_reg: Reg[uint1_t]  # toggles downstream ready every cycle

    # Inputs derived arithmetically from the case index, so no lookup table
    # (and therefore no dynamic array indexing) is needed in the testbench.
    x: case_t
    x.a = case_idx + 1
    x.b = case_idx + 2
    x.c = case_idx + 3
    x.d = case_idx + 4

    # Read old value, written for next cycle further down (matches
    # stream_pipeline.py's ready_reg convention) -- so ready_now is the value
    # actually presented to OPS_FSM's stream_out_if.ready this cycle.
    ready_now: uint1_t = ready_reg
    ready_reg = ~ready_reg

    in_stream: OPS_FSM.in_intrf.stream_t
    in_stream.data = x
    in_stream.valid = ~sent

    o = OPS_FSM(
        OPS_FSM.in_fwd_t(stream=in_stream),
        OPS_FSM.out_fb_t(ready=ready_now),
    )

    if in_stream.valid & o.stream_in_if.ready:
        sent = 1

    consumed: uint1_t = o.stream_out_if.stream.valid & ready_now
    if consumed:
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
        sim_assert(
            o.stream_out_if.stream.data == want,
            "make_stream_autofsm result did not match the pure function",
        )
        last = o.stream_out_if.stream.data
        sent = 0
        # No debug print on the sim_finish() cycle -- see self_check_counter_test.py.
        if case_idx < NUM_CASES - 1:
            sim_print(
                f"self_check_stream_autofsm case_idx={case_idx} data={o.stream_out_if.stream.data}",
                debug=True,
            )
        if case_idx == NUM_CASES - 1:
            sim_finish()
        case_idx += 1

    return last
