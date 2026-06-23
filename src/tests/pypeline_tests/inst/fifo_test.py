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
from pypeline import MAIN, uint1_t, uint32_t, sim_call

from fifo import make_fifo

fifo_fwft, fifo_fwft_t = make_fifo(uint32_t, 256)


@MAIN
def fifo_test_top(
    ready_for_data_out: uint1_t, data_in: uint32_t, data_in_valid: uint1_t
) -> fifo_fwft_t:
    return fifo_fwft(ready_for_data_out, data_in, data_in_valid)


def test_fifo_sim_raises():
    try:
        sim_call(fifo_test_top, 1, 0, 0)
    except NotImplementedError:
        return
    raise AssertionError("expected NotImplementedError from vhdl(...) simulation")


if __name__ == "__main__":
    test_fifo_sim_raises()
    print("OK: fifo(...) simulation correctly raises NotImplementedError")
