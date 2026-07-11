import os
import sys

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "../../../")
)

from pypeline import MAIN, sim_call, sim_reset, uint8_t

# T[A][B] must behave like C's `T x[A][B]`: the outer/first dimension is A (the
# first-written bracket), the inner/second dimension is B (the second-written
# bracket) -- x[i][j] with i<A, j<B. A square shape can't catch a transposed
# axis order, so these deliberately use unequal dimensions (3 rows, 4 cols).


@MAIN
def grid_3x4_write(v: uint8_t) -> uint8_t[3][4]:
    g: uint8_t[3][4]
    g[2][3] = v
    return g


@MAIN
def grid_3x4_row(g: uint8_t[3][4], i: uint8_t) -> uint8_t[4]:
    return g[i]


def test_shape_matches_declaration_order():
    sim_reset()
    r = sim_call(grid_3x4_write, v=7)
    assert len(r) == 3, f"outer dim should be 3 (first bracket), got {len(r)}"
    assert all(
        len(row) == 4 for row in r
    ), f"inner dim should be 4 (second bracket): {r}"
    assert int(r[2][3]) == 7, r
    assert sum(int(x) for row in r for x in row) == 7, "only one element should be set"
    print("test_shape_matches_declaration_order PASS")


def test_row_is_second_bracket_length():
    sim_reset()
    r = sim_call(
        grid_3x4_row, g=[[0, 1, 2, 3], [10, 11, 12, 13], [20, 21, 22, 23]], i=1
    )
    assert [int(x) for x in r] == [10, 11, 12, 13], r
    print("test_row_is_second_bracket_length PASS")


def test_in_range_index_succeeds_and_reversed_index_raises():
    sim_reset()
    r = sim_call(grid_3x4_write, v=9)  # a[2][3] -- valid: 2<3, 3<4
    assert int(r[2][3]) == 9, r
    try:
        int(r[3][2])  # would have been the (wrongly) "valid" index pre-fix
        raise AssertionError("expected IndexError indexing row 3 of a 3-row array")
    except IndexError:
        pass
    print("test_in_range_index_succeeds_and_reversed_index_raises PASS")


if __name__ == "__main__":
    test_shape_matches_declaration_order()
    test_row_is_second_bracket_length()
    test_in_range_index_succeeds_and_reversed_index_raises()
    print("ALL array_2d_order_test TESTS PASSED")
