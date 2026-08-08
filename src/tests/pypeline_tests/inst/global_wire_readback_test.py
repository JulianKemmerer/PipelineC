# pyright: reportInvalidTypeForm=none
"""Self-checking @MAIN test for cross-writer readback on a split compound
Wire[T]: a writer reading a leaf ANOTHER writer drives must see that writer's
live value (flattened-leaf semantics), not local zeros and not an error --
while its own read-before-write leaves still read zero.

main_a drives w.x and reads w.y (driven by main_b): the sim_assert inside
main_a is the proof, in both native sim and real GHDL simulation, that the
foreign leaf carries main_b's value. Mechanically this exercises the
<name>_PYPELINE_READBACK input wire (PY_TO_LOGIC._declare_global_write_wire)
and VHDL.py's readback feed: the top level drives the readback record field
with zeros in main_a's own region (.x) and main_b's live value in .y.

priv is the UNSHARED variant: written AND read only by its single writer
function, used by nobody else -- GLOBAL_VAR_IS_SHARED is False so its
readback input is fed all zeros by the dedicated unshared feed pass in
VHDL.py (read-before-write zero, write-then-read new value, exactly like a
local variable).

Registered in native_vs_vhdl_sim_tests.py, which runs the native (--sim --comb)
and cocotb+GHDL (--cocotb --ghdl) sims and diffs their sim_print(debug=True)
output cycle by cycle.
"""

import sys, os

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..")
)

from pypeline import (
    MAIN,
    NamedTuple,
    Reg,
    Wire,
    sim_assert,
    sim_finish,
    sim_print,
    struct,
    uint8_t,
)


@struct
class point_t(NamedTuple):
    x: uint8_t
    y: uint8_t


w: Wire[point_t]  # .x driven by main_a, .y driven by main_b
priv: Wire[uint8_t]  # written+read ONLY by main_a (unshared readback)

NUM_CHECKS = 10


@MAIN
def main_a():
    n: Reg[uint8_t]
    # Unshared self-read wire: read-before-write is zero every cycle...
    sim_assert(priv == 0, f"priv read-before-write expected 0 got {priv}")  # noqa: F823
    priv = n + 7
    # ...and write-then-read sees the new value.
    sim_assert(priv == n + 7, f"priv write-then-read expected {n + 7} got {priv}")
    w.x = n
    # Cross-writer readback: w.y is driven by main_b; the flattened-leaf model
    # requires this read to see main_b's live value.
    sim_assert(
        w.y == n + 100,
        f"main_a reads foreign leaf w.y: expected {n + 100} got {w.y}",
    )
    # No debug print on the sim_finish() cycle (checker calls it at n ==
    # NUM_CHECKS - 1) -- see global_wire_partial_field_test.py.
    if n < NUM_CHECKS - 1:
        sim_print(f"global_wire_readback priv={priv} wx={w.x} wy={w.y}", debug=True)
    n += 1


@MAIN
def main_b():
    n: Reg[uint8_t]
    w.y = n + 100
    n += 1


@MAIN
def checker():
    n: Reg[uint8_t]
    sim_assert(w.x == n, f"w.x expected {n} got {w.x}")
    sim_assert(w.y == n + 100, f"w.y expected {n + 100} got {w.y}")
    if n == NUM_CHECKS - 1:
        sim_finish()
    n += 1
