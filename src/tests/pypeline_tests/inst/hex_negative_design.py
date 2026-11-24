# pyright: reportInvalidTypeForm=none
"""Known-issue fixture: Pypeline's hex() of a negative signed value.

The guide says Pypeline's hex() renders identically in native and VHDL
simulation. For a negative intN_t value, native simulation prints a minus sign
and the magnitude (int8_t -1 gives "-1", int32_t -0x80000000 gives
"-80000000"), while VHDL simulation prints the value's bits ("FF",
"80000000").

Registered in known_issues_tests.py (expect_fail) through pypeline_sim_debug.py,
which fails while the two simulations print different text, and passes once
they print the same.
"""

import os
import sys

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..")
)

from pypeline import MAIN, Reg, hex, int8_t, int32_t, sim_finish, sim_print, uint1_t


@MAIN
def top():
    done: Reg[uint1_t]
    a: int8_t = -1
    b: int32_t = -0x80000000
    c: int32_t = -0x800
    # Print in cycle 0, finish in cycle 1 without a print: a print on the
    # sim_finish() cycle is missing from VHDL output (#361).
    if done:
        sim_finish()
    else:
        sim_print(f"a={hex(a)} b={hex(b)} c={hex(c)}", debug=True)
    done = 1
