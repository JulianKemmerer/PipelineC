# pyright: reportInvalidTypeForm=none
"""Self-checking @MAIN test of a global FIFO, Fifo[T] of a struct: a producer
offers numbered words on 3 cycles out of 4, a consumer takes them on 1 cycle
out of 4, so the FIFO fills and pushes back. The consumer checks order with
sim_assert and calls sim_finish() after the last word.

Registered in native_vs_vhdl_sim_tests.py, which runs the native (--sim --comb)
and cocotb+GHDL (--cocotb --ghdl) sims and diffs their sim_print(debug=True)
output cycle by cycle, and in synth_tests.py (--comb, sky130).
"""

import sys, os

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..")
)

from pypeline import (
    MAIN,
    Fifo,
    NamedTuple,
    Output,
    Reg,
    global_fifo,
    sim_assert,
    sim_finish,
    sim_print,
    struct,
    uint1_t,
    uint8_t,
    uint16_t,
)

N_WORDS = 12


@struct
class word_t(NamedTuple):
    n: uint8_t
    sq: uint16_t


words: Fifo[word_t] = global_fifo(4)
# The last word's square: a top-level output keeps the FIFO in the --comb
# synthesis netlist
last_sq: Output[uint16_t]


@MAIN
def producer():
    t: Reg[uint8_t]
    n: Reg[uint8_t]
    valid: uint1_t = (t[0] | t[1]) & (n < N_WORDS)
    words.wr.stream.data = word_t(n=n, sq=n * n)
    words.wr.stream.valid = valid
    if valid & words.wr.ready:
        n += 1
    if valid & ~words.wr.ready:
        sim_print(f"self_check_global_fifo full at n={n}", debug=True)
    t += 1


@MAIN
def consumer():
    t: Reg[uint8_t]
    n: Reg[uint8_t]
    sq: Reg[uint16_t]
    last_sq = sq
    ready: uint1_t = t[1] & t[2]
    words.rd.ready = ready
    if ready & words.rd.stream.valid:
        w: word_t = words.rd.stream.data
        sim_assert(w.n == n, f"self_check_global_fifo: got word {w.n}, expected {n}")
        sim_assert(w.sq == n * n, f"self_check_global_fifo: word {n} square {w.sq}")
        # No debug print on the sim_finish() cycle -- whether a same-cycle
        # VHDL write flushes before std.env.finish kills GHDL is a
        # process-ordering race the cycle diff must not depend on.
        if n < N_WORDS - 1:
            sim_print(f"self_check_global_fifo pop n={w.n} sq={w.sq}", debug=True)
        if n == N_WORDS - 1:
            sim_finish()
        sq = w.sq
        n += 1
    t += 1
