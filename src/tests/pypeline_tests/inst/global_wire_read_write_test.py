# pyright: reportInvalidTypeForm=none
"""Self-checking @MAIN test for reading AND writing the same global Wire[T]
within its one writer function: normal local-variable semantics apply --
writes and reads interleave in program order, the final value at the end of
the function is what every other function sees that cycle, and reading a
leaf before it has been written (even within the writer itself) returns zero
(the writer's own implicit zero-init), not an elaboration error.

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


# Scalar wire: write-then-read-then-augassign within the writer.
scalar_out: Wire[uint8_t]

# Compound wire: read-before-write of a leaf (expect zero), then write it,
# then augassign it (read-after-write, normal local semantics).
point_out: Wire[point_t]


@MAIN
def rw_writer():
    n: Reg[uint8_t]

    # scalar_out starts as an implicit zero this cycle; read it before writing
    # (must be zero, not an error), then write, then read-modify-write.
    sim_assert(scalar_out == 0, "scalar_out read-before-write must be zero")
    scalar_out = n
    scalar_out += 1  # read-after-write: normal local semantics

    # point_out.x: read before write must be zero.
    sim_assert(point_out.x == 0, "point_out.x read-before-write must be zero")
    point_out.x = 0
    point_out.x += n  # AugAssign on a struct-field global wire target

    n += 1


NUM_CHECKS = 10


@MAIN
def checker():
    n: Reg[uint8_t]
    sim_assert(
        scalar_out == n + 1,
        f"scalar_out should be n+1, expected {n + 1} got {scalar_out}",
    )
    sim_assert(
        point_out.x == n, f"point_out.x should be n, expected {n} got {point_out.x}"
    )
    sim_assert(
        point_out.y == 0, f"undriven point_out.y should read zero, got {point_out.y}"
    )
    # No debug print on the sim_finish() cycle -- see global_wire_partial_field_test.py.
    if n < NUM_CHECKS - 1:
        sim_print(f"global_wire_read_write scalar={scalar_out} x={point_out.x}", debug=True)
    if n == NUM_CHECKS - 1:
        sim_finish()
    n += 1
