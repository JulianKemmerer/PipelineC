# pyright: reportInvalidTypeForm=none
"""Self-checking @MAIN test for compound-type Wire[T] split across multiple
writer functions: main_a drives only `.x` of a shared struct wire, main_b
drives only `.y` -- disjoint top-level fields of the SAME wire, each with its
own writer function (elaboration validates the fields are non-overlapping;
VHDL.py emits one per-field concurrent assignment per field, sourced from
its own writer, instead of the single whole-wire assignment used when a
wire has exactly one writer).

This is the direct hardware realization of the guide's example:
    main_ab_in: Wire[uint1_t]    # input into main_a and into main_b
    main_ab_out: Wire[point_t]   # output .x from main_a and .y from main_b

Registered in both native_sim_tests.py (--sim --run all) and
vhdl_sim_tests.py (--sim --comb --cocotb --ghdl --run all) so native sim and
the generated VHDL are both checked against the same golden behavior.
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
    struct,
    uint8_t,
)


@struct
class point_t(NamedTuple):
    x: uint8_t
    y: uint8_t


main_ab_out: Wire[point_t]  # .x driven by main_a, .y driven by main_b


@MAIN
def main_a():
    n: Reg[uint8_t]
    main_ab_out.x = n
    n += 1


@MAIN
def main_b():
    n: Reg[uint8_t]
    main_ab_out.y = n + 100
    n += 1


NUM_CHECKS = 10


@MAIN
def checker():
    n: Reg[uint8_t]
    sim_assert(
        main_ab_out.x == n,
        f"main_ab_out.x should track main_a: expected {n} got {main_ab_out.x}",
    )
    sim_assert(
        main_ab_out.y == n + 100,
        f"main_ab_out.y should track main_b: expected {n + 100} got {main_ab_out.y}",
    )
    if n == NUM_CHECKS - 1:
        sim_finish()
    n += 1
