# pyright: reportInvalidTypeForm=none
"""Self-checking @MAIN test reproducing a crash in the elaboration of a
dynamic-indexed array WRITE nested inside an `if` inside a `for` loop:
_assemble_var_ref_coverage (PY_TO_LOGIC.py) does not forward branch_tag to
its per-position _read_ref calls, so once a second unrolled loop iteration's
`if`-false branch reads the first iteration's own if-mux alias (itself
variable-indexed, same VAR-shaped ref_toks), the true and false per-position
CONST_REF_RD reads collide on one generated instance name and elaboration
raises "Duplicate submodule instance name".

This is the exact limitation documented and worked around in
include/pypeline/axi/axis.py's make_axis_byte_sink (conditional
dynamic-indexed array write inside a for-loop).

Kept in its own file (rather than joined with var_ref_assign_readback_test.py)
because, pre-fix, this DESIGN FAILS TO ELABORATE AT ALL -- a crash here would
otherwise prevent that file's (data-corruption, not crash) bugs from being
observed independently.

Registered in native_vs_vhdl_sim_tests.py, which runs the native (--sim
--comb) and cocotb+GHDL (--cocotb --ghdl) sims and diffs their
sim_print(debug=True) output cycle by cycle.
"""

import sys, os

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..")
)

from pypeline import MAIN, Reg, sim_assert, sim_finish, sim_print, uint8_t

NUM_CHECKS = 20


@MAIN
def cond_dynamic_write_in_loop():
    n: Reg[uint8_t]
    idx: uint8_t = n & 3
    buf: uint8_t[4]
    for i in range(4):
        if i == idx:
            buf[idx] = 100 + idx

    for k in range(4):
        expected_k: uint8_t = 0
        if k == idx:
            expected_k = 100 + idx
        sim_assert(
            buf[k] == expected_k,
            f"cycle {n}: buf[{k}] expected {expected_k} got {buf[k]}",
        )

    # No debug print on the sim_finish() cycle.
    if n < NUM_CHECKS - 1:
        sim_print(
            f"var_ref_assign_cond_loop n={n} idx={idx} "
            f"buf={buf[0]},{buf[1]},{buf[2]},{buf[3]}",
            debug=True,
        )
    if n == NUM_CHECKS - 1:
        sim_finish()
    n += 1
