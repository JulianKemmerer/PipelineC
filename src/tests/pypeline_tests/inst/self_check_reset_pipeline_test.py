# pyright: reportInvalidTypeForm=none
"""Self-checking @MAIN test of a synchronous reset of a pipeline: dut calls
AUTO_PIPELINE(scale, latency=LAT) every cycle under reset_registers="all",
reset by gen_rst, a reset Wire the MAIN rst_gen pulses in cycles 0 and
RESET_AT.
scale multiplies and adds, so its stage registers carry data and a valid bit.

The source (tb, "requested", not reset) sends a valid word every cycle. The
checker asserts that every valid output is the right function of its seq,
that seqs follow each other, and that a reset leaves nothing stale: after
it, outputs stay invalid for LAT cycles, and the first valid one is the word
sent in the cycle after the reset.

Registered in native_vs_vhdl_sim_tests.py twice: --comb (a fixed latency is
built even then) and a sky130 build, each running native and cocotb+GHDL
sims and diffing their sim_print(debug=True) output cycle by cycle.
"""

import os
import sys

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..")
)

from pypeline import (
    AUTO_PIPELINE,
    MAIN,
    NamedTuple,
    Input,
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
    uint32_t,
)

LAT = 2
GAIN = 3
RESET_AT = 9
N_CYCLES = 30


@struct
class sample_t(NamedTuple):
    data: uint16_t
    seq: uint8_t
    valid: uint1_t


@struct
class result_t(NamedTuple):
    product: uint32_t
    seq: uint8_t
    valid: uint1_t


rst: Input[uint1_t] = make_reset()
clk = make_clock(100.0, reset=rst)
gen_rst: Wire[uint1_t] = make_reset()
t_out: Wire[uint8_t]
in_sample: Wire[sample_t]
out_result: Wire[result_t]


@hw_func
def scale(s: sample_t) -> result_t:
    r: result_t
    r.product = (s.data * GAIN + s.data) + (s.data + 1)
    r.seq = s.seq
    r.valid = s.valid
    return r


ap = AUTO_PIPELINE(scale, latency=LAT)


@MAIN(clk)
def rst_gen():
    t: Reg[uint8_t]
    gen_rst = (t == 0) | (t == RESET_AT)
    t_out = t
    t = t + 1


@MAIN(clk, reset=gen_rst, reset_registers="all")
def dut():
    out_result = ap(in_sample)


@MAIN(clk)
def tb():
    s: sample_t
    s.data = t_out * 7 + 2
    s.seq = t_out
    s.valid = 1
    in_sample = s


@MAIN(clk)
def checker() -> uint32_t:
    # Returning the product gives the design an output port, without which
    # synthesis optimizes the whole design away
    expect_seq: Reg[uint8_t]
    t: uint8_t = t_out
    o: result_t = out_result
    if t == N_CYCLES + 1:
        sim_finish()
    # In cycle 0 the stage registers hold no value yet (their power-up value
    # in VHDL simulation is 'U'); for LAT cycles after each reset edge nothing
    # valid may come out
    blank: uint1_t = ((t > 0) & (t <= LAT)) | (
        (t > RESET_AT) & (t <= RESET_AT + LAT)
    )
    if blank:
        sim_assert(o.valid == 0, f"stale valid at {t}: seq {o.seq}")
    elif (t > 0) & (t <= N_CYCLES):
        sim_assert(o.valid == 1, f"missing valid at {t}")
        d: uint32_t = o.seq * 7 + 2
        expected: uint32_t = (d * GAIN + d) + (d + 1)
        sim_assert(o.product == expected, f"product {o.product} != {expected} at {t}")
        sim_assert(o.seq == expect_seq, f"seq {o.seq} != {expect_seq} at {t}")
    if (t > 0) & (t <= N_CYCLES):
        sim_print(f"t={t} valid={o.valid} seq={o.seq} product={o.product}", debug=True)
    if (t == 0) | (t == RESET_AT):
        expect_seq = t + 1
    elif o.valid & (blank == 0):
        expect_seq = expect_seq + 1
    return o.product
