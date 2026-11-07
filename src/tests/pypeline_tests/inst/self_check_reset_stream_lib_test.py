# pyright: reportInvalidTypeForm=none
"""Self-checking reset-equivalence test of stream library blocks: a chain of
make_stream_fifo, a full skid buffer and a forward skid buffer, with its
source, runs in two MAINs under reset_registers="all":

- dut_a is reset in cycle RESET_AT, with words in flight;
- dut_b is held in reset from cycle 0 to RESET_AT.

Both see the same backpressure, a function of the cycle. After RESET_AT a
reset block is in its power-up state, so the two chains must produce the
same output in every cycle: the checker (the default "requested" policy,
not reset) asserts that, and that words come out in order. Data is compared
only with valid: a FIFO's output data register holds whatever its memory
gives while nothing is valid.

Registered in native_vs_vhdl_sim_tests.py (--comb), which diffs native and
cocotb+GHDL sim_print(debug=True) output cycle by cycle.
"""

import sys, os

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..")
)

from pypeline import (
    MAIN,
    Feedback,
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
)
from stream.skid_buffer import make_skid_buffer
from stream.stream_fifo import make_stream_fifo

RESET_AT = 13
N_CYCLES = 40

fifo = make_stream_fifo(uint8_t, 4)
skid = make_skid_buffer(uint8_t)
skid_fwd = make_skid_buffer(uint8_t, "forward")
word_t = fifo.stream_intrf.stream_t


@struct
class chain_t(NamedTuple):
    out: word_t
    in_ready: uint1_t


@hw_func
def chain(x: word_t, out_ready: uint1_t) -> chain_t:
    r1: Feedback[uint1_t]
    r2: Feedback[uint1_t]
    a = fifo(fifo.fwd_t(stream=x), fifo.fb_t(ready=r1))
    b = skid(skid.fwd_t(stream=a.out_stream_if.stream), skid.fb_t(ready=r2))
    r1 = b.stream_in_if.ready
    c = skid_fwd(skid_fwd.fwd_t(stream=b.stream_out_if.stream), skid_fwd.fb_t(ready=out_ready))
    r2 = c.stream_in_if.ready
    return chain_t(out=c.stream_out_if.stream, in_ready=a.in_stream_if.ready)


clk = make_clock(100.0)
rst_a: Wire[uint1_t] = make_reset()
rst_b: Wire[uint1_t] = make_reset()
t_out: Wire[uint8_t]
sink_ready: Wire[uint1_t]
a_out: Wire[word_t]
b_out: Wire[word_t]


@MAIN(clk)
def rst_gen():
    t: Reg[uint8_t]
    rst_a = t == RESET_AT
    rst_b = t <= RESET_AT
    t_out = t
    sink_ready = (t & 3) != 2
    t += 1


@hw_func
def source_and_chain() -> word_t:
    n: Reg[uint8_t]
    x: word_t
    x.data = n * 3 + 1
    x.valid = (t_out & 7) != 5
    o = chain(x, sink_ready)
    if x.valid & o.in_ready:
        n += 1
    return o.out


@MAIN(clk, reset=rst_a, reset_registers="all")
def dut_a():
    a_out = source_and_chain()


@MAIN(clk, reset=rst_b, reset_registers="all")
def dut_b():
    b_out = source_and_chain()


@MAIN(clk)
def checker():
    expect: Reg[uint8_t]
    t: uint8_t = t_out
    if t == N_CYCLES + 1:
        sim_finish()
    a: word_t = a_out
    b: word_t = b_out
    if (t > RESET_AT) & (t <= N_CYCLES):
        sim_assert(a.valid == b.valid, f"valid differs at {t}: {a.valid} {b.valid}")
        if a.valid:
            sim_assert(a.data == b.data, f"data differs at {t}: {a.data} {b.data}")
        if a.valid & sink_ready:
            sim_assert(a.data == expect * 3 + 1, f"word {a.data} out of order at {t}")
            expect += 1
        if a.valid:
            sim_print(f"t={t} word={a.data}", debug=True)
        else:
            sim_print(f"t={t} none", debug=True)
