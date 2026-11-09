# pyright: reportInvalidTypeForm=none
"""Self-checking @MAIN test of a synchronous reset of a pipelined pure MAIN:
the sweep slices pipelined_main (the double-division cone of
native_vs_vhdl_pipelined_main_test.py) to meet 50 MHz, and gen_rst, a reset
Wire the MAIN rst_gen pulses in cycles 0 and RESET_AT, resets its stage
registers (reset_registers="all").

The checker (not reset) sends a valid word with seq = cycle every cycle and
learns the depth k from the first valid output. It asserts that the word
sent in a reset cycle never comes out: the first valid output is seq 1, and
after the mid-run reset the outputs stay invalid for k cycles (the stage
registers hold null, not the words in flight) before seq RESET_AT + 1.

Native sim emulates the MAIN's depth as delayed global writes
(pypeline._sim_pipelined_main_info), so this checks that a reset replaces
them with zeros. Registered in native_vs_vhdl_sim_tests.py with a sky130
build, running native and cocotb+GHDL sims and diffing their
sim_print(debug=True) output cycle by cycle (the data of valid words, and
the valid bit of every cycle).
"""

import os
import sys

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..")
)

from pypeline import (
    MAIN,
    NamedTuple,
    Reg,
    Wire,
    hw_func,
    make_clock,
    make_reset,
    sim_assert,
    sim_finish,
    sim_print,
    struct,
    uint1_t,
    uint8_t,
    uint16_t,
)

RESET_AT = 12
N_CYCLES = 30


@struct
class word_t(NamedTuple):
    data: uint8_t
    seq: uint16_t
    valid: uint1_t


clk = make_clock(50.0)
gen_rst: Wire[uint1_t] = make_reset()
t_out: Wire[uint16_t]
in_word: Wire[word_t]
out_word: Wire[word_t]


@hw_func
def heavy(x: uint8_t) -> uint8_t:
    return x / ~x


@MAIN(clk)
def rst_gen():
    t: Reg[uint16_t]
    gen_rst = (t == 0) | (t == RESET_AT)
    t_out = t
    t = t + 1


# Pure comb MAIN: no Reg/Feedback state, so the sweep slices it as one cut
# subtree and its stage registers are all the state it has
@MAIN(clk, reset=gen_rst, reset_registers="all")
def pipelined_main():
    v: word_t = in_word
    o: word_t
    a: uint8_t = heavy(v.data)
    o.data = heavy(a) ^ v.data
    o.seq = v.seq
    o.valid = v.valid
    out_word = o


# Returns the observed output: without an output port synthesis optimizes the
# whole design away
@MAIN(clk)
def checker() -> word_t:
    lat: Reg[uint16_t]
    seen: Reg[uint1_t]
    t: uint16_t = t_out
    if t == N_CYCLES + 1:
        sim_finish()

    i: word_t
    i.valid = 1
    i.seq = t
    i.data = (t & 127) + 3  # 3..130: never 255 (~x would be 0, div by 0)
    in_word = i

    o: word_t = out_word
    # In cycle 0 the stage registers hold no value yet (their power-up value
    # in VHDL simulation is 'U')
    if (t > 0) & (t <= N_CYCLES):
        if seen == 0:
            if o.valid:
                # The word sent in reset cycle 0 is gone
                sim_assert(o.seq == 1, f"first valid seq {o.seq} at {t}, not 1")
                lat = t - o.seq
                seen = 1
        elif (t > RESET_AT) & (t <= RESET_AT + lat):
            sim_assert(o.valid == 0, f"stale valid at {t}: seq {o.seq}")
        else:
            sim_assert(o.valid == 1, f"missing valid at {t}")
            sim_assert(o.seq == t - lat, f"seq {o.seq} at {t}, depth {lat}")
        # While nothing is valid, the comb logic after the last stage computes
        # from null registers in hardware, and native sim shows typed zeros:
        # only the valid bit is compared then
        if o.valid:
            sim_print(f"t={t} valid=1 seq={o.seq} data={o.data}", debug=True)
        else:
            sim_print(f"t={t} valid=0", debug=True)
    return o
