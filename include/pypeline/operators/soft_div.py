"""Soft restoring divider/modulo.

make_soft_div/make_soft_mod are unsigned-only (the restoring-division loop
below only ever produces a non-negative quotient/remainder). Signed division
(make_soft_signed_div/make_soft_signed_mod) wraps the unsigned divider with
the same abs-operands-then-fix-sign structure
SW_LIB.GET_BIN_OP_DIV_INT_N_C_CODE / GET_BIN_OP_MOD_INT_N_C_CODE used to
generate as C: divide magnitudes unsigned, then negate the result if the
operand signs differed (quotient) or, matching that same (already a bit
unusual -- see the C version's own "TODO is the sign fixing here right for
signed modulo?" comment) sign rule, for the remainder too. Kept bit-for-bit
behaviorally identical to the old SW_LIB lowering rather than "fixed" to a
different convention, since nothing depended on this being C-style
truncating modulo and changing it now would be a silent behavior change of
its own.
"""
from pypeline import hw_func, uint1_t, bit_assign, concat, arith_result_type, make_int_t, make_uint_t


def _make_restoring(want_remainder):
    def factory(l_t, r_t):
        eff_l_t, eff_r_t, out_t = arith_result_type("DIV", l_t, r_t)
        n_bits = len(eff_l_t)

        @hw_func
        def restoring_div(a: l_t, b: r_t) -> out_t:
            ae: eff_l_t = a
            be: eff_r_t = b
            rem: eff_l_t = 0
            quot: eff_l_t = 0
            for bit_idx in range(n_bits):
                i = n_bits - 1 - bit_idx
                rem = (rem << 1) | ae[i]
                quot_bit: uint1_t = 0
                if rem >= be:
                    rem = rem - be
                    quot_bit = 1
                quot = bit_assign(quot, quot_bit, i)
            result: out_t = 0
            if want_remainder:
                result = rem
            else:
                result = quot
            return result

        return restoring_div

    return factory


make_soft_div = _make_restoring(want_remainder=False)
make_soft_mod = _make_restoring(want_remainder=True)


def _make_signed(want_remainder):
    def factory(l_t, r_t):
        eff_l_t, eff_r_t, out_t = arith_result_type("DIV", l_t, r_t)
        width = max(len(eff_l_t), len(eff_r_t))
        signed_t = make_int_t(width)
        unsigned_t = make_uint_t(width)
        unsigned_impl = _make_restoring(want_remainder)(unsigned_t, unsigned_t)

        @hw_func
        def signed_restoring_div(a: l_t, b: r_t) -> out_t:
            ae: signed_t = a
            be: signed_t = b
            l_sign: uint1_t = ae[width - 1]
            r_sign: uint1_t = be[width - 1]
            # Two's-complement negate via bitwise primitives (~x + 1), not
            # the NEGATE operator, so this never depends on what (if
            # anything) is registered for unary "-".
            a_abs: signed_t = ae
            if l_sign:
                a_abs = (~ae) + 1
            b_abs: signed_t = be
            if r_sign:
                b_abs = (~be) + 1
            a_u: unsigned_t = a_abs
            b_u: unsigned_t = b_abs
            u_result: unsigned_t = unsigned_impl(a_u, b_u)
            result: out_t = u_result
            if l_sign ^ r_sign:
                signed_result: signed_t = u_result
                result = (~signed_result) + 1
            return result

        return signed_restoring_div

    return factory


make_soft_signed_div = _make_signed(want_remainder=False)
make_soft_signed_mod = _make_signed(want_remainder=True)


def _make_radix4_restoring(want_remainder):
    """Radix-4 restoring divider: 2 quotient bits per step instead of 1,
    halving the step count of _make_restoring for the same per-step shape
    (one widened compare-and-subtract, now against 3 precomputed multiples
    of the divisor instead of 1). Measured on latchup.app's 32-bit divider
    (docs: div_qor_bench exploration) at 1.63x the fmax of the plain
    restoring divider under PyRTL estimates -- by a wide margin the best
    lever of everything tried there (loop-body-as-its-own-func, killing the
    redundant compare+subtract, non-restoring, un-normalized signed-digit).

    Unsigned-only, same as _make_restoring -- make_soft_signed_radix4_div/mod
    below wrap this with the same abs-then-fix-sign structure
    make_soft_signed_div/mod use.

    Odd bit widths take one leading radix-2 (single-bit) step so every
    remaining step is a clean 2-bit group -- this is what n_bits % 2 tests
    for below, entirely at elaboration time (n_bits is a closure constant,
    so the Python if/while here shapes which HDL gets generated, not
    hardware itself)."""
    def factory(l_t, r_t):
        eff_l_t, eff_r_t, out_t = arith_result_type("DIV", l_t, r_t)
        n_bits = len(eff_l_t)
        # 8 guard bits: generous, not tightly optimized (matching this
        # library's existing bias toward simple-and-clearly-correct over
        # minimal width -- see make_soft_ripple_add's plain bitwise leaves).
        # 3x the widest possible divisor (2**n_bits - 1) needs n_bits+2 bits;
        # +8 leaves headroom to spare.
        wide_t = make_uint_t(n_bits + 8)
        two_t = make_uint_t(2)

        # Elaboration-time step list: 2-bit (hi, lo) groups from the MSB
        # down, with a leading 1-bit group first when n_bits is odd.
        steps = []
        idx = n_bits - 1
        if n_bits % 2 == 1:
            steps.append((idx,))
            idx -= 1
        while idx >= 1:
            steps.append((idx, idx - 1))
            idx -= 2

        @hw_func
        def radix4_div(a: l_t, b: r_t) -> out_t:
            ae: eff_l_t = a
            be: eff_r_t = b
            d1: wide_t = be
            d2: wide_t = d1 + d1
            d3: wide_t = d2 + d1
            rem: wide_t = 0
            quot: eff_l_t = 0
            for step in steps:
                if len(step) == 1:
                    k = step[0]
                    rem = (rem << 1) | ae[k]
                    qbit: uint1_t = 0
                    if rem >= d1:
                        rem = rem - d1
                        qbit = 1
                    quot = bit_assign(quot, qbit, k)
                else:
                    hi, lo = step
                    bits2: two_t = concat(ae[hi], ae[lo])
                    rem = (rem << 2) | bits2
                    q2: two_t = 0
                    if rem >= d3:
                        rem = rem - d3
                        q2 = 3
                    elif rem >= d2:
                        rem = rem - d2
                        q2 = 2
                    elif rem >= d1:
                        rem = rem - d1
                        q2 = 1
                    quot = bit_assign(quot, q2[1], hi)
                    quot = bit_assign(quot, q2[0], lo)
            result: out_t = 0
            if want_remainder:
                rem_narrow: eff_l_t = rem
                result = rem_narrow
            else:
                result = quot
            return result

        return radix4_div

    return factory


make_soft_radix4_div = _make_radix4_restoring(want_remainder=False)
make_soft_radix4_mod = _make_radix4_restoring(want_remainder=True)


def _make_signed_radix4(want_remainder):
    def factory(l_t, r_t):
        eff_l_t, eff_r_t, out_t = arith_result_type("DIV", l_t, r_t)
        width = max(len(eff_l_t), len(eff_r_t))
        signed_t = make_int_t(width)
        unsigned_t = make_uint_t(width)
        unsigned_impl = _make_radix4_restoring(want_remainder)(unsigned_t, unsigned_t)

        @hw_func
        def signed_radix4_div(a: l_t, b: r_t) -> out_t:
            ae: signed_t = a
            be: signed_t = b
            l_sign: uint1_t = ae[width - 1]
            r_sign: uint1_t = be[width - 1]
            a_abs: signed_t = ae
            if l_sign:
                a_abs = (~ae) + 1
            b_abs: signed_t = be
            if r_sign:
                b_abs = (~be) + 1
            a_u: unsigned_t = a_abs
            b_u: unsigned_t = b_abs
            u_result: unsigned_t = unsigned_impl(a_u, b_u)
            result: out_t = u_result
            if l_sign ^ r_sign:
                signed_result: signed_t = u_result
                result = (~signed_result) + 1
            return result

        return signed_radix4_div

    return factory


make_soft_signed_radix4_div = _make_signed_radix4(want_remainder=False)
make_soft_signed_radix4_mod = _make_signed_radix4(want_remainder=True)
