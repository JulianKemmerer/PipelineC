# pyright: reportInvalidTypeForm=none
"""Self-checking AUTO_FSM design whose operations are too slow for one state,
so forced descent must open them: a 32-bit add and subtract and a 16x16
inferred multiply are split into half-width built-in operators (operators/
soft_add.make_soft_add_split, make_soft_sub_split, operators/soft_mult.
make_soft_mult_split), recursively, until each piece fits.

Registered in native_vs_vhdl_sim_tests.py (non---comb) with a small
--auto_fsm_budget_scale, which is what forces the descent: the generated FSM
then calls the split equivalents' carry-in-bit adds, bit_assign recombination
and pinned inferred products, and the cycle diff proves native sim and GHDL
agree on them -- sim_call checks in soft_ops_test.py cover the factories'
arithmetic but never elaborate them (see docs/pypeline_TESTS.md).

Same testbench shape as self_check_auto_fsm_test.py: it reacts to `o.valid`,
so it is correct at any latency.
"""

import os
import sys

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..")
)

from pypeline import (
    AUTO_FSM,
    MAIN,
    NamedTuple,
    Reg,
    hw_func,
    make_uint_t,
    sim_assert,
    sim_finish,
    sim_print,
    struct,
    uint1_t,
    uint4_t,
    uint16_t,
    uint32_t,
)

uint17_t = make_uint_t(17)
uint33_t = make_uint_t(33)

NUM_CASES = 6


@struct
class case_t(NamedTuple):
    a: uint32_t
    b: uint32_t
    m: uint16_t
    n: uint16_t


@struct
class result_t(NamedTuple):
    s: uint33_t
    d: uint32_t
    p: uint32_t


@hw_func
def wide_ops(x: case_t) -> result_t:
    """Unsigned add (carry out), subtract (wraps) and inferred product."""
    o: result_t
    o.s = x.a + x.b
    o.d = x.a - x.b
    o.p = x.m * x.n
    return o


OPS_FSM = AUTO_FSM(wide_ops)


@MAIN(25.0)
def self_check_auto_fsm_split() -> uint32_t:
    # A real output port keeps synthesis from deleting the FSM (see
    # self_check_auto_fsm_test.py).
    last: Reg[uint32_t]
    case_idx: Reg[uint4_t]
    busy: Reg[uint1_t]

    # Wide operands derived from the case index: carries cross the split
    # points, and a < b on odd cases so the subtract wraps.
    x: case_t
    x.a = 0xF0E1D2C3 + (case_idx * 0x01234567)
    x.b = 0x0F1E2D3C + (case_idx * 0x13579BDF)
    x.m = 0xFFFF - (case_idx * 0x0123)
    x.n = 0xABCD + (case_idx * 0x0456)

    s: OPS_FSM.in_stream_t
    s.data = x
    s.valid = 0
    if busy == 0:
        s.valid = 1
        busy = 1

    o = OPS_FSM(s)

    if o.valid:
        want_s: uint33_t = x.a + x.b
        want_d: uint32_t = x.a - x.b
        want_p: uint32_t = x.m * x.n
        sim_assert(o.data.s == want_s, "split add did not match")
        sim_assert(o.data.d == want_d, "split subtract did not match")
        sim_assert(o.data.p == want_p, "split multiply did not match")
        last = o.data.p ^ o.data.d
        busy = 0
        # Printed as 16/17-bit halves: VHDL prints through a 32-bit signed
        # integer, so a value of 2**31 or more stops GHDL (#360).
        s_lo: uint16_t = o.data.s
        s_hi: uint17_t = o.data.s >> 16
        d_lo: uint16_t = o.data.d
        d_hi: uint16_t = o.data.d >> 16
        p_lo: uint16_t = o.data.p
        p_hi: uint16_t = o.data.p >> 16
        # No debug print on the sim_finish() cycle -- see self_check_counter_test.py.
        if case_idx < NUM_CASES - 1:
            sim_print(
                f"self_check_auto_fsm_split case_idx={case_idx} s={s_hi}:{s_lo} "
                f"d={d_hi}:{d_lo} p={p_hi}:{p_lo}",
                debug=True,
            )
        if case_idx == NUM_CASES - 1:
            sim_finish()
        case_idx += 1

    return last
