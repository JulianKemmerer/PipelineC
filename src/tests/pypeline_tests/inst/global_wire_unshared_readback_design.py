# pyright: reportInvalidTypeForm=none
"""Known issue: a global wire that one function writes and reads back, in a
design where no global wire is shared, produces invalid VHDL.

The readback gives the function a w_PYPELINE_READBACK field in its
global_to_module record (LOGIC.LOGIC_NEEDS_GLOBAL_TO_MODULE), so top.vhd and
the MAIN's ports use the global_wires_pkg record types. The package itself is
only written when some wire is shared (VHDL.NEEDS_GLOBAL_WIRES_VHDL_PACKAGE),
so here it is missing and GHDL rejects top.vhd: 'signal "global_to_module"
does not designate a record'. Adding any shared wire makes it pass.

Registered in known_issues_tests.py (expect_fail): pypeline_sim_debug.py's
cocotb+GHDL run fails at VHDL analysis while the bug is present, and the
native and GHDL logs MATCH once it is fixed.
"""

import os
import sys

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..")
)

from pypeline import MAIN, Reg, Wire, sim_finish, sim_print, uint8_t

w: Wire[uint8_t]


@MAIN
def readback_top():
    t: Reg[uint8_t]
    w = t
    if t < 3:
        sim_print(f"t={t} w={w}", debug=True)  # reads w back
    if t == 4:  # one cycle after the last print
        sim_finish()
    t += 1
