"""Soft (bitwise-leaf) adders and subtractors.

Full-precision add/sub result width matches pypeline.arith_result_type exactly
-- the same rule the built-in inferred BIN_OP_PLUS/BIN_OP_MINUS path uses --
so registering these never changes an existing design's wire widths.

Loop bounds (n_bits/l_bits/r_bits) are elaboration-time Python ints captured
in the closure, so `for i in range(n_bits)` unrolls and `if i < l_bits`
branch-eliminates at elaboration time (matching the established idiom in
floating_point.py's _make_clz/_make_shifter_sr) -- only the runtime bit
values (ae[i], carry, ...) become real hardware.
"""
from pypeline import hw_func, uint1_t, bit_assign, arith_result_type


def make_soft_add_ripple(l_t, r_t):
    """Bit-by-bit ripple-carry adder: sum[i] = a[i] ^ b[i] ^ carry,
    carry' = majority(a[i], b[i], carry). Built entirely from bitwise
    AND/OR/XOR -- the leaf ops that stay inferred -- plus bit_assign wiring."""
    eff_l_t, eff_r_t, out_t = arith_result_type("PLUS", l_t, r_t)
    n_bits = len(out_t)
    l_bits = len(eff_l_t)
    r_bits = len(eff_r_t)

    @hw_func
    def soft_add_ripple(a: l_t, b: r_t) -> out_t:
        ae: eff_l_t = a
        be: eff_r_t = b
        result: out_t = 0
        carry: uint1_t = 0
        for i in range(n_bits):
            ai: uint1_t = 0
            bi: uint1_t = 0
            if i < l_bits:
                ai = ae[i]
            if i < r_bits:
                bi = be[i]
            bit_val: uint1_t = (ai ^ bi) ^ carry
            result = bit_assign(result, bit_val, i)
            carry = (ai & bi) | (ai & carry) | (bi & carry)
        return result

    return soft_add_ripple


def make_soft_add_carry_select(l_t, r_t, block_bits=4):
    """Carry-select adder: split into fixed-size blocks, compute each block's
    sum for both possible incoming carries (0 and 1), then bitwise-select the
    correct one once the true carry-in is known. Same full-precision result
    as make_soft_add_ripple -- a different structure, not a different answer
    -- to exercise the "multiple soft flavors" mechanism end to end."""
    eff_l_t, eff_r_t, out_t = arith_result_type("PLUS", l_t, r_t)
    n_bits = len(out_t)
    l_bits = len(eff_l_t)
    r_bits = len(eff_r_t)

    @hw_func
    def soft_add_carry_select(a: l_t, b: r_t) -> out_t:
        ae: eff_l_t = a
        be: eff_r_t = b
        result: out_t = 0
        carry: uint1_t = 0
        block_start = 0
        while block_start < n_bits:
            block_end = min(block_start + block_bits, n_bits)
            sum0: out_t = 0
            sum1: out_t = 0
            c0: uint1_t = 0
            c1: uint1_t = 1
            for i in range(block_start, block_end):
                ai: uint1_t = 0
                bi: uint1_t = 0
                if i < l_bits:
                    ai = ae[i]
                if i < r_bits:
                    bi = be[i]
                bit0: uint1_t = (ai ^ bi) ^ c0
                bit1: uint1_t = (ai ^ bi) ^ c1
                sum0 = bit_assign(sum0, bit0, i)
                sum1 = bit_assign(sum1, bit1, i)
                c0 = (ai & bi) | (ai & c0) | (bi & c0)
                c1 = (ai & bi) | (ai & c1) | (bi & c1)
            if carry:
                for i in range(block_start, block_end):
                    result = bit_assign(result, sum1[i], i)
                carry = c1
            else:
                for i in range(block_start, block_end):
                    result = bit_assign(result, sum0[i], i)
                carry = c0
            block_start = block_end
        return result

    return soft_add_carry_select


def make_soft_sub(l_t, r_t):
    """a - b == a + (~b) + 1 (two's-complement subtract-via-add), the same
    structure the SW_LIB C negate/compare lowerings already used. Uses the
    built-in inferred adder -- MINUS stays inferred by default; this is what
    a caller opts into via register_soft_sub()."""
    eff_l_t, eff_r_t, out_t = arith_result_type("MINUS", l_t, r_t)

    @hw_func
    def soft_sub(a: l_t, b: r_t) -> out_t:
        ae: out_t = a
        be: eff_r_t = b
        not_b: eff_r_t = ~be
        result: out_t = ae + not_b + 1
        return result

    return soft_sub
