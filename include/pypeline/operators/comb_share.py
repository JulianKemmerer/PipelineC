"""Exact integer implementation choices for the shared HLS area search."""
from pypeline import (
    INFERRED, any_integer_t, hw_func, make_uint_t,
    register_operator, register_left_operator,
)


def _primitive_math(func):
    # These helpers implement compiler primitives, not new user expressions.
    # Narrowing must not accidentally select a custom operator at the new width.
    for op in ("PLUS", "MINUS", "INFERRED_MULT", "AND", "OR", "XOR"):
        register_operator(op, any_integer_t, any_integer_t, INFERRED, scope=func)
    for op in ("SL", "SR"):
        register_left_operator(op, any_integer_t, INFERRED, scope=func)
    # Exact user registrations precede generic ones. Shadow those too, only
    # within this isolated helper (which never calls user functions).
    import pypeline

    for op, left, right in tuple(pypeline._operator_registry):
        if pypeline._ctype_is_int(left) and pypeline._ctype_is_int(right):
            register_operator(op, pypeline._reconstruct_int_ctype(left),
                              pypeline._reconstruct_int_ctype(right), INFERRED, scope=func)
    for op, left in tuple(pypeline._left_operator_registry):
        if pypeline._ctype_is_int(left):
            register_left_operator(op, pypeline._reconstruct_int_ctype(left), INFERRED, scope=func)
    return func


def signed_digits(value):
    """Non-adjacent signed binary representation (shift, sign)."""
    terms = []
    shift = 0
    while value:
        if value & 1:
            digit = 2 - (value & 3)
            terms.append((shift, digit))
            value -= digit
        value >>= 1
        shift += 1
    return tuple(terms)


def make_constant_mult(in_t, out_t, value):
    terms = signed_digits(value)

    @hw_func
    def constant_mult(x: in_t) -> out_t:
        v: out_t = x
        result: out_t = 0
        for shift, sign in terms:
            if sign > 0:
                result = result + (v << shift)
            else:
                result = result - (v << shift)
        return result

    return _primitive_math(constant_mult)


def make_power_of_two(in_t, out_t, shift, remainder):
    mask = (1 << shift) - 1

    @hw_func
    def power_of_two(x: in_t) -> out_t:
        result: out_t = 0
        if remainder:
            result = x & mask
        else:
            result = x >> shift
        return result

    return _primitive_math(power_of_two)


def make_narrow_binary(left_t, right_t, out_t, bits, op, left_bits=None, right_bits=None):
    narrow_t = make_uint_t(bits)
    narrow_left_t = make_uint_t(left_bits or bits)
    narrow_right_t = make_uint_t(right_bits or bits)

    @hw_func
    def narrow_binary(a: left_t, b: right_t) -> out_t:
        x: narrow_left_t = a
        y: narrow_right_t = b
        result: narrow_t = 0
        if op == 0:
            result = x + y
        elif op == 1:
            result = x - y
        elif op == 2:
            result = x * y
        elif op == 3:
            result = x & y
        elif op == 4:
            result = x | y
        else:
            result = x ^ y
        return result

    return _primitive_math(narrow_binary)


def make_distributed(common_t, left_t, right_t, out_t, bits):
    common_bits = min(bits, common_t.width)
    left_bits = min(bits, left_t.width)
    right_bits = min(bits, right_t.width)
    common_value_t = make_uint_t(common_bits)
    left_value_t = make_uint_t(left_bits)
    right_value_t = make_uint_t(right_bits)
    sum_t = make_uint_t(min(bits, max(left_bits, right_bits) + 1))
    result_t = make_uint_t(bits)

    @hw_func
    def distributed(x: common_t, a: left_t, b: right_t) -> out_t:
        common: common_value_t = x
        left: left_value_t = a
        right: right_value_t = b
        total: sum_t = left + right
        result: result_t = common * total
        return result

    return _primitive_math(distributed)
