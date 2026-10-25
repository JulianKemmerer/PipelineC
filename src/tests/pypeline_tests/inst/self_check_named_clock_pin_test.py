# pyright: reportInvalidTypeForm=none
"""Self-checking @MAIN test of a named clock arriving on a pin: two MAINs on
sys_clk, make_clock(50.0, name="sys"), whose pin SYS_CLK replaces its port
clk_50p0_sys. A producer pushes a counting sequence through a global FIFO,
and a consumer checks its order with sim_assert and calls sim_finish() after
the last word.

The generated cocotb testbench must drive the one clock SYS_CLK: its clock
list (SIM.GET_SIM_GEN_INFO) removes the named clock's own port by its full
name, clk_50p0_sys, and keeps the pin.

Registered in native_vs_vhdl_sim_tests.py, which runs the native (--sim --comb)
and cocotb+GHDL (--cocotb --ghdl) sims and diffs their sim_print(debug=True)
output cycle by cycle.
"""

import sys, os

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..")
)

from pypeline import (
    MAIN,
    Fifo,
    Input,
    Reg,
    global_fifo,
    make_clock,
    sim_assert,
    sim_finish,
    sim_print,
    uint1_t,
    uint8_t,
)

N_WORDS = 10

sys_clk = make_clock(50.0, name="sys")  # the clock clk_50p0_sys
SYS_CLK: Input[uint1_t] = sys_clk  # arrives on this pin

words: Fifo[uint8_t] = global_fifo(4)


@MAIN(sys_clk)
def producer():
    n: Reg[uint8_t]
    words.wr.stream.data = n
    words.wr.stream.valid = n < N_WORDS
    if words.wr.ready & (n < N_WORDS):
        n += 1


@MAIN(sys_clk)
def consumer():
    t: Reg[uint8_t]
    n: Reg[uint8_t]
    ready: uint1_t = t[0]
    words.rd.ready = ready
    if ready & words.rd.stream.valid:
        w: uint8_t = words.rd.stream.data
        sim_assert(w == n, f"self_check_named_clock_pin: got {w}, expected {n}")
        # No debug print on the sim_finish() cycle (see native_vs_vhdl_sim_tests.py)
        if n < N_WORDS - 1:
            sim_print(f"self_check_named_clock_pin pop {w}", debug=True)
        if n == N_WORDS - 1:
            sim_finish()
        n += 1
    t += 1
