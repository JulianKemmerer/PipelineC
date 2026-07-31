"""Soft restoring divider/modulo -- unsigned only (matches the width/output
rules of arith_result_type("DIV"/"MOD", ...); signed division is not
implemented in this pass -- see the plan's deferral notes)."""
from pypeline import hw_func, uint1_t, bit_assign, arith_result_type


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
