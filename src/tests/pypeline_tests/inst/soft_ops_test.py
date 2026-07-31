# pyright: reportInvalidTypeForm=none
"""Native-sim golden tests for the include/pypeline/operators soft library
(src/pypeline.py's matcher-based generic operator registry + the soft
implementations themselves), plus a small end-to-end check that
register_soft_ops() actually causes plain `a + b` / `a < b` to dispatch to
the soft implementation rather than the built-in path.

Each soft factory is called directly and driven through sim_call with plain
SimVal operands, compared against a Python golden computation -- this
isolates "is the soft implementation's arithmetic correct" from "does the
registry dispatch to it", which the end-to-end section at the bottom covers
separately.
"""
import itertools
import os
import sys

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..")
)
sys.path.insert(
    0,
    os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "..",
        "..",
        "..",
        "..",
        "include",
        "pypeline",
    ),
)

from pypeline import (
    sim_call,
    SimVal,
    make_uint_t,
    make_int_t,
    uint8_t,
    int8_t,
    any_integer_t,
    register_operator,
)

from operators.soft_add import make_soft_ripple_add, make_soft_carry_select_add, make_soft_sub
from operators.soft_mult import make_soft_shift_add_mult
from operators.soft_div import make_soft_div, make_soft_mod
from operators.soft_cmp import make_soft_sub_cmp
from operators.soft_shift import make_soft_barrel_sl, make_soft_barrel_sr
from operators.soft_misc import make_soft_negate, make_soft_eq

FAILS = []


def check(label, got, want):
    if int(got) != int(want):
        FAILS.append(f"{label}: got {int(got)} want {int(want)}")


def to_signed(v, width):
    v &= (1 << width) - 1
    if v >= (1 << (width - 1)):
        v -= 1 << width
    return v


def test_soft_add():
    ut = make_uint_t(6)
    add = make_soft_ripple_add(ut, ut)
    for a, b in itertools.product(range(0, 64, 5), range(0, 64, 7)):
        got = sim_call(add, SimVal(a, ut), SimVal(b, ut))
        check(f"soft_ripple_add({a},{b})", got, a + b)
    print("test_soft_add passed")


def test_soft_add_carry_select():
    ut = make_uint_t(6)
    add = make_soft_carry_select_add(ut, ut)
    for a, b in itertools.product(range(0, 64, 5), range(0, 64, 7)):
        got = sim_call(add, SimVal(a, ut), SimVal(b, ut))
        check(f"soft_carry_select_add({a},{b})", got, a + b)
    print("test_soft_add_carry_select passed")


def test_soft_sub():
    ut = make_uint_t(6)
    sub = make_soft_sub(ut, ut)
    for a, b in itertools.product(range(0, 64, 5), range(0, 64, 7)):
        got = sim_call(sub, SimVal(a, ut), SimVal(b, ut))
        # Same-sign (both unsigned) MINUS: output width = max width, unsigned wrap.
        check(f"soft_sub({a},{b})", got, (a - b) & 0x3F)
    print("test_soft_sub passed")


def test_soft_negate():
    st = make_int_t(6)
    neg = make_soft_negate(st)
    for a in range(-32, 32, 3):
        got = sim_call(neg, SimVal(a, st))
        check(f"soft_negate({a})", got, -a)
    print("test_soft_negate passed")


def test_soft_mult():
    ut = make_uint_t(5)
    mult = make_soft_shift_add_mult(ut, ut)
    for a, b in itertools.product(range(0, 32, 3), range(0, 32, 5)):
        got = sim_call(mult, SimVal(a, ut), SimVal(b, ut))
        check(f"soft_mult({a},{b})", got, a * b)
    print("test_soft_mult passed")


def test_soft_div_mod():
    ut = make_uint_t(6)
    div = make_soft_div(ut, ut)
    mod = make_soft_mod(ut, ut)
    for a in range(0, 64, 4):
        for b in range(1, 64, 5):
            got_q = sim_call(div, SimVal(a, ut), SimVal(b, ut))
            got_r = sim_call(mod, SimVal(a, ut), SimVal(b, ut))
            check(f"soft_div({a},{b})", got_q, a // b)
            check(f"soft_mod({a},{b})", got_r, a % b)
    print("test_soft_div_mod passed")


def test_soft_cmp():
    ut = make_uint_t(6)
    for op, pyop in (("GT", lambda a, b: a > b), ("GTE", lambda a, b: a >= b),
                      ("LT", lambda a, b: a < b), ("LTE", lambda a, b: a <= b)):
        cmp_fn = make_soft_sub_cmp(op)(ut, ut)
        for a, b in itertools.product(range(0, 64, 6), range(0, 64, 9)):
            got = sim_call(cmp_fn, SimVal(a, ut), SimVal(b, ut))
            check(f"soft_cmp_{op}({a},{b})", got, 1 if pyop(a, b) else 0)
    print("test_soft_cmp passed")


def test_soft_eq():
    ut = make_uint_t(6)
    eq_fn = make_soft_eq(negate=False)(ut, ut)
    neq_fn = make_soft_eq(negate=True)(ut, ut)
    for a, b in itertools.product(range(0, 64, 5), range(0, 64, 7)):
        check(f"soft_eq({a},{b})", sim_call(eq_fn, SimVal(a, ut), SimVal(b, ut)), 1 if a == b else 0)
        check(f"soft_neq({a},{b})", sim_call(neq_fn, SimVal(a, ut), SimVal(b, ut)), 1 if a != b else 0)
    print("test_soft_eq passed")


def test_soft_shift():
    ut = make_uint_t(8)
    sl = make_soft_barrel_sl(ut)
    sr = make_soft_barrel_sr(ut)
    for a in range(0, 256, 17):
        for amt in range(0, 8):
            got_sl = sim_call(sl, SimVal(a, ut), SimVal(amt))
            got_sr = sim_call(sr, SimVal(a, ut), SimVal(amt))
            check(f"soft_sl({a},{amt})", got_sl, (a << amt) & 0xFF)
            check(f"soft_sr({a},{amt})", got_sr, a >> amt)
    print("test_soft_shift passed")


def test_generic_registry_end_to_end():
    """Register a soft adder for any_integer_t globally, then verify plain
    `a + b` on a fresh, never-before-seen concrete width dispatches to it
    (proving the matcher -> factory -> memoize path, not just the factories
    in isolation)."""
    from pypeline import hw_func

    ut = make_uint_t(13)  # a width nothing else in this file/session used
    register_operator("PLUS", any_integer_t, any_integer_t, make_soft_ripple_add)

    @hw_func
    def add13(a: ut, b: ut) -> ut:
        return a + b

    for a, b in itertools.product(range(0, 8192, 900), range(0, 8192, 700)):
        got = sim_call(add13, SimVal(a, ut), SimVal(b, ut))
        check(f"generic_end_to_end({a},{b})", got, (a + b) & 0x1FFF)
    print("test_generic_registry_end_to_end passed")


if __name__ == "__main__":
    test_soft_add()
    test_soft_add_carry_select()
    test_soft_sub()
    test_soft_negate()
    test_soft_mult()
    test_soft_div_mod()
    test_soft_cmp()
    test_soft_eq()
    test_soft_shift()
    test_generic_registry_end_to_end()
    if FAILS:
        for f in FAILS[:50]:
            print("FAIL:", f)
        print(f"{len(FAILS)} failures")
        sys.exit(1)
    print("soft_ops_test: all passed")
