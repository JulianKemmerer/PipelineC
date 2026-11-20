# pyright: reportInvalidTypeForm=none
"""Regression test for issue #384: a global wire that one function writes and
reads back, in a design where no global wire is shared, builds valid VHDL.

The readback gives the function a w_PYPELINE_READBACK field in its
global_to_module record (LOGIC.LOGIC_NEEDS_GLOBAL_TO_MODULE), so top.vhd and
the MAIN's ports use the global_wires_pkg record types. The package is written
for any design where a MAIN has such a record
(VHDL.NEEDS_GLOBAL_WIRES_VHDL_PACKAGE), not only when a wire is shared, so GHDL
accepts the top.

Registered in native_vs_vhdl_sim_tests.py: the native sim and the cocotb+GHDL
sim of the generated VHDL print the same values, the readback reading zero
before the write.
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
