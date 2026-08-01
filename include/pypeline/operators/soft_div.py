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
from pypeline import hw_func, uint1_t, bit_assign, arith_result_type, make_int_t, make_uint_t


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
