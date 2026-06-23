# pyright: reportInvalidTypeForm=none
import sys, os

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "../../../")
)
sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "def")
)

from pypeline import MAIN, uint1_t, uint8_t, uint32_t, sim_reset, sim_call

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


@MAIN
def if_num_cond(num: uint8_t) -> uint1_t:
    rv: uint1_t = 1
    if num:
        rv = 0
    return rv


# ---------------------------------------------------------------------------
# Simulation tests
# ---------------------------------------------------------------------------


def test_if_num_cond():
    sim_reset()
    assert int(sim_call(if_num_cond, num=0)) == 1  # 0 → condition false, rv stays 1
    assert int(sim_call(if_num_cond, num=1)) == 0  # 1 != 0 → condition true, rv = 0
    # num=2 (0b00000010): bit[0]=0 but num!=0, so condition must be true → rv=0.
    # If the mux select were wired to bit[0] instead of (num!=0) this would wrongly return 1.
    assert int(sim_call(if_num_cond, num=2)) == 0  # 2 != 0 → condition true, rv = 0
    assert int(sim_call(if_num_cond, num=255)) == 0  # 255 != 0 → condition true, rv = 0
    print("test_if_num_cond PASS")


if __name__ == "__main__":
    test_if_num_cond()
    print("\nAll if_test simulation tests passed.")
