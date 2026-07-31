"""Soft integer comparators.

Two independent flavors, registered the same way any other operator overload
is: last registration for an overlapping matcher wins.

  * make_soft_sub_cmp   (default) -- widen, subtract, take the sign bit.
    Exactly the structure SW_LIB.GET_BIN_OP_GT_GTE_LT_LTE_UINT_C_CODE used to
    generate as C; here it is ordinary Pypeline HDL, built on the inferred
    subtractor (or the soft one, if the caller also registered soft sub).
  * make_soft_bitwise_cmp -- MSB-first bitwise magnitude compare, no
    arithmetic at all. Mirrors the (currently dead-code) algorithm in
    RAW_VHDL.py's GET_BIN_OP_GT_GTE_*_C_BUILT_IN_INT_N_/UINT_N_ generators,
    which are unreachable today because C_BUILT_IN_FUNC_IS_RAW_HDL returns
    False for integer GT/GTE/LT/LTE.
"""
from pypeline import hw_func, uint1_t, make_int_t, arith_result_type

_FLIP = {"GT": "LT", "LT": "GT", "GTE": "LTE", "LTE": "GTE"}
_STRICT = {"GT": True, "LT": True, "GTE": False, "LTE": False}
_GREATER = {"GT": True, "GTE": True, "LT": False, "LTE": False}


def make_soft_sub_cmp(op):
    """Return a factory(l_t, r_t) -> hw_func implementing `op` via
    widen + subtract + sign-bit (op in "GT"/"GTE"/"LT"/"LTE")."""
    strict = _STRICT[op]
    greater = _GREATER[op]

    def factory(l_t, r_t):
        # NOTE: arith_result_type("MINUS", ...) mirrors the built-in path's
        # rule that same-sign operands produce a same-sign (here: unsigned,
        # wrapping) result -- exactly wrong for a sign-bit trick. The
        # comparator instead needs an explicitly SIGNED, wide-enough-to-never-
        # overflow subtraction: width = max(operand widths) + 1 bits covers
        # every a-b in [-(2**n-1), 2**n-1] for n-bit unsigned operands.
        eff_l_t, eff_r_t, _ = arith_result_type("MINUS", l_t, r_t)
        width = max(len(eff_l_t), len(eff_r_t)) + 1
        sub_t = make_int_t(width)

        @hw_func
        def soft_sub_cmp(a: l_t, b: r_t) -> uint1_t:
            ae: sub_t = a
            be: sub_t = b
            # a - b: sign(diff) tells us a<b (negative) vs a>=b (non-negative);
            # strict/non-strict and greater/less variants derived from that.
            diff: sub_t = ae - be
            neg: uint1_t = diff[len(sub_t) - 1]
            is_zero: uint1_t = 1 if diff == 0 else 0
            result: uint1_t = 0
            if greater:
                if strict:
                    result = (1 - neg) & (1 - is_zero)
                else:
                    result = 1 - neg
            else:
                if strict:
                    result = neg
                else:
                    result = neg | is_zero
            return result

        return soft_sub_cmp

    return factory


def make_soft_bitwise_cmp(op):
    """Return a factory(l_t, r_t) -> hw_func implementing `op` via MSB-first
    bitwise magnitude comparison (no adder/subtractor at all)."""
    strict = _STRICT[op]
    greater = _GREATER[op]

    def factory(l_t, r_t):
        # Compare on same-signedness, equal-width operands (matches the
        # promotion the built-in inferred compare path already applies).
        eff_l_t, eff_r_t, _ = arith_result_type("MINUS", l_t, r_t)
        n_bits = len(eff_l_t)
        is_signed = str(l_t).startswith("int") or str(r_t).startswith("int")

        @hw_func
        def soft_bitwise_cmp(a: l_t, b: r_t) -> uint1_t:
            ae: eff_l_t = a
            be: eff_r_t = b
            gt: uint1_t = 0
            lt: uint1_t = 0
            decided: uint1_t = 0
            # MSB carries sign meaning for signed operands: an unset "gt/lt"
            # decision after the top bit flips outcome for mismatched signs.
            for bit_idx in range(n_bits):
                i = n_bits - 1 - bit_idx
                ai: uint1_t = ae[i]
                bi: uint1_t = be[i]
                if is_signed and i == n_bits - 1:
                    # Sign bit: 0 (non-negative) is greater than 1 (negative).
                    this_gt: uint1_t = (1 - ai) & bi
                    this_lt: uint1_t = ai & (1 - bi)
                else:
                    this_gt: uint1_t = ai & (1 - bi)
                    this_lt: uint1_t = (1 - ai) & bi
                if not decided:
                    if this_gt:
                        gt = 1
                        decided = 1
                    elif this_lt:
                        lt = 1
                        decided = 1
            result: uint1_t = 0
            if greater:
                result = gt if strict else (gt | (1 - (gt | lt)))
            else:
                result = lt if strict else (lt | (1 - (gt | lt)))
            return result

        return soft_bitwise_cmp

    return factory
