# pyright: reportInvalidTypeForm=none
"""Known-issue fixture: simulation statements inside a called function are
trimmed with the call.

LOGIC.TRIM_COLLAPSE_FUNC_DEFS_RECURSIVE treats a function instance as free of
side effects: an instance whose outputs drive nothing is removed, and two
instances with the same inputs become one. A sim_print or sim_assert inside
the function goes with it. Native simulation runs every call. Each cycle,
native simulation prints "unused-result call" once and "same-input call"
twice; the generated VHDL prints "same-input call" once and no
"unused-result call": the call whose result is unused is gone, and the two
identical calls were merged.

Registered in known_issues_tests.py (expect_fail) through
pypeline_sim_debug.py, which reports MISMATCH while either form is present.
"""

import os
import sys

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..")
)

from pypeline import MAIN, Reg, hw_func, sim_finish, sim_print, uint1_t, uint8_t


@hw_func
def log_unused(c: uint8_t) -> uint1_t:
    sim_print(f"unused-result call c={c}", debug=True)
    return 1


@hw_func
def log_twice(c: uint8_t) -> uint1_t:
    sim_print(f"same-input call c={c}", debug=True)
    return 1


@MAIN
def sim_statement_call_trim():
    c: Reg[uint8_t]
    c = c + 1
    unused: uint1_t = log_unused(c)  # result unused: the call is removed
    a: uint1_t = log_twice(c)  # a and b: same input, merged into one call
    b: uint1_t = log_twice(c)
    sim_print(f"c={c} a={a} b={b}", debug=True)
    if c == 3:
        sim_finish()
