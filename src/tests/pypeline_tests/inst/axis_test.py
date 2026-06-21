# pyright: reportInvalidTypeForm=none
import sys, os

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..")
)
sys.path.insert(
    0,
    os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "..",
        "..",
        "..",
        "..",
        "include",
        "pypeline",
    ),
)
from pypeline import MAIN, sim_call, uint1_t, uint8_t, make_uint_t

from kept_data_bus import make_kept_data_bus_t
from ndarray import make_ndarray_fragment_t
from axi.axis import make_axis_t, make_keep_count, make_count_to_keep

N = 4
bus4_t = make_kept_data_bus_t(uint8_t, N)
axis32_t = make_axis_t(N)  # full stream(ndarray_fragment(1, kept_data_bus))
count_t = make_uint_t(N.bit_length())
keep_count_4 = make_keep_count(bus4_t, N)
count_to_keep_4 = make_count_to_keep(N)
video_frag_t = make_ndarray_fragment_t(
    uint8_t, 2
)  # standalone ndarray_fragment_t, no kept_data_bus


@MAIN
def axis32_passthrough(x: axis32_t) -> axis32_t:  # exercises full composed type
    return x


@MAIN
def keep_count_4_main(lanes: bus4_t) -> count_t:
    return keep_count_4(lanes)


@MAIN
def count_to_keep_4_main(count: count_t) -> uint1_t[N]:
    return count_to_keep_4(count)


@MAIN
def video_frag_eod_test(
    frag: video_frag_t,
) -> uint1_t:  # exercises ndarray_fragment_t standalone
    return frag.eod[0] & frag.eod[1]


def test_keep_count_and_count_to_keep():
    for count in range(N + 1):
        keep = sim_call(count_to_keep_4, count)
        assert list(keep) == [1] * count + [0] * (
            N - count
        ), f"count_to_keep({count}) = {keep}"
        got = sim_call(keep_count_4, bus4_t(data=[0] * N, keep=keep))
        assert (
            got == count
        ), f"keep_count(count_to_keep({count})) = {got}, expected {count}"
    print("test_keep_count_and_count_to_keep passed")


if __name__ == "__main__":
    test_keep_count_and_count_to_keep()
