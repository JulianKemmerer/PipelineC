"""Bit-level primitives: count-leading-zeros and variable (barrel) shifters.

These three factories were originally private helpers inside
`floating_point.py`, where they implement the float adder's renormalize step
and the multiplier/divider's operand alignment. They are not float-specific --
a count-leading-zeros plus a left shift is the normalize step of *any*
fixed-point block that needs a base-2 exponent, which is exactly what a
log2/dB converter is (see `dsp/log2_db.py`).

They live here, rather than being re-derived at each call site, so there is
one definition of each. `floating_point.py` imports them and keeps its old
underscore-prefixed names as aliases, so nothing that used the private names
had to change.

Importing this module has no side effects -- unlike `floating_point.py`, whose
import registers casts and operators for float16/32/64.
"""

from pypeline import hw_func, make_uint_t


def make_clz(value_t):
    """Count leading zeros of `value_t`, which must be UNSIGNED.

    Returns `clz(v) -> uint_t(len(value_t).bit_length())`.
    An all-zero input returns `n_bits` -- one past the largest real bit index --
    so callers computing an exponent as `(n_bits - 1) - clz(v)` must special-case
    zero themselves, or the result underflows in an unsigned type.

    Structure: a binary search over the value, `ceil(log2(n_bits))` levels deep.
    Each level asks whether the top `step` bits are all zero and, if so, adds
    `step` to the count and shifts them away.

    The obvious alternative -- scan every bit and let later iterations override
    earlier ones -- is much shorter to write but elaborates to an `n_bits`-deep
    chain of dependent muxes. At 39 bits that measured as the critical path of
    an entire CORDIC (16.6 MHz under PyRTL timing), which is what prompted this
    version. Both forms produce identical results for every input at every
    width; this one is 6 levels instead of 39.

    Requires unsigned `value_t`: the `>>` used to test the high bits would
    sign-extend on a signed type and never compare equal to zero for a negative
    input.
    """
    n_bits = len(value_t)
    out_t = make_uint_t(n_bits.bit_length())

    # Descending powers of two: 32, 16, 8, 4, 2, 1 for a 33..64-bit input.
    step = 1
    while step < n_bits:
        step <<= 1
    step >>= 1
    steps = []
    while step >= 1:
        steps.append(step)
        step >>= 1

    @hw_func
    def clz(v: value_t) -> out_t:
        result: out_t = 0
        resid: value_t = v  # `rem` is a VHDL reserved word
        for s in steps:
            top: value_t = resid >> (n_bits - s)
            if top == 0:
                result = result + s
                resid = resid << s
        if v == 0:
            result = n_bits
        return result

    return clz


def make_shifter_sl(value_t, amount_t=None):
    """Variable left shift (barrel), log2(n) doubling stages.

    `amount_t=None` sizes the shift amount to `uint_t(len(value_t).bit_length())`.
    Pass an explicit `amount_t` to reuse an amount computed elsewhere (a CLZ
    result, typically); amounts wider than the value are clamped to `n_bits`.
    """
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


def make_shifter_sr(value_t, amount_t=None):
    """Variable right shift (barrel). See `make_shifter_sl` for `amount_t`."""
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
