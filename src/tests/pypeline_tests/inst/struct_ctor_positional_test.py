# pyright: reportInvalidTypeForm=none
"""Self-checking @MAIN test for a compiler bug where a hw_func's `return`
statement constructing a @struct with positional args (e.g. `return pair_t(a, b)`
instead of `return pair_t(a=a, b=b)`) silently failed to wire any struct field,
leaving the function's return_output permanently undriven -- SYN.py's pipeline
scheduler would then spin to its stage_num cap and sys.exit(-1) instead of
raising a clear elaboration error. Covers positional-only, keyword-only, and
mixed positional+keyword struct constructors, plus a plain local-variable
assignment with positional args (same underlying _elab_compound_init code path).

Registered in native_vs_vhdl_sim_tests.py, which runs the native (--sim --comb)
and cocotb+GHDL (--cocotb --ghdl) sims and diffs their sim_print(debug=True)
output cycle by cycle.
"""

import sys, os

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..")
)

from typing import NamedTuple

from pypeline import (
    MAIN,
    Reg,
    hw_func,
    sim_assert,
    sim_finish,
    sim_print,
    struct,
    uint1_t,
    uint8_t,
)

NUM_COUNTS = 10


@struct
class pair_t(NamedTuple):
    a: uint8_t
    b: uint1_t


@hw_func
def make_pair_positional(n: uint8_t, active: uint1_t) -> pair_t:
    return pair_t(n, active)


@hw_func
def make_pair_keyword(n: uint8_t, active: uint1_t) -> pair_t:
    return pair_t(a=n, b=active)


@hw_func
def make_pair_mixed(n: uint8_t, active: uint1_t) -> pair_t:
    return pair_t(n, b=active)


@MAIN
def struct_ctor_positional_test():
    n: Reg[uint8_t]
    active: uint1_t = n < NUM_COUNTS

    p_pos: pair_t = make_pair_positional(n, active)
    sim_assert(p_pos.a == n, f"positional ctor: expected a={n}, got {p_pos.a}")
    sim_assert(
        p_pos.b == active, f"positional ctor: expected b={active}, got {p_pos.b}"
    )

    p_kw: pair_t = make_pair_keyword(n, active)
    sim_assert(p_kw.a == n, f"keyword ctor: expected a={n}, got {p_kw.a}")
    sim_assert(p_kw.b == active, f"keyword ctor: expected b={active}, got {p_kw.b}")

    p_mixed: pair_t = make_pair_mixed(n, active)
    sim_assert(p_mixed.a == n, f"mixed ctor: expected a={n}, got {p_mixed.a}")
    sim_assert(
        p_mixed.b == active, f"mixed ctor: expected b={active}, got {p_mixed.b}"
    )

    # Same _elab_compound_init code path via plain local-variable assignment.
    local_pos: pair_t = pair_t(n, active)
    sim_assert(local_pos.a == n, f"local positional: expected a={n}, got {local_pos.a}")
    sim_assert(
        local_pos.b == active, f"local positional: expected b={active}, got {local_pos.b}"
    )

    # No debug print on the sim_finish() cycle -- see self_check_counter_test.py.
    if n < NUM_COUNTS - 1:
        sim_print(f"struct_ctor_positional n={n} active={active}", debug=True)
    if n == NUM_COUNTS - 1:
        sim_finish()
    n += 1
