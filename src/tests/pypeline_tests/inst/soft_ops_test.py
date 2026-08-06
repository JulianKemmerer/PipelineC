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
    _resolve_generic_operator,
)

from operators.soft_add import make_soft_ripple_add, make_soft_carry_select_add, make_soft_sub
from operators.soft_mult import make_soft_shift_add_mult, make_soft_karatsuba_mult
from operators.soft_div import make_soft_div, make_soft_mod, make_soft_signed_div, make_soft_signed_mod
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


def test_soft_karatsuba_mult():
    """Regression test for a bug caught by manual audit: odd-bit-width splits
    in the recursion (e.g. the 16-bit case recurses into a 9-bit middle-term
    multiply) undersized mid_t by one bit, truncating a_lo+a_hi and
    corrupting the result -- e.g. uint16_t 65535*1 elaborated to 67043327
    instead of 65535. threshold=4 forces recursion (and odd splits) even for
    the smaller 8-bit sweep below."""
    ut8 = make_uint_t(8)
    mult8 = make_soft_karatsuba_mult(ut8, ut8, threshold=4)
    for a, b in itertools.product(range(0, 256, 7), range(0, 256, 11)):
        got = sim_call(mult8, SimVal(a, ut8), SimVal(b, ut8))
        check(f"soft_karatsuba_mult8({a},{b})", got, a * b)

    ut16 = make_uint_t(16)
    mult16 = make_soft_karatsuba_mult(ut16, ut16)
    for a, b in [(65535, 1), (1, 65535), (65535, 65535), (0, 65535), (12345, 6789)]:
        got = sim_call(mult16, SimVal(a, ut16), SimVal(b, ut16))
        check(f"soft_karatsuba_mult16({a},{b})", got, a * b)
    print("test_soft_karatsuba_mult passed")


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


def test_soft_signed_div_mod():
    """make_soft_signed_div/make_soft_signed_mod: C-style truncating signed
    division (abs operands through the unsigned restoring divider, then fix
    the sign -- same structure SW_LIB.GET_BIN_OP_DIV_INT_N_C_CODE /
    GET_BIN_OP_MOD_INT_N_C_CODE used to generate as C). Regression test for
    a bug caught by manual audit: an earlier version of register_soft_div
    registered the *unsigned-only* divider for any_integer_t (matching signed
    types too), silently computing wrong results -- e.g. int8_t (-20) // 3
    elaborated to 78 instead of -6. Exhaustive small-width sweep against
    Python's abs/sign-fix reference, matching C's truncating (round-toward-
    zero) convention, not Python's floor // ."""
    st = make_int_t(6)
    div = make_soft_signed_div(st, st)
    mod = make_soft_signed_mod(st, st)

    def c_trunc_div(a, b):
        q = abs(a) // abs(b)
        return -q if (a < 0) != (b < 0) else q

    def c_trunc_mod(a, b):
        r = abs(a) % abs(b)
        return -r if (a < 0) != (b < 0) else r

    for a in range(-32, 32, 3):
        for b in list(range(-32, 0, 5)) + list(range(1, 32, 5)):
            got_q = sim_call(div, SimVal(a, st), SimVal(b, st))
            got_r = sim_call(mod, SimVal(a, st), SimVal(b, st))
            check(f"soft_signed_div({a},{b})", got_q, c_trunc_div(a, b))
            check(f"soft_signed_mod({a},{b})", got_r, c_trunc_mod(a, b))
    print("test_soft_signed_div_mod passed")


def test_soft_div_mod_registration():
    """register_soft_div/register_soft_mod split unsigned (any_uint_t ->
    make_soft_div/make_soft_mod) from signed (any_int_t ->
    make_soft_signed_div/make_soft_signed_mod). Mixed signedness (int/uint)
    is deliberately left unregistered, falling through to the built-in
    inferred path and from there to the PYPELINE_NO_SW_LIB_GUARD guard
    (raises loudly) rather than silently matching a factory never verified
    for that case."""
    import operators.soft as soft_lib

    soft_lib.register_soft_div()
    soft_lib.register_soft_mod()
    assert _resolve_generic_operator("DIV", "uint10_t", "uint10_t") is not None, (
        "unsigned DIV should resolve to the unsigned soft restoring divider"
    )
    assert _resolve_generic_operator("MOD", "uint10_t", "uint10_t") is not None, (
        "unsigned MOD should resolve to the unsigned soft restoring divider"
    )
    assert _resolve_generic_operator("DIV", "int10_t", "int10_t") is not None, (
        "signed DIV should resolve to the signed soft divider"
    )
    assert _resolve_generic_operator("MOD", "int10_t", "int10_t") is not None, (
        "signed MOD should resolve to the signed soft divider"
    )
    assert _resolve_generic_operator("DIV", "int10_t", "uint10_t") is None, (
        "mixed-signedness DIV must NOT match either soft divider"
    )
    print("test_soft_div_mod_registration passed")


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
    test_soft_karatsuba_mult()
    test_soft_div_mod()
    test_soft_signed_div_mod()
    test_soft_div_mod_registration()
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
