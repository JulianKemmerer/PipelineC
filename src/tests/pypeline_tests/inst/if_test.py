# pyright: reportInvalidTypeForm=none
import sys, os

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "def")
)

from pypeline import MAIN, uint1_t, uint32_t

import pypeline_tests


@MAIN
def if_ref_tok_resolve(
    points: pypeline_tests.point2d_t[3],
    new_point: pypeline_tests.point2d_t,
    test_u32: uint32_t,
    i: uint32_t,
    cond: uint1_t,
) -> pypeline_tests.point2d_t[3]:
    if cond:
        points[i] = new_point
    else:
        points[0].dim[1] = test_u32
    return points


@MAIN
def if_var1d_struct_wr_main(
    points: pypeline_tests.point2d_t[3],
    new_point: pypeline_tests.point2d_t,
    i: uint32_t,
    cond: uint1_t,
) -> pypeline_tests.point2d_t[3]:
    if cond:
        points[i] = new_point
    return points


@MAIN
def if_var2d_wr_main(
    points: pypeline_tests.point2d_t[3],
    test_u32: uint32_t,
    i: uint32_t,
    j: uint32_t,
    cond: uint1_t,
) -> pypeline_tests.point2d_t[3]:
    if cond:
        points[i].dim[j] = test_u32
    return points


@MAIN
def if_var1d_array_wr_main(
    points: pypeline_tests.point2d_t[3],
    new_dim: uint32_t[2],
    i: uint32_t,
    cond: uint1_t,
) -> pypeline_tests.point2d_t[3]:
    if cond:
        points[i].dim = new_dim
    return points


@MAIN
def if_var1d_wr_main1(
    points: pypeline_tests.point2d_t[3],
    test_u32: uint32_t,
    j: uint32_t,
    cond: uint1_t,
) -> pypeline_tests.point2d_t[3]:
    if cond:
        points[0].dim[j] = test_u32
    return points


@MAIN
def if_var1d_wr_main2(
    points: pypeline_tests.point2d_t[3],
    test_u32: uint32_t,
    i: uint32_t,
    cond: uint1_t,
) -> pypeline_tests.point2d_t[3]:
    if cond:
        points[i].dim[1] = test_u32
    return points


@MAIN
def if_var1d_struct_rd_main(
    points: pypeline_tests.point2d_t[3],
    test_u32: uint32_t,
    i: uint32_t,
    cond: uint1_t,
) -> pypeline_tests.point2d_t:
    rv: pypeline_tests.point2d_t
    if cond:
        rv = points[i]
    return rv


@MAIN
def if_var1d_array_rd_main(
    points: pypeline_tests.point2d_t[3],
    test_u32: uint32_t,
    i: uint32_t,
    cond: uint1_t,
) -> uint32_t[2]:
    rv: uint32_t[2]
    if cond:
        rv = points[i].dim
    return rv


@MAIN
def if_var1d_rd_main1(
    points: pypeline_tests.point2d_t[3],
    test_u32: uint32_t,
    j: uint32_t,
    cond: uint1_t,
) -> uint32_t:
    rv: uint32_t
    if cond:
        rv = points[0].dim[j]
    return rv


@MAIN
def if_var1d_rd_main2(
    points: pypeline_tests.point2d_t[3],
    test_u32: uint32_t,
    i: uint32_t,
    cond: uint1_t,
) -> uint32_t:
    rv: uint32_t
    if cond:
        rv = points[i].dim[1]
    return rv


@MAIN
def if_var2d_rd_main(
    points: pypeline_tests.point2d_t[3],
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
