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
from pypeline import (
    hw_func,
    uint1_t,
    bit_assign,
    arith_result_type,
    make_uint_t,
    register_operator,
    register_left_operator,
    INFERRED,
)


def _sign_bits(eff_t):
    """(is_signed, width) for an operand's effective type.

    The adders below work bit by bit, so they have to perform the WIDENING to
    the result type themselves. Above an operand's own width a signed value
    continues with its sign bit, not with zero -- getting this wrong produces an
    adder that is right for every non-negative input and quietly wrong for the
    rest (int16 -3 + 4 came out as 65537 rather than 1). Same
    `str(t).startswith("int")` test soft_cmp.py uses.
    """
    return str(eff_t).startswith("int"), len(eff_t)


def make_soft_add_ripple(l_t, r_t):
    """Bit-by-bit ripple-carry adder: sum[i] = a[i] ^ b[i] ^ carry,
    carry' = majority(a[i], b[i], carry). Built entirely from bitwise
    AND/OR/XOR -- the leaf ops that stay inferred -- plus bit_assign wiring."""
    eff_l_t, eff_r_t, out_t = arith_result_type("PLUS", l_t, r_t)
    n_bits = len(out_t)
    l_signed, l_bits = _sign_bits(eff_l_t)
    r_signed, r_bits = _sign_bits(eff_r_t)

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
            elif l_signed:
                ai = ae[l_bits - 1]
            if i < r_bits:
                bi = be[i]
            elif r_signed:
                bi = be[r_bits - 1]
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
    l_signed, l_bits = _sign_bits(eff_l_t)
    r_signed, r_bits = _sign_bits(eff_r_t)

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
                elif l_signed:
                    ai = ae[l_bits - 1]
                if i < r_bits:
                    bi = be[i]
                elif r_signed:
                    bi = be[r_bits - 1]
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
    structure the C front end's generated C negate/compare lowerings already used. Uses the
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


def _pin_inferred_add(func, l_t, r_t):
    """Keep `l_t + r_t` inside `func` on the built-in inferred adder, whatever
    PLUS registration is active (the same scoped-INFERRED pin
    soft_mult.make_inferred_mult uses for `*`). The split adders below exist
    to hand AUTO_FSM narrower BUILT-IN adds; a global register_soft_add()
    turning those into ripple adders would defeat that."""
    register_operator("PLUS", l_t, r_t, INFERRED, scope=func)
    # An INFERRED exact hit falls through to the left-operand registry.
    register_left_operator("PLUS", l_t, INFERRED, scope=func)


def _make_split_add(op, l_t, r_t):
    """Shared body of make_soft_add_split / make_soft_sub_split.

    out = a + b (op "PLUS") or a + ~b + 1 (op "MINUS"), modulo 2**len(out_t),
    computed as two built-in adds of about half the result width: the low half
    first, then the high half with the low half's carry. A carry-in enters an
    inferred adder through one extra low bit -- (x<<1 | 1) + (y<<1 | c) has
    bit 0 equal to 1 + c, whose carry out is exactly c -- so each half is ONE
    `+`, and the extra bit is dropped afterwards. Every shift, truncation and
    bit_assign here is wiring.
    """
    eff_l_t, eff_r_t, out_t = arith_result_type(op, l_t, r_t)
    if str(eff_l_t).startswith("int") or str(eff_r_t).startswith("int"):
        raise TypeError(f"split {op}: unsigned operands only (got {l_t}, {r_t})")
    n_bits = len(out_t)
    if n_bits < 2:
        raise ValueError(f"split {op}: a {n_bits}-bit result has no halves")
    lo_bits = n_bits // 2
    hi_bits = n_bits - lo_bits
    word_t = make_uint_t(n_bits)
    lo_t = make_uint_t(lo_bits)
    hi_t = make_uint_t(hi_bits)
    subtract = op == "MINUS"
    # Low half: a plain add, or for subtract the carry-in-1 form.
    lo_in_t = make_uint_t(lo_bits + 1) if subtract else lo_t
    lo_sum_t = make_uint_t(lo_bits + 2) if subtract else make_uint_t(lo_bits + 1)
    hi_in_t = make_uint_t(hi_bits + 1)
    hi_sum_t = make_uint_t(hi_bits + 2)

    @hw_func
    def soft_add_split(a: l_t, b: r_t) -> out_t:
        aw: word_t = a
        bw: word_t = b
        if subtract:
            bw = ~bw
        a_lo: lo_t = aw
        b_lo: lo_t = bw
        a_hi: hi_t = aw >> lo_bits
        b_hi: hi_t = bw >> lo_bits
        lo_sum: lo_sum_t = 0
        if subtract:
            a_lo_c: lo_in_t = 1
            a_lo_c = bit_assign(a_lo_c, a_lo, 1)
            b_lo_c: lo_in_t = 1
            b_lo_c = bit_assign(b_lo_c, b_lo, 1)
            lo_sum = (a_lo_c + b_lo_c) >> 1
        else:
            lo_sum = a_lo + b_lo
        carry: uint1_t = lo_sum >> lo_bits
        a_hi_c: hi_in_t = 1
        a_hi_c = bit_assign(a_hi_c, a_hi, 1)
        b_hi_c: hi_in_t = carry
        b_hi_c = bit_assign(b_hi_c, b_hi, 1)
        hi_sum: hi_sum_t = a_hi_c + b_hi_c
        hi_part: hi_t = hi_sum >> 1
        lo_part: lo_t = lo_sum
        result: word_t = 0
        result = bit_assign(result, lo_part, 0)
        result = bit_assign(result, hi_part, lo_bits)
        return result

    if subtract:
        _pin_inferred_add(soft_add_split, lo_in_t, lo_in_t)
    else:
        _pin_inferred_add(soft_add_split, lo_t, lo_t)
    _pin_inferred_add(soft_add_split, hi_in_t, hi_in_t)
    return soft_add_split


def make_soft_add_split(l_t, r_t):
    """Width-halving adder: the result as two built-in adds of about half its
    width, the high one taking the low one's carry. Unsigned operands only
    (callers fall back to make_soft_add_ripple for signed ones).

    This is AUTO_FSM's FORCED-descent flavor for an add too slow for one
    state: opening a 260-bit add gives two ~131-bit inferred carry chains --
    still FPGA carry-chain hardware, still shareable as word units -- where
    make_soft_add_ripple gives ~1300 one-bit gates. If a half is still too
    slow, descent splits it again, so the grain stays the coarsest that fits
    (docs/AUTO_FSM_DESIGN.md#descending-past-the-operator-level)."""
    return _make_split_add("PLUS", l_t, r_t)


def make_soft_sub_split(l_t, r_t):
    """Width-halving subtractor, a - b == a + ~b + 1 (mod 2**width) as two
    built-in adds of about half the result width; the +1 enters the low half
    as a carry-in. Unsigned operands only. See make_soft_add_split."""
    return _make_split_add("MINUS", l_t, r_t)
