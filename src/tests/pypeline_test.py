# pyright: reportInvalidTypeForm=none
from typing import NamedTuple
from pypeline import (
    MAIN,
    Reg,
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
    _RegType,
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
)


#       EXTRA struct init overload for float emt with float const
# TODO float e m t is struct
# TODO aim for float e m t adder
# LONGER TERM?
# TODO all of old SW_LIB includes fabric multiply, div, etc
# TODO Submodule instances with registers inside need CLOCK_ENABLE + if() clock enable muxing
# TODO printf for sim? is special func?
# TODO constant wires based reduction that interacts with graph submodule instances:
#       ex. var ref assign/read into constant
#       ex. shift by a uint6_t type wire driven by constant
#       ... some day might be helpful for making simulator?
# TODO global variable wires/fifos w/ #include style imports, start simple comb loop example


@struct
class point2d_t(NamedTuple):
    dim: uint32_t[2]


@MAIN
def struct_init_list_consts() -> point2d_t:
    my_point: point2d_t = {"dim": [0, 1]}
    return my_point


@MAIN
def struct_init_list_wires(v0: uint32_t, v1: uint32_t) -> point2d_t:
    my_point: point2d_t = {"dim": [v0, v1]}
    return my_point


@MAIN
def struct_init_dict_int_keys(v0: uint32_t, v1: uint32_t) -> point2d_t:
    my_point: point2d_t = {"dim": {1: v1, 0: v0}}
    return my_point


@MAIN
def array_init_list_consts() -> uint32_t[2]:
    my_arr: uint32_t[2] = [42, 99]
    return my_arr


@MAIN
def array_init_list_wires(v0: uint32_t, v1: uint32_t) -> uint32_t[2]:
    my_arr: uint32_t[2] = [v0, v1]
    return my_arr


def make_clz(VALUE_TYPE):
    n_bits = len(VALUE_TYPE)
    OUT_TYPE = make_uint(n_bits.bit_length())

    def clz(v: VALUE_TYPE) -> OUT_TYPE:
        result: OUT_TYPE = n_bits
        for i in range(n_bits):
            if v[i]:
                result = n_bits - 1 - i
        return result

    clz.out_type = OUT_TYPE
    return clz


clz_uint32 = make_clz(uint32_t)


@MAIN
def clz_uint32_test(a: uint32_t) -> uint6_t:
    return clz_uint32(a)


def make_abs(SIGNED_TYPE, OUT_TYPE):
    n_bits = len(SIGNED_TYPE)

    def abs_val(a: SIGNED_TYPE) -> OUT_TYPE:
        sign: uint1_t = a[n_bits - 1]
        result: OUT_TYPE
        if sign:
            result = -a
        else:
            result = a
        return result

    return abs_val


abs_int32 = make_abs(int32_t, uint32_t)


@MAIN
def abs_int32_test(a: int32_t) -> uint32_t:
    return abs_int32(a)


def make_shifter_SL(VALUE_TYPE):
    amount_bits = len(VALUE_TYPE).bit_length()
    AMOUNT_TYPE = make_uint(amount_bits)

    def shifter_SL(v: VALUE_TYPE, amount: AMOUNT_TYPE) -> VALUE_TYPE:
        result: VALUE_TYPE = v
        for i in range(amount_bits):
            shifted: VALUE_TYPE = result << (1 << i)
            if amount[i]:
                result = shifted
        return result

    shifter_SL.amount_type = AMOUNT_TYPE
    return shifter_SL


def make_shifter_SR(VALUE_TYPE):
    amount_bits = len(VALUE_TYPE).bit_length()
    AMOUNT_TYPE = make_uint(amount_bits)

    def shifter_SR(v: VALUE_TYPE, amount: AMOUNT_TYPE) -> VALUE_TYPE:
        result: VALUE_TYPE = v
        for i in range(amount_bits):
            shifted: VALUE_TYPE = result >> (1 << i)
            if amount[i]:
                result = shifted
        return result

    shifter_SR.amount_type = AMOUNT_TYPE
    return shifter_SR


shl_uint32 = make_shifter_SL(uint32_t)
register_left_operator("SL", uint32_t, "shl_uint32")

shr_uint32 = make_shifter_SR(uint32_t)
register_left_operator("SR", uint32_t, "shr_uint32")


@MAIN
def shift_var(v: uint32_t, amount: uint6_t) -> uint32_t:
    return v << amount


@MAIN
def shift_var_right(v: uint32_t, amount: uint6_t) -> uint32_t:
    return v >> amount


def make_negate(VALUE_TYPE, OUT_TYPE):
    def negate(a: VALUE_TYPE) -> OUT_TYPE:
        a_signed: OUT_TYPE = a
        return ~a_signed + 1

    return negate


negate_uint32 = make_negate(uint32_t, int33_t)
register_unary_operator("NEGATE", uint32_t, "negate_uint32")

negate_int32 = make_negate(int32_t, int33_t)
register_unary_operator("NEGATE", int32_t, "negate_int32")


@MAIN
def uint_negate_test(a: uint32_t) -> int33_t:
    return -a


@MAIN
def int_negate_test(a: int32_t) -> int33_t:
    return -a


def make_point_t(dim_type, dim_size, style="array"):
    if style == "array":

        @struct
        class point_t(NamedTuple):
            dim: dim_type[dim_size]

        point_t.style = "array"
        point_t.dim_size = dim_size
        point_t.dim_type = dim_type
        return point_t
    elif style == "fields":
        pass  # TODO


point_t = make_point_t(uint32_t, 2, style="array")


def types_test_foo(point: point_t) -> point_t:
    rv: point_t
    if point_t.style == "array":
        for i in range(point_t.dim_size):
            rv.dim[i] = point.dim[i]
    else:
        for f in point_t._fields:
            rv[f] = point[f]
    return rv


@MAIN
def types_test_main(point: point_t) -> point_t:
    return types_test_foo(point)


def sum_widths(n, m):
    return n + m


def make_concat(LO_SIZE, HI_SIZE):
    OUT_SIZE = sum_widths(LO_SIZE, HI_SIZE)  # arbitrary Python here

    def concat(
        bits_lo: uint1_t[LO_SIZE], bits_hi: uint1_t[HI_SIZE]
    ) -> uint1_t[OUT_SIZE]:
        bits: uint1_t[OUT_SIZE]
        b = 0
        for i in range(LO_SIZE):
            bits[b] = bits_lo[i]
            b = b + 1
        for i in range(HI_SIZE):
            bits[b] = bits_hi[i]
            b = b + 1
        return bits

    return concat


N = 3
M = 4
concat_N_M = make_concat(N, M)


@MAIN
def concat_main(bits_lo: uint1_t[N], bits_hi: uint1_t[M]) -> uint1_t[sum_widths(N, M)]:
    return concat_N_M(bits_lo, bits_hi)


@MAIN
def accumulator(data_in: uint32_t) -> uint32_t:
    acc: Reg[uint32_t]  # register — persists between clock cycles, init=0
    acc = acc + data_in  # read current value, compute next
    return acc


@MAIN
def while_concat_main(bits_lo: uint1_t[5], bits_hi: uint1_t[6]) -> uint1_t[11]:
    bits: uint1_t[11]
    b = 0
    i = 0
    while i < 5:
        bits[b] = bits_lo[i]
        b = b + 1
        i = i + 1
    i = 0
    while i < 6:
        bits[b] = bits_hi[i]
        b = b + 1
        i = i + 1
    return bits


@MAIN
def adder_extra(a: uint32_t, b: uint32_t, c: uint32_t) -> uint34_t:
    return (a + b) + c


@MAIN
def adder(l: uint32_t, r: uint32_t) -> uint32_t:
    return l + r


@MAIN
def if_ref_tok_resolve(
    points: point2d_t[3],
    new_point: point2d_t,
    test_u32: uint32_t,
    i: uint32_t,
    cond: uint1_t,
) -> point2d_t[3]:
    if cond:
        points[i] = new_point
    else:
        points[0].dim[1] = test_u32
    return points


@MAIN
def if_var1d_struct_wr_main(
    points: point2d_t[3], new_point: point2d_t, i: uint32_t, cond: uint1_t
) -> point2d_t[3]:
    if cond:
        points[i] = new_point
    return points


@MAIN
def if_var2d_wr_main(
    points: point2d_t[3], test_u32: uint32_t, i: uint32_t, j: uint32_t, cond: uint1_t
) -> point2d_t[3]:
    if cond:
        points[i].dim[j] = test_u32
    return points


@MAIN
def if_var1d_array_wr_main(
    points: point2d_t[3], new_dim: uint32_t[2], i: uint32_t, cond: uint1_t
) -> point2d_t[3]:
    if cond:
        points[i].dim = new_dim
    return points


@MAIN
def if_var1d_wr_main1(
    points: point2d_t[3], test_u32: uint32_t, j: uint32_t, cond: uint1_t
) -> point2d_t[3]:
    if cond:
        points[0].dim[j] = test_u32
    return points


@MAIN
def if_var1d_wr_main2(
    points: point2d_t[3], test_u32: uint32_t, i: uint32_t, cond: uint1_t
) -> point2d_t[3]:
    if cond:
        points[i].dim[1] = test_u32
    return points


@MAIN
def if_var1d_struct_rd_main(
    points: point2d_t[3], test_u32: uint32_t, i: uint32_t, cond: uint1_t
) -> point2d_t:
    rv: point2d_t
    if cond:
        rv = points[i]
    return rv


@MAIN
def if_var1d_array_rd_main(
    points: point2d_t[3], test_u32: uint32_t, i: uint32_t, cond: uint1_t
) -> uint32_t[2]:
    rv: uint32_t[2]
    if cond:
        rv = points[i].dim
    return rv


@MAIN
def if_var1d_rd_main1(
    points: point2d_t[3], test_u32: uint32_t, j: uint32_t, cond: uint1_t
) -> uint32_t:
    rv: uint32_t
    if cond:
        rv = points[0].dim[j]
    return rv


@MAIN
def if_var1d_rd_main2(
    points: point2d_t[3], test_u32: uint32_t, i: uint32_t, cond: uint1_t
) -> uint32_t:
    rv: uint32_t
    if cond:
        rv = points[i].dim[1]
    return rv


@MAIN
def if_var2d_rd_main(
    points: point2d_t[3],
    test_u32_array: uint32_t[2],
    i: uint32_t,
    j: uint32_t,
    cond: uint1_t,
) -> uint32_t:
    rv: uint32_t
    if cond:
        rv = points[i].dim[j]
    return rv


@MAIN
def if_main0(cond: uint1_t) -> uint1_t:
    rv: uint1_t = 1
    if cond:
        rv = 0
    return rv


@MAIN
def var1d_struct_wr_main(
    points: point2d_t[3], new_point: point2d_t, i: uint32_t
) -> point2d_t[3]:
    points[i] = new_point
    return points


@MAIN
def var2d_wr_main(
    points: point2d_t[3], test_u32: uint32_t, i: uint32_t, j: uint32_t
) -> point2d_t[3]:
    points[i].dim[j] = test_u32
    return points


@MAIN
def var1d_array_wr_main(
    points: point2d_t[3], new_dim: uint32_t[2], i: uint32_t
) -> point2d_t[3]:
    points[i].dim = new_dim
    return points


@MAIN
def var1d_wr_main1(
    points: point2d_t[3], test_u32: uint32_t, j: uint32_t
) -> point2d_t[3]:
    points[0].dim[j] = test_u32
    return points


@MAIN
def var1d_wr_main2(
    points: point2d_t[3], test_u32: uint32_t, i: uint32_t
) -> point2d_t[3]:
    points[i].dim[1] = test_u32
    return points


@MAIN
def var1d_struct_rd_main(
    points: point2d_t[3], test_u32: uint32_t, i: uint32_t
) -> point2d_t:
    points[0].dim[1] = test_u32
    return points[i]


@MAIN
def var1d_array_rd_main(
    points: point2d_t[3], test_u32: uint32_t, i: uint32_t
) -> uint32_t[2]:
    points[0].dim[1] = test_u32
    return points[i].dim


@MAIN
def var1d_rd_main1(points: point2d_t[3], test_u32: uint32_t, j: uint32_t) -> uint32_t:
    points[0].dim[1] = test_u32
    return points[0].dim[j]


@MAIN
def var1d_rd_main2(points: point2d_t[3], test_u32: uint32_t, i: uint32_t) -> uint32_t:
    points[0].dim[1] = test_u32
    return points[i].dim[1]


@MAIN
def var2d_rd_main(
    points: point2d_t[3], test_u32_array: uint32_t[2], i: uint32_t, j: uint32_t
) -> uint32_t:
    points[0].dim = test_u32_array
    return points[i].dim[j]


@struct
class point_xy_t(NamedTuple):
    x: uint32_t
    y: uint32_t


@MAIN
def main_const_ref_rd(my_points: point_xy_t[10]) -> point_xy_t[10]:
    p0 = my_points[0]  # CONST_REF_RD(my_points) -> p0_alias
    # [0] never written, input wire fallback, need to extract [0] from full array

    my_points[1].x = 1  # env["my_points[1].x"] = alias_1x (driven by const 1)
    my_points[1].y = 2  # env["my_points[1].y"] = alias_1y (driven by const 2)

    my_points[2] = p0  # env["my_points[2]"] = alias_2 driven directly by p0_alias
    # p0 is already point_t, same type as [2] element
    # no CONST_REF_RD needed - direct wire connection

    p1 = my_points[1]  # CONST_REF_RD(alias_1x, alias_1y) -> p1_alias
    # both leaves of [1] were individually written, no input fallback needed

    p2 = my_points[2]  # no CONST_REF_RD needed - alias_2 covers [2] entirely
    # p2_alias driven directly by alias_2

    my_points[3] = p1  # env["my_points[3]"] = alias_3 driven directly by p1_alias
    # no CONST_REF_RD needed

    my_points[4] = p2  # env["my_points[4]"] = alias_4 driven directly by p2_alias
    # no CONST_REF_RD needed

    return my_points  # CONST_REF_RD(my_points,   <- covers [0],[5..99] untouched input fallback
    #              alias_1x,     <- covers [1].x
    #              alias_1y,     <- covers [1].y
    #              alias_2,      <- covers [2]
    #              alias_3,      <- covers [3]
    #              alias_4)      <- covers [4]


# TODO
# @MAIN
# def shift_const_wire(v: uint32_t) -> uint32_t:
#    amount: uint32_t = 5
#    return v << amount

SHIFT_AMOUNT = 5


@MAIN
def shift_const_param(v: uint32_t) -> uint32_t:
    return v << SHIFT_AMOUNT


@MAIN
def shift_const_local_param(v: uint32_t) -> uint32_t:
    AMOUNT = 5
    return v << AMOUNT


@MAIN
def shift_const(v: uint32_t) -> uint32_t:
    return v << 5


@MAIN
def uint_inv_test(a: uint32_t) -> uint32_t:
    return ~a


def foo(x: uint1_t) -> uint1_t:
    y = ~x
    return y


@MAIN
def main_foo_foo_fooo(x: uint1_t) -> uint1_t:
    return foo(foo(foo(x)))


@MAIN
def main_foo(x: uint1_t) -> uint1_t:
    return foo(x)


@MAIN
def test_bit_select(x: uint32_t) -> uint1_t:
    return x[15]


@MAIN
def test_bit_slice(x: uint32_t) -> uint16_t:
    return x[15:0]


@MAIN
def test_bit_slice_assign(x: uint32_t, y: uint16_t) -> uint32_t:
    x[15:0] = y
    return x


@MAIN
def test_tuple_concat2(a: uint32_t, b: uint32_t) -> uint64_t:
    return (a, b)


@MAIN
def test_tuple_concat3(a: uint16_t, b: uint16_t, c: uint32_t) -> uint64_t:
    return (a, b, c)


@MAIN
def test_bit_dup(x: uint4_t) -> uint16_t:
    return bit_dup(x, 4)


@MAIN
def test_rotl(x: uint64_t) -> uint64_t:
    return rotl(x, 7)


@MAIN
def test_rotr(x: uint32_t) -> uint32_t:
    return rotr(x, 3)


@MAIN
def test_bswap(x: uint32_t) -> uint32_t:
    return bswap(x)


@MAIN
def test_bit_assign(base: uint64_t, x: uint16_t) -> uint64_t:
    return bit_assign(base, x, 2)


@MAIN
def test_array_to_uint_be(arr: uint8_t[8]) -> uint64_t:
    return array_to_uint_be(arr)


@MAIN
def test_array_to_uint_le(arr: uint8_t[8]) -> uint64_t:
    return array_to_uint_le(arr)


@MAIN
def test_uint_to_array_be(x: uint64_t) -> uint8_t[8]:
    return uint_to_array_be(x, 8)


@MAIN
def test_uint_to_array_le(x: uint64_t) -> uint8_t[8]:
    return uint_to_array_le(x, 8)
