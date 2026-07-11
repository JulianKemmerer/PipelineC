# pyright: reportInvalidTypeForm=none
import sys, os

# Path for pypeline import
sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "../../../")
)
# Path for fixed_point (include/pypeline) import
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
from fractions import Fraction

from pypeline import MAIN, sim_call
from fixed_point import (
    make_fixed_t,
    make_fixed_adder,
    make_fixed_subtractor,
    make_fixed_multiplier,
    make_fixed_negate,
    register_fixed_ops,
    make_fixed_resize,
    quantize_coeffs,
    _quantize,
)

# ─────────────────────────────────────────────
# Elaboration/synthesis coverage: bare +, -, *, unary -, and every distinct
# make_fixed_resize code path (each rounding mode, both overflow modes, and
# the widening/no-shift branch), exercised through @MAIN entry points
# (matches float_ops_test.py's pattern).
# ─────────────────────────────────────────────

q4_12 = make_fixed_t(4, 12)
q4_12_add, q4_12_sub, q4_12_mul, q4_12_neg = register_fixed_ops(q4_12)
q4_12_sum_t = q4_12_add.__annotations__["return"]
q4_12_diff_t = q4_12_sub.__annotations__["return"]
q4_12_prod_t = q4_12_mul.__annotations__["return"]

# Sign-mismatched pair, reused by both @MAIN coverage and the native-sim tests.
signed_t = make_fixed_t(4, 4, signed=True)
unsigned_t = make_fixed_t(6, 4, signed=False)
mixed_add = make_fixed_adder(signed_t, unsigned_t)
mixed_sub = make_fixed_subtractor(signed_t, unsigned_t)
mixed_mul = make_fixed_multiplier(signed_t, unsigned_t)
mixed_add_t = mixed_add.__annotations__["return"]
mixed_sub_t = mixed_sub.__annotations__["return"]
mixed_mul_t = mixed_mul.__annotations__["return"]

# Resize pairs, one per rounding mode (narrowing, SHIFT>0) plus the
# widening/no-shift branch (SHIFT<=0), both overflow modes.
resize_src = make_fixed_t(4, 1)
resize_dst = make_fixed_t(4, 0)
resize_truncate_wrap = make_fixed_resize(
    resize_src, resize_dst, rounding="truncate", overflow="wrap"
)
resize_half_up_wrap = make_fixed_resize(
    resize_src, resize_dst, rounding="round_half_up", overflow="wrap"
)
resize_half_even_saturate = make_fixed_resize(
    resize_src, resize_dst, rounding="round_half_even", overflow="saturate"
)
resize_half_away_saturate = make_fixed_resize(
    resize_src, resize_dst, rounding="round_half_away", overflow="saturate"
)

widen_src = make_fixed_t(8, 0)
widen_dst = make_fixed_t(4, 0)
resize_widen_wrap = make_fixed_resize(widen_src, widen_dst, overflow="wrap")
resize_widen_saturate = make_fixed_resize(widen_src, widen_dst, overflow="saturate")


@MAIN
def q4_12_add_main(a: q4_12, b: q4_12) -> q4_12_sum_t:
    return a + b


@MAIN
def q4_12_sub_main(a: q4_12, b: q4_12) -> q4_12_diff_t:
    return a - b


@MAIN
def q4_12_mul_main(a: q4_12, b: q4_12) -> q4_12_prod_t:
    return a * b


@MAIN
def q4_12_neg_main(a: q4_12) -> q4_12:
    return -a


@MAIN
def mixed_add_main(a: signed_t, b: unsigned_t) -> mixed_add_t:
    return mixed_add(a, b)


@MAIN
def mixed_sub_main(a: signed_t, b: unsigned_t) -> mixed_sub_t:
    return mixed_sub(a, b)


@MAIN
def mixed_mul_main(a: signed_t, b: unsigned_t) -> mixed_mul_t:
    return mixed_mul(a, b)


@MAIN
def resize_truncate_wrap_main(x: resize_src) -> resize_dst:
    return resize_truncate_wrap(x)


@MAIN
def resize_half_up_wrap_main(x: resize_src) -> resize_dst:
    return resize_half_up_wrap(x)


@MAIN
def resize_half_even_saturate_main(x: resize_src) -> resize_dst:
    return resize_half_even_saturate(x)


@MAIN
def resize_half_away_saturate_main(x: resize_src) -> resize_dst:
    return resize_half_away_saturate(x)


@MAIN
def resize_widen_wrap_main(x: widen_src) -> widen_dst:
    return resize_widen_wrap(x)


@MAIN
def resize_widen_saturate_main(x: widen_src) -> widen_dst:
    return resize_widen_saturate(x)


# ─────────────────────────────────────────────
# Native-simulation correctness tests
# ─────────────────────────────────────────────


def test_as_const_roundtrip():
    combos = [(4, 12, True), (8, 0, True), (0, 8, True), (4, 4, False), (6, 2, False)]
    for int_bits, frac_bits, signed in combos:
        t = make_fixed_t(int_bits, frac_bits, signed)
        lsb = 1.0 / (1 << frac_bits)
        total_bits = int_bits + frac_bits
        if signed:
            values = [0.0, lsb, -lsb, lsb * 3, -(lsb * 3)]
        else:
            values = [0.0, lsb, lsb * 3, lsb * ((1 << total_bits) - 1)]
        for v in values:
            x = t.as_const(v)
            got = float(x)
            assert (
                got == v
            ), f"make_fixed_t({int_bits},{frac_bits},{signed}).as_const({v}) -> {got}"
    print("test_as_const_roundtrip passed")


def test_arithmetic_vs_fraction_golden():
    # Random-ish deterministic operand pairs, all exact multiples of q4_12's
    # LSB (2**-12) so as_const introduces zero quantization error and the
    # golden model can use exact Fraction arithmetic throughout.
    lsb = Fraction(1, 1 << 12)
    cases = [
        (Fraction(3, 2), Fraction(9, 4)),
        (Fraction(-2), Fraction(3)),
        (Fraction(-15, 16), Fraction(-1, 4)),
        (Fraction(7, 8), Fraction(-7, 8)),
        (lsb * 5, lsb * -3),
    ]
    for a_frac, b_frac in cases:
        a = q4_12.as_const(float(a_frac))
        b = q4_12.as_const(float(b_frac))
        assert float(a) == float(a_frac), (a_frac, float(a))
        assert float(b) == float(b_frac), (b_frac, float(b))
        s = a + b
        d = a - b
        m = a * b
        assert float(s) == float(a_frac + b_frac), (a_frac, b_frac, "add", float(s))
        assert float(d) == float(a_frac - b_frac), (a_frac, b_frac, "sub", float(d))
        assert float(m) == float(a_frac * b_frac), (a_frac, b_frac, "mul", float(m))
    print("test_arithmetic_vs_fraction_golden passed")


def test_sign_mismatched_operand_pairs():
    # signed_t=(4,4,True) range [-8, 7.9375]; unsigned_t=(6,4,False) range
    # [0, 63.9375]. Corrected _promote_int_bits-based formula: add/sub ->
    # int_bits=8 (eff_a=4, eff_b=6+1=7, max+1=8); mul -> int_bits=11
    # (eff_a=4, eff_b=7, sum=11). The naive/flat max(int_bits)+1 (=7) /
    # int_bits_a+int_bits_b (=10) formulas would under-provision both by 1 bit.
    assert mixed_add_t.int_bits == 8, mixed_add_t.int_bits
    assert mixed_sub_t.int_bits == 8, mixed_sub_t.int_bits
    assert mixed_mul_t.int_bits == 11, mixed_mul_t.int_bits
    assert mixed_add_t.signed and mixed_sub_t.signed and mixed_mul_t.signed

    signed_max = signed_t.as_const(7.9375)
    signed_min = signed_t.as_const(-8.0)
    unsigned_max = unsigned_t.as_const(63.9375)

    # Worst-case sum (71.875) exceeds the naive 7-int_bits type's range
    # (max 63.9375) but fits the corrected 8-int_bits type's range (max
    # 127.9375) -- this is the case that would silently wrap under the
    # under-provisioned formula.
    r_add = sim_call(mixed_add, signed_max, unsigned_max)
    assert float(r_add) == 71.875, float(r_add)

    # Symmetric worst-case difference (-71.9375) exceeds the naive type's
    # min (-64.0) but fits the corrected type's min (-128.0).
    r_sub = sim_call(mixed_sub, signed_min, unsigned_max)
    assert float(r_sub) == -71.9375, float(r_sub)

    r_mul = sim_call(mixed_mul, signed_min, unsigned_max)
    assert float(r_mul) == float(
        Fraction(-8) * Fraction(63.9375).limit_denominator(16)
    ), float(r_mul)
    print("test_sign_mismatched_operand_pairs passed")


def test_mismatched_frac_bits_raises():
    a_t = make_fixed_t(4, 4)
    b_t = make_fixed_t(4, 6)
    try:
        make_fixed_adder(a_t, b_t)
        assert False, "expected TypeError for mismatched frac_bits (adder)"
    except TypeError as e:
        assert "frac_bits" in str(e)
    try:
        make_fixed_subtractor(a_t, b_t)
        assert False, "expected TypeError for mismatched frac_bits (subtractor)"
    except TypeError as e:
        assert "frac_bits" in str(e)
    print("test_mismatched_frac_bits_raises passed")


def test_unary_negate():
    t = make_fixed_t(4, 4, signed=True)
    neg = make_fixed_negate(t)

    normal = t.as_const(1.5)
    r = sim_call(neg, normal)
    assert float(r) == -1.5, float(r)

    most_negative = t.as_const(-8.0)  # raw -128, 8-bit signed
    r2 = sim_call(neg, most_negative)
    assert float(r2) == -8.0, float(r2)  # wraps back to itself, documented limitation

    unsigned_bad = make_fixed_t(4, 4, signed=False)
    try:
        make_fixed_negate(unsigned_bad)
        assert False, "expected TypeError for NEGATE on unsigned fixed_t"
    except TypeError as e:
        assert "signed" in str(e)
    print("test_unary_negate passed")


def test_resize_rounding_ties():
    # frac_bits: 1 -> 0, SHIFT=1. Ties at .5 boundaries, both parities of the
    # truncated integer and both signs, so round_half_even's odd/even branch
    # and round_half_away's sign branch are both genuinely exercised.
    src = make_fixed_t(4, 1)
    dst = make_fixed_t(4, 0)
    cases = [
        # (value, truncate, round_half_up, round_half_even, round_half_away)
        (-1.5, -2, -1, -2, -2),  # truncated=-2 (even)
        (1.5, 1, 2, 2, 2),  # truncated=1 (odd) -> half_even rounds up to 2
        (-3.5, -4, -3, -4, -4),  # truncated=-4 (even)
        (3.5, 3, 4, 4, 4),  # truncated=3 (odd) -> half_even rounds up to 4
    ]
    for value, exp_trunc, exp_up, exp_even, exp_away in cases:
        x = src.as_const(value)
        for rounding, expected in (
            ("truncate", exp_trunc),
            ("round_half_up", exp_up),
            ("round_half_even", exp_even),
            ("round_half_away", exp_away),
        ):
            resize_fn = make_fixed_resize(src, dst, rounding=rounding, overflow="wrap")
            r = sim_call(resize_fn, x)
            assert int(r.val) == expected, (value, rounding, int(r.val), expected)
    print("test_resize_rounding_ties passed")


def test_resize_saturation():
    src = make_fixed_t(8, 0)
    dst = make_fixed_t(4, 0)  # signed range [-8, 7]; SHIFT=0 (widening/no-shift branch)
    sat = make_fixed_resize(src, dst, overflow="saturate")
    wrap = make_fixed_resize(src, dst, overflow="wrap")

    # In-range value: both modes agree, no clamping.
    in_range = src(val=5)
    assert int(sim_call(sat, in_range).val) == 5
    assert int(sim_call(wrap, in_range).val) == 5

    # Positive overflow: saturate clamps to 7, wrap truncates to raw&0xF.
    big = src(val=100)
    r_sat = sim_call(sat, big)
    r_wrap = sim_call(wrap, big)
    assert int(r_sat.val) == 7, int(r_sat.val)
    assert int(r_wrap.val) == 100 - 96, int(
        r_wrap.val
    )  # 100 mod 16, sign-adjusted -> 4
    assert int(r_sat.val) != int(r_wrap.val)

    # Negative overflow: saturate clamps to -8.
    neg_big = src(val=-100)
    r_sat_neg = sim_call(sat, neg_big)
    assert int(r_sat_neg.val) == -8, int(r_sat_neg.val)

    # Exact boundary values: no clamping needed.
    assert (
        int(sim_call(sat, src(val=127)).val) == 7
    )  # already saturated by src's own range? no: 127 -> clamp to 7
    assert int(sim_call(sat, src(val=-128)).val) == -8
    print("test_resize_saturation passed")


def test_quantize_coeffs():
    coeff_t = make_fixed_t(2, 6)  # LSB = 1/64
    high_prec_t = make_fixed_t(2, 20)  # exact representation of all taps below
    taps = [0.5, -0.5, 1.0 / 64, -1.5, 0.0078125]  # last tap is an exact half-LSB tie
    for rounding in ("truncate", "round_half_up", "round_half_even", "round_half_away"):
        got = quantize_coeffs(taps, coeff_t, rounding=rounding)
        resize_fn = make_fixed_resize(
            high_prec_t, coeff_t, rounding=rounding, overflow="wrap"
        )
        for tap, expected_raw in zip(taps, got):
            hp = high_prec_t.as_const(
                tap
            )  # exact -- all taps representable at 20 frac bits
            resized = sim_call(resize_fn, hp)
            assert int(resized.val) == expected_raw, (
                tap,
                rounding,
                expected_raw,
                int(resized.val),
            )
    # Truncate must floor, not truncate-toward-zero, for negative values.
    assert quantize_coeffs([-1.5], coeff_t, rounding="truncate")[0] == _quantize(
        -1.5, 6, 8, True, "truncate"
    )
    print("test_quantize_coeffs passed")


if __name__ == "__main__":
    test_as_const_roundtrip()
    test_arithmetic_vs_fraction_golden()
    test_sign_mismatched_operand_pairs()
    test_mismatched_frac_bits_raises()
    test_unary_negate()
    test_resize_rounding_ties()
    test_resize_saturation()
    test_quantize_coeffs()
    print("All fixed_point tests passed.")
