# pyright: reportInvalidTypeForm=none
from typing import NamedTuple
from pypeline import MAIN, struct, uint1_t, uint32_t


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


@struct
class point2d_t(NamedTuple):
    dim: uint32_t[2]


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


def foo(x: uint1_t) -> uint1_t:
    y = ~x
    return y


@MAIN
def main_foo(x: uint1_t) -> uint1_t:
    return foo(x)
