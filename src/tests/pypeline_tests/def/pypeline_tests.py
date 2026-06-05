# pyright: reportInvalidTypeForm=none
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
    make_uint,
    make_int,
    make_float_t,
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
    sim_call,
)


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
      inv       -> make_double_inv_make_inv_t_<type>  (definition path in prefix)
      double_inv -> make_double_inv_T_<type>
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
    narrow_t = make_uint(narrow_bits)
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

    shifter_SL.amount_t = actual_amount_t
    return shifter_SL


def make_shifter_SR(value_t, amount_t=None):
    n_bits = len(value_t)
    narrow_bits = n_bits.bit_length()
    narrow_t = make_uint(narrow_bits)
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

    shifter_SR.amount_t = actual_amount_t
    return shifter_SR


shl_uint32 = make_shifter_SL(uint32_t)
register_left_operator("SL", uint32_t, shl_uint32)

shr_uint32 = make_shifter_SR(uint32_t)
register_left_operator("SR", uint32_t, shr_uint32)


def make_clz(value_t):
    n_bits = len(value_t)
    out_t = make_uint(n_bits.bit_length())

    @hw_func
    def clz(v: value_t) -> out_t:
        result: out_t = n_bits
        for i in range(n_bits):
            if v[i]:
                result = n_bits - 1 - i
        return result

    clz.out_t = out_t
    return clz


clz_uint32 = make_clz(uint32_t)


float32_t = make_float_t(8, 23)


def make_float_adder(float_t):
    exp_t = float_t.typeof("exp")
    man_t = float_t.typeof("man")
    M_LEN = len(man_t)
    man_hidden_t = make_uint(M_LEN + 1)
    signed_man_t = make_int(M_LEN + 2)
    sum_man_t = make_int(M_LEN + 3)
    abs_sum_t = make_uint(M_LEN + 2)
    narrow_t = make_uint(M_LEN + 1)
    clz_narrow = make_clz(narrow_t)
    clz_out_t = clz_narrow.out_t
    negate_man_h = make_negate(man_hidden_t, signed_man_t)
    negate_sum_man = make_negate(sum_man_t, abs_sum_t)
    sr_signed = make_shifter_SR(signed_man_t, exp_t)
    sl_narrow = make_shifter_SL(narrow_t, clz_out_t)
    abs_sum = make_abs(sum_man_t, abs_sum_t)

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

    # Operator registrations scoped to float_add's elaboration only.
    register_unary_operator("NEGATE", man_hidden_t, negate_man_h, scope=float_add)
    register_unary_operator("NEGATE", sum_man_t, negate_sum_man, scope=float_add)
    register_operator("SR", signed_man_t, exp_t, sr_signed, scope=float_add)
    register_operator("SL", narrow_t, clz_out_t, sl_narrow, scope=float_add)

    return float_add


float_add_32 = make_float_adder(float32_t)
register_operator("PLUS", float32_t, float32_t, float_add_32)
