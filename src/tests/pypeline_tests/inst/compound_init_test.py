# pyright: reportInvalidTypeForm=none
import sys, os

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "def")
)

from pypeline import MAIN, uint32_t

import pypeline_tests


@MAIN
def point_init_from_func() -> pypeline_tests.point_xy_t:
    p: pypeline_tests.point_xy_t = pypeline_tests.make_point_xy_const(3, 4)
    return p


@MAIN
def struct_init_list_consts() -> pypeline_tests.point2d_t:
    my_point: pypeline_tests.point2d_t = pypeline_tests.point2d_t(dim=[0, 1])
    return my_point


@MAIN
def struct_init_list_wires(v0: uint32_t, v1: uint32_t) -> pypeline_tests.point2d_t:
    my_point: pypeline_tests.point2d_t = pypeline_tests.point2d_t(dim=[v0, v1])
    return my_point


@MAIN
def struct_init_dict_int_keys(v0: uint32_t, v1: uint32_t) -> pypeline_tests.point2d_t:
    my_point: pypeline_tests.point2d_t = pypeline_tests.point2d_t(dim=[v0, v1])
    return my_point


@MAIN
def array_init_list_consts() -> uint32_t[2]:
    my_arr: uint32_t[2] = [42, 99]
    return my_arr


@MAIN
def array_init_list_wires(v0: uint32_t, v1: uint32_t) -> uint32_t[2]:
    my_arr: uint32_t[2] = [v0, v1]
    return my_arr
