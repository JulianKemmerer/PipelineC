# pyright: reportInvalidTypeForm=none
"""Self-checking @MAIN test: a free-running counter checks its own value against
the expected sequential count via sim_assert, then calls sim_finish() once done --
no external Python sim_call/assert harness needed. Pass/fail is entirely
determined by whether the simulation halts cleanly (sim_finish, no assertion
failure) vs. aborts (sim_assert failure) vs. runs forever without finishing.

Registered in native_vs_vhdl_sim_tests.py, which runs the native (--sim --comb)
and cocotb+GHDL (--cocotb --ghdl) sims and diffs their sim_print(debug=True)
output cycle by cycle -- one source file, two run modes, proving native and
VHDL sim agree. Modeled after wireguard-fpga's syn_tb testbenches (fixed
expected-value checks via sim_assert, sim_finish() on completion).
"""

import sys, os

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..")
)

from pypeline import MAIN, Reg, sim_assert, sim_finish, sim_print, uint8_t

NUM_COUNTS = 10


@MAIN
def self_check_counter():
    n: Reg[uint8_t]
    sim_assert(n < NUM_COUNTS, f"counter exceeded expected range: {n}")
    # No debug print on the sim_finish() cycle -- whether a same-cycle VHDL
    # write flushes before std.env.finish kills GHDL is a process-ordering
    # race the cycle diff must not depend on.
    if n < NUM_COUNTS - 1:
        sim_print(f"self_check_counter n={n}", debug=True)
    if n == NUM_COUNTS - 1:
        sim_finish()
    n += 1
