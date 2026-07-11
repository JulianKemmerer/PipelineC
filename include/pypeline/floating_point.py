import struct as _struct

from pypeline import (
    struct,
    NamedTuple,
    uint1_t,
    int32_t,
    make_uint_t,
    make_int_t,
    concat,
    hw_func,
    hw_return_type,
    register_operator,
    register_left_operator,
    register_unary_operator,
)


def _float_to_fields(value, exponent_width, mantissa_width):
    """Convert a Python float to an IEEE 754-like sign/exp/man dict at elaboration time."""
    f = float(value)
    if exponent_width == 8 and mantissa_width == 23:
        bits = _struct.unpack(">I", _struct.pack(">f", f))[0]
    elif exponent_width == 11 and mantissa_width == 52:
        bits = _struct.unpack(">Q", _struct.pack(">d", f))[0]
    else:
        # General: rebase from FP64 representation
        bits64 = _struct.unpack(">Q", _struct.pack(">d", f))[0]
        sign = (bits64 >> 63) & 1
        exp64 = (bits64 >> 52) & 0x7FF
        man64 = bits64 & ((1 << 52) - 1)
        bias64 = 1023
        bias_t = (1 << (exponent_width - 1)) - 1
        exp_max = (1 << exponent_width) - 1
        if exp64 == 0x7FF:  # inf / nan
            biased_exp = exp_max
            man = man64 >> (52 - mantissa_width) if man64 else 0
        elif exp64 == 0 and man64 == 0:  # zero
            biased_exp = 0
            man = 0
        else:  # normal
            true_exp = exp64 - bias64
            biased_exp = true_exp + bias_t
            biased_exp = max(1, min(exp_max - 1, biased_exp))
            man = man64 >> (52 - mantissa_width)
        return {"sign": sign, "exp": biased_exp, "man": man}
    sign = (bits >> (exponent_width + mantissa_width)) & 1
    exp = (bits >> mantissa_width) & ((1 << exponent_width) - 1)
    man = bits & ((1 << mantissa_width) - 1)
    return {"sign": sign, "exp": exp, "man": man}


def _fields_to_float(sign, exp, man, exponent_width, mantissa_width):
    """Inverse of _float_to_fields: sign/exp/man bit fields -> Python float."""
    sign, exp, man = int(sign), int(exp), int(man)
    if exponent_width == 8 and mantissa_width == 23:
        bits = (sign << 31) | (exp << 23) | man
        return _struct.unpack(">f", _struct.pack(">I", bits))[0]
    if exponent_width == 11 and mantissa_width == 52:
        bits = (sign << 63) | (exp << 52) | man
        return _struct.unpack(">d", _struct.pack(">Q", bits))[0]
    # General: rebase up to FP64 and reuse its unpack
    bias_t = (1 << (exponent_width - 1)) - 1
    exp_max = (1 << exponent_width) - 1
    bias64 = 1023
    if exp == exp_max:  # inf / nan
        exp64 = 0x7FF
        man64 = man << (52 - mantissa_width) if man else 0
    elif exp == 0:  # zero
        exp64 = 0
        man64 = 0
    else:
        exp64 = (exp - bias_t) + bias64
        man64 = man << (52 - mantissa_width)
    bits64 = (sign << 63) | (exp64 << 52) | man64
    return _struct.unpack(">d", _struct.pack(">Q", bits64))[0]


def make_float_t(exponent_width, mantissa_width):
    """Create an IEEE 754-like floating-point struct type with variable field widths.

    Fields: sign (uint1_t), exp (uintE_t), man (uintM_t).
    The returned type has an .as_const(value) staticmethod for elaboration-time
    conversion of a Python float into the dict initializer form, and a __float__
    method (the inverse) for reading a value back out during simulation/debugging.

    Usage:
        float32_t = make_float_t(8, 23)   # standard FP32
        x: float32_t = float32_t.as_const(1.23)
    """
    exp_t = make_uint_t(exponent_width)
    man_t = make_uint_t(mantissa_width)

    @struct
    class float_t(NamedTuple):
        sign: uint1_t
        exp: exp_t
        man: man_t

    float_t.as_const = staticmethod(
        lambda value: float_t(**_float_to_fields(value, exponent_width, mantissa_width))
    )
    float_t.__float__ = lambda self: _fields_to_float(
        self.sign, self.exp, self.man, exponent_width, mantissa_width
    )
    return float_t


# ─────────────────────────────────────────────
# Private bit-manipulation helpers, used internally to build the arithmetic
# factories below. Not part of the public API.
# ─────────────────────────────────────────────


def _make_negate(value_t, out_t):
    # Negation via multiply-by-(-1), not `~a + 1`: a negative Python literal
    # (-1) is inferred as a signed ctype, correctly triggering sign/width
    # promotion to out_t regardless of simulation context. `~a_signed + 1`
    # (the two's-complement identity) looks equivalent but silently computes
    # the wrong value in pure simulation: the widening annotation on the
    # intermediate is a no-op there, and `+ 1` (a positive literal) infers
    # unsigned, so the result never actually promotes to a signed type.
    #
    # The literal is written inline (`* -1`), not hoisted into a named
    # closure constant: factory-produced hw_func names are mangled from
    # referenced closure variables' values, and a negative-valued one (e.g.
    # NEG_ONE = -1) bakes a bare '-' into the generated VHDL entity name,
    # which VHDL's identifier syntax rejects.

    @hw_func
    def negate(a: value_t) -> out_t:
        result: out_t = a * -1
        return result

    return negate


def _make_abs(in_t, out_t):
    n_bits = len(in_t)

    @hw_func
    def abs_val(a: in_t) -> out_t:
        sign: uint1_t = a[n_bits - 1]
        result: out_t
        if sign:
            result = -a
        else:
            result = a
        return result

    return abs_val


def _make_shifter_sl(value_t, amount_t=None):
    n_bits = len(value_t)
    narrow_bits = n_bits.bit_length()
    narrow_t = make_uint_t(narrow_bits)
    actual_amount_t = narrow_t if amount_t is None else amount_t
    # Bit positions at or beyond actual_amount_t's own width don't exist on
    # it (and can never be set), so the doubling loop below must not probe
    # them -- e.g. a caller-supplied amount_t narrower than value_t needs
    # (a CLZ result reused to align a wider register) would otherwise index
    # out of range on effective[i] for i >= len(actual_amount_t).
    loop_bits = min(narrow_bits, len(actual_amount_t))

    @hw_func
    def shifter_sl(v: value_t, amount: actual_amount_t) -> value_t:
        effective: actual_amount_t
        if amount_t is None or len(actual_amount_t) <= narrow_bits:
            effective = amount
        else:
            if amount > n_bits:
                effective = n_bits
            else:
                effective = amount
        result: value_t = v
        for i in range(loop_bits):
            shifted: value_t = result << (1 << i)
            if effective[i]:
                result = shifted
        return result

    return shifter_sl


def _make_shifter_sr(value_t, amount_t=None):
    n_bits = len(value_t)
    narrow_bits = n_bits.bit_length()
    narrow_t = make_uint_t(narrow_bits)
    actual_amount_t = narrow_t if amount_t is None else amount_t
    loop_bits = min(narrow_bits, len(actual_amount_t))

    @hw_func
    def shifter_sr(v: value_t, amount: actual_amount_t) -> value_t:
        effective: actual_amount_t
        if amount_t is None or len(actual_amount_t) <= narrow_bits:
            effective = amount
        else:
            if amount > n_bits:
                effective = n_bits
            else:
                effective = amount
        result: value_t = v
        for i in range(loop_bits):
            shifted: value_t = result >> (1 << i)
            if effective[i]:
                result = shifted
        return result

    return shifter_sr


def _make_clz(value_t):
    n_bits = len(value_t)
    out_t = make_uint_t(n_bits.bit_length())

    @hw_func
    def clz(v: value_t) -> out_t:
        result: out_t = n_bits
        for i in range(n_bits):
            if v[i]:
                result = n_bits - 1 - i
        return result

    return clz


# ─────────────────────────────────────────────
# Public factories
#
# None of these handle subnormals, inf/nan, or rounding specially -- they
# match the level of rigor already established by the original float adder:
# common-case IEEE-754-shaped arithmetic, with edge cases (exp==0 operands,
# overflow/underflow) flushed to zero rather than fully modeled.
# ─────────────────────────────────────────────


def make_float_adder(float_t):
    """Float addition: hidden-bit extract, align via variable shift, sum,
    renormalize via count-leading-zeros + shift."""
    exp_t = float_t.typeof("exp")
    man_t = float_t.typeof("man")
    M_LEN = len(man_t)
    man_hidden_t = make_uint_t(M_LEN + 1)
    signed_man_t = make_int_t(M_LEN + 2)
    sum_man_t = make_int_t(M_LEN + 3)
    abs_sum_t = make_uint_t(M_LEN + 2)
    narrow_t = make_uint_t(M_LEN + 1)
    clz_narrow = _make_clz(narrow_t)
    clz_out_t = hw_return_type(clz_narrow)
    negate_man_h = _make_negate(man_hidden_t, signed_man_t)
    negate_sum_man = _make_negate(sum_man_t, abs_sum_t)
    sr_signed = _make_shifter_sr(signed_man_t, exp_t)
    sl_narrow = _make_shifter_sl(narrow_t, clz_out_t)
    abs_sum = _make_abs(sum_man_t, abs_sum_t)

    @hw_func
    def float_add(left: float_t, right: float_t) -> float_t:
        # Step 1: x gets the larger exponent
        x: float_t
        y: float_t
        if right.exp > left.exp:
            x = right
            y = left
        else:
            x = left
            y = right

        # Step 2: hidden bit via concat uint(M_LEN+1)
        x_hidden: uint1_t
        if x.exp == 0:
            x_hidden = 0
        else:
            x_hidden = 1
        x_man_h: man_hidden_t = concat(x_hidden, x.man)

        y_hidden: uint1_t
        if y.exp == 0:
            y_hidden = 0
        else:
            y_hidden = 1
        y_man_h: man_hidden_t = concat(y_hidden, y.man)

        # Step 3: sign-adjust int(M_LEN+2) via NEGATE
        x_signed: signed_man_t
        if x.sign:
            x_signed = -x_man_h
        else:
            x_signed = x_man_h

        y_signed: signed_man_t
        if y.sign:
            y_signed = -y_man_h
        else:
            y_signed = y_man_h

        # Step 4: align y via SR (diff may exceed narrow range; shifter clamps)
        diff: exp_t = x.exp - y.exp
        y_aligned: signed_man_t = y_signed >> diff

        # Step 5: sum int(M_LEN+3)
        sum_man: sum_man_t = x_signed + y_aligned

        # Step 6: sign and absolute value
        sum_sign: uint1_t = sum_man[M_LEN + 2]
        sum_abs: abs_sum_t = abs_sum(sum_man)

        # Step 7: normalize (nested if-else, three cases)
        sum_overflow: uint1_t = sum_abs[M_LEN + 1]
        result_exp: exp_t
        result_man: man_t
        if sum_overflow:
            # Case 1: carry out right shift, bump exponent
            result_exp = x.exp + 1
            result_man = sum_abs[M_LEN:1]
        else:
            if sum_abs == 0:
                # Case 3: zero
                result_exp = 0
                result_man = 0
            else:
                # Case 2: normal remove leading zeros
                sum_narrow: narrow_t = sum_abs[M_LEN:0]
                lz: clz_out_t = clz_narrow(sum_narrow)
                lz_wide: exp_t = lz
                result_exp = x.exp - lz_wide
                shifted: narrow_t = sum_narrow << lz
                result_man = shifted[M_LEN - 1 : 0]

        result: float_t = float_t(sign=sum_sign, exp=result_exp, man=result_man)
        return result

    # Operator registrations scoped to float_add's elaboration/simulation only.
    register_unary_operator("NEGATE", man_hidden_t, negate_man_h, scope=float_add)
    register_unary_operator("NEGATE", sum_man_t, negate_sum_man, scope=float_add)
    register_operator("SR", signed_man_t, exp_t, sr_signed, scope=float_add)
    register_operator("SL", narrow_t, clz_out_t, sl_narrow, scope=float_add)

    return float_add


def make_float_subtractor(float_t, adder=None):
    """Float subtraction via sign-flip + add: a - b == a + (-b)."""
    add = adder if adder is not None else make_float_adder(float_t)

    @hw_func
    def float_sub(left: float_t, right: float_t) -> float_t:
        neg_right: float_t = float_t(sign=~right.sign, exp=right.exp, man=right.man)
        result: float_t = add(left, neg_right)
        return result

    return float_sub


def make_float_multiplier(float_t):
    """Float multiplication: hidden-bit mantissas multiplied directly (plain
    unsigned multiply is a built-in elaborator op, no registration needed),
    exponents added, single-bit renormalize (product of two [1,2) mantissas
    is always in [1,4))."""
    exp_t = float_t.typeof("exp")
    man_t = float_t.typeof("man")
    E_LEN = len(exp_t)
    M_LEN = len(man_t)
    man_hidden_t = make_uint_t(M_LEN + 1)
    prod_t = make_uint_t(2 * (M_LEN + 1))
    wide_exp_t = make_int_t(E_LEN + 2)
    BIAS = (1 << (E_LEN - 1)) - 1

    @hw_func
    def float_mul(left: float_t, right: float_t) -> float_t:
        sign: uint1_t = left.sign ^ right.sign

        result_exp: exp_t
        result_man: man_t
        if left.exp == 0 or right.exp == 0:
            # Flush subnormal/zero operands to zero (simplification).
            result_exp = 0
            result_man = 0
        else:
            l_hidden: uint1_t = 1
            r_hidden: uint1_t = 1
            l_man_h: man_hidden_t = concat(l_hidden, left.man)
            r_man_h: man_hidden_t = concat(r_hidden, right.man)
            product: prod_t = l_man_h * r_man_h

            # Written as "+ (-BIAS)", not "- BIAS": a positive literal
            # operand infers as an unsigned ctype (see module docstring),
            # which would silently keep this whole expression unsigned and
            # corrupt negative results. BIAS itself stays a positive named
            # closure constant (safe to mangle into a VHDL entity name);
            # only its literal negation is inline.
            combined_exp: wide_exp_t = left.exp + right.exp + (-BIAS)

            top_bit: uint1_t = product[2 * (M_LEN + 1) - 1]
            if top_bit:
                result_exp = combined_exp + 1
                result_man = product[2 * M_LEN : M_LEN + 1]
            else:
                result_exp = combined_exp
                result_man = product[2 * M_LEN - 1 : M_LEN]

        result: float_t = float_t(sign=sign, exp=result_exp, man=result_man)
        return result

    return float_mul


def make_float_divider(float_t):
    """Float division: exponents subtracted (via a comparison-guarded,
    always-non-negative unsigned subtraction), mantissa division via a
    restoring-division bit loop (subtract-and-shift only -- deliberately not
    using native '/', to avoid also needing SimVal truediv/hardware-DIV
    truncation-semantics work this library doesn't otherwise need)."""
    exp_t = float_t.typeof("exp")
    man_t = float_t.typeof("man")
    E_LEN = len(exp_t)
    M_LEN = len(man_t)
    man_hidden_t = make_uint_t(M_LEN + 1)
    rem_t = make_uint_t(M_LEN + 2)
    quot_t = make_uint_t(M_LEN + 2)
    exp_wide_t = make_uint_t(E_LEN + 2)
    BIAS = (1 << (E_LEN - 1)) - 1

    @hw_func
    def float_div(left: float_t, right: float_t) -> float_t:
        sign: uint1_t = left.sign ^ right.sign

        result_exp: exp_t
        result_man: man_t
        if left.exp == 0 or right.exp == 0:
            result_exp = 0
            result_man = 0
        else:
            l_hidden: uint1_t = 1
            r_hidden: uint1_t = 1
            l_man_h: man_hidden_t = concat(l_hidden, left.man)
            r_man_h: man_hidden_t = concat(r_hidden, right.man)
            r_man_wide: rem_t = r_man_h

            # Restoring division: quotient = floor(l_man_h * 2^(M_LEN+1) / r_man_h),
            # an (M_LEN+2)-bit result with the hidden bit either already at
            # position M_LEN+1 (no renormalize) or M_LEN (needs one
            # renormalizing left-shift + exponent decrement). Feeding
            # M_LEN+1 real numerator bits followed by M_LEN+1 zero-padding
            # bits (2*(M_LEN+1) total iterations) achieves that scale.
            remainder: rem_t = 0
            quotient: quot_t = 0
            for i in range(2 * (M_LEN + 1)):
                bit_idx = M_LEN - i
                if bit_idx >= 0:
                    next_bit: uint1_t = l_man_h[bit_idx]
                else:
                    next_bit: uint1_t = 0
                shifted_rem: rem_t = (remainder << 1) | next_bit
                q_bit: uint1_t
                if shifted_rem >= r_man_wide:
                    remainder = shifted_rem - r_man_wide
                    q_bit = 1
                else:
                    remainder = shifted_rem
                    q_bit = 0
                quotient = (quotient << 1) | q_bit

            lhs_plus_bias: exp_wide_t = left.exp + BIAS
            biased_exp: exp_wide_t
            if lhs_plus_bias < right.exp:
                # Underflow -- flush toward zero (simplification).
                biased_exp = 0
            else:
                biased_exp = lhs_plus_bias - right.exp

            top_bit: uint1_t = quotient[M_LEN + 1]
            hidden_man: man_hidden_t
            final_exp: exp_wide_t
            if top_bit:
                hidden_man = quotient[M_LEN + 1 : 1]
                final_exp = biased_exp
            else:
                hidden_man = quotient[M_LEN:0]
                final_exp = biased_exp + (-1)

            result_exp = final_exp
            result_man = hidden_man[M_LEN - 1 : 0]

        result: float_t = float_t(sign=sign, exp=result_exp, man=result_man)
        return result

    return float_div


def make_float_converter(src_t, dst_t):
    """General float-precision conversion (widen or narrow). Replaces the
    hand-written per-pair promotion/demotion helpers this pattern used to
    need (e.g. a project's own f32_to_f64): debias by src_t's bias, rebias
    by dst_t's bias (as a single compile-time-constant offset), then slice
    the top DST_M mantissa bits when narrowing or zero-pad when widening --
    the branch is chosen once in Python at factory-call time (compile-time
    constant widths), not as a runtime hardware mux."""
    src_e_t = src_t.typeof("exp")
    src_m_t = src_t.typeof("man")
    dst_e_t = dst_t.typeof("exp")
    dst_m_t = dst_t.typeof("man")
    SRC_E = len(src_e_t)
    SRC_M = len(src_m_t)
    DST_E = len(dst_e_t)
    DST_M = len(dst_m_t)
    src_bias = (1 << (SRC_E - 1)) - 1
    dst_bias = (1 << (DST_E - 1)) - 1
    # Kept as a positive magnitude + a widening flag rather than a single
    # signed EXP_OFFSET: a negative-valued named closure constant bakes a
    # bare '-' into the auto-generated VHDL entity name (invalid syntax),
    # and (separately, for simulation) a positive literal operand infers as
    # unsigned, silently breaking the exponent arithmetic when narrowing.
    # Only ONE of the two branches below is ever elaborated for a given
    # (src_t, dst_t) pair -- WIDENING is a plain Python bool, fixed at
    # factory-call time, not a runtime hardware condition.
    WIDENING = dst_bias >= src_bias
    EXP_OFFSET_MAG = dst_bias - src_bias if WIDENING else src_bias - dst_bias
    pad_t = make_uint_t(DST_M - SRC_M) if DST_M > SRC_M else None

    @hw_func
    def convert(x: src_t) -> dst_t:
        new_sign: uint1_t = x.sign
        out_exp: dst_e_t
        out_man: dst_m_t
        if x.exp == 0:
            out_exp = 0
            out_man = 0
        else:
            if WIDENING:
                out_exp = x.exp + EXP_OFFSET_MAG
            else:
                out_exp = x.exp + (-EXP_OFFSET_MAG)
            if DST_M <= SRC_M:
                out_man = x.man[SRC_M - 1 : SRC_M - DST_M]
            else:
                pad: pad_t = 0
                out_man = concat(x.man, pad)
        result: dst_t = dst_t(sign=new_sign, exp=out_exp, man=out_man)
        return result

    return convert


def make_float_to_int(float_t, int_t):
    """Truncating float -> int cast (toward zero, like C's (int)f). No
    overflow clamping (simplification)."""
    exp_t = float_t.typeof("exp")
    man_t = float_t.typeof("man")
    E_LEN = len(exp_t)
    M_LEN = len(man_t)
    man_hidden_t = make_uint_t(M_LEN + 1)
    N_BITS = len(int_t)
    wide_t = make_uint_t(max(M_LEN + 1, N_BITS) + 1)
    BIAS = (1 << (E_LEN - 1)) - 1
    # true_exp = x.exp - BIAS; shift_amt = true_exp - M_LEN, as a single
    # addition of a compile-time negative constant so the sign is inferred
    # correctly regardless of simulation context.
    NEG_BIAS_MINUS_M_LEN = -(BIAS + M_LEN)
    shift_amount_t = make_int_t(max(E_LEN, wide_t.width) + 2)
    sl_wide = _make_shifter_sl(wide_t, shift_amount_t)
    sr_wide = _make_shifter_sr(wide_t, shift_amount_t)
    negate_result = _make_negate(int_t, int_t)

    @hw_func
    def float_to_int(x: float_t) -> int_t:
        result: int_t
        if x.exp == 0:
            result = 0
        else:
            hidden: uint1_t = 1
            man_h: man_hidden_t = concat(hidden, x.man)
            man_h_wide: wide_t = man_h
            shift_amount: shift_amount_t = x.exp + NEG_BIAS_MINUS_M_LEN
            magnitude: wide_t
            if shift_amount >= 0:
                magnitude = sl_wide(man_h_wide, shift_amount)
            else:
                neg_shift_amount: shift_amount_t = shift_amount * -1
                magnitude = sr_wide(man_h_wide, neg_shift_amount)
            unsigned_result: int_t = magnitude
            if x.sign:
                result = negate_result(unsigned_result)
            else:
                result = unsigned_result

        return result

    register_operator("SL", wide_t, shift_amount_t, sl_wide, scope=float_to_int)
    register_operator("SR", wide_t, shift_amount_t, sr_wide, scope=float_to_int)
    register_unary_operator("NEGATE", int_t, negate_result, scope=float_to_int)

    return float_to_int


def make_int_to_float(int_t, float_t):
    """Value-preserving int -> float conversion: magnitude + sign, leading-1
    position via CLZ, shift to align the top bit into the hidden-bit slot."""
    exp_t = float_t.typeof("exp")
    man_t = float_t.typeof("man")
    E_LEN = len(exp_t)
    M_LEN = len(man_t)
    N_BITS = len(int_t)
    abs_t = make_uint_t(N_BITS)
    abs_val = _make_abs(int_t, abs_t)
    clz_abs = _make_clz(abs_t)
    clz_out_t = hw_return_type(clz_abs)
    align_wide_t = make_uint_t(N_BITS + M_LEN)
    sl_align = _make_shifter_sl(align_wide_t, clz_out_t)
    BIAS = (1 << (E_LEN - 1)) - 1
    pad_t = make_uint_t(M_LEN)

    @hw_func
    def int_to_float(n: int_t) -> float_t:
        sign: uint1_t = n[N_BITS - 1]
        magnitude: abs_t = abs_val(n)

        out_exp: exp_t
        out_man: man_t
        if magnitude == 0:
            out_exp = 0
            out_man = 0
        else:
            lz: clz_out_t = clz_abs(magnitude)
            true_exp: exp_t = (N_BITS - 1) - lz
            out_exp = true_exp + BIAS

            pad: pad_t = 0
            wide: align_wide_t = concat(magnitude, pad)
            shifted: align_wide_t = sl_align(wide, lz)
            # drop the implicit leading 1 (hidden bit) at the top bit, keep
            # the next M_LEN bits as the mantissa (truncating any bits below).
            out_man = shifted[N_BITS + M_LEN - 2 : N_BITS - 1]

        result: float_t = float_t(sign=sign, exp=out_exp, man=out_man)
        return result

    register_operator("SL", align_wide_t, clz_out_t, sl_align, scope=int_to_float)

    return int_to_float


def register_float_ops(float_t):
    """Build and globally register +, -, *, / for float_t x float_t.
    Returns (add, sub, mul, div)."""
    add = make_float_adder(float_t)
    sub = make_float_subtractor(float_t, adder=add)
    mul = make_float_multiplier(float_t)
    div = make_float_divider(float_t)
    register_operator("PLUS", float_t, float_t, add)
    register_operator("MINUS", float_t, float_t, sub)
    register_operator("INFERRED_MULT", float_t, float_t, mul)
    register_operator("DIV", float_t, float_t, div)
    return add, sub, mul, div


# ─────────────────────────────────────────────
# Predefined, ready-to-use types: one or two imports and +, -, *, / are
# already overloaded.
# ─────────────────────────────────────────────

float16_t = make_float_t(5, 10)
float32_t = make_float_t(8, 23)
float64_t = make_float_t(11, 52)

float16_add, float16_sub, float16_mul, float16_div = register_float_ops(float16_t)
float32_add, float32_sub, float32_mul, float32_div = register_float_ops(float32_t)
float64_add, float64_sub, float64_mul, float64_div = register_float_ops(float64_t)

float32_to_float64 = make_float_converter(float32_t, float64_t)
float64_to_float32 = make_float_converter(float64_t, float32_t)

float64_to_int32 = make_float_to_int(float64_t, int32_t)
int32_to_float64 = make_int_to_float(int32_t, float64_t)
