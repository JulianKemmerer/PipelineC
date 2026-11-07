# pyright: reportInvalidTypeForm=none
"""Self-checking @MAIN test of global instances resetting with their clock's
reset. clk's primary reset is gen_rst, a reset Wire that rst_gen (reset=None)
pulses in cycle RESET_AT. With no keyword on their declarations:

- c1: Inst[counter] restarts from its initial value;
- piped: Inst[AUTO_PIPELINE(plus7, latency=LAT)] drops what it holds;
- words: a same-clock Fifo[T] empties: its read end shows no valid word in
  the cycle after the reset, and the next word read is the first one the
  producer (reset_registers="all", the same reset) sends after it.

The checker uses all three under the default "requested" policy, so it is
not reset itself and checks the values across the reset. The pipeline's
output in the LAT cycles after its first input and after the reset is not
checked: it is the function of zeroed stages there, which native sim does
not model.

Registered in native_vs_vhdl_sim_tests.py (--comb), which diffs native and
cocotb+GHDL sim_print(debug=True) output cycle by cycle.
"""

import sys, os

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..")
)

from pypeline import (
    AUTO_PIPELINE,
    MAIN,
    Fifo,
    Inst,
    Reg,
    Wire,
    global_fifo,
    hw_func,
    make_clock,
    make_reset,
    sim_assert,
    sim_finish,
    sim_print,
    uint1_t,
    uint8_t,
)

LAT = 2
RESET_AT = 9
N_CYCLES = 24
COUNT_START = 4


@hw_func
def counter(step: uint8_t) -> uint8_t:
    n: Reg[uint8_t] = COUNT_START
    rv = n
    n += step
    return rv


@hw_func
def plus7(x: uint8_t) -> uint8_t:
    return x + 7


gen_rst: Wire[uint1_t] = make_reset()
clk = make_clock(100.0, reset=gen_rst)
t_out: Wire[uint8_t]

c1: Inst[counter]
piped: Inst[AUTO_PIPELINE(plus7, latency=LAT)]
words: Fifo[uint8_t] = global_fifo(4)


@MAIN(clk, reset=None)
def rst_gen():
    t: Reg[uint8_t]
    gen_rst = t == RESET_AT
    t_out = t
    t += 1


@MAIN(clk, reset_registers="all")
def producer():
    n: Reg[uint8_t]
    words.wr.stream.data = n
    words.wr.stream.valid = 1
    if words.wr.ready:
        n += 1


@MAIN(clk)
def checker():
    expect: Reg[uint8_t]
    t: uint8_t = t_out
    if t == N_CYCLES + 1:
        sim_finish()
    c1.step = 1
    piped.x = t
    take: uint1_t = (t & 1) == 0  # every other cycle, so words wait in the FIFO
    words.rd.ready = take
    # The counter: COUNT_START + cycles since its last start
    since: uint8_t = t
    if t > RESET_AT:
        since = t - (RESET_AT + 1)
    sim_assert(c1.out == COUNT_START + since, f"c1: got {c1.out} at {t}")
    # The pipeline, outside the cycles where its stages hold no input
    piped_ok: uint1_t = (since >= LAT) & (t <= N_CYCLES)
    if piped_ok:
        sim_assert(piped.out == t + 5, f"piped: got {piped.out} at {t}")
    # The FIFO
    if t == RESET_AT + 1:
        sim_assert(words.rd.stream.valid == 0, f"FIFO not empty after reset")
    got: uint1_t = take & words.rd.stream.valid
    if got:
        sim_assert(
            words.rd.stream.data == expect, f"FIFO: got {words.rd.stream.data} at {t}"
        )
    if t == RESET_AT:
        expect = 0
    elif got:
        expect = expect + 1
    if t <= N_CYCLES:
        sim_print(
            f"t={t} c1={c1.out} valid={words.rd.stream.valid} got={got} expect={expect}",
            debug=True,
        )
        if piped_ok:
            sim_print(f"t={t} piped={piped.out}", debug=True)
