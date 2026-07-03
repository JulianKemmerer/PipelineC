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


@MAIN
def struct_field_reassign_from_func() -> pypeline_tests.point_xy_wrap_t:
    # struct-field assignment case: o.field = helper() where o already declared
    o: pypeline_tests.point_xy_wrap_t
    o.p = pypeline_tests.make_point_xy_const(3, 4)
    o.tag = 0
    return o


@MAIN
def point_reassign_from_func() -> pypeline_tests.point_xy_t:
    # already-declared-var reassignment case: bare annotation, then plain assign
    p: pypeline_tests.point_xy_t
    p = pypeline_tests.make_point_xy_const(3, 4)
    return p


@MAIN
def point_reassign_twice_from_func() -> pypeline_tests.point_xy_t:
    # already-assigned-once variable, reassigned again via a helper call
    p: pypeline_tests.point_xy_t = pypeline_tests.make_point_xy_const(1, 2)
    p = pypeline_tests.make_point_xy_const(3, 4)
    return p


@MAIN
def mixed_granularity_branch_reassign(
    sel: uint32_t, other: pypeline_tests.point2d_t, keep0: uint32_t
) -> pypeline_tests.point2d_t:
    # Elaboration-only smoke coverage for the "mixed granularity across sibling
    # if/elif branches" shape (compound-init default, then a whole-aggregate
    # reassignment in one branch with a nested per-element override, then a
    # per-element loop write in a sibling branch). This alone does not regression-guard
    # the miscompile it's modeled on -- elaboration succeeds either way, before and
    # after the fix -- see mixed_granularity_reassign_test.py for the actual guard
    # (in-process Logic() inspection, since the bug is a silent wrong-wire miscompile).
    p: pypeline_tests.point2d_t
    p = pypeline_tests.point2d_t(dim=[0, 0])
    if sel == 0:
        _unused = 0  # branch intentionally never touches p (mirrors an IDLE state)
    elif sel == 1:
        p = other
        if ~keep0:
            p.dim[0] = 0
    else:
        p.dim[0] = 1
        p.dim[1] = 2
    return p
