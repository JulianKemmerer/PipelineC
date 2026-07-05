# pyright: reportInvalidTypeForm=none
"""Regression test: clock domain inference must trace a global Wire[T] access
up through a called helper function, not just uses directly inside a MAIN's
own top-level body.

Before the fix, `parser_state.func_name_to_calls` / `func_names_to_called_from`
were never populated on the Python front-end, so
`C_TO_LOGIC.RECURSIVE_FIND_MAIN_FUNCS` could only resolve a global var's owning
MAIN when the var was touched directly inside that MAIN's own body (its only
working base case was "function is itself a MAIN"). `write_via_helper` here
writes `shared_wire` from inside a plain `@hw_func`, one call deep from
`driver` (a `@MAIN(100.0)`); `reader` (a plain `@MAIN` with no explicit MHz)
reads `shared_wire` directly. `reader` must have 100.0 MHz inferred -- this
mirrors the wireguard-fpga chacha20_pipeline_shared.py failure, where a shared
pipeline MAIN read a Wire[T] directly while the writer was a helper function
called from another MAIN's clocked hierarchy.
"""

import sys, os

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "def")
)

from pypeline import MAIN, hw_func, Wire, uint1_t


shared_wire: Wire[uint1_t]


@hw_func
def write_via_helper(x: uint1_t) -> uint1_t:
    shared_wire = x
    return x


@MAIN(100.0)
def driver(x: uint1_t) -> uint1_t:
    return write_via_helper(x)


@MAIN
def reader() -> uint1_t:
    return shared_wire
