# pyright: reportInvalidTypeForm=none
"""Fixture for sim_assert_fail_print_test.py: a sim_print on the cycle a
sim_assert fails, and a message that prints a value the next clock edge
changes. Native simulation prints "c=1" to "c=3", then stops on the assertion
with "c reached 3". See that file's docstring.
"""

import os
import sys

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..")
)

from pypeline import MAIN, Reg, sim_assert, sim_print, uint8_t


@MAIN
def sim_assert_fail_print():
    c: Reg[uint8_t]
    c = c + 1
    sim_print(f"c={c}")
    sim_assert(c != 3, f"c reached {c}")
