# pyright: reportInvalidTypeForm=none
"""A sim_print on the sim_finish() cycle appears in VHDL simulation output, as
it does in native simulation (issue #361).

std.env.finish stops GHDL inside the delta cycle that calls it, so a print
process GHDL had not yet run at that clock edge was dropped: the "finishing"
line was missing from the cocotb + GHDL log, and the run still passed. Both
@MAINs print on the finishing cycle: `finisher` before its own sim_finish(),
and `watcher`, registered first, so that native simulation runs its print
before the finish too.

Registered in native_vs_vhdl_sim_tests.py: pypeline_sim_debug.py fails while
the VHDL log lacks the finishing cycle's lines.
"""

import os
import sys

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..")
)

from pypeline import MAIN, Reg, Wire, sim_finish, sim_print, uint8_t

NUM_CYCLES = 3

# The finisher's count, for the watcher to print
count_w: Wire[uint8_t]


@MAIN
def watcher():
    sim_print(f"watcher count={count_w}", debug=True)


@MAIN
def finisher():
    c: Reg[uint8_t]
    c = c + 1
    count_w = c
    sim_print(f"finisher c={c}", debug=True)
    if c == NUM_CYCLES:
        sim_finish()
