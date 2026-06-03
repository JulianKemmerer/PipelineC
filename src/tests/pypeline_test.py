# pyright: reportInvalidTypeForm=none
from typing import NamedTuple
from pypeline import (
    MAIN,
    Reg,
    Feedback,
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
    _RegType,
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
    SimVal,
    hw_func,
    sim_call,
)

"""
TODO
Global wires Wire[T]
    test connecting MAINs together
Top level inputs and outputs global wires
    InputWire InputReg options etc
Import syntax, multiple files, std lib, etc
    organize tests into multiple files with imports and such
Single clock domain simulator?
    test regs,feedback,global wires
Aim for VGA as demo on simulation+board?
    Sphery ... or similar chasing the beam VGA with auto pipeline is good demo?
Dream is really some kind of software->hardware flow right?
BACKLOG
# Multiple clock domains
# Global FIFOs 
# TODO printf for sim? is special func?
# TODO RAW VHDL
# Revisit register init values
# Do something nice with port/pin mappings for constraint gen
# TODO unions? struct methods, only void return for now? struct.thing(a,b,c) to struct = struct_t_thing(struct,a,b,c)
#       ex. float_var .to/from uint(), .bit_length(), .bits() for to from slv stuff
# TODO all of old SW_LIB includes fabric multiply, div, etc
# TODO support tuple=concat assignment
#       ex. left: float32_t ; (left.sign, left.exp, left.man) = left_as_u32
# TODO stream(type_t) equivalent with valid flag
# TODO handshake(type) w/ valid+ feedback ready
#         what can be done with feedback wires to automate connection handshakes with ready?
# TODO constant wires based reduction that interacts with graph submodule instances:
#         ex. var ref assign/read into constant
#         ex. shift by a uint6_t type wire driven by constant
#         ... some day might be helpful for making simulator?
"""


@MAIN
def feedback_test(a: uint1_t, b: uint1_t) -> uint1_t:
    # Declare feedback, is not zero initalized
    f: Feedback[uint1_t]
    # Use feedback before it has been assigned a value
    # (typically would be zeros, but not for feedback)
    rv: uint1_t = f | a
    # Do the 'later' computation that needs to be fed back
    f = ~b
    return rv


def accumulator(data_in: uint32_t) -> uint32_t:
    acc: Reg[uint32_t]
    acc = acc + data_in
    return acc


@MAIN
def ce_accum_test(sel0: uint1_t, sel1: uint1_t, data_in: uint32_t) -> uint32_t:
    rv: uint32_t
    if sel0:
        if sel1:
            rv = accumulator(data_in)
    return rv


@struct
class point_xy_t(NamedTuple):
    x: uint32_t
    y: uint32_t


@MAIN
def comp_null_test(sel: uint1_t) -> point_xy_t:
    p: point_xy_t
    if sel:
        p.x = 1
    else:
        p.y = 1
    return p


@MAIN
def void_ret_test2(sel: uint1_t):
    p: point_xy_t
    if sel:
        p.x = 1
    else:
        p.y = 1


def make_point_xy_const(x, y):
    return point_xy_t(x=x, y=y)


@MAIN
def point_init_from_func() -> point_xy_t:
    p: point_xy_t = make_point_xy_const(3, 4)
    return p


@struct
class point2d_t(NamedTuple):
    dim: uint32_t[2]


@MAIN
def struct_init_list_consts() -> point2d_t:
    my_point: point2d_t = point2d_t(dim=[0, 1])
    return my_point


@MAIN
def struct_init_list_wires(v0: uint32_t, v1: uint32_t) -> point2d_t:
    my_point: point2d_t = point2d_t(dim=[v0, v1])
    return my_point


@MAIN
def struct_init_dict_int_keys(v0: uint32_t, v1: uint32_t) -> point2d_t:
    my_point: point2d_t = point2d_t(dim=[v0, v1])
    return my_point


@MAIN
def array_init_list_consts() -> uint32_t[2]:
    my_arr: uint32_t[2] = [42, 99]
    return my_arr


@MAIN
def array_init_list_wires(v0: uint32_t, v1: uint32_t) -> uint32_t[2]:
    my_arr: uint32_t[2] = [v0, v1]
    return my_arr


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


@MAIN
def test_point_u8_t(point: point_u8_t) -> point_u8_t:
    return point


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


@MAIN
def types_test_main(point: point_t) -> point_t:
    return types_test_foo(point)


def sum_widths(n, m):
    return n + m


@MAIN
def reg_test(data_in: uint32_t) -> uint32_t:
    acc: Reg[uint32_t]
    acc = acc + data_in
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


def make_adder(T):
    def add(a: T, b: T) -> T:
        return a + b

    return add


add_u32 = make_adder(uint32_t)
add_u32_dup = make_adder(uint32_t)
add_u8 = make_adder(uint8_t)


@MAIN
def adder_factory_test(a: uint32_t, b: uint32_t) -> uint32_t:
    return add_u32(a, b)


@MAIN
def adder_factory_dedup_test(a: uint32_t, b: uint32_t) -> uint32_t:
    return add_u32_dup(a, b)


@MAIN
def adder_factory_u8_test(a: uint8_t, b: uint8_t) -> uint8_t:
    return add_u8(a, b)


def make_sum3(T):
    local_add = make_adder(T)

    def sum3(a: T, b: T, c: T) -> T:
        return local_add(local_add(a, b), c)

    return sum3


sum3_u32 = make_sum3(uint32_t)
sum3_u32_dup = make_sum3(uint32_t)
sum3_u8 = make_sum3(uint8_t)


@MAIN
def nested_func_factory_test(a: uint32_t, b: uint32_t, c: uint32_t) -> uint32_t:
    return sum3_u32(a, b, c)


@MAIN
def nested_func_factory_dedup_test(a: uint32_t, b: uint32_t, c: uint32_t) -> uint32_t:
    return sum3_u32_dup(a, b, c)


@MAIN
def nested_func_factory_u8_test(a: uint8_t, b: uint8_t, c: uint8_t) -> uint8_t:
    return sum3_u8(a, b, c)


def make_pair_t(T):
    @struct
    class pair_t(NamedTuple):
        a: T
        b: T

    return pair_t


pair_u32_t = make_pair_t(uint32_t)
pair_u32_t_dup = make_pair_t(uint32_t)  # same params — should share canonical name


@MAIN
def pair_passthrough(p: pair_u32_t) -> pair_u32_t:
    return p


@MAIN
def pair_swap_fields(p: pair_u32_t) -> pair_u32_t:
    rv: pair_u32_t = pair_u32_t(a=p.b, b=p.a)
    return rv


@MAIN
def pair_dup_passthrough(p: pair_u32_t_dup) -> pair_u32_t_dup:
    return p


def make_swap(T):
    local_pair_t = make_pair_t(T)  # nested: local_pair_t not visible at module level

    def swap(p: local_pair_t) -> local_pair_t:
        rv: local_pair_t = local_pair_t(a=p.b, b=p.a)
        return rv

    return swap


swap_u32 = make_swap(uint32_t)


@MAIN
def nested_factory_swap_test(p: pair_u32_t) -> pair_u32_t:
    return swap_u32(p)


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


@MAIN
def nested_factory_def_test(a: uint32_t) -> uint32_t:
    return double_inv_u32(a)


@MAIN
def nested_factory_def_u8_test(a: uint8_t) -> uint8_t:
    return double_inv_u8(a)


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


def make_negate(value_t, out_t):
    @hw_func
    def negate(a: value_t) -> out_t:
        a_signed: out_t = a
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


@MAIN
def abs_int32_test(a: int32_t) -> uint32_t:
    return abs_int32(a)


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
register_left_operator("SL", uint32_t, "shl_uint32")

shr_uint32 = make_shifter_SR(uint32_t)
register_left_operator("SR", uint32_t, "shr_uint32")


@MAIN
def shift_var(v: uint32_t, amount: uint6_t) -> uint32_t:
    return v << amount


@MAIN
def shift_var_right(v: uint32_t, amount: uint6_t) -> uint32_t:
    return v >> amount


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


@MAIN
def clz_uint32_test(a: uint32_t) -> uint6_t:
    return clz_uint32(a)


float32_t = make_float_t(8, 23)


@MAIN
def float32_const_init() -> float32_t:
    x: float32_t = float32_t.as_const(1.5)
    return x


@MAIN
def float32_const_neg() -> float32_t:
    x: float32_t = float32_t.as_const(-1.0)
    return x


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


@MAIN
def float_add_32_main(left_as_u32: uint32_t, right_as_u32: uint32_t) -> uint32_t:
    # Un/pack float32_t from uint32_t bit representation (mostly for sim/top level ports)
    E_LEN = len(float32_t.typeof("exp"))
    M_LEN = len(float32_t.typeof("man"))
    M_SLICE = slice(M_LEN - 1, 0)
    E_SLICE = slice(E_LEN + M_LEN - 1, M_LEN)
    S_BIT = E_LEN + M_LEN
    left: float32_t = float32_t(
        sign=left_as_u32[S_BIT],
        man=left_as_u32[M_SLICE],
        exp=left_as_u32[E_SLICE],
    )
    right: float32_t = float32_t(
        sign=right_as_u32[S_BIT],
        man=right_as_u32[M_SLICE],
        exp=right_as_u32[E_SLICE],
    )
    result: float32_t = left + right
    result_as_u32: uint32_t = concat(result.sign, result.exp, result.man)
    return result_as_u32


def test_float_add_32():
    import struct as _struct

    def py_to_float32(f):
        bits = _struct.unpack(">I", _struct.pack(">f", float(f)))[0]
        return float32_t(
            sign=(bits >> 31) & 1,
            exp=(bits >> 23) & 0xFF,
            man=bits & 0x7FFFFF,
        )

    def float32_to_py(r):
        bits = (int(r.sign) << 31) | (int(r.exp) << 23) | int(r.man)
        return _struct.unpack(">f", _struct.pack(">I", bits))[0]

    cases = [
        (1.0, 2.0, 3.0),
        (0.0, 0.0, 0.0),
        (-1.0, 2.0, 1.0),
        (1.5, 2.5, 4.0),
        (-2.0, -2.0, -4.0),
        (0.5, 0.5, 1.0),
    ]
    for a, b, expected in cases:
        result = sim_call(float_add_32, py_to_float32(a), py_to_float32(b))
        got = float32_to_py(result)
        assert got == expected, f"{a} + {b} = {got}, expected {expected}"
    print("test_float_add_32 passed")


@MAIN
def point_max(points: point2d_t[3]) -> uint32_t:
    max_val: uint32_t = points[0].dim[0]
    for i in range(3):
        for j in range(2):
            if points[i].dim[j] > max_val:
                max_val = points[i].dim[j]
    return max_val


def test_point_max():
    def make_points(*pairs):
        return [point2d_t(dim=list(pair)) for pair in pairs]

    cases = [
        (make_points((1, 2), (3, 4), (5, 6)), 6),
        (make_points((10, 0), (0, 10), (5, 5)), 10),
        (make_points((0, 0), (0, 0), (0, 0)), 0),
        (make_points((100, 50), (200, 10), (150, 75)), 200),
        (make_points((7, 7), (7, 7), (7, 8)), 8),
    ]
    for points, expected in cases:
        result = sim_call(point_max, points)
        assert (
            int(result) == expected
        ), f"point_max(points) = {result}, expected {expected}"
    print("test_point_max passed")


# cd /media/1TB/Dropbox/PipelineC/git/PipelineC/src && PYTHONPATH=/media/1TB/Dropbox/PipelineC/git/PipelineC/src python3 tests/pypeline_test.py 2>&1
if __name__ == "__main__":
    test_float_add_32()
    test_point_max()
