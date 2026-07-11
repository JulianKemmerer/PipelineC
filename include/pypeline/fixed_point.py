import math

from pypeline import (
    struct,
    NamedTuple,
    uint1_t,
    make_uint_t,
    make_int_t,
    hw_func,
    register_operator,
    register_unary_operator,
)


def _quantize(value, frac_bits, total_bits, signed, rounding="round_half_even"):
    """Elaboration-time float -> raw fixed-point integer quantizer, shared by
    as_const (always round_half_even, matching Python's own round()) and
    quantize_coeffs (rounding mode configurable). "truncate" uses math.floor
    (not int()/math.trunc()) so it matches make_fixed_resize's own
    arithmetic-shift-is-floor truncation semantics for negative values.
    """
    scaled = float(value) * (1 << frac_bits)
    if rounding == "truncate":
        raw = math.floor(scaled)
    elif rounding == "round_half_up":
        raw = math.floor(scaled + 0.5)
    elif rounding == "round_half_even":
        raw = round(scaled)
    elif rounding == "round_half_away":
        raw = math.floor(abs(scaled) + 0.5)
        if scaled < 0:
            raw = -raw
    else:
        raise ValueError(
            f"_quantize: unsupported rounding mode {rounding!r}, expected one of "
            "('truncate', 'round_half_up', 'round_half_even', 'round_half_away')"
        )
    mask = (1 << total_bits) - 1
    raw &= mask
    if signed and raw >= (1 << (total_bits - 1)):
        raw -= mask + 1
    return raw


def make_fixed_t(int_bits: int, frac_bits: int, signed: bool = True):
    """Create a fixed-point struct type wrapping a single raw integer field.

    Fields: val (make_int_t(int_bits+frac_bits) if signed, else make_uint_t(...)).
    The returned type has .int_bits/.frac_bits/.signed plain attributes, an
    .as_const(value) staticmethod for elaboration-time conversion of a Python
    float into the raw fixed-point representation, and a __float__ method (the
    inverse) for reading a value back out during simulation/debugging.

    Usage:
        q4_12_t = make_fixed_t(4, 12)   # signed Q4.12
        x: q4_12_t = q4_12_t.as_const(1.5)
    """
    total_bits = int_bits + frac_bits
    val_t = make_int_t(total_bits) if signed else make_uint_t(total_bits)

    @struct
    class fixed_t(NamedTuple):
        val: val_t

    fixed_t.int_bits = int_bits
    fixed_t.frac_bits = frac_bits
    fixed_t.signed = signed
    fixed_t.as_const = staticmethod(
        lambda value: fixed_t(
            val=_quantize(value, frac_bits, total_bits, signed, "round_half_even")
        )
    )
    fixed_t.__float__ = lambda self: int(self.val) / (1 << frac_bits)
    return fixed_t


def _promote_int_bits(a_t, b_t):
    """Mirror pypeline.py's native _arith_promote sign-promotion rule, expressed
    in int_bits terms for two fixed_t types with equal frac_bits: whichever
    operand is unsigned effectively gains +1 bit before the add/sub/mul width
    rule applies, when signedness differs. This is the same shared rule real
    hardware elaboration (PY_TO_LOGIC.py) and native simulation (SimVal
    arithmetic) both use for plain scalar ints -- so applying it here keeps
    the fixed-point output type wide enough to hold the exact result with no
    truncation, identically in both simulation and real hardware.
    """
    if a_t.signed == b_t.signed:
        return a_t.int_bits, b_t.int_bits
    if a_t.signed:
        return a_t.int_bits, b_t.int_bits + 1
    return a_t.int_bits + 1, b_t.int_bits


def make_fixed_adder(a_t, b_t):
    """a + b for two fixed_t types with identical frac_bits. Output int_bits
    always grows enough to hold the exact result with no truncation -- never
    a side effect of arithmetic; a caller wanting a narrower result must
    explicitly resize afterward via make_fixed_resize."""
    if a_t.frac_bits != b_t.frac_bits:
        raise TypeError(
            f"make_fixed_adder: mismatched frac_bits ({a_t.frac_bits} vs "
            f"{b_t.frac_bits}) -- PLUS requires identical frac_bits; resize "
            "one operand first via make_fixed_resize()"
        )
    eff_a, eff_b = _promote_int_bits(a_t, b_t)
    out_t = make_fixed_t(
        max(eff_a, eff_b) + 1, a_t.frac_bits, signed=a_t.signed or b_t.signed
    )
    out_val_t = out_t.typeof("val")

    @hw_func
    def fixed_add(a: a_t, b: b_t) -> out_t:
        result_val: out_val_t = a.val + b.val
        result: out_t = out_t(val=result_val)
        return result

    return fixed_add


def make_fixed_subtractor(a_t, b_t):
    """a - b for two fixed_t types with identical frac_bits. Same
    guaranteed-no-truncation width-growth rule as make_fixed_adder."""
    if a_t.frac_bits != b_t.frac_bits:
        raise TypeError(
            f"make_fixed_subtractor: mismatched frac_bits ({a_t.frac_bits} vs "
            f"{b_t.frac_bits}) -- MINUS requires identical frac_bits; resize "
            "one operand first via make_fixed_resize()"
        )
    eff_a, eff_b = _promote_int_bits(a_t, b_t)
    out_t = make_fixed_t(
        max(eff_a, eff_b) + 1, a_t.frac_bits, signed=a_t.signed or b_t.signed
    )
    out_val_t = out_t.typeof("val")

    @hw_func
    def fixed_sub(a: a_t, b: b_t) -> out_t:
        result_val: out_val_t = a.val - b.val
        result: out_t = out_t(val=result_val)
        return result

    return fixed_sub


def make_fixed_multiplier(a_t, b_t):
    """a * b, full precision, exact -- no rounding, no frac_bits constraint.
    Native multiply of an N-bit and M-bit operand is exactly N+M bits, so the
    output type is sized to hold the product exactly."""
    eff_a, eff_b = _promote_int_bits(a_t, b_t)
    out_t = make_fixed_t(
        eff_a + eff_b, a_t.frac_bits + b_t.frac_bits, signed=a_t.signed or b_t.signed
    )
    out_val_t = out_t.typeof("val")

    @hw_func
    def fixed_mul(a: a_t, b: b_t) -> out_t:
        result_val: out_val_t = a.val * b.val
        result: out_t = out_t(val=result_val)
        return result

    return fixed_mul


def make_fixed_negate(a_t):
    """-a, same width in and out. Requires a_t.signed. Negating the
    most-negative representable value wraps back to itself (accepted two's
    complement limitation, same as everywhere else in this codebase)."""
    if not a_t.signed:
        raise TypeError("make_fixed_negate: NEGATE requires a signed fixed_t")
    val_t = a_t.typeof("val")

    @hw_func
    def fixed_negate(a: a_t) -> a_t:
        result_val: val_t = a.val * -1
        result: a_t = a_t(val=result_val)
        return result

    return fixed_negate


def register_fixed_ops(fixed_t):
    """Build and globally register +, -, * (and unary - iff fixed_t.signed)
    for fixed_t x fixed_t. Returns (add, sub, mul, negate_or_None)."""
    add = make_fixed_adder(fixed_t, fixed_t)
    sub = make_fixed_subtractor(fixed_t, fixed_t)
    mul = make_fixed_multiplier(fixed_t, fixed_t)
    register_operator("PLUS", fixed_t, fixed_t, add)
    register_operator("MINUS", fixed_t, fixed_t, sub)
    register_operator("INFERRED_MULT", fixed_t, fixed_t, mul)
    negate = None
    if fixed_t.signed:
        negate = make_fixed_negate(fixed_t)
        register_unary_operator("NEGATE", fixed_t, negate)
    return add, sub, mul, negate


def make_fixed_resize(src_t, dst_t, rounding="truncate", overflow="wrap"):
    """Change (int_bits, frac_bits) and/or signedness between two fixed_t
    types -- e.g. rounding a wide accumulator down to a narrower output type,
    vendor-FIR-IP "output precision control" style.

    rounding: "truncate" | "round_half_up" | "round_half_even" | "round_half_away"
              Only meaningful when narrowing the fraction (src_t.frac_bits >
              dst_t.frac_bits); ignored (no-op) when widening or unchanged.
    overflow: "wrap" | "saturate"
    """
    ROUNDINGS = ("truncate", "round_half_up", "round_half_even", "round_half_away")
    OVERFLOWS = ("wrap", "saturate")
    if rounding not in ROUNDINGS:
        raise ValueError(
            f"make_fixed_resize: unsupported rounding mode {rounding!r}, "
            f"expected one of {ROUNDINGS}"
        )
    if overflow not in OVERFLOWS:
        raise ValueError(
            f"make_fixed_resize: unsupported overflow mode {overflow!r}, "
            f"expected one of {OVERFLOWS}"
        )

    S = src_t.int_bits + src_t.frac_bits
    D = dst_t.int_bits + dst_t.frac_bits
    SHIFT = src_t.frac_bits - dst_t.frac_bits

    S_prime = S + (0 if src_t.signed else 1)
    D_prime = D + (0 if dst_t.signed else 1)
    shifted_bits = S_prime + max(0, -SHIFT)
    rounding_headroom = 1 if SHIFT > 0 else 0
    WIDE_BITS = max(shifted_bits + rounding_headroom, D_prime) + 1
    wide_t = make_int_t(WIDE_BITS)

    DST_MAX = (1 << (D - 1)) - 1 if dst_t.signed else (1 << D) - 1
    DST_MIN = -(1 << (D - 1)) if dst_t.signed else 0

    dst_val_t = dst_t.typeof("val")

    # Resolved to plain bools before the hw_func body references them: a raw
    # string closure variable (the "rounding"/"overflow" parameters
    # themselves) can't be embedded in a factory-produced hw_func's canonical
    # VHDL entity name (only C types/ints/bools/None/callables can), so the
    # mode selection must happen once here in Python, leaving only bools in
    # the body -- this also means each concrete (rounding, overflow) pairing
    # elaborates as a single straight-line combinational path, not a runtime
    # mux over the mode strings.
    SATURATE = overflow == "saturate"
    IS_TRUNCATE = rounding == "truncate"
    IS_ROUND_HALF_UP = rounding == "round_half_up"
    IS_ROUND_HALF_EVEN = rounding == "round_half_even"

    if SHIFT > 0:
        remainder_t = make_uint_t(SHIFT)
        HALF = 1 << (SHIFT - 1)

        @hw_func
        def fixed_resize(x: src_t) -> dst_t:
            x_wide: wide_t = x.val
            truncated: wide_t = x_wide >> SHIFT
            rounded: wide_t
            if IS_TRUNCATE:
                rounded = truncated
            else:
                remainder: remainder_t = x_wide[SHIFT - 1 : 0]
                if IS_ROUND_HALF_UP:
                    if remainder >= HALF:
                        rounded = truncated + 1
                    else:
                        rounded = truncated
                elif IS_ROUND_HALF_EVEN:
                    if remainder > HALF:
                        rounded = truncated + 1
                    elif remainder < HALF:
                        rounded = truncated
                    else:
                        lsb: uint1_t = truncated[0]
                        if lsb:
                            rounded = truncated + 1
                        else:
                            rounded = truncated
                else:  # round_half_away
                    if remainder > HALF:
                        rounded = truncated + 1
                    elif remainder < HALF:
                        rounded = truncated
                    else:
                        sign_bit: uint1_t = truncated[WIDE_BITS - 1]
                        if sign_bit:
                            rounded = truncated
                        else:
                            rounded = truncated + 1

            clamped: wide_t
            if SATURATE:
                if rounded > DST_MAX:
                    clamped = DST_MAX
                elif rounded < DST_MIN:
                    clamped = DST_MIN
                else:
                    clamped = rounded
            else:
                clamped = rounded

            result_val: dst_val_t = clamped
            result: dst_t = dst_t(val=result_val)
            return result

    else:
        SHIFT_LEFT = -SHIFT

        @hw_func
        def fixed_resize(x: src_t) -> dst_t:
            x_wide: wide_t = x.val
            rounded: wide_t = x_wide << SHIFT_LEFT

            clamped: wide_t
            if SATURATE:
                if rounded > DST_MAX:
                    clamped = DST_MAX
                elif rounded < DST_MIN:
                    clamped = DST_MIN
                else:
                    clamped = rounded
            else:
                clamped = rounded

            result_val: dst_val_t = clamped
            result: dst_t = dst_t(val=result_val)
            return result

    return fixed_resize


def quantize_coeffs(taps, coeff_t, rounding="round_half_even"):
    """Plain-Python (no hardware) quantization of a list of floats into
    coeff_t's raw integer representation. No symmetry-preservation -- each
    tap is quantized independently. Out-of-range taps silently wrap, matching
    make_fixed_t.as_const's precedent of not handling overflow specially."""
    total_bits = coeff_t.int_bits + coeff_t.frac_bits
    return [
        _quantize(t, coeff_t.frac_bits, total_bits, coeff_t.signed, rounding)
        for t in taps
    ]
