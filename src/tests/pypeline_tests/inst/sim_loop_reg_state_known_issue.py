# pyright: reportInvalidTypeForm=none
"""KNOWN ISSUE (reproducer, not a fix): a stateful hw_func called twice from
the SAME source line inside an unrolled `for` loop gets two independent
Reg[T] register banks in real hardware (one per unrolled call site, per
PY_TO_LOGIC.py's loop_instance_prefix -- see the FOR_<var>_ITER_<n>_ naming
this file's sibling loop_iter_naming_test.py / self_check_loop_unpack_test.py
cover), but only ONE shared register bank in native (Python) sim: sim
instance identity is `_sim_inst_stack`'s `(fn.__qualname__, call_loc)`
(pypeline.py), which carries no per-iteration/ordinal component at all, so
every unrolled call from one source line collapses onto the same
_sim_reg_state key.

With two calls chained within one cycle (call 1's output feeds call 2's
input, both updating the SAME accumulator variable), this is not just an
internal-bookkeeping difference -- the printed values genuinely diverge
after a couple of cycles: hardware's two independent registers settle into
a distinct 0, 0, 10, 30, ... sequence; native sim's one shared register
(read always sees the value committed at the LAST clock edge, never a
same-cycle write -- see pypeline.py's buffered-write discipline -- so both
calls within a cycle read identically, and the second call's write simply
overwrites the first's, last-write-wins) gets stuck at a steady 0 forever.
Confirmed via pypeline_sim_debug.py: native and cocotb+GHDL sim_print(debug=
True) output MISMATCHES starting at cycle 2.

Not fixed here -- see docs/pypeline_sim_DESIGN.md's Limitations section.
Registered directly against pypeline_sim_debug.py (not a custom wrapper):
its own exit code is already 1 on a MISMATCH, which is exactly what
`expect_fail=True` wants -- a clean fix would make this MATCH and XPASS,
signalling it should be promoted out of known_issues.
"""

import sys, os

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..")
)

from pypeline import MAIN, Reg, hw_func, sim_finish, sim_print, uint8_t

NUM_COUNTS = 4


@hw_func
def acc_step(x: uint8_t) -> uint8_t:
    c: Reg[uint8_t]
    old: uint8_t = c
    c = old + x
    return old


@MAIN
def sim_loop_reg_state():
    n: Reg[uint8_t]

    y: uint8_t = 10
    for i in range(2):
        y = acc_step(y)

    if n < NUM_COUNTS - 1:
        sim_print(f"sim_loop_reg_state y={y}", debug=True)
    if n == NUM_COUNTS - 1:
        sim_finish()
    n += 1
