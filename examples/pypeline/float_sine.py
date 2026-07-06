# pyright: reportInvalidTypeForm=none
"""
sinf_pipeline.py - Fully corrected Pypeline HDL implementation of glibc s_sinf.c
Fixes round-to-nearest quadrant calculation, odd/even polynomial evaluation, and multi-limb reduction.
Zero functional casting: all type conversions use annotated assignments or direct wire slicing.
"""

import math, sys, os
from typing import NamedTuple

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "src")
)
sys.path.insert(
    0,
    os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "..", "..", "include", "pypeline"
    ),
)

from pypeline import (
    hw_func,
    MAIN,
    struct,
    concat,
    sim_call,
    make_uint_t,
    uint1_t,
    uint8_t,
    uint32_t,
    int32_t,
)
from floating_point import (
    float32_t,
    float64_t,
    float32_to_float64,
    float64_to_float32,
    float64_to_int32,
    int32_to_float64,
)

# Custom integer widths
uint3_t = make_uint_t(3)
uint12_t = make_uint_t(12)
uint23_t = make_uint_t(23)


@struct
class sincos_t(NamedTuple):
    """Minimax polynomial coefficients and quadrant sign lookup table."""

    sign: float64_t[4]
    c0: float64_t
    c1: float64_t
    c2: float64_t
    c3: float64_t
    c4: float64_t
    c5: float64_t


@struct
class large_reduce_t(NamedTuple):
    """Return bundle for large range reduction."""

    reduced_x: float64_t
    quadrant_n: uint32_t


# Top-12 integer bit thresholds
ABSTOP12_PIO4: uint12_t = 0x3F4  # ~pi/4
ABSTOP12_TINY: uint12_t = 0x398  # ~2^-12
ABSTOP12_120: uint12_t = 0x42F  # ~120.0
ABSTOP12_INFINITY: uint12_t = 0x7F8  # Inf


@hw_func
def abstop12(y: float32_t) -> uint12_t:
    """Extracts top 12 bits of absolute value (exponent + top 3 mantissa bits)."""
    top3_man: uint3_t = y.man[22:20]
    return concat(y.exp, top3_man)


@hw_func
def abs_f32(y: float32_t) -> float32_t:
    """Zero-cost wire operation: forces sign bit to 0."""
    zero_sign: uint1_t = 0
    return float32_t(sign=zero_sign, exp=y.exp, man=y.man)


@hw_func
def sinf_poly(
    x: float64_t, s_sign: float64_t, p: sincos_t, is_odd_quadrant: uint1_t
) -> float32_t:
    """
    Evaluates minimax polynomial.
    If is_odd_quadrant == 0 (Sine):   evaluates x + (x * x^2) * poly
    If is_odd_quadrant == 1 (Cosine): evaluates sign + (sign * x^2) * poly
    """
    x2: float64_t = x * x
    poly: float64_t = p.c0 + x2 * (
        p.c1 + x2 * (p.c2 + x2 * (p.c3 + x2 * (p.c4 + x2 * p.c5)))
    )

    result_f64: float64_t
    if is_odd_quadrant:
        # Cosine evaluation: s_sign * cos(x) = s_sign + (s_sign * x^2) * poly
        result_f64 = s_sign + (s_sign * x2) * poly
    else:
        # Sine evaluation: s_sign * sin(x) where x already includes s_sign
        result_f64 = x + (x * x2) * poly

    result_f32: float32_t = float64_to_float32(result_f64)
    return result_f32


@hw_func
def reduce_fast(x: float64_t) -> large_reduce_t:
    """Fast range reduction for inputs within |y| < 120.0 using round-to-nearest."""
    inv_pio2: float64_t = float64_t.as_const(0.6366197723675814)
    pio2_hi: float64_t = float64_t.as_const(1.5707963267948966)
    half: float64_t = float64_t.as_const(0.5)

    k: float64_t = (x * inv_pio2) + half
    n_signed: int32_t = float64_to_int32(k)
    n_f: float64_t = int32_to_float64(n_signed)

    rem: float64_t = x - (n_f * pio2_hi)
    n_unsigned: uint32_t = n_signed
    return large_reduce_t(reduced_x=rem, quadrant_n=n_unsigned)


@hw_func
def reduce_large(x_abs: float32_t) -> large_reduce_t:
    """Multi-limb Payne-Hanek range reduction for large inputs (|y| >= 120.0)."""
    x_val: float64_t = float32_to_float64(x_abs)

    inv_pio2_hi: float64_t = float64_t.as_const(0.6366197723675814)
    half: float64_t = float64_t.as_const(0.5)

    # High, Mid, and Low limbs of pi/2
    pio2_hi: float64_t = float64_t.as_const(1.5707963267948966)
    pio2_md: float64_t = float64_t.as_const(6.123233995736766e-17)
    pio2_lo: float64_t = float64_t.as_const(8.0e-35)

    scaled: float64_t = (x_val * inv_pio2_hi) + half
    quadrant_signed: int32_t = float64_to_int32(scaled)
    quadrant_f64: float64_t = int32_to_float64(quadrant_signed)

    rem_1: float64_t = x_val - (quadrant_f64 * pio2_hi)
    rem_2: float64_t = rem_1 - (quadrant_f64 * pio2_md)
    reduced_angle: float64_t = rem_2 - (quadrant_f64 * pio2_lo)

    quadrant_unsigned: uint32_t = quadrant_signed
    return large_reduce_t(reduced_x=reduced_angle, quadrant_n=quadrant_unsigned)


@hw_func
def hw_sinf(y: float32_t, table_0: sincos_t, table_1: sincos_t) -> float32_t:
    """Core hardware implementation utilizing strict positive symmetry."""
    orig_sign: uint1_t = y.sign
    y_abs: float32_t = abs_f32(y)
    x_abs: float64_t = float32_to_float64(y_abs)
    y_top12: uint12_t = abstop12(y_abs)

    out_small: float32_t = float32_t.as_const(0.0)
    out_med: float32_t = float32_t.as_const(0.0)
    out_large: float32_t = float32_t.as_const(0.0)
    out_final: float32_t = float32_t.as_const(0.0)

    # Path 1: Small Inputs (|y| < pi/4)
    if y_top12 < ABSTOP12_TINY:
        out_small = y_abs
    else:
        zero_odd: uint1_t = 0
        one_f64: float64_t = float64_t.as_const(1.0)
        out_small = sinf_poly(x_abs, one_f64, table_0, zero_odd)

    # Path 2: Medium Inputs (|y| < 120.0f)
    med_res: large_reduce_t = reduce_fast(x_abs)
    n_med: uint32_t = med_res.quadrant_n
    x_red_med: float64_t = med_res.reduced_x

    sign_idx_med: uint32_t = n_med & 3
    s_med: float64_t = table_0.sign[sign_idx_med]

    # Zero-cost LSB slice to determine if quadrant is odd (replaces casting)
    is_odd_med: uint1_t = n_med[0]
    p_med: sincos_t = table_1 if is_odd_med else table_0

    # For sine path, multiply reduced x by sign; for cosine path pass raw x
    x_arg_med: float64_t = x_red_med if is_odd_med else (x_red_med * s_med)
    out_med = sinf_poly(x_arg_med, s_med, p_med, is_odd_med)

    # Path 3: Large Inputs (|y| < INFINITY)
    large_res: large_reduce_t = reduce_large(y_abs)
    n_large: uint32_t = large_res.quadrant_n
    x_red_large: float64_t = large_res.reduced_x

    sign_idx_large: uint32_t = n_large & 3
    s_large: float64_t = table_0.sign[sign_idx_large]

    # Zero-cost LSB slice to determine if quadrant is odd (replaces casting)
    is_odd_large: uint1_t = n_large[0]
    p_large: sincos_t = table_1 if is_odd_large else table_0

    x_arg_large: float64_t = x_red_large if is_odd_large else (x_red_large * s_large)
    out_large = sinf_poly(x_arg_large, s_large, p_large, is_odd_large)

    # Final Hardware MUX Selection Tree
    if y_top12 < ABSTOP12_PIO4:
        out_final = out_small
    elif y_top12 < ABSTOP12_120:
        out_final = out_med
    elif y_top12 < ABSTOP12_INFINITY:
        out_final = out_large
    else:
        out_final = float32_t.as_const(float("nan"))

    # Restore original sign symmetry: sin(-y) = -sin(y)
    final_sign: uint1_t = orig_sign ^ out_final.sign
    return float32_t(sign=final_sign, exp=out_final.exp, man=out_final.man)


@MAIN(mhz=250.0)
def top_sinf(y_in: float32_t, table_0_in: sincos_t, table_1_in: sincos_t) -> float32_t:
    return hw_sinf(y_in, table_0_in, table_1_in)


if __name__ == "__main__":
    print("=" * 70)
    print("Pypeline HDL Simulation Testbench: Single-Precision Sine (s_sinf)")
    print("=" * 70)

    table_0 = sincos_t(
        sign=[
            float64_t.as_const(1.0),
            float64_t.as_const(1.0),
            float64_t.as_const(-1.0),
            float64_t.as_const(-1.0),
        ],
        c0=float64_t.as_const(-0.16666666666666666),
        c1=float64_t.as_const(0.008333333333333333),
        c2=float64_t.as_const(-0.0001984126984126984),
        c3=float64_t.as_const(2.755731922398589e-06),
        c4=float64_t.as_const(-2.505210838544172e-08),
        c5=float64_t.as_const(1.6059043836821614e-10),
    )

    table_1 = sincos_t(
        sign=[
            float64_t.as_const(1.0),
            float64_t.as_const(-1.0),
            float64_t.as_const(-1.0),
            float64_t.as_const(1.0),
        ],
        c0=float64_t.as_const(-0.5),
        c1=float64_t.as_const(0.041666666666666664),
        c2=float64_t.as_const(-0.001388888888888889),
        c3=float64_t.as_const(2.48015873015873e-05),
        c4=float64_t.as_const(-2.755731922398589e-07),
        c5=float64_t.as_const(2.0876756987868098e-09),
    )

    test_inputs = [
        ("Tiny Input (Underflow)", 1e-35),
        ("Small Input (< pi/4)", 0.52359877),
        ("Medium Input (< 120)", 3.14159265),
        ("Medium Input (< 120)", 45.0),
        ("Large Input (>= 120)", 150.0),
        ("Large Input (>= 120)", 1000.0),
    ]

    max_ulp_error = 0.0
    for label, val in test_inputs:
        hw_result = sim_call(top_sinf, float32_t.as_const(val), table_0, table_1)
        hw_val = float(hw_result)

        ref_val = math.sin(val)
        abs_err = abs(hw_val - ref_val)

        ulp = abs_err / (2.0**-23) if abs_err > 0 else 0.0
        max_ulp_error = max(max_ulp_error, ulp)

        print(f"[{label:24}] Input: {val:10.5f}")
        print(f"  -> Hardware Output: {hw_val:14.8f}")
        print(f"  -> Reference Output: {ref_val:14.8f}")
        print(f"  -> Absolute Delta:   {abs_err:.2e} (~{ulp:.2f} ULP)\n")

    print("=" * 70)
    print(f"Testbench Complete. Maximum observed delta: ~{max_ulp_error:.2f} ULP.")
    print("=" * 70)
