# pyright: reportInvalidTypeForm=none
import sys as _sys, os as _os

_sys.path.insert(
    0,
    _os.path.join(
        _os.path.dirname(_os.path.abspath(__file__)),
        "..",
        "..",
        "..",
        "..",
        "include",
        "pypeline",
    ),
)

from typing import NamedTuple
from pypeline import (
    Reg,
    Feedback,
    Wire,
    Input,
    Output,
    struct,
    uint1_t,
    uint4_t,
    uint6_t,
    uint8_t,
    uint16_t,
    uint32_t,
    uint34_t,
    uint64_t,
    int32_t,
    int33_t,
    make_uint_t,
    make_int_t,
    register_operator,
    register_left_operator,
    register_unary_operator,
    bit_dup,
    rotl,
    rotr,
    bswap,
    bit_assign,
    array_to_uint_be,
    array_to_uint_le,
    uint_to_array_be,
    uint_to_array_le,
    concat,
    hw_func,
    hw_return_type,
    sim_call,
)
from floating_point import float32_t, float32_add as float_add_32


@hw_func
def accumulator(data_in: uint32_t) -> uint32_t:
    acc: Reg[uint32_t]
    acc = acc + data_in
    return acc


@struct
class point_xy_t(NamedTuple):
    x: uint32_t
    y: uint32_t


def make_point_xy_const(x, y):
    return point_xy_t(x=x, y=y)


@struct
class point_xy_wrap_t(NamedTuple):
    p: point_xy_t
    tag: uint32_t


@struct
class point2d_t(NamedTuple):
    dim: uint32_t[2]


def make_point_t(dim_t, DIM_SIZE, style="array"):
    if style == "array":

        @struct
        class point(NamedTuple):
            dim: dim_t[DIM_SIZE]

        point.style = "array"
        return point
    elif style == "fields":
        pass  # TODO


point_u8_t = make_point_t(uint8_t, 2, style="array")


point_t = make_point_t(uint32_t, 2, style="array")


def types_test_foo(point: point_t) -> point_t:
    rv: point_t
    if point_t.style == "array":
        for i in range(len(point_t.typeof("dim"))):
            rv.dim[i] = point.dim[i]
    else:
        for f in point_t._fields:
            rv[f] = point[f]
    return rv


def sum_widths(n, m):
    return n + m


def make_adder(T):
    def add(a: T, b: T) -> T:
        return a + b

    return add


add_u32 = make_adder(uint32_t)
add_u32_dup = make_adder(uint32_t)
add_u8 = make_adder(uint8_t)


def make_sum3(T):
    local_add = make_adder(T)

    def sum3(a: T, b: T, c: T) -> T:
        return local_add(local_add(a, b), c)

    return sum3


sum3_u32 = make_sum3(uint32_t)
sum3_u32_dup = make_sum3(uint32_t)
sum3_u8 = make_sum3(uint8_t)


def make_pair_t(T):
    @struct
    class pair_t(NamedTuple):
        a: T
        b: T

    return pair_t


pair_u32_t = make_pair_t(uint32_t)
pair_u32_t_dup = make_pair_t(uint32_t)  # same params — should share canonical name


def make_swap(T):
    local_pair_t = make_pair_t(T)  # nested: local_pair_t not visible at module level

    def swap(p: local_pair_t) -> local_pair_t:
        rv: local_pair_t = local_pair_t(a=p.b, b=p.a)
        return rv

    return swap


swap_u32 = make_swap(uint32_t)


def make_double_inv(T):
    """Outer factory containing a locally-defined inner factory.
    double_inv(a) = ~~a = a (double bitwise NOT).

    Canonical names:
      inv        -> inv_t_<type>         (inner function name as prefix)
      double_inv -> double_inv_T_<type>
    """

    def make_inv(
        t,
    ):  # locally defined — qualname: make_double_inv.<locals>.make_inv.<locals>.inv
        def inv(a: t) -> t:
            return ~a

        return inv

    local_inv = make_inv(T)

    def double_inv(a: T) -> T:
        return local_inv(local_inv(a))

    return double_inv


double_inv_u32 = make_double_inv(uint32_t)
double_inv_u8 = make_double_inv(uint8_t)


# TODO
# @MAIN
# def shift_const_wire(v: uint32_t) -> uint32_t:
#    amount: uint32_t = 5
#    return v << amount

SHIFT_AMOUNT = 5


def foo(x: uint1_t) -> uint1_t:
    y = ~x
    return y


def make_negate(value_t, out_t):
    @hw_func
    def negate(a: value_t) -> out_t:
        a_signed: out_t = a
        return ~a_signed + 1

    return negate


negate_uint32 = make_negate(uint32_t, int33_t)


negate_int32 = make_negate(int32_t, int33_t)


def make_abs(in_t, out_t):
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


abs_int32 = make_abs(int32_t, uint32_t)


def make_shifter_SL(value_t, amount_t=None):
    n_bits = len(value_t)
    narrow_bits = n_bits.bit_length()
    narrow_t = make_uint_t(narrow_bits)
    actual_amount_t = narrow_t if amount_t is None else amount_t

    @hw_func
    def shifter_SL(v: value_t, amount: actual_amount_t) -> value_t:
        effective: actual_amount_t
        if amount_t is None or len(actual_amount_t) <= narrow_bits:
            effective = amount
        else:
            if amount > n_bits:
                effective = n_bits
            else:
                effective = amount
        result: value_t = v
        for i in range(narrow_bits):
            shifted: value_t = result << (1 << i)
            if effective[i]:
                result = shifted
        return result

    return shifter_SL


def make_shifter_SR(value_t, amount_t=None):
    n_bits = len(value_t)
    narrow_bits = n_bits.bit_length()
    narrow_t = make_uint_t(narrow_bits)
    actual_amount_t = narrow_t if amount_t is None else amount_t

    @hw_func
    def shifter_SR(v: value_t, amount: actual_amount_t) -> value_t:
        effective: actual_amount_t
        if amount_t is None or len(actual_amount_t) <= narrow_bits:
            effective = amount
        else:
            if amount > n_bits:
                effective = n_bits
            else:
                effective = amount
        result: value_t = v
        for i in range(narrow_bits):
            shifted: value_t = result >> (1 << i)
            if effective[i]:
                result = shifted
        return result

    return shifter_SR


shl_uint32 = make_shifter_SL(uint32_t)
register_left_operator("SL", uint32_t, shl_uint32)

shr_uint32 = make_shifter_SR(uint32_t)
register_left_operator("SR", uint32_t, shr_uint32)


def make_clz(value_t):
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


clz_uint32 = make_clz(uint32_t)
