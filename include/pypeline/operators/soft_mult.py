"""Soft multipliers: shift-and-add (default) and a recursive Karatsuba split
(alternate flavor, built on the soft adder/subtractor so it exercises the
same composability the plan calls for)."""
from pypeline import hw_func, uint1_t, bit_dup, arith_result_type


def make_soft_shift_add_mult(l_t, r_t):
    """Grade-school shift-and-add multiplier: for each bit of b, add
    (a << i) to the accumulator if that bit is set. Same partial-product
    structure as SW_LIB.GET_BIN_OP_MULT_UINT_N_C_CODE, now as Pypeline HDL."""
    eff_l_t, eff_r_t, out_t = arith_result_type("INFERRED_MULT", l_t, r_t)
    n_bits = len(out_t)
    r_bits = len(eff_r_t)

    @hw_func
    def soft_shift_add_mult(a: l_t, b: r_t) -> out_t:
        ae: out_t = a
        be: eff_r_t = b
        acc: out_t = 0
        for i in range(r_bits):
            bit_mask: out_t = bit_dup(be[i], n_bits)
            partial: out_t = (ae << i) & bit_mask
            acc = acc + partial
        return acc

    return soft_shift_add_mult


def make_soft_karatsuba_mult(l_t, r_t, threshold=8):
    """Recursive Karatsuba multiply. Below `threshold` bits, falls back to
    the shift-and-add multiplier (same style as a soft library implementation
    pinning its own base case rather than recursing forever)."""
    eff_l_t, eff_r_t, out_t = arith_result_type("INFERRED_MULT", l_t, r_t)
    n_bits = max(len(eff_l_t), len(eff_r_t))

    if n_bits <= threshold:
        return make_soft_shift_add_mult(l_t, r_t)

    from pypeline import make_uint_t

    half = n_bits // 2
    lo_t = make_uint_t(half)
    hi_t = make_uint_t(n_bits - half)
    mid_t = make_uint_t(max(half, n_bits - half) + 1)

    mult_lo = make_soft_karatsuba_mult(lo_t, lo_t, threshold)
    mult_hi = make_soft_karatsuba_mult(hi_t, hi_t, threshold)
    mult_mid = make_soft_karatsuba_mult(mid_t, mid_t, threshold)

    @hw_func
    def soft_karatsuba_mult(a: l_t, b: r_t) -> out_t:
        ae: eff_l_t = a
        be: eff_r_t = b
        a_lo: lo_t = ae
        a_hi: hi_t = ae >> half
        b_lo: lo_t = be
        b_hi: hi_t = be >> half
        z0: out_t = mult_lo(a_lo, b_lo)
        z2: out_t = mult_hi(a_hi, b_hi)
        a_sum: mid_t = a_lo + a_hi
        b_sum: mid_t = b_lo + b_hi
        z1_full: out_t = mult_mid(a_sum, b_sum)
        z1: out_t = z1_full - z0 - z2
        result: out_t = z2
        result = (result << (2 * half)) + (z1 << half) + z0
        return result

    return soft_karatsuba_mult
