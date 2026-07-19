# pyright: reportInvalidTypeForm=none
"""Self-checking @MAIN test for a global Wire[T] field driven from INSIDE the
instance hierarchy, not a plain top-level @MAIN body: main_a -> mid ->
leaf_writer, where leaf_writer (two call levels deep) drives w.x, while
main_b drives w.y directly at MAIN level -- a split-field wire whose writers
sit at different hierarchy depths.

The write function is leaf_writer (the Logic that has w in
write_only_global_wires); validation counts it as the single-instance writer,
and VHDL.py's _inst_text assembles the full hierarchical record path
(module_to_global.main_a.<mid inst>.<leaf_writer inst>.w.x) with the
global_to_module/module_to_global record ports threaded down through mid's
entity automatically (LOGIC_NEEDS_* recursion).

Registered in native_sim_tests.py (--sim --comb --run all) and vhdl_sim_tests.py
(--sim --comb --cocotb --ghdl --run all).
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
    hw_func,
    sim_assert,
    sim_finish,
    struct,
    uint8_t,
)


@struct
class point_t(NamedTuple):
    x: uint8_t
    y: uint8_t


w: Wire[point_t]  # .x driven by leaf_writer (2 levels deep), .y by main_b

NUM_CHECKS = 10


@hw_func
def leaf_writer(n: uint8_t) -> uint8_t:
    w.x = n
    return n


@hw_func
def mid(n: uint8_t) -> uint8_t:
    return leaf_writer(n)


@MAIN
def main_a():
    n: Reg[uint8_t]
    mid(n)
    n += 1


@MAIN
def main_b():
    n: Reg[uint8_t]
    w.y = n + 100
    n += 1


@MAIN
def checker():
    n: Reg[uint8_t]
    sim_assert(w.x == n, f"w.x (written 2 levels deep) expected {n} got {w.x}")
    sim_assert(w.y == n + 100, f"w.y expected {n + 100} got {w.y}")
    if n == NUM_CHECKS - 1:
        sim_finish()
    n += 1
