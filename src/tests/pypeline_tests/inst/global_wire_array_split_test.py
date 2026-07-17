# pyright: reportInvalidTypeForm=none
"""Self-checking @MAIN test for an ARRAY-typed global Wire[T] split by
constant element indices between two writer functions: main_01 drives
arr_w[0..1] via an unrolled `for i in range(2)` loop, main_23 drives
arr_w[2..3] via `range(2, 4)`.

Elaboration unrolls the loops so each write records a precise constant-index
driven path ((0,), (1,) vs (2,), (3,)) -- following elaboration's existing
index-precision precedent -- and VHDL.py emits one per-element concurrent
assignment `global_to_module...arr_w(i) <= module_to_global.<owner>...arr_w(i)`
per region. In native sim the loop is NOT unrolled (a real Python loop with a
variable index): runtime claim tracking records the concrete indices each
function actually touched, so each writer's per-invocation reset zeros
exactly its own elements and never the other writer's.

Registered in native_sim_tests.py (--sim --run all) and vhdl_sim_tests.py
(--sim --comb --cocotb --ghdl --run all).
"""

import sys, os

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..")
)

from pypeline import MAIN, Reg, Wire, sim_assert, sim_finish, uint8_t


arr_w: Wire[uint8_t[4]]  # [0..1] driven by main_01, [2..3] by main_23

NUM_CHECKS = 10


@MAIN
def main_01():
    n: Reg[uint8_t]
    for i in range(2):
        arr_w[i] = n + i
    n += 1


@MAIN
def main_23():
    n: Reg[uint8_t]
    for i in range(2, 4):
        arr_w[i] = n + 10 + i
    n += 1


@MAIN
def checker():
    n: Reg[uint8_t]
    for i in range(2):
        sim_assert(arr_w[i] == n + i, f"arr_w[{i}] expected {n + i} got {arr_w[i]}")
    for i in range(2, 4):
        sim_assert(
            arr_w[i] == n + 10 + i, f"arr_w[{i}] expected {n + 10 + i} got {arr_w[i]}"
        )
    if n == NUM_CHECKS - 1:
        sim_finish()
    n += 1
