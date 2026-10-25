# pyright: reportInvalidTypeForm=none
"""Known issue: register_*(..., scope=f) on a plain top-level @hw_func is
ignored in hardware.

PARSE_FILE Step 7 elaborates top-level functions without pushing their scoped
registrations (only _elaborate_live_func does), so:

  - top_scoped_int's `+` is the built-in BIN_OP_PLUS_uint9_t_uint9_t, not the
    soft adder register_soft_add(scope=top_scoped_int) asked for;
  - top_scoped_struct's `+` on a @struct has no implementation at all, and the
    build stops in LOGIC.C_BUILT_IN_FUNC_IS_RAW_HDL ("Is built in C function
    named BIN_OP_PLUS_pair_t_... raw VHDL or not?").

Native simulation applies both registrations. Checked by
scoped_operator_registration_test.py (known_issues_tests.py).
"""

import os
import sys
from typing import NamedTuple

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..")
)
sys.path.insert(
    0,
    os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "..",
        "include", "pypeline",
    ),
)

from pypeline import MAIN, hw_func, register_operator, struct, uint8_t, uint9_t
from operators.soft import register_soft_add


@hw_func
def top_scoped_int(a: uint9_t, b: uint9_t) -> uint9_t:
    return a + b


register_soft_add(scope=top_scoped_int)


@struct
class pair_t(NamedTuple):
    lo: uint8_t
    hi: uint8_t


@hw_func
def pair_add(a: pair_t, b: pair_t) -> pair_t:
    lo: uint8_t = a.lo + b.lo
    hi: uint8_t = a.hi + b.hi
    return pair_t(lo=lo, hi=hi)


@hw_func
def top_scoped_struct(a: pair_t, b: pair_t) -> pair_t:
    return a + b


register_operator("PLUS", pair_t, pair_t, pair_add, scope=top_scoped_struct)


@MAIN
def scoped_top_level_main(a: uint9_t, b: uint9_t, p: pair_t, q: pair_t) -> uint9_t:
    s = top_scoped_int(a, b)
    r = top_scoped_struct(p, q)
    rv: uint9_t = s
    if r.lo == 0:
        rv = 0
    return rv
