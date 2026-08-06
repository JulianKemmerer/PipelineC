"""Soft multipliers: shift-and-add (default) and a recursive Karatsuba split
(alternate flavor, built on the soft adder/subtractor so it exercises the
same composability the plan calls for)."""
from pypeline import hw_func, uint1_t, bit_dup, arith_result_type


def make_soft_shift_add_mult(l_t, r_t):
    """Grade-school shift-and-add multiplier: for each bit of b, produce a
    partial product (a << i) or 0, then sum all partial products with a
    balanced binary adder tree (log2(n) deep) of the inferred + operator
    instead of a linear O(n)-deep accumulator chain -- same partial-product
    structure as SW_LIB.GET_BIN_OP_MULT_UINT_N_C_CODE, now as one flat
    Pypeline @hw_func with a node array reduced level by level, the same
    single-function balanced-tree shape as dsp/fir_common.make_fir_core's
    `nodes: T[LEVELS+1][NPAD]` reduction (no per-level submodule boundaries,
    which a first attempt at composing recursive per-level sub-@hw_funcs with
    growing per-level widths turned out to synthesize *larger*, not smaller,
    through this generic non-FPGA-targeted yosys `synth` pass -- so this
    version keeps one uniform out_t-width node array throughout, trading the
    narrower-intermediate-width idea for a design proven not to regress
    area)."""
    eff_l_t, eff_r_t, out_t = arith_result_type("INFERRED_MULT", l_t, r_t)
    n_bits = len(out_t)
    r_bits = len(eff_r_t)
    levels = max(1, (r_bits - 1).bit_length())
    npad = 1 << levels

    @hw_func
    def soft_shift_add_mult(a: l_t, b: r_t) -> out_t:
        ae: out_t = a
        be: eff_r_t = b
        nodes: out_t[levels + 1][npad]
        for i in range(r_bits):
            bit_mask: out_t = bit_dup(be[i], n_bits)
            nodes[0][i] = (ae << i) & bit_mask
        for i in range(r_bits, npad):
            nodes[0][i] = 0
        for lvl in range(levels):
            for i in range(npad >> (lvl + 1)):
                nodes[lvl + 1][i] = nodes[lvl][2 * i] + nodes[lvl][2 * i + 1]
        return nodes[levels][0]

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
