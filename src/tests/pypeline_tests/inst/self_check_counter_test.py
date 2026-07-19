# pyright: reportInvalidTypeForm=none
"""Self-checking @MAIN test: a free-running counter checks its own value against
the expected sequential count via sim_assert, then calls sim_finish() once done --
no external Python sim_call/assert harness needed. Pass/fail is entirely
determined by whether the simulation halts cleanly (sim_finish, no assertion
failure) vs. aborts (sim_assert failure) vs. runs forever without finishing.

Registered in both native_sim_tests.py (--sim --comb --run all) and vhdl_sim_tests.py
(--sim --comb --cocotb --ghdl --run all) -- same source file, two run modes,
proving native and VHDL sim agree. Modeled after wireguard-fpga's syn_tb
testbenches (fixed expected-value checks via sim_assert, sim_finish() on
completion).
"""

import sys, os

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..")
)

from pypeline import MAIN, Reg, sim_assert, sim_finish, uint8_t

NUM_COUNTS = 10


@MAIN
def self_check_counter():
    n: Reg[uint8_t]
    sim_assert(n < NUM_COUNTS, f"counter exceeded expected range: {n}")
    if n == NUM_COUNTS - 1:
        sim_finish()
    n += 1
