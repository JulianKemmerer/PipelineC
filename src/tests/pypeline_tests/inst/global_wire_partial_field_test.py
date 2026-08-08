# pyright: reportInvalidTypeForm=none
"""Self-checking @MAIN test for compound-type Wire[T] partial-field driving
(single writer): the sole writer of a Wire[point_t] drives only `.x`, leaving
`.y` untouched. `.y` must read as zero everywhere -- the base wire behaves as
if implicitly driven with zeros before the writer's real assignments, exactly
like a local variable's implicit zero-init.

Registered in native_vs_vhdl_sim_tests.py, which runs the native (--sim --comb)
and cocotb+GHDL (--cocotb --ghdl) sims and diffs their sim_print(debug=True)
output cycle by cycle, so native sim and the generated VHDL are both checked
against the same golden behavior.
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


point_out: Wire[point_t]  # sole writer drives only .x


@MAIN
def partial_writer():
    n: Reg[uint8_t]
    point_out.x = n + 1
    n += 1


NUM_CHECKS = 10


@MAIN
def checker():
    n: Reg[uint8_t]
    sim_assert(point_out.y == 0, f"undriven .y should read zero, got {point_out.y}")
    sim_assert(
        point_out.x == n + 1,
        f"driven .x should track writer, expected {n + 1} got {point_out.x}",
    )
    # No debug print on the sim_finish() cycle -- whether a same-cycle VHDL
    # write flushes before std.env.finish kills GHDL is a process-ordering
    # race the cycle diff must not depend on (see docs/pypeline_sim_DESIGN.md).
    if n < NUM_CHECKS - 1:
        sim_print(f"global_wire_partial_field x={point_out.x}", debug=True)
    if n == NUM_CHECKS - 1:
        sim_finish()
    n += 1
