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

from operators.soft_add import make_soft_add_ripple, make_soft_add_carry_select, make_soft_sub
from operators.soft_mult import (
    make_soft_mult_shift_add,
    make_soft_mult_karatsuba,
    make_soft_add_tree_shifted,
    make_soft_mult_carry_save,
)
from operators.soft_div import (
    make_soft_div, make_soft_mod, make_soft_signed_div, make_soft_signed_mod,
    make_soft_div_radix4, make_soft_mod_radix4,
    make_soft_div_signed_radix4, make_soft_mod_signed_radix4,
    make_soft_div_radix, make_soft_mod_radix,
    make_soft_div_signed_radix, make_soft_mod_signed_radix,
)
from operators.soft_cmp import make_soft_cmp_sub
from operators.soft_shift import (
    make_soft_shift_barrel_sl,
    make_soft_shift_barrel_sr,
    make_soft_rot_barrel_l,
    make_soft_rot_barrel_r,
    make_soft_shift_rot,
)
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
    add = make_soft_add_ripple(ut, ut)
    for a, b in itertools.product(range(0, 64, 5), range(0, 64, 7)):
        got = sim_call(add, SimVal(a, ut), SimVal(b, ut))
        check(f"soft_ripple_add({a},{b})", got, a + b)
    print("test_soft_add passed")


def test_soft_add_carry_select():
    ut = make_uint_t(6)
    add = make_soft_add_carry_select(ut, ut)
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
    mult = make_soft_mult_shift_add(ut, ut)
    for a, b in itertools.product(range(0, 32, 3), range(0, 32, 5)):
        got = sim_call(mult, SimVal(a, ut), SimVal(b, ut))
        check(f"soft_mult({a},{b})", got, a * b)
    print("test_soft_mult passed")


def test_soft_mult_asymmetric():
    """Non-square operand widths, both orders -- make_soft_mult_shift_add's
    tree is sized by r_bits with eff_l_t-wide leaves, so unequal left/right
    widths are the case most likely to expose a tree sizing mistake."""
    lt = make_uint_t(12)
    rt = make_uint_t(5)
    mult_lr = make_soft_mult_shift_add(lt, rt)
    mult_rl = make_soft_mult_shift_add(rt, lt)
    for a in range(0, 4096, 137):
        for b in range(0, 32, 3):
            got_lr = sim_call(mult_lr, SimVal(a, lt), SimVal(b, rt))
            check(f"soft_mult_asymmetric_lr({a},{b})", got_lr, a * b)
            got_rl = sim_call(mult_rl, SimVal(b, rt), SimVal(a, lt))
            check(f"soft_mult_asymmetric_rl({b},{a})", got_rl, a * b)
    print("test_soft_mult_asymmetric passed")


def test_soft_carry_save_mult():
    """make_soft_mult_carry_save against the same golden sweep as
    test_soft_mult, across several max_width values -- including
    max_width >= the operand width, which degenerates toward a small number
    of wide adds and is the closest thing this shape has to a built-in
    control (though not byte-identical to make_soft_mult_shift_add's own
    tree, unlike Karatsuba's T>=n_bits case -- see docs/SYN_DESIGN.md
    section 11)."""
    ut = make_uint_t(5)
    for max_width in (1, 2, 3, 5, 8):
        mult = make_soft_mult_carry_save(ut, ut, max_width=max_width)
        for a, b in itertools.product(range(0, 32, 3), range(0, 32, 5)):
            got = sim_call(mult, SimVal(a, ut), SimVal(b, ut))
            check(f"soft_carry_save_mult(mw={max_width})({a},{b})", got, a * b)
    print("test_soft_carry_save_mult passed")


def test_soft_carry_save_mult_asymmetric():
    """Non-square operand widths, both orders -- same rationale as
    test_soft_mult_asymmetric."""
    lt = make_uint_t(12)
    rt = make_uint_t(5)
    for max_width in (2, 4):
        mult_lr = make_soft_mult_carry_save(lt, rt, max_width=max_width)
        mult_rl = make_soft_mult_carry_save(rt, lt, max_width=max_width)
        for a in range(0, 4096, 137):
            for b in range(0, 32, 3):
                got_lr = sim_call(mult_lr, SimVal(a, lt), SimVal(b, rt))
                check(f"soft_carry_save_mult_asymmetric_lr(mw={max_width})({a},{b})", got_lr, a * b)
                got_rl = sim_call(mult_rl, SimVal(b, rt), SimVal(a, lt))
                check(f"soft_carry_save_mult_asymmetric_rl(mw={max_width})({b},{a})", got_rl, a * b)
    print("test_soft_carry_save_mult_asymmetric passed")


def test_soft_carry_save_mult_degenerate():
    """Regression test for a real non-termination bug found while building
    this multiplier: when EVERY remaining summand in the carry-save
    reduction is simultaneously non-overlapping with its neighbors (only
    possible when the left operand is 1 bit wide, so every partial product
    is a single disjoint bit), the naive pairing scan marks everything
    'pass' and the element count never shrinks -- uint1 x uint5 hung
    indefinitely before _plan_carry_save_levels merged shift-contiguous
    'pass' runs. Covers both operand orders (1-bit on the left forces the
    tree path; 1-bit on the right is the already-handled r_bits==1
    passthrough) and the exact-square 1x1 corner."""
    for lw, rw in ((1, 5), (1, 8), (5, 1), (1, 1)):
        for max_width in (2, 4):
            lt, rt = make_uint_t(lw), make_uint_t(rw)
            mult = make_soft_mult_carry_save(lt, rt, max_width=max_width)
            for a in range(1 << lw):
                for b in range(1 << rw):
                    got = sim_call(mult, SimVal(a, lt), SimVal(b, rt))
                    check(f"soft_carry_save_mult_degenerate(lw={lw},rw={rw},mw={max_width})({a},{b})", got, a * b)
    print("test_soft_carry_save_mult_degenerate passed")


def test_tree_add_shifted():
    """make_soft_add_tree_shifted directly, against the Python reference
    sum(t << i for i, t in enumerate(terms)). Exercised independently of the
    multiplier because its per-level shift/width/leftover bookkeeping is where a
    mistake would hide: odd leaf counts take the leftover path, and levels whose
    node width saturates at out_t exercise the width cap. Leaf counts include
    non-powers-of-two on purpose."""
    leaf_t = make_uint_t(6)
    lo, hi = 0, 63
    for n_leaves in (2, 3, 5, 6, 9, 16):
        # Widest possible sum for this leaf count, so out_t never truncates.
        max_sum = sum(hi << i for i in range(n_leaves))
        out_t = make_uint_t(max_sum.bit_length())
        tree = make_soft_add_tree_shifted(n_leaves, leaf_t, out_t)
        cases = [
            [0] * n_leaves,
            [hi] * n_leaves,
            [(i * 7 + 1) % 64 for i in range(n_leaves)],
            [hi if i % 2 else lo for i in range(n_leaves)],
        ]
        for terms in cases:
            want = sum(t << i for i, t in enumerate(terms))
            got = sim_call(tree, terms)
            check(f"tree_add_shifted(n={n_leaves},{terms})", got, want)
    print("test_tree_add_shifted passed")


def test_soft_karatsuba_mult():
    """Regression test for a bug caught by manual audit: odd-bit-width splits
    in the recursion (e.g. the 16-bit case recurses into a 9-bit middle-term
    multiply) undersized mid_t by one bit, truncating a_lo+a_hi and
    corrupting the result -- e.g. uint16_t 65535*1 elaborated to 67043327
    instead of 65535. threshold=4 forces recursion (and odd splits) even for
    the smaller 8-bit sweep below."""
    ut8 = make_uint_t(8)
    mult8 = make_soft_mult_karatsuba(ut8, ut8, threshold=4)
    for a, b in itertools.product(range(0, 256, 7), range(0, 256, 11)):
        got = sim_call(mult8, SimVal(a, ut8), SimVal(b, ut8))
        check(f"soft_karatsuba_mult8({a},{b})", got, a * b)

    ut16 = make_uint_t(16)
    mult16 = make_soft_mult_karatsuba(ut16, ut16)
    for a, b in [(65535, 1), (1, 65535), (65535, 65535), (0, 65535), (12345, 6789)]:
        got = sim_call(mult16, SimVal(a, ut16), SimVal(b, ut16))
        check(f"soft_karatsuba_mult16({a},{b})", got, a * b)

    # threshold < 3 never terminates: a 3-bit operand splits into half=1/hi=2
    # with mid = max(1,2)+1 = 3, so the middle sub-multiply is the same width
    # as its parent and recurses forever unless threshold >= 3 catches it.
    try:
        make_soft_mult_karatsuba(ut16, ut16, threshold=2)
        check("soft_karatsuba_mult threshold=2 should raise", False, True)
    except ValueError:
        pass
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


def test_soft_radix4_div_mod():
    """make_soft_div_radix4/mod: 2-quotient-bits-per-step restoring divider,
    against the same golden a//b, a%b as test_soft_div_mod. Even width (6,
    exercises only 2-bit steps) and odd width (7, exercises the leading
    1-bit step) both covered -- the odd-width path is the one most likely to
    have an off-by-one in the elaboration-time step-list construction."""
    for width in (6, 7):
        ut = make_uint_t(width)
        div = make_soft_div_radix4(ut, ut)
        mod = make_soft_mod_radix4(ut, ut)
        n = 1 << width
        for a in range(0, n, 3):
            for b in range(1, n, 5):
                got_q = sim_call(div, SimVal(a, ut), SimVal(b, ut))
                got_r = sim_call(mod, SimVal(a, ut), SimVal(b, ut))
                check(f"soft_radix4_div_w{width}({a},{b})", got_q, a // b)
                check(f"soft_radix4_mod_w{width}({a},{b})", got_r, a % b)
    print("test_soft_radix4_div_mod passed")


def test_soft_signed_radix4_div_mod():
    """Signed radix-4 divider: same C-style truncating convention as
    test_soft_signed_div_mod, same abs-then-fix-sign wrapper, radix-4
    unsigned core instead of the plain restoring one."""
    st = make_int_t(6)
    div = make_soft_div_signed_radix4(st, st)
    mod = make_soft_mod_signed_radix4(st, st)

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
            check(f"soft_signed_radix4_div({a},{b})", got_q, c_trunc_div(a, b))
            check(f"soft_signed_radix4_mod({a},{b})", got_r, c_trunc_mod(a, b))
    print("test_soft_signed_radix4_div_mod passed")


def test_soft_radix_div_mod_generalized():
    """make_soft_div_radix/mod(bits_per_step): the generalized factory
    make_soft_div_radix4/mod are built from (bits_per_step=2). Sweeps
    bits_per_step in {1,2,3,4} x widths {6,7,8,12} so both the leading
    partial-group path (n_bits % bits_per_step != 0, e.g. width 7 at
    bits_per_step=2, or width 6 at bits_per_step=4) and the clean-multiple
    path get exercised. bits_per_step=1 must match plain make_soft_div/mod
    exactly (same recurrence, one bit at a time)."""
    for bits_per_step in (1, 2, 3, 4):
        for width in (6, 7, 8, 12):
            ut = make_uint_t(width)
            div = make_soft_div_radix(bits_per_step)(ut, ut)
            mod = make_soft_mod_radix(bits_per_step)(ut, ut)
            n = 1 << width
            step = max(1, n // 11)
            for a in range(0, n, step):
                for b in range(1, n, step + 2):
                    got_q = sim_call(div, SimVal(a, ut), SimVal(b, ut))
                    got_r = sim_call(mod, SimVal(a, ut), SimVal(b, ut))
                    check(f"soft_radix{bits_per_step}_div_w{width}({a},{b})", got_q, a // b)
                    check(f"soft_radix{bits_per_step}_mod_w{width}({a},{b})", got_r, a % b)
    print("test_soft_radix_div_mod_generalized passed")


def test_soft_signed_radix_div_mod_generalized():
    """Signed generalized radix divider: same abs-then-fix-sign wrapper and
    C-style truncating convention as test_soft_signed_radix4_div_mod, swept
    across bits_per_step."""
    def c_trunc_div(a, b):
        q = abs(a) // abs(b)
        return -q if (a < 0) != (b < 0) else q

    def c_trunc_mod(a, b):
        r = abs(a) % abs(b)
        return -r if (a < 0) != (b < 0) else r

    for bits_per_step in (1, 2, 3, 4):
        st = make_int_t(6)
        div = make_soft_div_signed_radix(bits_per_step)(st, st)
        mod = make_soft_mod_signed_radix(bits_per_step)(st, st)
        for a in range(-32, 32, 5):
            for b in list(range(-32, 0, 7)) + list(range(1, 32, 7)):
                got_q = sim_call(div, SimVal(a, st), SimVal(b, st))
                got_r = sim_call(mod, SimVal(a, st), SimVal(b, st))
                check(f"soft_signed_radix{bits_per_step}_div({a},{b})", got_q, c_trunc_div(a, b))
                check(f"soft_signed_radix{bits_per_step}_mod({a},{b})", got_r, c_trunc_mod(a, b))
    print("test_soft_signed_radix_div_mod_generalized passed")


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


def test_soft_mult_registration_unsigned_only():
    """register_soft_mult/register_soft_mult_karatsuba must register for
    any_uint_t x any_uint_t ONLY. Regression test for the same bug class
    test_soft_div_mod_registration guards for DIV: both soft multipliers sum
    `a << i` over the set bits of b treating b as unsigned, so for a signed b
    (whose MSB has weight -2**(n-1)) the final partial product would have to be
    subtracted, not added. An earlier version registered them for any_integer_t,
    so a signed multiply silently elaborated to wrong hardware -- int5_t
    (-16)*(-16) gave -256 instead of 256. Signed must stay unregistered so it
    falls through to the built-in inferred HDL `*`, which is correct for signed
    (unlike DIV, which has no inferred lowering and so raises via the
    PYPELINE_NO_SW_LIB_GUARD guard instead)."""
    import operators.soft as soft_lib

    for register in (
        soft_lib.register_soft_mult,
        soft_lib.register_soft_mult_shift_add,
        soft_lib.register_soft_mult_karatsuba,
        soft_lib.register_soft_mult_carry_save,
    ):
        register()
        assert _resolve_generic_operator("INFERRED_MULT", "uint10_t", "uint10_t") is not None, (
            f"{register.__name__}: unsigned MULT should resolve to a soft multiplier"
        )
        assert _resolve_generic_operator("INFERRED_MULT", "int10_t", "int10_t") is None, (
            f"{register.__name__}: signed MULT must NOT match a soft multiplier -- "
            "the shift-and-add partial-product sum is only correct for unsigned operands"
        )
        assert _resolve_generic_operator("INFERRED_MULT", "int10_t", "uint10_t") is None, (
            f"{register.__name__}: mixed-signedness MULT must NOT match a soft multiplier"
        )
    print("test_soft_mult_registration_unsigned_only passed")


def test_soft_mult_karatsuba_threshold_override():
    """register_soft_mult_karatsuba(threshold=...) must actually thread the
    override into the registered factory (not silently fall back to
    make_soft_mult_karatsuba's own default), and the default (threshold=None)
    must resolve to a working multiplier at all. Regression test for the
    functools.partial-based override added alongside the threshold=16 default
    (docs/SYN_DESIGN.md section 10)."""
    import operators.soft as soft_lib

    ut10 = make_uint_t(10)
    soft_lib.register_soft_mult_karatsuba(threshold=4)
    kar_t4 = _resolve_generic_operator("INFERRED_MULT", "uint10_t", "uint10_t")
    assert kar_t4 is not None, "register_soft_mult_karatsuba(threshold=4) should register"
    for a, b in [(0, 0), (1023, 1023), (731, 5), (17, 400)]:
        got = sim_call(kar_t4, SimVal(a, ut10), SimVal(b, ut10))
        check(f"soft_karatsuba(threshold=4)({a},{b})", got, a * b)

    soft_lib.register_soft_mult_karatsuba()  # default (threshold=None)
    kar_default = _resolve_generic_operator("INFERRED_MULT", "uint10_t", "uint10_t")
    got = sim_call(kar_default, SimVal(731, ut10), SimVal(5, ut10))
    check("soft_karatsuba(default)(731,5)", got, 731 * 5)
    print("test_soft_mult_karatsuba_threshold_override passed")


def test_soft_mult_carry_save_max_width_override():
    """Same regression shape as test_soft_mult_karatsuba_threshold_override,
    for register_soft_mult_carry_save(max_width=...)."""
    import operators.soft as soft_lib

    ut10 = make_uint_t(10)
    soft_lib.register_soft_mult_carry_save(max_width=3)
    cs_mw3 = _resolve_generic_operator("INFERRED_MULT", "uint10_t", "uint10_t")
    assert cs_mw3 is not None, "register_soft_mult_carry_save(max_width=3) should register"
    for a, b in [(0, 0), (1023, 1023), (731, 5), (17, 400)]:
        got = sim_call(cs_mw3, SimVal(a, ut10), SimVal(b, ut10))
        check(f"soft_carry_save(max_width=3)({a},{b})", got, a * b)

    soft_lib.register_soft_mult_carry_save()  # default (max_width=None)
    cs_default = _resolve_generic_operator("INFERRED_MULT", "uint10_t", "uint10_t")
    got = sim_call(cs_default, SimVal(731, ut10), SimVal(5, ut10))
    check("soft_carry_save(default)(731,5)", got, 731 * 5)
    print("test_soft_mult_carry_save_max_width_override passed")


def test_soft_mult_default_is_carry_save():
    """register_soft_mult() must resolve to make_soft_mult_carry_save, not
    make_soft_mult_shift_add -- regression test for the default switch
    (docs/SYN_DESIGN.md section 11: the port of solution.vhd's sky130
    reference design is now the default; the old tree stays reachable via
    register_soft_mult_shift_add()). Distinguishes the two by canonical
    entity name rather than by measuring anything -- soft_mult_carry_save
    and soft_mult_shift_add name their top hw_func differently."""
    import operators.soft as soft_lib
    from PY_TO_LOGIC import CANONICAL_CALLABLE_KEY
    from operators.soft_mult import make_soft_mult_carry_save, make_soft_mult_shift_add

    ut8 = make_uint_t(8)
    soft_lib.register_soft_mult()
    default_mult = _resolve_generic_operator("INFERRED_MULT", "uint8_t", "uint8_t")
    assert default_mult is not None, "register_soft_mult() should register"
    assert CANONICAL_CALLABLE_KEY(default_mult) == CANONICAL_CALLABLE_KEY(
        make_soft_mult_carry_save(ut8, ut8)
    ), "register_soft_mult() must default to make_soft_mult_carry_save"
    assert CANONICAL_CALLABLE_KEY(default_mult) != CANONICAL_CALLABLE_KEY(
        make_soft_mult_shift_add(ut8, ut8)
    ), "register_soft_mult() must NOT default to make_soft_mult_shift_add anymore"
    got = sim_call(default_mult, SimVal(37, ut8), SimVal(6, ut8))
    check("register_soft_mult default (37,6)", got, 37 * 6)
    print("test_soft_mult_default_is_carry_save passed")


def test_soft_cmp():
    ut = make_uint_t(6)
    for op, pyop in (("GT", lambda a, b: a > b), ("GTE", lambda a, b: a >= b),
                      ("LT", lambda a, b: a < b), ("LTE", lambda a, b: a <= b)):
        cmp_fn = make_soft_cmp_sub(op)(ut, ut)
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
    """Exhaustive over uint8_t (every value x every amount, both
    directions), plus a signed sweep of make_soft_shift_barrel_sr against Python's
    arithmetic >> -- each CONST_SR stage lowers via VHDL's numeric_std
    shift_right, which is arithmetic (sign-extending) for a signed operand
    type, so a signed value_t should already match Python's sign-extending
    >> with no separate signed implementation needed. Also covers uint1_t
    (amount_bits floors at 1) and non-power-of-two widths, since the amount
    width formula (n_bits-1).bit_length() is the part most likely to be off
    by one at an edge width."""
    for n_bits in (1, 2, 3, 8):
        ut = make_uint_t(n_bits)
        sl = make_soft_shift_barrel_sl(ut)
        sr = make_soft_shift_barrel_sr(ut)
        mask = (1 << n_bits) - 1
        for a in range(0, 1 << n_bits):
            for amt in range(0, n_bits):
                got_sl = sim_call(sl, SimVal(a, ut), SimVal(amt))
                got_sr = sim_call(sr, SimVal(a, ut), SimVal(amt))
                check(f"soft_sl_n{n_bits}({a},{amt})", got_sl, (a << amt) & mask)
                check(f"soft_sr_n{n_bits}({a},{amt})", got_sr, a >> amt)

    it = make_int_t(8)
    sr_signed = make_soft_shift_barrel_sr(it)
    for a in range(-128, 128):
        for amt in range(0, 8):
            check(f"soft_sr_signed({a},{amt})", sim_call(sr_signed, SimVal(a, it), SimVal(amt)), a >> amt)
    print("test_soft_shift passed")


def _golden_shift(a, amt, n_bits, left):
    mask = (1 << n_bits) - 1
    if left:
        return (a << amt) & mask if amt < n_bits else 0
    return (a >> amt) & mask if amt < n_bits else 0


def _golden_rot(a, amt, n_bits, left):
    a &= (1 << n_bits) - 1
    amt %= n_bits
    if amt == 0:
        return a
    if left:
        return ((a << amt) | (a >> (n_bits - amt))) & ((1 << n_bits) - 1)
    return ((a >> amt) | (a << (n_bits - amt))) & ((1 << n_bits) - 1)


def test_soft_rotate():
    """make_soft_rot_barrel_l/rotr: exhaustive over uint8_t, both directions,
    including amount == 0 (identity) and amount == n_bits-1."""
    for n_bits in (1, 2, 3, 8):
        ut = make_uint_t(n_bits)
        rotl = make_soft_rot_barrel_l(ut)
        rotr = make_soft_rot_barrel_r(ut)
        for a in range(0, 1 << n_bits):
            for amt in range(0, n_bits):
                got_l = sim_call(rotl, SimVal(a, ut), SimVal(amt))
                got_r = sim_call(rotr, SimVal(a, ut), SimVal(amt))
                check(f"soft_rotl_n{n_bits}({a},{amt})", got_l, _golden_rot(a, amt, n_bits, True))
                check(f"soft_rotr_n{n_bits}({a},{amt})", got_r, _golden_rot(a, amt, n_bits, False))
    print("test_soft_rotate passed")


def test_soft_shift_rot():
    """make_soft_shift_rot: the unified 4-mode (direction x rotate) funnel
    barrel, exhaustive over uint8_t against the same shift/rotate goldens
    test_soft_shift/test_soft_rotate use -- this is the primitive that
    answers the pasted latchup_rotate C with one barrel instead of four."""
    for n_bits in (1, 2, 3, 8):
        ut = make_uint_t(n_bits)
        u1 = make_uint_t(1)
        fn = make_soft_shift_rot(ut)
        for a in range(0, 1 << n_bits):
            for amt in range(0, n_bits):
                for direction in (0, 1):
                    for rotate in (0, 1):
                        got = sim_call(
                            fn, SimVal(a, ut), SimVal(amt), SimVal(direction, u1), SimVal(rotate, u1)
                        )
                        want = (
                            _golden_rot(a, amt, n_bits, bool(direction))
                            if rotate
                            else _golden_shift(a, amt, n_bits, bool(direction))
                        )
                        check(f"soft_shift_rot_n{n_bits}({a},{amt},d={direction},r={rotate})", got, want)
    print("test_soft_shift_rot passed")


def test_generic_registry_end_to_end():
    """Register a soft adder for any_integer_t globally, then verify plain
    `a + b` on a fresh, never-before-seen concrete width dispatches to it
    (proving the matcher -> factory -> memoize path, not just the factories
    in isolation)."""
    from pypeline import hw_func

    ut = make_uint_t(13)  # a width nothing else in this file/session used
    register_operator("PLUS", any_integer_t, any_integer_t, make_soft_add_ripple)

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
    test_soft_mult_asymmetric()
    test_soft_carry_save_mult()
    test_soft_carry_save_mult_asymmetric()
    test_soft_carry_save_mult_degenerate()
    test_tree_add_shifted()
    test_soft_karatsuba_mult()
    test_soft_div_mod()
    test_soft_signed_div_mod()
    test_soft_radix4_div_mod()
    test_soft_signed_radix4_div_mod()
    test_soft_radix_div_mod_generalized()
    test_soft_signed_radix_div_mod_generalized()
    test_soft_div_mod_registration()
    test_soft_mult_registration_unsigned_only()
    test_soft_mult_karatsuba_threshold_override()
    test_soft_mult_carry_save_max_width_override()
    test_soft_mult_default_is_carry_save()
    test_soft_cmp()
    test_soft_eq()
    test_soft_shift()
    test_soft_rotate()
    test_soft_shift_rot()
    test_generic_registry_end_to_end()
    if FAILS:
        for f in FAILS[:50]:
            print("FAIL:", f)
        print(f"{len(FAILS)} failures")
        sys.exit(1)
    print("soft_ops_test: all passed")
