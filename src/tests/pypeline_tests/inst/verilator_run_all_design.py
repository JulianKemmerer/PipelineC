# pyright: reportInvalidTypeForm=none
"""Known-issue fixture: a design that ends itself with sim_finish() in cycle 4.
See verilator_run_all_test.py.
"""

import os
import sys

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..")
)

from pypeline import MAIN, Reg, sim_finish, uint8_t


@MAIN
def top():
    cyc: Reg[uint8_t]
    if cyc == 4:
        sim_finish()
    cyc += 1
