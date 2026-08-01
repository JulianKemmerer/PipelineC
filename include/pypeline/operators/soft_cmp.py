"""Soft integer comparators.

Three flavors, registered the same way any other operator overload is: last
registration for an overlapping matcher wins.

  * make_soft_sub_cmp_swapped (default, see soft.py:register_soft_cmp) --
    widen, subtract, take the sign bit, with the operand order swapped per
    op so a single sign-bit read is always enough (see below). Matches the
    structure SW_LIB.GET_BIN_OP_GT_GTE_LT_LTE_UINT_C_CODE used to generate
    as C; here it is ordinary Pypeline HDL, built on the inferred subtractor
    (or the soft one, if the caller also registered soft sub).
  * make_soft_sub_cmp -- same idea but a fixed a-b subtraction reused across
    all four ops, which forces an extra EQ+MUX for GT/LTE (see its
    docstring). Kept for QoR comparison (src/tests/pypeline_tests/
    op_qor_bench.py) and as a simpler reference implementation; no longer
    the default.
  * make_soft_bitwise_cmp -- MSB-first bitwise magnitude compare, no
    arithmetic at all. Mirrors the (currently dead-code) algorithm in
    RAW_VHDL.py's GET_BIN_OP_GT_GTE_*_C_BUILT_IN_INT_N_/UINT_N_ generators,
    which are unreachable today because C_BUILT_IN_FUNC_IS_RAW_HDL returns
    False for integer GT/GTE/LT/LTE.

QoR data (src/tests/pypeline_tests/op_qor_results_pyrtl.csv, docs/SYN_DESIGN.md)
confirms make_soft_sub_cmp_swapped strictly dominates make_soft_sub_cmp at
every measured width and cut count for GT/LTE (identical for GTE/LT, where
the un-swapped default was already cheap) -- not just combinationally, the
win holds across the full sliced/pipelined range that matters for fmax.
"""
from pypeline import hw_func, uint1_t, make_int_t, make_uint_t, arith_result_type

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


def make_soft_sub_cmp_swapped(op):
    """Default comparator flavor (see soft.py:register_soft_cmp): operand-swap
    instead of a fixed diff + separate is_zero test, matching the structure
    SW_LIB.GET_BIN_OP_GT_GTE_LT_LTE_UINT_C_CODE actually used (see
    docs/SYN_DESIGN.md) -- one subtract, one sign-bit read, no EQ submodule
    and no MUX. `a>b` == neg(b-a); `a>=b` == !neg(a-b); `a<b` == neg(a-b);
    `a<=b` == !neg(b-a)."""
    strict = _STRICT[op]
    greater = _GREATER[op]

    def factory(l_t, r_t):
        eff_l_t, eff_r_t, _ = arith_result_type("MINUS", l_t, r_t)
        width = max(len(eff_l_t), len(eff_r_t)) + 1
        sub_t = make_int_t(width)

        @hw_func
        def soft_sub_cmp_swapped(a: l_t, b: r_t) -> uint1_t:
            ae: sub_t = a
            be: sub_t = b
            result: uint1_t = 0
            if greater:
                # a>b: neg(b-a).  a>=b: !neg(a-b)
                if strict:
                    diff: sub_t = be - ae
                else:
                    diff: sub_t = ae - be
                neg: uint1_t = diff[len(sub_t) - 1]
                result = neg if strict else (1 - neg)
            else:
                # a<b: neg(a-b).  a<=b: !neg(b-a)
                if strict:
                    diff: sub_t = ae - be
                else:
                    diff: sub_t = be - ae
                neg: uint1_t = diff[len(sub_t) - 1]
                result = neg if strict else (1 - neg)
            return result

        return soft_sub_cmp_swapped

    return factory


def make_soft_bitwise_cmp(op):
    """Return a factory(l_t, r_t) -> hw_func implementing `op` via MSB-first
    bitwise magnitude comparison (no adder/subtractor at all)."""
    strict = _STRICT[op]
    greater = _GREATER[op]

    def factory(l_t, r_t):
        # arith_result_type("MINUS", ...) only sign-promotes -- for
        # mismatched-width unsigned operands (e.g. uint32_t vs uint3_t) it
        # returns eff_l_t/eff_r_t at their ORIGINAL differing widths, not a
        # common one (confirmed: arith_result_type("MINUS", uint32_t, uint3_t)
        # == (uint32_t, uint3_t, ...)). Indexing both at n_bits=len(eff_l_t)
        # then overruns the narrower operand. Resize both to one common width
        # explicitly, same pattern make_soft_sub_cmp uses.
        eff_l_t, eff_r_t, _ = arith_result_type("MINUS", l_t, r_t)
        n_bits = max(len(eff_l_t), len(eff_r_t))
        is_signed = str(l_t).startswith("int") or str(r_t).startswith("int")
        make_t = make_int_t if is_signed else make_uint_t
        common_t = make_t(n_bits)

        @hw_func
        def soft_bitwise_cmp(a: l_t, b: r_t) -> uint1_t:
            ae: common_t = a
            be: common_t = b
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
