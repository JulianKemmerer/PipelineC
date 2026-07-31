"""Soft variable-amount barrel shifter.

Variable-amount << / >> have no built-in inferred path at all -- PY_TO_LOGIC
raises NotImplementedError unless something is registered (register_left_
operator, since the shift amount type is derived from the value width, not
matched exactly). This is the same log2-stage barrel-shift structure as
floating_point.py's _make_shifter_sr, generalized to both directions and
registered as a left-operator so it applies to any width automatically.
"""
from pypeline import hw_func, make_uint_t


def _make_barrel(value_t, left):
    n_bits = len(value_t)
    amount_bits = max(1, n_bits.bit_length())
    amount_t = make_uint_t(amount_bits)

    @hw_func
    def barrel(v: value_t, amount: amount_t) -> value_t:
        result: value_t = v
        for i in range(amount_bits):
            shift_amt = 1 << i
            if left:
                shifted: value_t = result << shift_amt
            else:
                shifted: value_t = result >> shift_amt
            if amount[i]:
                result = shifted
        return result

    return barrel


def make_soft_barrel_sl(value_t):
    return _make_barrel(value_t, left=True)


def make_soft_barrel_sr(value_t):
    return _make_barrel(value_t, left=False)
