"""Unchanged canonical Poly1305 arithmetic for manual compiler QoR comparisons.

Source: wireguard-fpga/3.build/pypeline_build/src/poly1305/poly1305_math.py.
Only imports and the fixed hybrid_square configuration are fixture scaffolding.
"""
# Extracted from wireguard-fpga, accepted shared-poly1305-fsm64-latest-qor-20261017.
# WireGuard revision: a9eb0608 (plus the archived working-tree design).
# Archive SHA-256: 2c0989d316e83abd7c68e9126b541bd0537ec38266f4eb500ab4c17a17971cea.
from types import SimpleNamespace
from pypeline import hw_func, make_uint_t, register_operator

# Match the accepted design's arithmetic configuration.
wireguard_env = SimpleNamespace(POLY1305_MULT_IMPL="hybrid_square")
# Tag half transported by the epilogue.
uint128_t = make_uint_t(128)

uint130_t = make_uint_t(130)
uint131_t = make_uint_t(131)
uint133_t = make_uint_t(133)
uint260_t = make_uint_t(260)
uint3_t = make_uint_t(3)
POLY1305_P = (1 << 130) - 5

# Exact-type registration reaches both modular multiply helpers while leaving
# legacy 64-bit limbs and the reducer's constant products unchanged. Ordinary
# module-level hw_func scope= does not currently affect HDL elaboration.
# The library's pinned inferred leaves prevent recursive operator dispatch.
if wireguard_env.POLY1305_MULT_IMPL in ("hybrid", "hybrid_square"):
    from operators.soft_mult import make_mult_karatsuba_inferred_leaves
    register_operator("INFERRED_MULT", uint130_t, uint130_t,
                      make_mult_karatsuba_inferred_leaves(uint130_t, uint130_t, threshold=34))


@hw_func
def uint260_mod_prime(value: uint260_t) -> uint130_t:
    """Exact reduction for every 260-bit input, with explicit carry widths."""
    low: uint130_t = value
    high: uint130_t = value >> 130
    # < 6*2^130, so the remaining quotient fits three bits (at most 5).
    folded: uint133_t = low + high * 5
    low_again: uint130_t = folded
    high_again: uint3_t = folded >> 130
    # <= 2^130+24 < 2*p: one full-width subtraction canonicalizes it.
    reduced: uint131_t = low_again + high_again * 5
    if reduced >= POLY1305_P:
        reduced -= POLY1305_P
    result: uint130_t = reduced
    return result


@hw_func
def residue_mul_mod(a: uint130_t, b: uint130_t) -> uint130_t:
    product: uint260_t = a * b
    return uint260_mod_prime(product)


def make_hybrid_square(width):
    """Unsigned full square: Karatsuba above 34 bits, three DSP-sized products below.

    This is a local experiment, independent of the library's multiplier defaults.
    Every shift acts on an already widened value. Only the final recombination
    is narrowed to the exact 2*width-bit result.
    """
    from operators.soft_mult import make_inferred_mult
    if not isinstance(width, int) or width < 1:
        raise ValueError("square width must be a positive integer")
    input_t = make_uint_t(width)
    result_t = make_uint_t(2 * width)
    if width <= 17:
        multiply = make_inferred_mult(input_t, input_t)

        @hw_func
        def inferred_square(x: input_t) -> result_t:
            return multiply(x, x)
        return inferred_square

    half = width // 2
    lo_t = make_uint_t(half)
    hi_t = make_uint_t(width - half)
    if width <= 34:
        multiply_lo = make_inferred_mult(lo_t, lo_t)
        multiply_hi = make_inferred_mult(hi_t, hi_t)
        multiply_cross = make_inferred_mult(lo_t, hi_t)

        @hw_func
        def three_product_square(x: input_t) -> result_t:
            lo: lo_t = x
            hi: hi_t = x >> half
            z0: result_t = multiply_lo(lo, lo)
            z2: result_t = multiply_hi(hi, hi)
            cross: result_t = multiply_cross(lo, hi)
            result: result_t = z0 + (cross << (half + 1)) + (z2 << (2 * half))
            return result
        return three_product_square

    sum_t = make_uint_t(width - half + 1)
    square_lo = make_hybrid_square(half)
    square_hi = make_hybrid_square(width - half)
    square_sum = make_hybrid_square(width - half + 1)

    @hw_func
    def karatsuba_square(x: input_t) -> result_t:
        lo: lo_t = x
        hi: hi_t = x >> half
        total: sum_t = lo + hi
        z0: result_t = square_lo(lo)
        z2: result_t = square_hi(hi)
        zs: result_t = square_sum(total)
        cross: result_t = zs - z0 - z2
        result: result_t = z0 + (cross << half) + (z2 << (2 * half))
        return result
    return karatsuba_square


square130 = make_hybrid_square(130)


@hw_func
def residue_square_mod(a: uint130_t) -> uint130_t:
    product: uint260_t = square130(a)
    return uint260_mod_prime(product)


@hw_func
def residue_mul_add_mod(a: uint130_t, b: uint130_t, c: uint130_t) -> uint130_t:
    product: uint260_t = a * b
    # Even for all-ones 130-bit operands, a*b+c is strictly below 2^260.
    value: uint260_t = product + c
    return uint260_mod_prime(value)


@hw_func
def residue_add_mod(a: uint130_t, b: uint130_t) -> uint130_t:
    value: uint131_t = a + b
    low: uint130_t = value
    high: uint3_t = value >> 130
    folded: uint131_t = low + high * 5
    if folded >= POLY1305_P:
        folded -= POLY1305_P
    result: uint130_t = folded
    return result
