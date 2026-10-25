# pyright: reportInvalidTypeForm=none
"""Regression test: clock assignment must trace a global Wire[T] access up
through a called helper function, not just uses directly inside a MAIN's own
top-level body.

`write_via_helper` here writes `shared_wire` from inside a plain `@hw_func`,
one call deep from `driver` (a `@MAIN(100.0)`); `reader` (a plain `@MAIN`
with no explicit MHz) reads `shared_wire` directly. `reader` must get
100.0 MHz. PY_TO_LOGIC._assign_clocks finds a function's MAINs from
FuncToInstances; before it, the C front end's LOGIC.INFER_CLOCK_DOMAINS
walked a function-name call graph that the Python front end first left
empty. This mirrors the wireguard-fpga chacha20_pipeline_shared.py failure,
where a shared pipeline MAIN read a Wire[T] directly while the writer was a
helper function called from another MAIN's clocked hierarchy.
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
