# pyright: reportInvalidTypeForm=none
import sys, os

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "def")
)

from pypeline import MAIN, uint32_t

import pypeline_tests


@MAIN
def var1d_struct_wr_main(
    points: pypeline_tests.point2d_t[3],
    new_point: pypeline_tests.point2d_t,
    i: uint32_t,
) -> pypeline_tests.point2d_t[3]:
    points[i] = new_point
    return points


@MAIN
def var2d_wr_main(
    points: pypeline_tests.point2d_t[3],
    test_u32: uint32_t,
    i: uint32_t,
    j: uint32_t,
) -> pypeline_tests.point2d_t[3]:
    points[i].dim[j] = test_u32
    return points


@MAIN
def var1d_array_wr_main(
    points: pypeline_tests.point2d_t[3],
    new_dim: uint32_t[2],
    i: uint32_t,
) -> pypeline_tests.point2d_t[3]:
    points[i].dim = new_dim
    return points


@MAIN
def var1d_wr_main1(
    points: pypeline_tests.point2d_t[3],
    test_u32: uint32_t,
    j: uint32_t,
) -> pypeline_tests.point2d_t[3]:
    points[0].dim[j] = test_u32
    return points


@MAIN
def var1d_wr_main2(
    points: pypeline_tests.point2d_t[3],
    test_u32: uint32_t,
    i: uint32_t,
) -> pypeline_tests.point2d_t[3]:
    points[i].dim[1] = test_u32
    return points


@MAIN
def var1d_struct_rd_main(
    points: pypeline_tests.point2d_t[3],
    test_u32: uint32_t,
    i: uint32_t,
) -> pypeline_tests.point2d_t:
    points[0].dim[1] = test_u32
    return points[i]


@MAIN
def var1d_array_rd_main(
    points: pypeline_tests.point2d_t[3],
    test_u32: uint32_t,
    i: uint32_t,
) -> uint32_t[2]:
    points[0].dim[1] = test_u32
    return points[i].dim


@MAIN
def var1d_rd_main1(
    points: pypeline_tests.point2d_t[3],
    test_u32: uint32_t,
    j: uint32_t,
) -> uint32_t:
    points[0].dim[1] = test_u32
    return points[0].dim[j]


@MAIN
def var1d_rd_main2(
    points: pypeline_tests.point2d_t[3],
    test_u32: uint32_t,
    i: uint32_t,
) -> uint32_t:
    points[0].dim[1] = test_u32
    return points[i].dim[1]


@MAIN
def var2d_rd_main(
    points: pypeline_tests.point2d_t[3],
    test_u32_array: uint32_t[2],
    i: uint32_t,
    j: uint32_t,
) -> uint32_t:
    points[0].dim = test_u32_array
    return points[i].dim[j]
