# pyright: reportInvalidTypeForm=none
"""Self-checking @MAIN test for a genuinely RUNTIME (non-unrolled) variable
index write to an array-typed global Wire[T]: writer computes its target
index from a free-running Reg (`idx = n & 3`, a real hardware value, not a
Python `for` loop constant), so elaboration must go through
_emit_var_ref_assign / VAR_REF_ASSIGN rather than unrolling to constant
indices the way global_wire_array_split_test.py's `for i in range(N)` loops
do.

Regression test for the VAR_REF_ASSIGN "position count mismatch" bug: prior
to the fix, _emit_var_ref_assign used the RHS expression's own elaborated
type (rhs_type) as elem_c_type instead of the array's declared element type,
so a bare-literal-typed or narrower-typed RHS (here `n + 100`, a uint8_t
Reg expression, matches the array's uint8_t element type exactly -- the
point is that the WRITE PATH ITSELF must elaborate at all, which it could
not, for ANY runtime index, before the fix) crashed
_build_var_ref_assign_logic's position-count assertion. This design would
not elaborate at all pre-fix.

Only one element of arr_w is written each cycle (idx = n & 3); every other
element must read as zero that cycle (implicit zero-init, same convention
as global_wire_array_split_test.py's constant-index case).

Registered in native_vs_vhdl_sim_tests.py, which runs the native (--sim --comb)
and cocotb+GHDL (--cocotb --ghdl) sims and diffs their sim_print(debug=True)
output cycle by cycle.
"""

import sys, os

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..")
)

from pypeline import MAIN, Reg, Wire, sim_assert, sim_finish, sim_print, uint8_t


arr_w: Wire[uint8_t[4]]  # single writer, runtime (non-unrolled) index each cycle

NUM_CHECKS = 20


@MAIN
def writer():
    n: Reg[uint8_t]
    idx: uint8_t = n & 3
    arr_w[idx] = n + 100
    n += 1


@MAIN
def checker():
    n: Reg[uint8_t]
    idx: uint8_t = n & 3
    for i in range(4):
        expected: uint8_t = 0
        if i == idx:
            expected = n + 100
        sim_assert(
            arr_w[i] == expected,
            f"cycle {n}: arr_w[{i}] expected {expected} got {arr_w[i]}",
        )
    # No debug print on the sim_finish() cycle -- see global_wire_partial_field_test.py.
    if n < NUM_CHECKS - 1:
        sim_print(
            f"global_wire_dynamic_index_write idx={idx} arr="
            f"{arr_w[0]},{arr_w[1]},{arr_w[2]},{arr_w[3]}",
            debug=True,
        )
    if n == NUM_CHECKS - 1:
        sim_finish()
    n += 1
